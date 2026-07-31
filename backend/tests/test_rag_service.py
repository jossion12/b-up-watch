"""RAG 业务服务测试。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.rag import service as service_mod
from app.rag.service import (
    _milvus_filter_expr,
    _video_filter_expr,
    chat_reviews,
    ingest_directory,
    ingest_file,
    search_reviews,
)


@pytest.fixture()
def mock_store(monkeypatch):
    store = MagicMock()
    store.add_chunks.side_effect = lambda data: len(data)
    store.search.return_value = []
    store.stats.return_value = {"total_chunks": 0}
    monkeypatch.setattr(
        service_mod.MilvusReviewStore,
        "get_instance",
        classmethod(lambda *args, **kwargs: store),
    )
    return store


@pytest.fixture()
def sample_md(tmp_path: Path):
    path = tmp_path / "20260111-test_video.md"
    path.write_text(
        "[00:00.000 -> 00:03.000] 这是第一个观点\n"
        "[00:06.000 -> 00:08.000] 这是第二个观点",
        encoding="utf-8",
    )
    return path


@pytest.mark.asyncio
async def test_ingest_directory_clears_and_adds_chunks(mock_store, tmp_path: Path, monkeypatch):
    async def _fake_extract(segment_text, time_position, video_title, up_name):
        from app.rag.extractor import ArgumentChunk

        return [
            ArgumentChunk(
                content=segment_text,
                content_type="观点",
                argument_role="主论点",
                core_topic="测试主题",
                sub_topics=[],
                stance_type="判断",
                confidence="中",
                verifiability="可验证",
                source_type="UP主本人",
                original_arguments=[],
                time_position=time_position,
            )
        ]

    monkeypatch.setattr(service_mod, "extract_chunks", _fake_extract)

    result = await ingest_directory(
        directory=tmp_path,
        uploader_id="u1",
        up_name="测试UP",
        clear=True,
    )

    assert result["files"] == 0  # tmp_path 下没有 .md
    assert result["segments"] == 0
    assert result["chunks"] == 0
    mock_store.clear.assert_called_once_with(filter_expr=_milvus_filter_expr("测试UP"))


@pytest.mark.asyncio
async def test_ingest_file_replaces_and_adds_chunks(mock_store, sample_md, monkeypatch):
    async def _fake_extract(segment_text, time_position, video_title, up_name):
        from app.rag.extractor import ArgumentChunk

        return [
            ArgumentChunk(
                content=segment_text,
                content_type="观点",
                argument_role="主论点",
                core_topic="测试主题",
                sub_topics=[],
                stance_type="判断",
                confidence="中",
                verifiability="可验证",
                source_type="UP主本人",
                original_arguments=[],
                time_position=time_position,
            )
        ]

    monkeypatch.setattr(service_mod, "extract_chunks", _fake_extract)

    result = await ingest_file(
        file_path=sample_md,
        uploader_id="u1",
        up_name="测试UP",
        replace_video=True,
    )

    assert result["segments"] == 2
    assert result["chunks"] == 2
    mock_store.clear.assert_called_once_with(
        filter_expr=_video_filter_expr("测试UP", "test_video")
    )
    assert mock_store.add_chunks.call_count == 1
    added = mock_store.add_chunks.call_args[0][0]
    assert len(added) == 2
    assert added[0]["metadata"]["video_title"] == "test_video"


def test_milvus_filter_expr_escapes_quotes():
    assert _milvus_filter_expr('UP"A') == 'up_name == "UP\\"A"'


def test_video_filter_expr_escapes_quotes():
    expr = _video_filter_expr('UP"A', 'Title"B')
    assert expr == 'up_name == "UP\\"A" and video_title == "Title\\"B"'


@pytest.mark.asyncio
async def test_search_reviews_passes_filter(mock_store):
    await search_reviews("query", up_name="测试UP", n_results=3)
    mock_store.search.assert_called_once_with(
        "query",
        n_results=3,
        filter_expr=_milvus_filter_expr("测试UP"),
    )


@pytest.mark.asyncio
async def test_chat_reviews_returns_answer_when_chunks_found(mock_store, monkeypatch):
    mock_store.search.return_value = [
        {
            "chunk_id": "c1",
            "content": "答案",
            "metadata": {
                "video_title": "vt",
                "date": "2026-01-01",
                "time_position": "00:00 -> 00:01",
                "content_type": "观点",
                "argument_role": "主论点",
                "stance_type": "判断",
                "original_arguments": [],
            },
        }
    ]

    async def _fake_chat(messages, temperature=0.3):
        return {"answer": "这是回答"}, {"prompt_tokens": 10}

    monkeypatch.setattr(service_mod, "chat", _fake_chat)

    result = await chat_reviews("question", up_name="测试UP", n_results=1)
    assert result["answer"] == "这是回答"
    assert len(result["chunks"]) == 1
