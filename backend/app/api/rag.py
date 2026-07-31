"""UP 复盘 RAG API。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.errors import BizError
from app.models import Uploader
from app.rag import chat_reviews, get_stats, ingest_directory, search_reviews

log = logging.getLogger(__name__)

router = APIRouter(prefix="/rag", tags=["rag"])


class IngestOut(BaseModel):
    files: int
    segments: int
    chunks: int


class SearchOut(BaseModel):
    items: list[dict]


class ChatIn(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    n_results: int = Field(5, ge=1, le=20)


class ChatOut(BaseModel):
    answer: str
    chunks: list[dict]
    token_usage: Optional[dict] = None


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


@router.post("/up/{uploader_id}/ingest", response_model=IngestOut)
async def up_ingest(uploader_id: str, db: Session = Depends(get_db)):
    """扫描 UP 主复盘目录并全量导入 Milvus。"""
    up, directory = _get_uploader_dir(uploader_id, db)
    if not directory.exists():
        raise BizError(
            "RAG_DIR_NOT_FOUND",
            f"复盘目录不存在: {directory}",
            http_status=400,
        )

    result = await ingest_directory(
        directory=directory,
        uploader_id=up.id,
        up_name=up.name,
        clear=True,
    )
    return IngestOut(**result)


@router.get("/up/{uploader_id}/search", response_model=SearchOut)
async def up_search(
    uploader_id: str,
    q: str = Query(..., min_length=1, max_length=500),
    n: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db),
):
    """语义检索指定 UP 主的复盘观点卡片。"""
    up, _ = _get_uploader_dir(uploader_id, db)
    results = await search_reviews(q, up_name=up.name, n_results=n)
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
