"""Task runner 唤醒通知。

将 ``notify_runner`` 独立出来，避免 ``runner <-> handlers`` 之间的循环导入。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.tasks.runner import TaskRunner

_active_runner: TaskRunner | None = None


def notify_runner() -> None:
    """唤醒后台任务 runner（如果有）。"""
    if _active_runner is not None:
        _active_runner.notify()
