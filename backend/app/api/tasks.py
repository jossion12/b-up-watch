"""任务查询：3.5.1 / 3.5.2。"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import BizError
from app.models import Task
from app.schemas import TaskListOut, TaskOut

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


# ---------- 3.5.1 任务详情 ----------

@router.get("/tasks/{task_id}", response_model=TaskOut)
def get_task(task_id: str, db: Session = Depends(get_db)) -> TaskOut:
    t = db.get(Task, task_id)
    if t is None:
        raise BizError("TASK_NOT_FOUND", "任务不存在", http_status=404)
    return TaskOut.model_validate(t)
