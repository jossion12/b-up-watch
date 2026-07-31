"""UP 复盘 RAG 业务服务。

对外提供：扫描目录并导入、语义检索、基于检索的对话。
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from pathlib import Path
from datetime import datetime
from typing import Any, Callable, Dict, List, Literal, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import BizError
from app.llm.client import chat
from app.models import Video
from app.rag.extractor import extract_chunks
from app.rag.milvus_store import MilvusReviewStore
from app.rag.parser import parse_markdown_file, segments_from_subtitle_lines

log = logging.getLogger(__name__)

DEFAULT_PAUSE_THRESHOLD = 2.5


def _slug(text: str) -> str:
    """生成 ID 用的 slug。"""
    if not text:
        return "unknown"
    return re.sub(r"[^\w]", "_", text)[:40]


def _milvus_filter_expr(up_name: str) -> str:
    """生成按 UP 主过滤的 Milvus expression。"""
    # Milvus expression 需要转义双引号
    escaped = up_name.replace('"', '\\"')
    return f'up_name == "{escaped}"'


def _video_filter_expr(up_name: str, video_title: str) -> str:
    """生成按 UP 主 + 视频标题过滤的 Milvus expression。"""
    up_escaped = up_name.replace('"', '\\"')
    title_escaped = video_title.replace('"', '\\"')
    return f'up_name == "{up_escaped}" and video_title == "{title_escaped}"'


def _video_id_filter_expr(video_id: str) -> str:
    """生成按视频 ID 过滤的 Milvus expression。"""
    escaped = video_id.replace('"', '\\"')
    return f'video_id == "{escaped}"'


def _video_ids_filter_expr(video_ids: List[str]) -> str:
    """生成按多个视频 ID 过滤的 Milvus expression。"""
    escaped = [v.replace('"', '\\"') for v in video_ids]
    inner = ", ".join(f'"{v}"' for v in escaped)
    return f"video_id in [{inner}]"


def _combine_filter_exprs(*exprs: Optional[str]) -> Optional[str]:
    """组合多个 Milvus 过滤表达式。"""
    non_empty = [e for e in exprs if e]
    if not non_empty:
        return None
    if len(non_empty) == 1:
        return non_empty[0]
    return " and ".join(f"({e})" for e in non_empty)


def _iso_or_empty(dt: Optional[datetime]) -> str:
    return dt.isoformat() if dt else ""


def _lookup_video_by_title(db: Session, uploader_id: str, title: str) -> Optional[Video]:
    """根据标题（或归档文件名中的标题）查找视频。"""
    from app.collect.fetch_subtitle import _sanitize_filename

    # 先尝试精确匹配
    video = db.execute(
        select(Video).where(
            Video.uploader_id == uploader_id,
            Video.title == title,
        )
    ).scalars().first()
    if video is not None:
        return video

    # 再按归档文件名中的 sanitized title 匹配
    sanitized = _sanitize_filename(title)
    candidates = db.execute(
        select(Video).where(Video.uploader_id == uploader_id)
    ).scalars().all()
    for v in candidates:
        if _sanitize_filename(v.title) == sanitized:
            return v
    return None


async def _build_chunks_from_segments(
    segments,
    uploader_id: str,
    up_name: str,
    video_title: str,
    date: str,
    video_id: str = "",
    published_at: str = "",
) -> List[Dict[str, Any]]:
    """异步将话题段列表转换为观点卡片列表。"""
    chunks: List[Dict[str, Any]] = []
    file_slug = _slug(video_title)
    for seg_idx, seg in enumerate(segments, 1):
        extracted = await extract_chunks(
            segment_text=seg.text,
            time_position=seg.time_position,
            video_title=video_title,
            up_name=up_name,
        )
        for c_idx, c in enumerate(extracted, 1):
            chunk_id = f"{file_slug}_{seg_idx:03d}_{c_idx:03d}_{uuid.uuid4().hex[:8]}"
            chunks.append({
                "chunk_id": chunk_id,
                "content": c.content,
                "metadata": {
                    "uploader_id": uploader_id,
                    "video_id": video_id,
                    "video_title": video_title,
                    "up_name": up_name,
                    "date": date,
                    "published_at": published_at,
                    "time_position": c.time_position,
                    "content_type": c.content_type,
                    "argument_role": c.argument_role,
                    "core_topic": c.core_topic,
                    "sub_topics": c.sub_topics,
                    "stance_type": c.stance_type,
                    "confidence": c.confidence,
                    "verifiability": c.verifiability,
                    "source_type": c.source_type,
                    "original_arguments": c.original_arguments,
                },
            })
    return chunks


async def _build_chunks_from_parsed(
    parsed,
    uploader_id: str,
    up_name: str,
    video_id: str = "",
    published_at: str = "",
) -> List[Dict[str, Any]]:
    """异步将解析后的复盘文件转换为观点卡片列表。"""
    return await _build_chunks_from_segments(
        segments=parsed.segments,
        uploader_id=uploader_id,
        up_name=up_name,
        video_title=parsed.title,
        date=parsed.date or "",
        video_id=video_id,
        published_at=published_at,
    )


async def ingest_directory(
    directory: str | Path,
    uploader_id: str,
    up_name: str,
    clear: bool = True,
    db: Optional[Session] = None,
) -> Dict[str, Any]:
    """扫描目录下所有 Markdown 复盘文件，提取观点卡片并写入 Milvus。

    Args:
        directory: Markdown 文件目录
        uploader_id: UP 主数据库 ID
        up_name: UP 主名称（用于目录与过滤）
        clear: 是否先清空该 UP 主在 collection 中的数据（默认 True，保证幂等）
        db: 可选的数据库会话；提供时会尝试把文件与 DB 中的 video 关联，写入 video_id

    Returns:
        {"files": 文件数, "segments": 话题段数, "chunks": 观点卡片数}
    """
    store = MilvusReviewStore.get_instance()
    if clear:
        store.clear(filter_expr=_milvus_filter_expr(up_name))

    dir_path = Path(directory)
    files = sorted([p for p in dir_path.glob("*.md") if p.is_file()])

    total_segments = 0
    all_chunks: List[Dict[str, Any]] = []

    for file_path in files:
        log.info("Processing %s", file_path.name)
        parsed = parse_markdown_file(file_path)
        total_segments += len(parsed.segments)

        video_id = ""
        published_at = ""
        if db is not None:
            video = _lookup_video_by_title(db, uploader_id, parsed.title)
            if video is not None:
                video_id = video.id
                published_at = _iso_or_empty(video.published_at)

        chunks = await _build_chunks_from_parsed(
            parsed, uploader_id, up_name, video_id=video_id, published_at=published_at
        )
        all_chunks.extend(chunks)

    inserted = store.add_chunks(all_chunks)
    return {
        "files": len(files),
        "segments": total_segments,
        "chunks": inserted,
    }


async def ingest_file(
    file_path: str | Path,
    uploader_id: str,
    up_name: str,
    replace_video: bool = True,
    db: Optional[Session] = None,
) -> Dict[str, Any]:
    """导入单个 Markdown 复盘文件到 Milvus。

    默认会先删除该 UP 主 + 该视频标题已有的卡片，避免重复写入。
    适用于字幕获取成功后对单个视频做增量更新。

    Args:
        file_path: Markdown 文件路径
        uploader_id: UP 主数据库 ID
        up_name: UP 主名称
        replace_video: 是否先替换同视频标题的已有卡片
        db: 可选的数据库会话；提供时会尝试把文件与 DB 中的 video 关联

    Returns:
        {"segments": 话题段数, "chunks": 观点卡片数}
    """
    store = MilvusReviewStore.get_instance()
    parsed = parse_markdown_file(file_path)

    if replace_video:
        store.clear(filter_expr=_video_filter_expr(up_name, parsed.title))

    video_id = ""
    published_at = ""
    if db is not None:
        video = _lookup_video_by_title(db, uploader_id, parsed.title)
        if video is not None:
            video_id = video.id
            published_at = _iso_or_empty(video.published_at)

    chunks = await _build_chunks_from_parsed(
        parsed, uploader_id, up_name, video_id=video_id, published_at=published_at
    )
    inserted = store.add_chunks(chunks)
    return {
        "segments": len(parsed.segments),
        "chunks": inserted,
    }


async def ingest_video(
    video_id: str,
    db: Session,
    replace: bool = True,
) -> Dict[str, Any]:
    """从 DB 读取单个视频的字幕，提取观点卡片并写入 Milvus。

    这是日常增量导入的推荐入口：字幕获取成功后直接调用，无需先写 Markdown。

    Args:
        video_id: 视频数据库 ID
        db: 数据库会话
        replace: 是否先删除该视频已有 chunk（默认 True，保证幂等）

    Returns:
        {"segments": 话题段数, "chunks": 观点卡片数}
    """
    from app.models import Subtitle

    video = db.get(Video, video_id)
    if video is None:
        raise BizError("VIDEO_NOT_FOUND", "视频不存在", http_status=404)

    sub = db.get(Subtitle, video_id)
    if sub is None or not sub.lines:
        return {"segments": 0, "chunks": 0}

    up = video.uploader
    segments = segments_from_subtitle_lines(sub.lines)
    date_str = video.published_at.strftime("%Y-%m-%d") if video.published_at else ""
    published_at_str = _iso_or_empty(video.published_at)

    store = MilvusReviewStore.get_instance()
    if replace:
        store.clear(filter_expr=_video_id_filter_expr(video_id))

    chunks = await _build_chunks_from_segments(
        segments=segments,
        uploader_id=up.id,
        up_name=up.name,
        video_title=video.title,
        date=date_str,
        video_id=video.id,
        published_at=published_at_str,
    )
    inserted = store.add_chunks(chunks)
    return {"segments": len(segments), "chunks": inserted}


async def ingest_uploader(
    uploader_id: str,
    db: Session,
    up_name: str,
    on_progress: Optional[Callable[[int], None]] = None,
) -> Dict[str, Any]:
    """重建某位 UP 主下所有有字幕视频的 RAG 索引。

    作为 /up/{id}/ingest 全量重建的后端实现。

    Args:
        on_progress: 每处理完一个视频回调一次，参数为 0-100 的进度百分比。

    Returns:
        {"files": 视频数, "segments": 话题段数, "chunks": 观点卡片数}
    """
    videos = db.execute(
        select(Video).where(
            Video.uploader_id == uploader_id,
            Video.has_subtitle.is_(True),
        )
    ).scalars().all()

    total_segments = 0
    total_chunks = 0
    total = len(videos)
    for i, video in enumerate(videos):
        try:
            result = await ingest_video(video.id, db, replace=True)
            total_segments += result["segments"]
            total_chunks += result["chunks"]
        except Exception as e:
            log.warning("[ingest_uploader] video=%s failed: %s", video.id, e)

        if on_progress is not None and total > 0:
            on_progress(int((i + 1) / total * 100))

    return {
        "files": total,
        "segments": total_segments,
        "chunks": total_chunks,
    }


async def search_reviews(
    query: str,
    up_name: str,
    n_results: int = 5,
    mode: Literal["vector", "keyword", "hybrid"] = "vector",
    video_ids: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """检索指定 UP 主的复盘观点卡片。

    Args:
        query: 查询文本
        up_name: UP 主名称
        n_results: 返回数量
        mode: 检索模式，vector=向量检索，keyword=关键词检索，hybrid=混合检索（RRF）
        video_ids: 可选，进一步限定在若干视频内检索
    """
    store = MilvusReviewStore.get_instance()
    filter_expr = _combine_filter_exprs(
        _milvus_filter_expr(up_name),
        _video_ids_filter_expr(video_ids) if video_ids else None,
    )
    if mode == "keyword":
        return store.keyword_search(query, n_results=n_results, filter_expr=filter_expr)
    if mode == "hybrid":
        return store.hybrid_search(query, n_results=n_results, filter_expr=filter_expr)
    return store.search(query, n_results=n_results, filter_expr=filter_expr)


async def search_global_reviews(
    query: str,
    n_results: int = 5,
    mode: Literal["vector", "keyword", "hybrid"] = "vector",
) -> List[Dict[str, Any]]:
    """跨所有 UP 主检索复盘观点卡片。"""
    store = MilvusReviewStore.get_instance()
    if mode == "keyword":
        return store.keyword_search(query, n_results=n_results, filter_expr=None)
    if mode == "hybrid":
        return store.hybrid_search(query, n_results=n_results, filter_expr=None)
    return store.search(query, n_results=n_results, filter_expr=None)


async def search_videos(
    query: str,
    n_results: int = 10,
    mode: Literal["vector", "keyword", "hybrid"] = "hybrid",
) -> List[Dict[str, Any]]:
    """跨所有 UP 主按话题检索视频。

    先对 chunk 做全局检索，再按 video_id 聚合，返回相关视频列表。
    """
    chunks = await search_global_reviews(query, n_results=n_results * 5, mode=mode)
    groups: Dict[str, Dict[str, Any]] = {}
    for c in chunks:
        meta = c["metadata"]
        vid = meta.get("video_id") or f"{meta.get('up_name')}::{meta.get('video_title')}"
        if vid not in groups:
            groups[vid] = {
                "video_id": meta.get("video_id", ""),
                "video_title": meta.get("video_title", ""),
                "up_name": meta.get("up_name", ""),
                "uploader_id": meta.get("uploader_id", ""),
                "date": meta.get("date", ""),
                "published_at": meta.get("published_at", ""),
                "best_distance": c["distance"],
                "chunk_count": 0,
                "top_chunk": c["content"],
            }
        groups[vid]["chunk_count"] += 1
        if c["distance"] < groups[vid]["best_distance"]:
            groups[vid]["best_distance"] = c["distance"]
            groups[vid]["top_chunk"] = c["content"]

    sorted_groups = sorted(
        groups.values(),
        key=lambda x: (-x["chunk_count"], x["best_distance"]),
    )
    return sorted_groups[:n_results]


SYSTEM_PROMPT_TEMPLATE = """你是一位股票复盘观点分析助手。你的回答必须基于检索到的{up_name}观点片段。

规则：
1. 每个观点必须标注来源：日期 + 视频标题 + 时间戳
2. 区分「事实陈述」和「主观观点」，用不同语气表述
3. 如果检索片段不足以回答问题，明确说"根据现有资料无法判断"
4. 用户追问证据时，引用原始论据列表
5. 对于预测类观点，标注给出该预测的时间
"""


def _normalize_answer(raw: Any) -> str:
    """将 LLM 返回的答案归一化为字符串。

    某些模型会把回答包装成 JSON 数组/对象，这里统一转成可返回的字符串，
    保证上层 ChatOut.answer 始终为 str。
    """
    if isinstance(raw, str):
        return raw
    if raw is None:
        return ""
    try:
        return json.dumps(raw, ensure_ascii=False)
    except TypeError:
        return str(raw)


async def chat_reviews(
    question: str,
    up_name: str,
    n_results: int = 5,
    mode: Literal["vector", "keyword", "hybrid"] = "vector",
) -> Dict[str, Any]:
    """基于检索结果的 RAG 对话。"""
    chunks = await search_reviews(question, up_name=up_name, n_results=n_results, mode=mode)
    if not chunks:
        return {"answer": "根据现有资料库，没有找到相关观点。", "chunks": []}

    context = _build_context(chunks, up_name=up_name)
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(up_name=up_name)
    try:
        parsed, usage = await chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"检索到的观点片段：\n{context}\n\n用户问题：{question}"},
            ],
            temperature=0.3,
        )
        answer = _normalize_answer(
            parsed.get("answer") or parsed.get("content") or parsed
        )
    except Exception as e:
        log.warning("RAG chat LLM failed: %s", e)
        answer = "模型调用失败，请稍后重试。"
        usage = {}

    return {"answer": answer, "chunks": chunks, "token_usage": usage}


GLOBAL_SYSTEM_PROMPT = """你是一位股票复盘观点分析助手。你的回答必须基于检索到的观点片段。

规则：
1. 每个观点必须标注来源：UP主 + 日期 + 视频标题 + 时间戳
2. 区分「事实陈述」和「主观观点」，用不同语气表述
3. 如果检索片段不足以回答问题，明确说"根据现有资料无法判断"
4. 用户追问证据时，引用原始论据列表
5. 对于预测类观点，标注给出该预测的时间
"""


async def chat_global_reviews(
    question: str,
    n_results: int = 5,
    mode: Literal["vector", "keyword", "hybrid"] = "vector",
    video_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """跨 UP 主（或限定视频）的 RAG 对话。"""
    store = MilvusReviewStore.get_instance()
    filter_expr = _video_ids_filter_expr(video_ids) if video_ids else None
    if mode == "keyword":
        chunks = store.keyword_search(question, n_results=n_results, filter_expr=filter_expr)
    elif mode == "hybrid":
        chunks = store.hybrid_search(question, n_results=n_results, filter_expr=filter_expr)
    else:
        chunks = store.search(question, n_results=n_results, filter_expr=filter_expr)

    if not chunks:
        return {"answer": "根据现有资料库，没有找到相关观点。", "chunks": []}

    context = _build_context(chunks)
    try:
        parsed, usage = await chat(
            messages=[
                {"role": "system", "content": GLOBAL_SYSTEM_PROMPT},
                {"role": "user", "content": f"检索到的观点片段：\n{context}\n\n用户问题：{question}"},
            ],
            temperature=0.3,
        )
        answer = _normalize_answer(
            parsed.get("answer") or parsed.get("content") or parsed
        )
    except Exception as e:
        log.warning("Global RAG chat LLM failed: %s", e)
        answer = "模型调用失败，请稍后重试。"
        usage = {}

    return {"answer": answer, "chunks": chunks, "token_usage": usage}


def _build_context(chunks: List[Dict[str, Any]], up_name: str = "") -> str:
    lines: List[str] = []
    for i, c in enumerate(chunks, 1):
        meta = c["metadata"]
        chunk_up_name = meta.get("up_name") or up_name
        lines.append(f"【片段{i}】")
        lines.append(
            f"来源: {meta.get('date', '')} {chunk_up_name}《{meta.get('video_title', '未知标题')}》{meta.get('time_position', '')}"
        )
        lines.append(
            f"类型: {meta.get('content_type', '')} | 角色: {meta.get('argument_role', '')} | 立场: {meta.get('stance_type', '')}"
        )
        lines.append(f"内容: {c['content']}")
        args = meta.get("original_arguments", [])
        if args:
            lines.append(f"论据: {'; '.join(args)}")
        lines.append("")
    return "\n".join(lines)


def get_stats(up_name: str) -> Dict[str, Any]:
    """返回指定 UP 主已导入 Milvus 的复盘观点卡片数量。"""
    store = MilvusReviewStore.get_instance()
    return store.stats(filter_expr=_milvus_filter_expr(up_name))
