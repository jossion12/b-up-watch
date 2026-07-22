"""周期性任务调度器。

负责在后台持续扫描数据库，按需生成 subtitle_fetch / ai_summary / feed_refresh
任务并通知 TaskRunner 立即消费。三个循环相互独立：

- subtitle_loop：发现尚未获取字幕的视频，排队 subtitle_fetch。
- summary_loop：发现已有字幕但尚未总结的视频，排队 ai_summary。
- backfill_loop：当当前库中已没有“未获取字幕”且“未总结”的视频时，为某个 UP 主
  创建 feed_refresh 任务以拉取更早的视频。

设计上不直接做 IO/LLM 调用，只操作 tasks 表，实际执行仍由 TaskRunner 单 worker
顺序处理，保持现有风控与并发策略。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import DEFAULT_USER_ID, Task, Uploader, Video

log = logging.getLogger(__name__)


class TaskScheduler:
    """周期性任务生成器。"""

    def __init__(
        self,
        runner,
        *,
        subtitle_interval_sec: float | None = None,
        summary_interval_sec: float | None = None,
        backfill_interval_sec: float | None = None,
        batch_size: int | None = None,
        backfill_extra_days: int | None = None,
        backfill_max_pages: int | None = None,
        session_factory=None,
    ) -> None:
        self.runner = runner
        settings = get_settings()
        self.subtitle_interval = subtitle_interval_sec if subtitle_interval_sec is not None else settings.scheduler_subtitle_interval_sec
        self.summary_interval = summary_interval_sec if summary_interval_sec is not None else settings.scheduler_summary_interval_sec
        self.backfill_interval = backfill_interval_sec if backfill_interval_sec is not None else settings.scheduler_backfill_interval_sec
        self.batch_size = batch_size if batch_size is not None else settings.scheduler_batch_size
        self.backfill_extra_days = backfill_extra_days if backfill_extra_days is not None else settings.backfill_extra_days
        self.backfill_max_pages = backfill_max_pages if backfill_max_pages is not None else settings.backfill_max_pages
        self._session_factory = session_factory or SessionLocal
        self._tasks: list[asyncio.Task] = []
        self._stop = asyncio.Event()
        self._enabled = {
            "subtitle": True,
            "summary": True,
            "backfill": True,
        }

    async def start(self) -> None:
        self._stop.clear()
        self._tasks = [
            asyncio.create_task(self._subtitle_loop(), name="scheduler-subtitle"),
            asyncio.create_task(self._summary_loop(), name="scheduler-summary"),
            asyncio.create_task(self._backfill_loop(), name="scheduler-backfill"),
        ]
        log.info(
            "task scheduler started: subtitle=%.0fs summary=%.0fs backfill=%.0fs batch=%d",
            self.subtitle_interval,
            self.summary_interval,
            self.backfill_interval,
            self.batch_size,
        )

    async def stop(self) -> None:
        self._stop.set()
        for t in self._tasks:
            t.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        log.info("task scheduler stopped")

    def list_jobs(self) -> list[dict]:
        labels = {
            "subtitle": "字幕抓取",
            "summary": "AI 总结",
            "backfill": "历史回溯",
        }
        return [
            {"name": name, "enabled": enabled, "label": labels[name]}
            for name, enabled in self._enabled.items()
        ]

    def is_enabled(self, name: str) -> bool:
        return self._enabled.get(name, False)

    def set_enabled(self, name: str, enabled: bool) -> None:
        if name not in self._enabled:
            raise ValueError(f"unknown job: {name}")
        self._enabled[name] = enabled
        log.info("job %s %s", name, "enabled" if enabled else "disabled")

    async def _subtitle_loop(self) -> None:
        while not self._stop.is_set():
            try:
                if self._enabled.get("subtitle"):
                    created = await self._enqueue_subtitle_tasks()
                    if created:
                        log.info("scheduler enqueued %d subtitle task(s)", created)
                        self._notify_runner()
            except Exception:
                log.exception("subtitle scheduler loop failed")
            await self._sleep(self.subtitle_interval)

    async def _summary_loop(self) -> None:
        while not self._stop.is_set():
            try:
                if self._enabled.get("summary"):
                    created = await self._enqueue_summary_tasks()
                    if created:
                        log.info("scheduler enqueued %d summary task(s)", created)
                        self._notify_runner()
            except Exception:
                log.exception("summary scheduler loop failed")
            await self._sleep(self.summary_interval)

    async def _backfill_loop(self) -> None:
        while not self._stop.is_set():
            try:
                if self._enabled.get("backfill"):
                    created = await self._enqueue_backfill_task()
                    if created:
                        log.info("scheduler enqueued backfill task")
                        self._notify_runner()
            except Exception:
                log.exception("backfill scheduler loop failed")
            await self._sleep(self.backfill_interval)

    async def _sleep(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    def _notify_runner(self) -> None:
        if self.runner is not None:
            try:
                self.runner.notify()
            except Exception:
                log.warning("notify runner failed", exc_info=True)

    def _new_id(self) -> str:
        return uuid.uuid4().hex[:12]

    def _new_task(self, type_: str, ref_type: str | None, ref_id: str | None, meta: dict | None = None) -> Task:
        return Task(
            task_id=self._new_id(),
            type=type_,
            status="pending",
            progress=0,
            ref_type=ref_type,
            ref_id=ref_id,
            meta=meta,
            created_at=datetime.now(timezone.utc),
        )

    async def _enqueue_subtitle_tasks(self) -> int:
        """为尚未获取字幕的视频创建 subtitle_fetch 任务。"""
        with self._session_factory() as db:
            active_subtitle = (
                select(Task)
                .where(
                    Task.type == "subtitle_fetch",
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
                    Video.has_subtitle.is_(False),
                    ~active_subtitle,
                )
                .order_by(Video.published_at.desc())
                .limit(self.batch_size)
            ).scalars().all()

            created = 0
            for v in videos:
                db.add(self._new_task("subtitle_fetch", "video", v.id))
                created += 1
            if created:
                db.commit()
            return created

    async def _enqueue_summary_tasks(self) -> int:
        """为已有字幕但尚未总结的视频创建 ai_summary 任务。"""
        with self._session_factory() as db:
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
                    Video.has_subtitle.is_(True),
                    Video.has_summary.is_(False),
                    ~active_summary,
                )
                .order_by(Video.published_at.desc())
                .limit(self.batch_size)
            ).scalars().all()

            created = 0
            for v in videos:
                db.add(self._new_task("ai_summary", "video", v.id))
                created += 1
            if created:
                db.commit()
            return created

    async def _enqueue_backfill_task(self) -> bool:
        """若当前没有待处理/未完成的字幕或总结工作，则为一个 UP 主拉取更早视频。"""
        with self._session_factory() as db:
            # 1) 库中是否还有未获取字幕或未总结的视频
            pending_video = db.execute(
                select(Video.id)
                .where(
                    Video.user_id == DEFAULT_USER_ID,
                    (Video.has_subtitle.is_(False) | Video.has_summary.is_(False)),
                )
                .limit(1)
            ).scalar_one_or_none()

            # 2) 是否还有进行中的字幕/总结任务
            active_task = db.execute(
                select(Task.task_id)
                .where(
                    Task.type.in_(["subtitle_fetch", "ai_summary"]),
                    Task.status.in_(["pending", "running"]),
                )
                .limit(1)
            ).scalar_one_or_none()

            if pending_video is not None or active_task is not None:
                return False

            # 3) 选一个最久没更新到的 UP 主
            up = db.execute(
                select(Uploader)
                .where(Uploader.user_id == DEFAULT_USER_ID)
                .order_by(Uploader.last_video_at.asc().nullsfirst())
                .limit(1)
            ).scalar_one_or_none()
            if up is None:
                return False

            # 4) 避免重复创建回溯任务
            active_backfill = db.execute(
                select(Task.task_id)
                .where(
                    Task.type == "feed_refresh",
                    Task.ref_type == "uploader",
                    Task.ref_id == up.id,
                    Task.status.in_(["pending", "running"]),
                )
                .limit(1)
            ).scalar_one_or_none()
            if active_backfill is not None:
                return False

            # 5) 计算需要回溯多久：当前 UP 主最老的视频再往前推 extra_days
            oldest_video = db.execute(
                select(Video)
                .where(
                    Video.user_id == DEFAULT_USER_ID,
                    Video.uploader_id == up.id,
                )
                .order_by(Video.published_at.asc())
                .limit(1)
            ).scalar_one_or_none()

            if oldest_video is not None:
                oldest_pub = oldest_video.published_at
                if oldest_pub is None or oldest_pub.tzinfo is None:
                    oldest_pub = (oldest_pub or datetime.now(timezone.utc)).replace(tzinfo=timezone.utc)
                days_back = (datetime.now(timezone.utc) - oldest_pub).days + self.backfill_extra_days
            else:
                days_back = 90

            db.add(
                self._new_task(
                    "feed_refresh",
                    "uploader",
                    up.id,
                    meta={
                        "days_back": max(days_back, self.backfill_extra_days),
                        "max_pages": self.backfill_max_pages,
                        "mode": "backfill",
                    },
                )
            )
            db.commit()
            return True
