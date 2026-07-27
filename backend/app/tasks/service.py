"""任务服务：统一任务创建入口。

其他业务模块（uploaders / videos / summaries 等）不应直接构造 Task 模型，
而是通过 create_task 创建，以保证 task_id、状态、时间戳等字段一致。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Task


def create_task(
    db: Session,
    task_type: str,
    ref_type: Optional[str] = None,
    ref_id: Optional[str] = None,
    meta: Optional[dict] = None,
    priority: int = 0,
) -> Task:
    """创建一条 pending 任务并加入 session（不自动 commit）。"""
    task = Task(
        task_id=uuid.uuid4().hex[:12],
        type=task_type,
        status="pending",
        progress=0,
        ref_type=ref_type,
        ref_id=ref_id,
        meta=meta,
        priority=priority,
        created_at=datetime.now(timezone.utc),
    )
    db.add(task)
    return task
