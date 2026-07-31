"""UP 复盘 RAG 业务服务。

对外提供：扫描目录并导入、语义检索、基于检索的对话。
"""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List

from app.config import get_settings
from app.llm.client import chat
from app.rag.extractor import extract_chunks
from app.rag.milvus_store import MilvusReviewStore
from app.rag.parser import parse_markdown_file

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


async def _build_chunks_from_parsed(
    parsed,
    uploader_id: str,
    up_name: str,
) -> List[Dict[str, Any]]:
    """异步将解析后的复盘文件转换为观点卡片列表。"""
    chunks: List[Dict[str, Any]] = []
    file_slug = _slug(parsed.title)
    for seg_idx, seg in enumerate(parsed.segments, 1):
        extracted = await extract_chunks(
            segment_text=seg.text,
            time_position=seg.time_position,
            video_title=parsed.title,
            up_name=up_name,
        )
        for c_idx, c in enumerate(extracted, 1):
            chunk_id = f"{file_slug}_{seg_idx:03d}_{c_idx:03d}_{uuid.uuid4().hex[:8]}"
            chunks.append({
                "chunk_id": chunk_id,
                "content": c.content,
                "metadata": {
                    "uploader_id": uploader_id,
                    "video_title": parsed.title,
                    "up_name": up_name,
                    "date": parsed.date or "",
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


async def ingest_directory(
    directory: str | Path,
    uploader_id: str,
    up_name: str,
    clear: bool = True,
) -> Dict[str, Any]:
    """扫描目录下所有 Markdown 复盘文件，提取观点卡片并写入 Milvus。

    Args:
        directory: Markdown 文件目录
        uploader_id: UP 主数据库 ID
        up_name: UP 主名称（用于目录与过滤）
        clear: 是否先清空该 UP 主在 collection 中的数据（默认 True，保证幂等）

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
        chunks = await _build_chunks_from_parsed(parsed, uploader_id, up_name)
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
) -> Dict[str, Any]:
    """导入单个 Markdown 复盘文件到 Milvus。

    默认会先删除该 UP 主 + 该视频标题已有的卡片，避免重复写入。
    适用于字幕获取成功后对单个视频做增量更新。

    Args:
        file_path: Markdown 文件路径
        uploader_id: UP 主数据库 ID
        up_name: UP 主名称
        replace_video: 是否先替换同视频标题的已有卡片

    Returns:
        {"segments": 话题段数, "chunks": 观点卡片数}
    """
    store = MilvusReviewStore.get_instance()
    parsed = parse_markdown_file(file_path)

    if replace_video:
        store.clear(filter_expr=_video_filter_expr(up_name, parsed.title))

    chunks = await _build_chunks_from_parsed(parsed, uploader_id, up_name)
    inserted = store.add_chunks(chunks)
    return {
        "segments": len(parsed.segments),
        "chunks": inserted,
    }


async def search_reviews(
    query: str,
    up_name: str,
    n_results: int = 5,
) -> List[Dict[str, Any]]:
    """语义检索指定 UP 主的复盘观点卡片。"""
    store = MilvusReviewStore.get_instance()
    return store.search(
        query,
        n_results=n_results,
        filter_expr=_milvus_filter_expr(up_name),
    )


SYSTEM_PROMPT_TEMPLATE = """你是一位股票复盘观点分析助手。你的回答必须基于检索到的{up_name}观点片段。

规则：
1. 每个观点必须标注来源：日期 + 视频标题 + 时间戳
2. 区分「事实陈述」和「主观观点」，用不同语气表述
3. 如果检索片段不足以回答问题，明确说"根据现有资料无法判断"
4. 用户追问证据时，引用原始论据列表
5. 对于预测类观点，标注给出该预测的时间
"""


async def chat_reviews(
    question: str,
    up_name: str,
    n_results: int = 5,
) -> Dict[str, Any]:
    """基于检索结果的 RAG 对话。"""
    chunks = await search_reviews(question, up_name=up_name, n_results=n_results)
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
        answer = parsed.get("answer") or parsed.get("content") or str(parsed)
    except Exception as e:
        log.warning("RAG chat LLM failed: %s", e)
        answer = "模型调用失败，请稍后重试。"
        usage = {}

    return {"answer": answer, "chunks": chunks, "token_usage": usage}


def _build_context(chunks: List[Dict[str, Any]], up_name: str) -> str:
    lines: List[str] = []
    for i, c in enumerate(chunks, 1):
        meta = c["metadata"]
        lines.append(f"【片段{i}】")
        lines.append(
            f"来源: {meta.get('date', '')} {up_name}《{meta.get('video_title', '未知标题')}》{meta.get('time_position', '')}"
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
