"""任务处理器注册表。

所有具体任务执行逻辑通过 @task_handler("type_name") 注册，runner 只负责
取任务、改状态、调用注册表中的处理器。新增任务类型只需新增 handler 并注册，
无需修改 runner。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from app.errors import BizError

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.models import Task

Handler = Callable[["Session", "Task"], Awaitable[None]]

_REGISTRY: dict[str, Handler] = {}


def task_handler(task_type: str) -> Callable[[Handler], Handler]:
    """装饰器：将函数注册为某类任务的处理器。"""

    def decorator(fn: Handler) -> Handler:
        _REGISTRY[task_type] = fn
        return fn

    return decorator


def get_handler(task_type: str) -> Handler:
    """获取某类任务的处理器；未注册时抛出业务错误。"""
    if task_type not in _REGISTRY:
        raise BizError(
            "TASK_TYPE_UNSUPPORTED",
            f"本期暂不支持任务类型: {task_type}",
            http_status=500,
        )
    return _REGISTRY[task_type]
