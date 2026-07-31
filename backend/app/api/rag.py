"""UP 复盘 RAG API。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.errors import BizError
from app.models import Task, Uploader
from app.rag import (
    chat_global_reviews,
    chat_reviews,
    get_stats,
    search_global_reviews,
    search_reviews,
    search_videos,
)
from app.schemas import RagIngestTaskOut
from app.tasks.service import create_task

log = logging.getLogger(__name__)

router = APIRouter(prefix="/rag", tags=["rag"])


class SearchOut(BaseModel):
    items: list[dict]


class ChatIn(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    n_results: int = Field(5, ge=1, le=20)
    mode: str = Field("vector", pattern="^(vector|keyword|hybrid)$")


class ChatOut(BaseModel):
    answer: str
    chunks: list[dict]
    token_usage: Optional[dict] = None


class GlobalChatIn(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    n_results: int = Field(5, ge=1, le=20)
    mode: str = Field("vector", pattern="^(vector|keyword|hybrid)$")
    video_ids: list[str] = Field(default_factory=list)


class VideoSearchOut(BaseModel):
    videos: list[dict]


class StatsOut(BaseModel):
    total_chunks: int


def _get_uploader_dir(uploader_id: str, db: Session) -> tuple[Uploader, Path]:
    """根据 uploader_id 查询 UP 主并返回其复盘目录。"""
    up = db.get(Uploader, uploader_id)
    if up is None:
        raise BizError("UPLOADER_NOT_FOUND", "UP主不存在", http_status=404)

    settings = get_settings()
    directory = Path(settings.review_base_dir) / up.name
    return up, directory


@router.post("/up/{uploader_id}/ingest", response_model=RagIngestTaskOut)
def up_ingest(
    uploader_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """提交重新导入某位 UP 主下所有有字幕视频 RAG 索引的后台任务。"""
    up = db.get(Uploader, uploader_id)
    if up is None:
        raise BizError("UPLOADER_NOT_FOUND", "UP主不存在", http_status=404)

    active = db.execute(
        select(Task).where(
            Task.type == "rag_ingest",
            Task.ref_type == "uploader",
            Task.ref_id == up.id,
            Task.status.in_(["pending", "running"]),
        )
    ).scalar_one_or_none()
    if active is not None:
        return RagIngestTaskOut(task_id=active.task_id, type=active.type)

    task = create_task(
        db,
        task_type="rag_ingest",
        ref_type="uploader",
        ref_id=up.id,
        meta={"up_name": up.name},
    )
    db.commit()
    db.refresh(task)

    runner = getattr(request.app.state, "runner", None)
    if runner is not None:
        runner.notify()

    return RagIngestTaskOut(task_id=task.task_id, type=task.type)


@router.get("/up/{uploader_id}/search", response_model=SearchOut)
async def up_search(
    uploader_id: str,
    q: str = Query(..., min_length=1, max_length=500),
    n: int = Query(5, ge=1, le=20),
    mode: str = Query("vector", pattern="^(vector|keyword|hybrid)$"),
    db: Session = Depends(get_db),
):
    """检索指定 UP 主的复盘观点卡片。"""
    up, _ = _get_uploader_dir(uploader_id, db)
    results = await search_reviews(q, up_name=up.name, n_results=n, mode=mode)
    return SearchOut(items=results)


@router.post("/up/{uploader_id}/chat", response_model=ChatOut)
async def up_chat(
    uploader_id: str,
    payload: ChatIn,
    db: Session = Depends(get_db),
):
    """基于检索结果的 RAG 对话。"""
    up, _ = _get_uploader_dir(uploader_id, db)
    result = await chat_reviews(
        payload.question,
        up_name=up.name,
        n_results=payload.n_results,
        mode=payload.mode,
    )
    return ChatOut(
        answer=result["answer"],
        chunks=result["chunks"],
        token_usage=result.get("token_usage"),
    )


@router.get("/up/{uploader_id}/stats", response_model=StatsOut)
async def up_stats(uploader_id: str, db: Session = Depends(get_db)):
    """返回指定 UP 主已导入 Milvus 的复盘观点卡片数量。"""
    up, _ = _get_uploader_dir(uploader_id, db)
    stats = get_stats(up_name=up.name)
    return StatsOut(total_chunks=stats["total_chunks"])


@router.get("/search", response_model=SearchOut)
async def global_search(
    q: str = Query(..., min_length=1, max_length=500),
    n: int = Query(5, ge=1, le=20),
    mode: str = Query("vector", pattern="^(vector|keyword|hybrid)$"),
):
    """跨所有 UP 主检索观点卡片。"""
    results = await search_global_reviews(q, n_results=n, mode=mode)
    return SearchOut(items=results)


@router.get("/videos/search", response_model=VideoSearchOut)
async def video_search(
    q: str = Query(..., min_length=1, max_length=500),
    n: int = Query(10, ge=1, le=50),
    mode: str = Query("hybrid", pattern="^(vector|keyword|hybrid)$"),
):
    """按话题检索相关视频。"""
    results = await search_videos(q, n_results=n, mode=mode)
    return VideoSearchOut(videos=results)


@router.post("/chat", response_model=ChatOut)
async def global_chat(payload: GlobalChatIn):
    """跨 UP 主（或限定视频）的 RAG 对话。"""
    result = await chat_global_reviews(
        payload.question,
        n_results=payload.n_results,
        mode=payload.mode,
        video_ids=payload.video_ids or None,
    )
    return ChatOut(
        answer=result["answer"],
        chunks=result["chunks"],
        token_usage=result.get("token_usage"),
    )
