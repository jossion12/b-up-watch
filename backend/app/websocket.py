"""WebSocket 事件推送。

提供简单的内存连接管理器与广播函数，供任务、采集、总结等流程调用。
事件契约见接口文档 3.5.3。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

log = logging.getLogger(__name__)


class _ConnectionManager:
    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self._connections:
            self._connections.remove(websocket)

    async def broadcast(self, event: str, payload: dict[str, Any]) -> None:
        if not self._connections:
            return
        message = json.dumps({"event": event, "payload": payload}, ensure_ascii=False, default=_json_default)
        disconnected: list[WebSocket] = []
        for conn in self._connections:
            try:
                await conn.send_text(message)
            except RuntimeError:
                disconnected.append(conn)
            except Exception:
                log.exception("websocket send failed")
                disconnected.append(conn)
        for conn in disconnected:
            self.disconnect(conn)


manager = _ConnectionManager()


def _json_default(obj: Any) -> Any:
    from datetime import datetime
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


async def push_video_new(video: dict[str, Any]) -> None:
    await manager.broadcast("video.new", video)


async def push_task_updated(task: dict[str, Any]) -> None:
    await manager.broadcast("task.updated", task)


async def push_summary_completed(video_id: str, summary: dict[str, Any]) -> None:
    await manager.broadcast("summary.completed", {"video_id": video_id, "summary": summary})


async def push_uploader_unread(uploader_id: str, unread_count: int) -> None:
    await manager.broadcast("uploader.unread", {"uploader_id": uploader_id, "unread_count": unread_count})


def _fire(factory) -> None:
    """在异步上下文中调度一个协程工厂；无事件循环时静默跳过。"""
    try:
        import asyncio
        loop = asyncio.get_running_loop()
        loop.create_task(factory())
    except RuntimeError:
        pass


def push_video_new_sync(video: dict[str, Any]) -> None:
    _fire(lambda: push_video_new(video))


def push_task_updated_sync(task: dict[str, Any]) -> None:
    _fire(lambda: push_task_updated(task))


def push_summary_completed_sync(video_id: str, summary: dict[str, Any]) -> None:
    _fire(lambda: push_summary_completed(video_id, summary))


def push_uploader_unread_sync(uploader_id: str, unread_count: int) -> None:
    _fire(lambda: push_uploader_unread(uploader_id, unread_count))
