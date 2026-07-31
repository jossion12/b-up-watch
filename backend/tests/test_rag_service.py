"""RAG 业务服务测试。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.rag import service as service_mod
from app.rag.service import (
    _milvus_filter_expr,
    _normalize_answer,
    _video_filter_expr,
    _video_id_filter_expr,
    _video_ids_filter_expr,
    chat_reviews,
    ingest_directory,
    ingest_file,
    ingest_video,
    search_global_reviews,
    search_reviews,
    search_videos,
)


@pytest.fixture()
def mock_store(monkeypatch):
    store = MagicMock()
    store.add_chunks.side_effect = lambda data: len(data)
    store.search.return_value = []
    store.keyword_search.return_value = []
    store.hybrid_search.return_value = []
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
async def test_search_reviews_keyword_mode(mock_store):
    await search_reviews("query", up_name="测试UP", n_results=3, mode="keyword")
    mock_store.keyword_search.assert_called_once_with(
        "query",
        n_results=3,
        filter_expr=_milvus_filter_expr("测试UP"),
    )


@pytest.mark.asyncio
async def test_search_reviews_hybrid_mode(mock_store):
    await search_reviews("query", up_name="测试UP", n_results=3, mode="hybrid")
    mock_store.hybrid_search.assert_called_once_with(
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


@pytest.mark.asyncio
async def test_chat_reviews_hybrid_mode(mock_store, monkeypatch):
    mock_store.hybrid_search.return_value = [
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

    result = await chat_reviews("question", up_name="测试UP", n_results=1, mode="hybrid")
    assert result["answer"] == "这是回答"
    assert len(result["chunks"]) == 1
    mock_store.hybrid_search.assert_called_once()


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("plain text", "plain text"),
        (None, ""),
        ([{"category": "市场宏观", "text": "看好"}], '[{"category": "市场宏观", "text": "看好"}]'),
        ({"answer": "obj"}, '{"answer": "obj"}'),
    ],
)
def test_normalize_answer_converts_non_string_to_json(raw, expected):
    assert _normalize_answer(raw) == expected


def test_video_id_filter_expr_escapes_quotes():
    assert _video_id_filter_expr('v"1') == 'video_id == "v\\"1"'


def test_video_ids_filter_expr():
    expr = _video_ids_filter_expr(["v1", "v2"])
    assert expr == 'video_id in ["v1", "v2"]'


def test_video_ids_filter_expr_escapes_quotes():
    assert _video_ids_filter_expr(['v"1']) == 'video_id in ["v\\"1"]'


@pytest.mark.asyncio
async def test_ingest_video_builds_chunks_with_video_id(
    mock_store, db_session_factory, monkeypatch
):
    from datetime import datetime, timezone

    from app.models import Subtitle, Uploader, Video
    from app.rag.extractor import ArgumentChunk

    db = db_session_factory()
    up = Uploader(id="u1", bilibili_uid="123", name="测试UP")
    published = datetime(2026, 1, 11, 10, 0, 0, tzinfo=timezone.utc)
    video = Video(
        id="v1",
        bvid="BV1",
        uploader_id="u1",
        title="测试视频",
        duration_sec=100,
        published_at=published,
        has_subtitle=True,
        status="subtitled",
    )
    sub = Subtitle(
        video_id="v1",
        source="bilibili_ai",
        lines=[
            {"start_sec": 0.0, "end_sec": 3.0, "text": "第一个观点"},
            {"start_sec": 6.0, "end_sec": 8.0, "text": "第二个观点"},
        ],
    )
    db.add(up)
    db.add(video)
    db.add(sub)
    db.commit()

    async def _fake_extract(segment_text, time_position, video_title, up_name):
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

    result = await ingest_video("v1", db)
    assert result["segments"] == 2
    assert result["chunks"] == 2
    mock_store.clear.assert_called_once_with(filter_expr=_video_id_filter_expr("v1"))
    added = mock_store.add_chunks.call_args[0][0]
    assert added[0]["metadata"]["video_id"] == "v1"
    assert added[0]["metadata"]["uploader_id"] == "u1"
    assert added[0]["metadata"]["published_at"] == published.isoformat()


@pytest.mark.asyncio
async def test_search_global_reviews_no_filter(mock_store):
    await search_global_reviews("query", n_results=3)
    mock_store.search.assert_called_once_with("query", n_results=3, filter_expr=None)


@pytest.mark.asyncio
async def test_search_videos_aggregates_by_video(mock_store, monkeypatch):
    async def _fake_search(query, n_results, mode):
        return [
            {
                "chunk_id": "c1",
                "content": "A",
                "distance": 0.1,
                "metadata": {
                    "video_id": "v1",
                    "video_title": "t1",
                    "up_name": "up1",
                    "uploader_id": "u1",
                    "date": "2026-01-01",
                    "published_at": "2026-01-01T00:00:00+00:00",
                },
            },
            {
                "chunk_id": "c2",
                "content": "B",
                "distance": 0.2,
                "metadata": {
                    "video_id": "v1",
                    "video_title": "t1",
                    "up_name": "up1",
                    "uploader_id": "u1",
                    "date": "2026-01-01",
                    "published_at": "2026-01-01T00:00:00+00:00",
                },
            },
            {
                "chunk_id": "c3",
                "content": "C",
                "distance": 0.3,
                "metadata": {
                    "video_id": "v2",
                    "video_title": "t2",
                    "up_name": "up2",
                    "uploader_id": "u2",
                    "date": "2026-01-02",
                    "published_at": "2026-01-02T00:00:00+00:00",
                },
            },
        ]

    monkeypatch.setattr(service_mod, "search_global_reviews", _fake_search)

    videos = await search_videos("query", n_results=2, mode="vector")
    assert len(videos) == 2
    assert videos[0]["video_id"] == "v1"
    assert videos[0]["chunk_count"] == 2
    assert videos[1]["video_id"] == "v2"
