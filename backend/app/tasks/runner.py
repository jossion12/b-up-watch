"""后台任务 Runner。

- 单 worker 顺序消费 `tasks` 表中 status=pending 的记录（接口文档分析文档：单 worker 顺序执行防风控）
- 支持 `notify()` 唤醒立即处理（POST /uploaders、POST /videos/refresh 后调用）
- 处理失败写入 `task.error`，不抛到外层
- 具体任务逻辑注册在 `app.tasks.handlers`，runner 只负责状态机流转
- 测试中可通过 `runner.tick()` 手动驱动一轮
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

# 导入 handlers 以触发 @task_handler 注册
from app.errors import BizError
from app.models import Task
from app.tasks import handlers  # noqa: F401
from app.tasks.registry import get_handler
from app.websocket import push_task_updated_sync

log = logging.getLogger(__name__)


class TaskRunner:
    def __init__(self, tick_interval_sec: float = 60.0, session_factory=None):
        self.interval = tick_interval_sec
        self._task: asyncio.Task | None = None
        self._handler_task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        # 测试时可注入 session 工厂；默认懒加载 app.db.SessionLocal（支持夹具 monkeypatch）
        self._session_factory = session_factory
        # 当前正在执行的任务（仅用于展示），单 worker 无需锁
        self.current_task: Task | None = None

    def _recover_stale_tasks(self) -> int:
        """启动时把上次崩溃遗留的 running 任务重置为 pending，避免永远卡住。"""
        from app.db import SessionLocal
        factory = self._session_factory or SessionLocal
        with factory() as db:
            tasks = db.execute(
                select(Task).where(Task.status == "running")
            ).scalars().all()
            for task in tasks:
                task.status = "pending"
                task.error = None
            if tasks:
                db.commit()
                log.info("recovered %d stale running task(s) to pending", len(tasks))
            return len(tasks)

    async def start(self) -> None:
        self._stop.clear()
        self._wake.clear()
        recovered = self._recover_stale_tasks()
        self._task = asyncio.create_task(self._loop(), name="task-runner")
        log.info("task runner started, interval=%.1fs, recovered=%d", self.interval, recovered)

    async def stop(self) -> None:
        self._stop.set()
        self._wake.set()  # 立即唤醒 sleep
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except asyncio.TimeoutError:
                self._task.cancel()
        self._task = None
        log.info("task runner stopped")

    def notify(self) -> None:
        """让下一轮 tick 立即执行（不等 interval）。"""
        self._wake.set()

    def cancel_current_handler(self) -> bool:
        """取消当前正在执行的 handler 任务。返回是否成功触发取消。"""
        if self._handler_task is None or self._handler_task.done():
            return False
        self._handler_task.cancel()
        return True

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.tick()
            except Exception:
                log.exception("tick failed")
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()

    async def tick(self) -> str | None:
        """处理一条 pending 任务；返回处理过的 task_id 或 None。"""
        from app.db import SessionLocal  # 懒加载，便于测试 monkeypatch
        factory = self._session_factory or SessionLocal
        with factory() as db:
            task = db.execute(
                select(Task)
                .where(Task.status == "pending")
                .order_by(Task.priority.desc(), Task.created_at.asc())
                .limit(1)
            ).scalar_one_or_none()
            if task is None:
                return None

            task.status = "running"
            db.commit()
            db.refresh(task)
            self.current_task = task

            try:
                handler = get_handler(task.type)
                self._handler_task = asyncio.create_task(handler(db, task), name=f"handler-{task.task_id}")
                try:
                    await self._handler_task
                except asyncio.CancelledError:
                    task.status = "failed"
                    task.error = {"code": "CANCELLED", "message": "任务已取消"}
                    log.info("task %s cancelled", task.task_id)
                else:
                    task.status = "success"
                finally:
                    self._handler_task = None
            except BizError as e:
                task.status = "failed"
                task.error = {"code": e.code, "message": e.message, "details": e.details}
                log.warning("task %s biz-error: %s", task.task_id, e.message)
            except Exception as e:
                task.status = "failed"
                task.error = {"code": "TASK_FAILED", "message": str(e) or e.__class__.__name__}
                log.exception("task %s failed", task.task_id)
            finally:
                self.current_task = None
                task.finished_at = datetime.now(timezone.utc)
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
            return task.task_id
