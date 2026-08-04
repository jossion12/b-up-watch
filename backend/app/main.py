"""FastAPI 应用入口。"""

import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.api.insights import router as insights_router
from app.api.rag import router as rag_router
from app.api.subtitles import router as subtitles_router
from app.api.summaries import router as summaries_router
from app.api.system import router as system_router
from app.api.tasks import router as tasks_router
from app.api.templates import router as templates_router
from app.api.uploaders import router as uploaders_router
from app.api.videos import router as videos_router
from app.bilibili.client import close_client
from app.config import get_settings, set_bilibili_cookie, set_bilibili_sessdata
from app.db import SessionLocal, init_db
from app.errors import register_exception_handlers
from app.tasks.runner import TaskRunner
from app.tasks.scheduler import TaskScheduler
from app.websocket import manager

log = logging.getLogger("upwatch")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    log.info("upwatch backend starting, db=%s", settings.database_url)
    init_db()

    # 从数据库加载 B站 SESSDATA / 完整 Cookie 到内存缓存；.env 作为兜底。
    try:
        with SessionLocal() as db:
            from app.models import SystemConfig

            cfg = db.get(SystemConfig, 1)
            if cfg:
                set_bilibili_sessdata(cfg.bilibili_sessdata)
                set_bilibili_cookie(cfg.bilibili_cookie)
    except Exception as exc:
        log.warning("failed to load bilibili config from db: %s", exc)

    runner = TaskRunner(tick_interval_sec=settings.worker_tick_sec)
    app.state.runner = runner
    if settings.worker_enabled:
        await runner.start()
    else:
        log.info("task runner disabled (UPWATCH_WORKER_ENABLED=false)")

    scheduler: TaskScheduler | None = None
    if settings.worker_enabled and settings.scheduler_enabled:
        scheduler = TaskScheduler(runner)
        app.state.scheduler = scheduler
        await scheduler.start()
    else:
        log.info(
            "task scheduler disabled (worker=%s scheduler=%s)",
            settings.worker_enabled,
            settings.scheduler_enabled,
        )

    try:
        yield
    finally:
        if scheduler is not None:
            await scheduler.stop()
        if settings.worker_enabled:
            await runner.stop()
        await close_client()
        log.info("upwatch backend shutting down")


app = FastAPI(
    title="UP雷达 后端",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)

# 路由前缀 /api/v1
app.include_router(uploaders_router, prefix="/api/v1", tags=["uploaders"])
app.include_router(videos_router, prefix="/api/v1", tags=["videos"])
app.include_router(subtitles_router, prefix="/api/v1", tags=["subtitles"])
app.include_router(summaries_router, prefix="/api/v1", tags=["summaries"])
app.include_router(templates_router, prefix="/api/v1", tags=["templates"])
app.include_router(tasks_router, prefix="/api/v1", tags=["tasks"])
app.include_router(insights_router, prefix="/api/v1", tags=["insights"])
app.include_router(rag_router, prefix="/api/v1", tags=["rag"])
app.include_router(system_router, prefix="/api/v1", tags=["system"])


@app.get("/health", include_in_schema=False)
async def health():
    return {"ok": True}

# ---------- 3.5.3 WebSocket 事件推送 ----------

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # 保持连接，可选接收客户端心跳
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text(json.dumps({"event": "pong"}))
    except WebSocketDisconnect:
        manager.disconnect(websocket)
