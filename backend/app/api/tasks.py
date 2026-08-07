"""任务查询：3.5.1 / 3.5.2。"""

from __future__ import annotations

from typing import Optional

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import BizError
from app.models import Task, Uploader, Video
from app.schemas import TaskCancelIn, TaskCancelOut, TaskListOut, TaskOut, TaskStatsOut

router = APIRouter()


_OPERATION_LABELS = {
    "subtitle_fetch": "获取字幕",
    "ai_summary": "生成总结",
    "feed_refresh": "拉取视频",
    "whisper_transcribe": "Whisper 转写",
    "video_stats_refresh": "回填点赞",
    "rag_ingest": "生成语料",
}


def _operation_label(task_type: str) -> str:
    return _OPERATION_LABELS.get(task_type, task_type)


def _resolve_ref_title(db: Session, task: Task) -> Optional[str]:
    if not task.ref_id:
        return None
    if task.ref_type == "video":
        v = db.get(Video, task.ref_id)
        return v.title if v is not None else None
    if task.ref_type == "uploader":
        up = db.get(Uploader, task.ref_id)
        return up.name if up is not None else None
    return None


def _task_out(db: Session, task: Task) -> TaskOut:
    return TaskOut(
        task_id=task.task_id,
        type=task.type,
        status=task.status,
        progress=task.progress,
        ref_type=task.ref_type,
        ref_id=task.ref_id,
        ref_title=_resolve_ref_title(db, task),
        operation_label=_operation_label(task.type),
        error=task.error,
        priority=task.priority,
        created_at=task.created_at,
        finished_at=task.finished_at,
    )


# ---------- 3.5.2 任务列表 ----------

@router.get("/tasks", response_model=TaskListOut)
def list_tasks(
    status: Optional[str] = Query(None, description="逗号分隔状态，如 running,pending"),
    task_type: Optional[str] = Query(None, description="任务类型，如 rag_ingest"),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> TaskListOut:
    stmt = select(Task).order_by(Task.created_at.desc())
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if statuses:
            stmt = stmt.where(Task.status.in_(statuses))
    if task_type:
        stmt = stmt.where(Task.type == task_type)
    rows = db.execute(stmt.limit(limit)).scalars().all()
    return TaskListOut(items=[_task_out(db, r) for r in rows], total=len(rows))


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
    return _task_out(db, t)


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

    return _task_out(db, t)


# ---------- 取消指定类型的任务 ----------

@router.post("/tasks/cancel", response_model=TaskCancelOut)
async def cancel_tasks(
    payload: TaskCancelIn,
    request: Request,
    db: Session = Depends(get_db),
) -> TaskCancelOut:
    """取消指定类型的任务：删除 pending 任务，取消/标记 running 任务为失败。"""
    task_types = payload.task_type

    cancelled_ids: list[str] = []
    deleted_ids: list[str] = []

    pending = db.execute(
        select(Task).where(Task.type.in_(task_types), Task.status == "pending")
    ).scalars().all()
    for t in pending:
        deleted_ids.append(t.task_id)
        db.delete(t)

    running = db.execute(
        select(Task).where(Task.type.in_(task_types), Task.status == "running")
    ).scalars().all()

    runner = getattr(request.app.state, "runner", None)
    cancelled_current = False
    if runner is not None and runner.current_task is not None and runner.current_task.type in task_types:
        cancelled_current = runner.cancel_current_handler()

    for t in running:
        if cancelled_current and runner is not None and runner.current_task is not None and runner.current_task.task_id == t.task_id:
            # 已由 runner 触发取消，等待其把状态设为失败即可
            cancelled_ids.append(t.task_id)
            continue
        # 没有活跃 handler 的 running 任务（僵尸状态），直接标记失败
        t.status = "failed"
        t.error = {"code": "CANCELLED", "message": "任务已取消"}
        t.finished_at = datetime.now(timezone.utc)
        cancelled_ids.append(t.task_id)

    db.commit()
    return TaskCancelOut(
        cancelled_task_ids=cancelled_ids,
        deleted_task_ids=deleted_ids,
    )
