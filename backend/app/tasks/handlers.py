"""具体任务处理器。

每个处理器通过 @task_handler("type_name") 注册到 registry；runner 负责通用
状态流转，handler 只关注业务逻辑。
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
from app.tasks.registry import task_handler
from app.transcriber import pipeline as asr_pipeline

log = logging.getLogger(__name__)


@task_handler("ai_summary")
async def handle_ai_summary(db, task: Task) -> None:
    # AI 总结功能已暂停：直接返回，不执行任何逻辑
    return
    # if task.ref_type != "video" or not task.ref_id:
    #     raise BizError("TASK_INVALID_REF", "ai_summary 必须绑定 video", http_status=500)
    # v = db.get(Video, task.ref_id)
    # if v is None or v.user_id != DEFAULT_USER_ID:
    #     raise BizError("VIDEO_NOT_FOUND", "视频不存在", http_status=404)
    # meta = dict(task.meta or {})
    # template_id = meta.get("template_id")
    # model = meta.get("model")
    # await collect_summary.summarize_video(db, v, template_id=template_id, model=model)


@task_handler("subtitle_fetch")
async def handle_subtitle_fetch(db, task: Task) -> None:
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
        log.info("subtitle %s for %s, falling back to whisper", e.code.lower(), v.bvid)
        await _run_whisper_fallback(db, v)


async def _run_whisper_fallback(db, v: Video) -> None:
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


@task_handler("feed_refresh")
async def handle_feed_refresh(db, task: Task) -> None:
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
        # AI 总结功能已暂停：不再自动排队总结任务
        # if auto:
        #     _enqueue_auto_summaries(db, up)
        return

    # 全局刷新：遍历所有关注的 UP主
    uploaders = db.execute(
        select(Uploader).where(Uploader.user_id == DEFAULT_USER_ID)
    ).scalars().all()
    for i, up in enumerate(uploaders):
        try:
            await collect_fetch.fetch_uploader_videos(db, up, **kwargs)
            # AI 总结功能已暂停：不再自动排队总结任务
            # if auto:
            #     _enqueue_auto_summaries(db, up)
        except BizError as e:
            log.warning("global refresh: uploader %s failed: %s", up.bilibili_uid, e.message)
        task.progress = int((i + 1) / max(len(uploaders), 1) * 100)
        db.commit()

    if cfg is not None:
        cfg.last_refresh_at = datetime.now(timezone.utc)
        db.commit()


def _enqueue_auto_summaries(db, up: Uploader) -> None:
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
            Video.has_subtitle.is_(True),
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


@task_handler("video_stats_refresh")
async def handle_video_stats_refresh(db, task: Task) -> None:
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
