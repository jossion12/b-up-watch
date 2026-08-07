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
from app.collect.corpus import save_ragflow_corpus
from app.collect.fetch_subtitle import save_subtitle_to_file
from app.collect import fetch_summary as collect_summary
from app.collect import fetch_uploader as collect_fetch
from app.config import get_settings
from app.errors import BizError
from app.models import DEFAULT_USER_ID, Subtitle, SystemConfig, Task, Uploader, Video
# 原 Milvus + LLM 提取的 RAG ingest 路径已暂停，改用 RAGFlow 语料生成
# from app.rag.service import ingest_uploader, ingest_video
from app.tasks.registry import task_handler
from app.transcriber import pipeline as asr_pipeline
from app.websocket import push_task_updated_sync

log = logging.getLogger(__name__)


async def _ingest_video_subtitle(
    video: Video,
    lines: list[dict],
    db,
    source: str = "unknown",
) -> None:
    """将视频字幕归档，并生成 RAGFlow 语料文件。

    原 Milvus + LLM 提取的 RAG ingest 路径已暂停，失败不应阻塞字幕任务，仅记录日志。
    """
    settings = get_settings()
    try:
        md_path = save_subtitle_to_file(video, lines)

        # 生成 RAGFlow 语料（无 LLM，纯规则清洗）
        if settings.ragflow_corpus_enabled:
            corpus_path = save_ragflow_corpus(video, lines, source=source)
            log.info(
                "[rag corpus] video=%s, subtitle=%s, corpus=%s",
                video.id,
                md_path.name,
                corpus_path.name if corpus_path else "disabled",
            )

        # 原 LLM 提取 + Milvus 写入路径已暂停
        # if settings.rag_auto_ingest_enabled:
        #     await ingest_video(video_id=video.id, db=db, replace=True)
        #     log.info("[rag ingest] video=%s, path=%s, ingested", video.id, md_path.name)
    except Exception as e:
        log.warning("[rag corpus] video=%s, failed: %s", video.id, e)


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
    log.info("[task subtitle_fetch] task=%s, bvid=%s, title=%s", task.task_id, v.bvid, v.title)
    try:
        sub = await collect_subtitle.fetch_video_subtitle(db, v)
        log.info("[task subtitle_fetch] task=%s, bvid=%s, fetched bilibili subtitle successfully", task.task_id, v.bvid)
        await _ingest_video_subtitle(v, sub.lines, db, source=sub.source)
        return
    except BizError as e:
        if e.code == "VIDEO_UNAVAILABLE":
            log.info("[task subtitle_fetch] task=%s, bvid=%s, video unavailable, marking as complete: %s", task.task_id, v.bvid, e.message)
            v.has_subtitle = True
            if v.status == "new":
                v.status = "subtitled"
            db.commit()
            return
        if e.code not in ("SUBTITLE_UNAVAILABLE", "SUBTITLE_DURATION_MISMATCH"):
            log.error("[task subtitle_fetch] task=%s, bvid=%s, fetch subtitle failed with non-retryable error: %s - %s", task.task_id, v.bvid, e.code, e.message)
            raise
        log.info("[task subtitle_fetch] task=%s, bvid=%s, %s, falling back to whisper: %s", task.task_id, v.bvid, e.code, e.message)
        await _run_whisper_fallback(db, v, task)


async def _run_whisper_fallback(db, v: Video, task: Task | None = None) -> None:
    """拉音轨 + 本地 ASR 转写，写入 Subtitle(source='whisper')。"""
    task_id = task.task_id if task else None
    log.info("[task whisper_fallback] task=%s, bvid=%s, starting whisper fallback", task_id, v.bvid)
    try:
        lines = await asr_pipeline.transcribe_video(v.bvid)
    except BizError as e:
        if e.code == "AUDIO_UNAVAILABLE":
            log.info("[task whisper_fallback] task=%s, bvid=%s, audio unavailable, marking as complete", task_id, v.bvid)
            v.has_subtitle = True
            if v.status == "new":
                v.status = "subtitled"
            db.commit()
            return
        log.error("[task whisper_fallback] task=%s, bvid=%s, whisper fallback failed: %s", task_id, v.bvid, e)
        raise
    except Exception as e:
        log.error("[task whisper_fallback] task=%s, bvid=%s, whisper fallback failed: %s", task_id, v.bvid, e)
        raise
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
        log.info("[task whisper_fallback] task=%s, bvid=%s, created new whisper subtitle", task_id, v.bvid)
    else:
        sub.language = "zh-CN"
        sub.source = "whisper"
        sub.lines = lines
        sub.fetched_at = now
        log.info("[task whisper_fallback] task=%s, bvid=%s, updated existing subtitle to whisper", task_id, v.bvid)
    v.has_subtitle = True
    if v.status == "new":
        v.status = "subtitled"
    db.commit()

    # 本地归档 + RAGFlow 语料生成：data/{up主名称}/YYYYMMDD-{视频名称}.md
    try:
        await _ingest_video_subtitle(v, lines, db, source="whisper")
        log.info("[task whisper_fallback] task=%s, bvid=%s, saved subtitle and corpus", task_id, v.bvid)
    except Exception as e:
        # 文件归档/RAGFlow 语料生成失败不影响 DB 写入，仅记录日志
        log.warning("[task whisper_fallback] task=%s, bvid=%s, failed to save subtitle/corpus: %s", task_id, v.bvid, e)

    log.info("[task whisper_fallback] task=%s, bvid=%s, done: %d lines", task_id, v.bvid, len(lines))


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


@task_handler("rag_ingest")
async def handle_rag_ingest(db, task: Task) -> None:
    """重新生成某位 UP 主下所有有字幕视频的 RAGFlow 语料。

    原 Milvus + LLM 提取的 RAG 索引重建已暂停，现改为批量刷新语料文件。
    """
    if task.ref_type != "uploader" or not task.ref_id:
        raise BizError("TASK_INVALID_REF", "rag_ingest 必须绑定 uploader", http_status=500)

    up = db.get(Uploader, task.ref_id)
    if up is None or up.user_id != DEFAULT_USER_ID:
        raise BizError("UPLOADER_NOT_FOUND", "UP主不存在", http_status=404)

    settings = get_settings()
    if not settings.ragflow_corpus_enabled:
        log.info("[task rag_ingest] task=%s, uploader=%s, corpus generation disabled", task.task_id, up.id)
        return

    videos = db.execute(
        select(Video).where(
            Video.uploader_id == up.id,
            Video.has_subtitle.is_(True),
        )
    ).scalars().all()

    total = len(videos)
    generated = 0
    failed = 0

    def _update_progress(progress: int) -> None:
        task.progress = progress
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

    log.info("[task rag_ingest] task=%s, uploader=%s, start, videos=%s", task.task_id, up.id, total)

    for i, v in enumerate(videos):
        sub = db.get(Subtitle, v.id)
        if sub is None or not sub.lines:
            continue
        try:
            save_ragflow_corpus(v, sub.lines, source=sub.source)
            generated += 1
        except Exception as e:
            failed += 1
            log.warning("[task rag_ingest] task=%s, video=%s, corpus failed: %s", task.task_id, v.id, e)

        if total > 0:
            _update_progress(int((i + 1) / total * 100))

    task.meta = {
        **(task.meta or {}),
        "videos": total,
        "generated": generated,
        "failed": failed,
    }
    db.commit()
    log.info(
        "[task rag_ingest] task=%s, uploader=%s, done: videos=%s generated=%s failed=%s",
        task.task_id, up.id, total, generated, failed,
    )

    # 原 Milvus + LLM 提取的 RAG 索引重建路径已暂停
    # result = await ingest_uploader(uploader_id=up.id, db=db, up_name=up.name, on_progress=_update_progress)
    # task.meta = {**(task.meta or {}), "files": result["files"], "segments": result["segments"], "chunks": result["chunks"]}
    # db.commit()
