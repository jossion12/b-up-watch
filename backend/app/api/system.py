"""系统状态：3.7.1。"""

from __future__ import annotations

import os

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.errors import BizError
from app.models import Subtitle, SummaryTemplate, SystemConfig, Task, Uploader, Video
from app.schemas import (
    JobCurrentTaskOut,
    JobListOut,
    JobOut,
    JobUpdateIn,
    SystemConfigIn,
    SystemConfigOut,
    SystemStatusLLM,
    SystemStatusOut,
    SystemStatusStorage,
)

router = APIRouter()


@router.get("/system/status", response_model=SystemStatusOut)
def system_status(db: Session = Depends(get_db)) -> SystemStatusOut:
    cfg = db.get(SystemConfig, 1)
    settings = get_settings()

    running = db.execute(
        select(func.count()).select_from(Task).where(Task.status == "running")
    ).scalar() or 0
    pending = db.execute(
        select(func.count()).select_from(Task).where(Task.status == "pending")
    ).scalar() or 0
    sub_count = db.execute(select(func.count()).select_from(Subtitle)).scalar() or 0

    db_mb = 0.0
    if settings.database_url.startswith("sqlite"):
        path = settings.database_url.replace("sqlite:///", "")
        if os.path.exists(path):
            db_mb = round(os.path.getsize(path) / 1024 / 1024, 2)

    return SystemStatusOut(
        last_refresh_at=cfg.last_refresh_at if cfg else None,
        refresh_interval_sec=cfg.refresh_interval_sec if cfg else 600,
        running_tasks=int(running),
        queued_tasks=int(pending),
        llm=SystemStatusLLM(
            provider="openai-compatible",
            model=cfg.summary_model if cfg else "",
            available=bool(settings.llm_api_key),
        ),
        storage=SystemStatusStorage(db_mb=db_mb, subtitles_count=int(sub_count)),
    )

# ---------- 3.7.2 更新监控设置 ----------

@router.patch("/system/config", response_model=SystemConfigOut)
def update_system_config(
    payload: SystemConfigIn,
    db: Session = Depends(get_db),
) -> SystemConfigOut:
    cfg = db.get(SystemConfig, 1)
    if cfg is None:
        raise BizError("SYSTEM_CONFIG_NOT_FOUND", "系统配置不存在", http_status=500)

    if payload.summary_template_id is not None:
        tpl = db.get(SummaryTemplate, payload.summary_template_id)
        if tpl is None:
            raise BizError("TEMPLATE_NOT_FOUND", "模板不存在", http_status=404)
        cfg.summary_template_id = payload.summary_template_id

    if payload.refresh_interval_sec is not None:
        cfg.refresh_interval_sec = payload.refresh_interval_sec
    if payload.summary_model is not None:
        cfg.summary_model = payload.summary_model
    if payload.auto_summarize is not None:
        cfg.auto_summarize = payload.auto_summarize

    cfg.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(cfg)
    return SystemConfigOut(
        refresh_interval_sec=cfg.refresh_interval_sec,
        summary_model=cfg.summary_model,
        summary_template_id=cfg.summary_template_id,
        auto_summarize=cfg.auto_summarize,
    )


# ---------- 调度 Job 控制 ----------

_JOB_TASK_TYPES = {
    "subtitle": "subtitle_fetch",
    "summary": "ai_summary",
    "backfill": "feed_refresh",
}

_JOB_LABELS = {
    "subtitle": "字幕抓取",
    "summary": "AI 总结",
    "backfill": "历史回溯",
}

_OPERATION_LABELS = {
    "subtitle_fetch": "获取字幕",
    "ai_summary": "生成总结",
    "feed_refresh": "拉取视频",
    "whisper_transcribe": "Whisper 转写",
    "video_stats_refresh": "回填点赞",
}


def _current_task_for_job(db: Session, runner, job_name: str) -> JobCurrentTaskOut | None:
    if runner is None:
        return None
    task = runner.current_task
    if task is None or task.type != _JOB_TASK_TYPES[job_name]:
        return None

    title: str | None = None
    if task.ref_type == "video" and task.ref_id:
        v = db.get(Video, task.ref_id)
        if v is not None:
            title = v.title
    elif task.ref_type == "uploader" and task.ref_id:
        up = db.get(Uploader, task.ref_id)
        if up is not None:
            title = up.name

    return JobCurrentTaskOut(
        task_id=task.task_id,
        type=task.type,
        status=task.status,
        progress=task.progress,
        ref_type=task.ref_type,
        ref_id=task.ref_id,
        title=title,
        operation_label=_OPERATION_LABELS.get(task.type, task.type),
    )


@router.get("/system/jobs", response_model=JobListOut)
def list_jobs(request: Request, db: Session = Depends(get_db)) -> JobListOut:
    scheduler = getattr(request.app.state, "scheduler", None)
    runner = getattr(request.app.state, "runner", None)
    jobs = scheduler.list_jobs() if scheduler else [
        {"name": name, "enabled": True, "label": label}
        for name, label in _JOB_LABELS.items()
    ]
    items: list[JobOut] = []
    for job in jobs:
        name = job["name"]
        current = _current_task_for_job(db, runner, name) if runner else None
        items.append(JobOut(
            name=name,
            label=job["label"],
            enabled=job["enabled"],
            current=current,
        ))
    return JobListOut(items=items)


@router.patch("/system/jobs/{name}", response_model=JobOut)
def update_job(
    name: str,
    payload: JobUpdateIn,
    request: Request,
    db: Session = Depends(get_db),
) -> JobOut:
    if name not in _JOB_LABELS:
        raise BizError("JOB_NOT_FOUND", "Job 不存在", http_status=404)
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is None:
        raise BizError("SCHEDULER_UNAVAILABLE", "调度器不可用", http_status=503)
    scheduler.set_enabled(name, payload.enabled)
    current = _current_task_for_job(db, request.app.state.runner, name)
    return JobOut(
        name=name,
        label=_JOB_LABELS[name],
        enabled=scheduler.is_enabled(name),
        current=current,
    )
