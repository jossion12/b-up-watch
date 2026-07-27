"""任务查询：3.5.1 / 3.5.2。"""

from __future__ import annotations

from typing import Optional

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import BizError
from app.models import Task
from app.schemas import TaskListOut, TaskOut, TaskStatsOut

router = APIRouter()


# ---------- 3.5.2 任务列表 ----------

@router.get("/tasks", response_model=TaskListOut)
def list_tasks(
    status: Optional[str] = Query(None, description="逗号分隔状态，如 running,pending"),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> TaskListOut:
    stmt = select(Task).order_by(Task.created_at.desc())
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if statuses:
            stmt = stmt.where(Task.status.in_(statuses))
    rows = db.execute(stmt.limit(limit)).scalars().all()
    return TaskListOut(items=[TaskOut.model_validate(r) for r in rows], total=len(rows))


# ---------- 3.5.3 任务统计 ----------

SUBTITLE_TASK_TYPES = ("subtitle_fetch", "whisper_transcribe")
PENDING_STATUSES = ("pending", "running")
COMPLETED_STATUSES = ("success",)
FAILED_STATUSES = ("failed",)


@router.get("/tasks/stats", response_model=TaskStatsOut)
def task_stats(db: Session = Depends(get_db)) -> TaskStatsOut:
    rows = db.execute(
        select(Task.type, Task.status, func.count()).where(
            Task.type.in_(SUBTITLE_TASK_TYPES + ("ai_summary",))
        ).group_by(Task.type, Task.status)
    ).all()

    totals: dict[str, int] = {}
    pending: dict[str, int] = {}
    completed: dict[str, int] = {}
    failed: dict[str, int] = {}
    for task_type, status, count in rows:
        totals[task_type] = totals.get(task_type, 0) + count
        if status in PENDING_STATUSES:
            pending[task_type] = pending.get(task_type, 0) + count
        if status in COMPLETED_STATUSES:
            completed[task_type] = completed.get(task_type, 0) + count
        if status in FAILED_STATUSES:
            failed[task_type] = failed.get(task_type, 0) + count

    subtitle_total = sum(totals.get(t, 0) for t in SUBTITLE_TASK_TYPES)
    subtitle_pending = sum(pending.get(t, 0) for t in SUBTITLE_TASK_TYPES)
    subtitle_completed = sum(completed.get(t, 0) for t in SUBTITLE_TASK_TYPES)
    subtitle_failed = sum(failed.get(t, 0) for t in SUBTITLE_TASK_TYPES)
    summary_total = totals.get("ai_summary", 0)
    summary_pending = pending.get("ai_summary", 0)
    summary_completed = completed.get("ai_summary", 0)
    summary_failed = failed.get("ai_summary", 0)

    return TaskStatsOut(
        subtitle_total=subtitle_total,
        subtitle_pending=subtitle_pending,
        subtitle_completed=subtitle_completed,
        subtitle_failed=subtitle_failed,
        summary_total=summary_total,
        summary_pending=summary_pending,
        summary_completed=summary_completed,
        summary_failed=summary_failed,
    )


# ---------- 3.5.1 任务详情 ----------

@router.get("/tasks/{task_id}", response_model=TaskOut)
def get_task(task_id: str, db: Session = Depends(get_db)) -> TaskOut:
    t = db.get(Task, task_id)
    if t is None:
        raise BizError("TASK_NOT_FOUND", "任务不存在", http_status=404)
    return TaskOut.model_validate(t)


# ---------- 3.5.4 重试失败任务 ----------

@router.post("/tasks/{task_id}/retry", response_model=TaskOut)
def retry_task(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> TaskOut:
    t = db.get(Task, task_id)
    if t is None:
        raise BizError("TASK_NOT_FOUND", "任务不存在", http_status=404)
    if t.status != "failed":
        raise BizError("TASK_NOT_RETRYABLE", "只有失败任务可以重试", http_status=400)

    t.status = "pending"
    t.progress = 0
    t.error = None
    t.finished_at = None
    t.created_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(t)

    runner = getattr(request.app.state, "runner", None)
    if runner is not None:
        runner.notify()

    return TaskOut.model_validate(t)
