"""AI 总结接口：3.4.1 / 3.4.2 / 3.4.3 / 3.4.4。

工作流：
- 3.4.1：若已有 Summary 且 force=false → 200 返回现有；否则 → 202 建 ai_summary 任务
  - 若视频无字幕，自动级联先建 subtitle_fetch 任务（chain 字段）
- 3.4.2：取 Summary 行；不存在 → 404
- 3.4.3：总是建任务（模板/模型切换场景）
- 3.4.4：批量建任务（不做防重，便于重排队）

template_id / model 通过 Task.meta JSON 列透传到执行层，由 runner._dispatch_ai_summary 读取。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import BizError
from app.models import Subtitle, Summary, SummaryTemplate, Task, Video
from app.schemas import (
    BatchSummaryIn,
    BatchSummaryOut,
    StanceOut,
    SummaryCreateIn,
    SummaryOut,
    SummaryRegenerateIn,
    SummaryRegenerateOut,
    SummaryTaskRef,
)

router = APIRouter()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _summary_out(summary: Summary) -> SummaryOut:
    """ORM → Schema 适配（stance dict → StanceOut）。"""
    raw = summary.stance or {}
    return SummaryOut(
        video_id=summary.video_id,
        template_id=summary.template_id,
        brief=summary.brief,
        points=list(summary.points or []),
        stance=StanceOut(
            label=raw.get("label", ""),
            sentiment=raw.get("sentiment", "neutral"),
            detail=raw.get("detail", ""),
        ),
        topics=list(summary.topics or []),
        quote=summary.quote,
        model=summary.model,
        token_usage=dict(summary.token_usage or {}),
        created_at=summary.created_at,
    )


def _check_template(db: Session, template_id: str | None) -> None:
    if template_id is None:
        return
    if db.get(SummaryTemplate, template_id) is None:
        raise BizError("TEMPLATE_NOT_FOUND", "模板不存在", http_status=404)


def _existing_active_summary_task(db: Session, video_id: str) -> Optional[Task]:
    return (
        db.query(Task)
        .filter(
            Task.type == "ai_summary",
            Task.ref_type == "video",
            Task.ref_id == video_id,
            Task.status.in_(["pending", "running"]),
        )
        .first()
    )


def _enqueue_summary_task(
    db: Session,
    video_id: str,
    template_id: Optional[str],
    model: Optional[str],
) -> Task:
    meta: dict = {}
    if template_id:
        meta["template_id"] = template_id
    if model:
        meta["model"] = model
    task = Task(
        task_id=_new_id(),
        type="ai_summary",
        status="pending",
        progress=0,
        ref_type="video",
        ref_id=video_id,
        meta=meta or None,
        created_at=datetime.now(timezone.utc),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


# ---------- 3.4.1 创建总结任务 ----------

@router.post("/videos/{video_id}/summary")
def create_summary(
    video_id: str,
    payload: SummaryCreateIn,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    v = db.get(Video, video_id)
    if v is None:
        raise BizError("VIDEO_NOT_FOUND", "视频不存在", http_status=404)

    _check_template(db, payload.template_id)

    existing = db.get(Summary, video_id)

    # 已有总结 + !force → 200 直接返回现有
    if existing is not None and not payload.force:
        body = _summary_out(existing).model_dump(mode="json")
        return JSONResponse(status_code=200, content=body)

    # 防重
    dup = _existing_active_summary_task(db, video_id)
    if dup is not None:
        raise BizError("TASK_CONFLICT", "已有进行中的总结任务", http_status=409)

    chain: list[SummaryTaskRef] = []

    # 无字幕时级联字幕获取
    sub = db.get(Subtitle, video_id)
    if sub is None:
        sub_dup = (
            db.query(Task)
            .filter(
                Task.type == "subtitle_fetch",
                Task.ref_type == "video",
                Task.ref_id == video_id,
                Task.status.in_(["pending", "running"]),
            )
            .first()
        )
        if sub_dup is None:
            sub_task = Task(
                task_id=_new_id(),
                type="subtitle_fetch",
                status="pending",
                progress=0,
                ref_type="video",
                ref_id=video_id,
                created_at=datetime.now(timezone.utc),
            )
            db.add(sub_task)
            db.commit()
            db.refresh(sub_task)
            chain.append(SummaryTaskRef(task_id=sub_task.task_id, type="subtitle_fetch"))

    task = _enqueue_summary_task(db, video_id, payload.template_id, payload.model)

    runner = getattr(request.app.state, "runner", None)
    if runner is not None:
        runner.notify()

    return JSONResponse(
        status_code=202,
        content={
            "task_id": task.task_id,
            "type": "ai_summary",
            "chain": [c.model_dump(mode="json") for c in chain],
        },
    )


# ---------- 3.4.2 获取总结结果 ----------

@router.get("/videos/{video_id}/summary", response_model=SummaryOut)
def get_summary(video_id: str, db: Session = Depends(get_db)) -> SummaryOut:
    if db.get(Video, video_id) is None:
        raise BizError("VIDEO_NOT_FOUND", "视频不存在", http_status=404)
    s = db.get(Summary, video_id)
    if s is None:
        raise BizError("SUMMARY_NOT_FOUND", "尚未生成总结", http_status=404)
    return _summary_out(s)


# ---------- 3.4.3 重新生成总结 ----------

@router.post(
    "/videos/{video_id}/summary/regenerate",
    response_model=SummaryRegenerateOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def regenerate_summary(
    video_id: str,
    payload: SummaryRegenerateIn,
    request: Request,
    db: Session = Depends(get_db),
) -> SummaryRegenerateOut:
    v = db.get(Video, video_id)
    if v is None:
        raise BizError("VIDEO_NOT_FOUND", "视频不存在", http_status=404)
    _check_template(db, payload.template_id)

    dup = _existing_active_summary_task(db, video_id)
    if dup is not None:
        raise BizError("TASK_CONFLICT", "已有进行中的总结任务", http_status=409)

    task = _enqueue_summary_task(db, video_id, payload.template_id, payload.model)

    runner = getattr(request.app.state, "runner", None)
    if runner is not None:
        runner.notify()

    return SummaryRegenerateOut(task_id=task.task_id, type="ai_summary")


# ---------- 3.4.4 批量总结 ----------

@router.post(
    "/summaries/batch",
    response_model=BatchSummaryOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def batch_summarize(
    payload: BatchSummaryIn,
    request: Request,
    db: Session = Depends(get_db),
) -> BatchSummaryOut:
    _check_template(db, payload.template_id)

    batch_id = "b_" + _new_id()
    task_ids: list[str] = []

    for vid in payload.video_ids:
        v = db.get(Video, vid)
        if v is None:
            # 跳过不存在的视频 —— 接口文档允许多 video_ids 部分缺失
            continue
        task = _enqueue_summary_task(db, vid, payload.template_id, payload.model)
        task_ids.append(task.task_id)

    runner = getattr(request.app.state, "runner", None)
    if runner is not None:
        runner.notify()

    return BatchSummaryOut(batch_id=batch_id, task_ids=task_ids)
