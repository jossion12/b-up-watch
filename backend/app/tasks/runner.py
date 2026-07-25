"""后台任务 Runner。

- 单 worker 顺序消费 `tasks` 表中 status=pending 的记录（接口文档分析文档：单 worker 顺序执行防风控）
- 支持 `notify()` 唤醒立即处理（POST /uploaders、POST /videos/refresh 后调用）
- 处理失败写入 `task.error`，不抛到外层
- 测试中可通过 `runner.tick()` 手动驱动一轮
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.bilibili import subtitle as bili_sub
from app.collect import fetch_subtitle as collect_subtitle
from app.collect import fetch_summary as collect_summary
from app.collect import fetch_uploader as collect_fetch
from app.errors import BizError
from app.models import DEFAULT_USER_ID, Subtitle, SystemConfig, Task, Uploader, Video
from app.transcriber import pipeline as asr_pipeline
from app.websocket import push_task_updated_sync

log = logging.getLogger(__name__)


class TaskRunner:
    def __init__(self, tick_interval_sec: float = 60.0, session_factory=None):
        self.interval = tick_interval_sec
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        # 测试时可注入 session 工厂；默认懒加载 app.db.SessionLocal（支持夹具 monkeypatch）
        self._session_factory = session_factory
        # 当前正在执行的任务（仅用于展示），单 worker 无需锁
        self.current_task: Task | None = None

    def _recover_stale_tasks(self) -> int:
        """启动时把上次崩溃遗留的 running 任务重置为 pending，避免永远卡住。"""
        from app.db import SessionLocal
        factory = self._session_factory or SessionLocal
        with factory() as db:
            tasks = db.execute(
                select(Task).where(Task.status == "running")
            ).scalars().all()
            for task in tasks:
                task.status = "pending"
                task.error = None
            if tasks:
                db.commit()
                log.info("recovered %d stale running task(s) to pending", len(tasks))
            return len(tasks)

    async def start(self) -> None:
        self._stop.clear()
        self._wake.clear()
        recovered = self._recover_stale_tasks()
        self._task = asyncio.create_task(self._loop(), name="task-runner")
        log.info("task runner started, interval=%.1fs, recovered=%d", self.interval, recovered)

    async def stop(self) -> None:
        self._stop.set()
        self._wake.set()  # 立即唤醒 sleep
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except asyncio.TimeoutError:
                self._task.cancel()
        self._task = None
        log.info("task runner stopped")

    def notify(self) -> None:
        """让下一轮 tick 立即执行（不等 interval）。"""
        self._wake.set()

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.tick()
            except Exception:
                log.exception("tick failed")
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()

    async def tick(self) -> str | None:
        """处理一条 pending 任务；返回处理过的 task_id 或 None。"""
        from app.db import SessionLocal  # 懒加载，便于测试 monkeypatch
        factory = self._session_factory or SessionLocal
        with factory() as db:
            task = db.execute(
                select(Task)
                .where(Task.status == "pending")
                .order_by(Task.priority.desc(), Task.created_at.asc())
                .limit(1)
            ).scalar_one_or_none()
            if task is None:
                return None

            task.status = "running"
            db.commit()
            db.refresh(task)
            self.current_task = task

            try:
                await self._dispatch(db, task)
                task.status = "success"
            except BizError as e:
                task.status = "failed"
                task.error = {"code": e.code, "message": e.message, "details": e.details}
                log.warning("task %s biz-error: %s", task.task_id, e.message)
            except Exception as e:
                task.status = "failed"
                task.error = {"code": "TASK_FAILED", "message": str(e) or e.__class__.__name__}
                log.exception("task %s failed", task.task_id)
            finally:
                self.current_task = None
                task.finished_at = datetime.now(timezone.utc)
                db.commit()
                push_task_updated_sync({
                    "task_id": task.task_id,
                    "type": task.type,
                    "status": task.status,
                    "progress": task.progress,
                    "ref_type": task.ref_type,
                    "ref_id": task.ref_id,
                    "error": task.error,
                    "created_at": task.created_at,
                    "finished_at": task.finished_at,
                })
            return task.task_id

    async def _dispatch(self, db, task: Task) -> None:
        if task.type == "feed_refresh":
            await self._dispatch_feed_refresh(db, task)
            return
        if task.type == "subtitle_fetch":
            await self._dispatch_subtitle_fetch(db, task)
            return
        if task.type == "ai_summary":
            await self._dispatch_ai_summary(db, task)
            return
        if task.type == "video_stats_refresh":
            await self._dispatch_video_stats_refresh(db, task)
            return
        raise BizError(
            "TASK_TYPE_UNSUPPORTED",
            f"本期暂不支持任务类型: {task.type}",
            http_status=500,
        )

    async def _dispatch_ai_summary(self, db, task: Task) -> None:
        if task.ref_type != "video" or not task.ref_id:
            raise BizError("TASK_INVALID_REF", "ai_summary 必须绑定 video", http_status=500)
        v = db.get(Video, task.ref_id)
        if v is None or v.user_id != DEFAULT_USER_ID:
            raise BizError("VIDEO_NOT_FOUND", "视频不存在", http_status=404)
        meta = dict(task.meta or {})
        template_id = meta.get("template_id")
        model = meta.get("model")
        await collect_summary.summarize_video(db, v, template_id=template_id, model=model)

    async def _dispatch_subtitle_fetch(self, db, task: Task) -> None:
        if task.ref_type != "video" or not task.ref_id:
            raise BizError("TASK_INVALID_REF", "subtitle_fetch 必须绑定 video", http_status=500)
        v = db.get(Video, task.ref_id)
        if v is None or v.user_id != DEFAULT_USER_ID:
            raise BizError("VIDEO_NOT_FOUND", "视频不存在", http_status=404)
        try:
            await collect_subtitle.fetch_video_subtitle(db, v)
            return
        except BizError as e:
            if e.code not in ("SUBTITLE_UNAVAILABLE", "SUBTITLE_DURATION_MISMATCH"):
                raise
            # 兜底：自动级联 Whisper 转写
            log.info(
                "subtitle %s for %s, falling back to whisper",
                e.code.lower(), v.bvid,
            )
            await self._run_whisper_fallback(db, v)

    async def _run_whisper_fallback(self, db, v: Video) -> None:
        """拉音轨 + 本地 ASR 转写，写入 Subtitle(source='whisper')。"""
        lines = await asr_pipeline.transcribe_video(v.bvid)
        sub = db.get(Subtitle, v.id)
        now = datetime.now(timezone.utc)
        if sub is None:
            sub = Subtitle(
                video_id=v.id,
                language="zh-CN",
                source="whisper",
                lines=lines,
                fetched_at=now,
            )
            db.add(sub)
        else:
            sub.language = "zh-CN"
            sub.source = "whisper"
            sub.lines = lines
            sub.fetched_at = now
        v.has_subtitle = True
        if v.status == "new":
            v.status = "subtitled"
        db.commit()
        log.info("whisper fallback done for %s: %d lines", v.bvid, len(lines))

    async def _dispatch_feed_refresh(self, db, task: Task) -> None:
        cfg = db.get(SystemConfig, 1)
        auto = bool(cfg.auto_summarize if cfg else False)
        meta = dict(task.meta or {})
        days_back = meta.get("days_back")
        max_pages = meta.get("max_pages")
        kwargs: dict = {}
        if isinstance(days_back, int) and days_back > 0:
            kwargs["days_back"] = days_back
        if isinstance(max_pages, int) and max_pages > 0:
            kwargs["max_pages"] = max_pages

        if task.ref_type == "uploader" and task.ref_id:
            up = db.get(Uploader, task.ref_id)
            if up is None or up.user_id != DEFAULT_USER_ID:
                raise BizError("UPLOADER_NOT_FOUND", "UP主不存在", http_status=404)
            await collect_fetch.fetch_uploader_videos(db, up, **kwargs)
            if auto:
                self._enqueue_auto_summaries(db, up)
            return

        # 全局刷新：遍历所有关注的 UP主
        uploaders = db.execute(
            select(Uploader).where(Uploader.user_id == DEFAULT_USER_ID)
        ).scalars().all()
        for i, up in enumerate(uploaders):
            try:
                await collect_fetch.fetch_uploader_videos(db, up, **kwargs)
                if auto:
                    self._enqueue_auto_summaries(db, up)
            except BizError as e:
                # 单个 UP 主失败不影响整体，但记到进度日志
                log.warning("global refresh: uploader %s failed: %s", up.bilibili_uid, e.message)
            task.progress = int((i + 1) / max(len(uploaders), 1) * 100)
            db.commit()

        if cfg is not None:
            cfg.last_refresh_at = datetime.now(timezone.utc)
            db.commit()

    async def _dispatch_video_stats_refresh(self, db, task: Task) -> None:
        """回填视频真实点赞数（从 `x/web-interface/view` 的 stat.like）。

        支持：
        - ref_type=video, ref_id=video_id：回填单个视频
        - ref_type=uploader, ref_id=uploader_id：回填该 UP 主下所有视频
        """
        if task.ref_type == "video" and task.ref_id:
            videos = [db.get(Video, task.ref_id)]
            if videos[0] is None or videos[0].user_id != DEFAULT_USER_ID:
                raise BizError("VIDEO_NOT_FOUND", "视频不存在", http_status=404)
        elif task.ref_type == "uploader" and task.ref_id:
            up = db.get(Uploader, task.ref_id)
            if up is None or up.user_id != DEFAULT_USER_ID:
                raise BizError("UPLOADER_NOT_FOUND", "UP主不存在", http_status=404)
            videos = db.execute(
                select(Video)
                .where(Video.user_id == DEFAULT_USER_ID, Video.uploader_id == up.id)
                .order_by(Video.published_at.desc())
            ).scalars().all()
        else:
            raise BizError(
                "TASK_INVALID_REF",
                "video_stats_refresh 必须绑定 video 或 uploader",
                http_status=500,
            )

        total = len(videos)
        updated = 0
        failed = 0
        for i, v in enumerate(videos):
            if v is None:
                continue
            try:
                info = await bili_sub.get_video_info(v.bvid)
                stat = (info or {}).get("stat") or {}
                real_likes = stat.get("like")
                if real_likes is not None:
                    v.likes = int(real_likes)
                    updated += 1
                    log.info(
                        "backfill likes for %s: %s -> %s",
                        v.bvid, v.likes, int(real_likes),
                    )
                else:
                    log.warning("backfill likes for %s: stat.like missing", v.bvid)
            except BizError as e:
                failed += 1
                log.warning("backfill likes failed for %s: %s", v.bvid, e.message)
            except Exception:
                failed += 1
                log.exception("backfill likes failed for %s", v.bvid)

            task.progress = int((i + 1) / max(total, 1) * 100)
            db.commit()

            # 顺序执行 + 限速，降低 B 站风控概率
            if i < total - 1:
                await asyncio.sleep(0.6)

        log.info(
            "video_stats_refresh done: total=%s updated=%s failed=%s",
            total, updated, failed,
        )

    def _enqueue_auto_summaries(self, db, up: Uploader) -> None:
        """为 UP 主下所有尚未总结且无进行中的总结任务的视频排队 ai_summary。"""
        active_summary = (
            select(Task)
            .where(
                Task.type == "ai_summary",
                Task.ref_type == "video",
                Task.ref_id == Video.id,
                Task.status.in_(["pending", "running"]),
            )
            .exists()
        )

        videos = db.execute(
            select(Video)
            .where(
                Video.user_id == DEFAULT_USER_ID,
                Video.uploader_id == up.id,
                Video.status.in_(["new", "subtitled"]),
                Video.has_summary.is_(False),
                ~active_summary,
            )
        ).scalars().all()

        created = 0
        for v in videos:
            db.add(Task(
                task_id=uuid.uuid4().hex[:12],
                type="ai_summary",
                status="pending",
                progress=0,
                ref_type="video",
                ref_id=v.id,
                created_at=datetime.now(timezone.utc),
            ))
            created += 1
        if created:
            db.commit()
            log.info("auto_summarize: enqueued %d summary tasks for uploader %s", created, up.bilibili_uid)
