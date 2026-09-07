"""系统状态：3.7.1。"""

from __future__ import annotations

import logging
import os

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.bilibili.login import check_bilibili_login
from app.config import get_settings, set_bilibili_cookie, set_bilibili_sessdata, set_ragflow_embed_auth
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

log = logging.getLogger(__name__)

router = APIRouter()


def _extract_sessdata_from_cookie(cookie: str | None) -> str | None:
    """从 B 站完整 Cookie 字符串中提取 SESSDATA 值。

    支持浏览器 DevTools 复制的标准格式 "name1=value1; name2=value2"；
    也容忍 DevTools Network > Request Headers > Cookie 行（可能带 "cookie:" 前缀、
    含换行）。大小写不敏感、容忍前后空白；首个非空 SESSDATA 胜出。
    """
    if not cookie:
        return None
    # 剥掉 DevTools Network 复制可能带的 "cookie:" 前缀
    cookie = cookie.strip()
    if cookie.lower().startswith("cookie:"):
        cookie = cookie[len("cookie:"):].strip()
    # 兼容多行（DevTools 复制请求头时偶尔带换行）
    cookie = " ".join(cookie.splitlines())
    for part in cookie.split(";"):
        name, sep, value = part.strip().partition("=")
        if name.lower() == "sessdata" and sep and value:
            # 剥掉外层引号（DevTools 偶尔会带）
            return value.strip().strip('"').strip("'")
    return None


@router.get("/system/status", response_model=SystemStatusOut)
async def system_status(db: Session = Depends(get_db)) -> SystemStatusOut:
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

    bilibili_login = await check_bilibili_login()

    return SystemStatusOut(
        last_refresh_at=cfg.last_refresh_at if cfg else None,
        refresh_interval_sec=cfg.refresh_interval_sec if cfg else 600,
        running_tasks=int(running),
        queued_tasks=int(pending),
        llm=SystemStatusLLM(
            provider="openai-compatible",
            model=settings.llm_model or (cfg.summary_model if cfg else ""),
            available=bool(settings.llm_api_key),
        ),
        storage=SystemStatusStorage(db_mb=db_mb, subtitles_count=int(sub_count)),
        bilibili_login=bilibili_login,
    )

# ---------- 3.7.2 系统配置 ----------

@router.get("/system/config", response_model=SystemConfigOut)
def get_system_config(db: Session = Depends(get_db)) -> SystemConfigOut:
    cfg = db.get(SystemConfig, 1)
    if cfg is None:
        raise BizError("SYSTEM_CONFIG_NOT_FOUND", "系统配置不存在", http_status=500)
    return SystemConfigOut(
        refresh_interval_sec=cfg.refresh_interval_sec,
        summary_model=cfg.summary_model,
        summary_template_id=cfg.summary_template_id,
        auto_summarize=cfg.auto_summarize,
        bilibili_sessdata=cfg.bilibili_sessdata,
        bilibili_cookie=cfg.bilibili_cookie,
        ragflow_embed_auth=cfg.ragflow_embed_auth,
    )


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
    if payload.bilibili_sessdata is not None:
        cfg.bilibili_sessdata = payload.bilibili_sessdata or None
        set_bilibili_sessdata(cfg.bilibili_sessdata)
        # 脱敏日志：确认设置页的保存请求真的把值传过来了
        v = cfg.bilibili_sessdata or ""
        masked = (v[:4] + "***" + v[-3:]) if len(v) > 8 else repr(v)
        log.info(
            "[system.config] bilibili_sessdata saved: len=%d value=%s",
            len(v), masked,
        )
    if payload.bilibili_cookie is not None:
        cfg.bilibili_cookie = payload.bilibili_cookie or None
        set_bilibili_cookie(cfg.bilibili_cookie)
        # 自动从 Cookie 中提取 SESSDATA，避免用户单独粘贴
        extracted = _extract_sessdata_from_cookie(cfg.bilibili_cookie)
        cfg.bilibili_sessdata = extracted
        set_bilibili_sessdata(extracted)
        if extracted:
            log.info(
                "[system.config] SESSDATA auto-extracted from cookie: len=%d",
                len(extracted),
            )
        else:
            log.warning(
                "[system.config] cookie 中未找到 SESSDATA；B 站风控拦截可能导致下载失败"
            )
    if payload.ragflow_embed_auth is not None:
        cfg.ragflow_embed_auth = payload.ragflow_embed_auth or None
        set_ragflow_embed_auth(cfg.ragflow_embed_auth)

    cfg.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(cfg)
    return SystemConfigOut(
        refresh_interval_sec=cfg.refresh_interval_sec,
        summary_model=cfg.summary_model,
        summary_template_id=cfg.summary_template_id,
        auto_summarize=cfg.auto_summarize,
        bilibili_sessdata=cfg.bilibili_sessdata,
        bilibili_cookie=cfg.bilibili_cookie,
        ragflow_embed_auth=cfg.ragflow_embed_auth,
    )


# ---------- 调度 Job 控制 ----------

_JOB_TASK_TYPES = {
    "subtitle": "subtitle_fetch",
    "summary": "ai_summary",
}

_JOB_LABELS = {
    "subtitle": "字幕抓取",
    "summary": "AI 总结",
}

_OPERATION_LABELS = {
    "subtitle_fetch": "获取字幕",
    "ai_summary": "生成总结",
    "feed_refresh": "拉取视频",
    "whisper_transcribe": "Whisper 转写",
    "video_stats_refresh": "回填点赞",
}


def _resolve_ref_title(db: Session, task: Task) -> str | None:
    if not task.ref_id:
        return None
    if task.ref_type == "video":
        v = db.get(Video, task.ref_id)
        return v.title if v is not None else None
    if task.ref_type == "uploader":
        up = db.get(Uploader, task.ref_id)
        return up.name if up is not None else None
    return None


def _current_task_for_job(db: Session, job_name: str) -> JobCurrentTaskOut | None:
    task_type = _JOB_TASK_TYPES.get(job_name)
    if task_type is None:
        return None

    task = db.execute(
        select(Task)
        .where(Task.type == task_type, Task.status == "running")
        .order_by(Task.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if task is None:
        return None

    return JobCurrentTaskOut(
        task_id=task.task_id,
        type=task.type,
        status=task.status,
        progress=task.progress,
        ref_type=task.ref_type,
        ref_id=task.ref_id,
        title=_resolve_ref_title(db, task),
        operation_label=_OPERATION_LABELS.get(task.type, task.type),
    )


@router.get("/system/jobs", response_model=JobListOut)
def list_jobs(request: Request, db: Session = Depends(get_db)) -> JobListOut:
    scheduler = getattr(request.app.state, "scheduler", None)
    jobs = scheduler.list_jobs() if scheduler else [
        {"name": name, "enabled": True, "label": label}
        for name, label in _JOB_LABELS.items()
    ]
    items: list[JobOut] = []
    for job in jobs:
        name = job["name"]
        current = _current_task_for_job(db, name)
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
    current = _current_task_for_job(db, name)
    return JobOut(
        name=name,
        label=_JOB_LABELS[name],
        enabled=scheduler.is_enabled(name),
        current=current,
    )
