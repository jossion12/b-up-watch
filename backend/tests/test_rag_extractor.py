"""RAG 观点卡片提取器测试。"""

from __future__ import annotations

import pytest

from app.rag import extractor as extractor_mod
from app.rag.extractor import ArgumentChunk, ExtractionResult, extract_chunks


@pytest.fixture()
def valid_extraction_result():
    return {
        "chunks": [
            {
                "content": "该股未来一周可能上涨",
                "content_type": "预测",
                "argument_role": "主论点",
                "core_topic": "个股走势预测",
                "sub_topics": ["技术面"],
                "stance_type": "预测",
                "confidence": "中",
                "verifiability": "待验证",
                "source_type": "UP主本人",
                "original_arguments": ["突破了20日均线"],
                "time_position": "00:10 -> 00:20",
                "discard_reason": None,
            }
        ]
    }


@pytest.mark.asyncio
async def test_extract_chunks_returns_valid_chunks(monkeypatch, valid_extraction_result):
    async def _fake_chat(messages, temperature=0.2):
        return valid_extraction_result, {"prompt_tokens": 100, "completion_tokens": 50}

    monkeypatch.setattr(extractor_mod, "chat", _fake_chat)

    chunks = await extract_chunks(
        segment_text="该股未来一周可能上涨，因为突破了20日均线",
        time_position="00:10 -> 00:20",
        video_title="每日复盘",
        up_name="测试UP",
    )

    assert len(chunks) == 1
    assert chunks[0].content == "该股未来一周可能上涨"
    assert chunks[0].core_topic == "个股走势预测"
    assert chunks[0].time_position == "00:10 -> 00:20"


@pytest.mark.asyncio
async def test_extract_chunks_filters_discarded(monkeypatch):
    async def _fake_chat(messages, temperature=0.2):
        return {
            "chunks": [
                {
                    "content": "",
                    "content_type": "情感",
                    "argument_role": "无",
                    "core_topic": "",
                    "sub_topics": [],
                    "stance_type": "无",
                    "confidence": "弱",
                    "verifiability": "不可验证",
                    "source_type": "UP主本人",
                    "original_arguments": [],
                    "time_position": "00:10 -> 00:20",
                    "discard_reason": "纯感叹",
                }
            ]
        }, {}

    monkeypatch.setattr(extractor_mod, "chat", _fake_chat)

    chunks = await extract_chunks(
        segment_text="太牛逼了",
        time_position="00:10 -> 00:20",
        video_title="每日复盘",
        up_name="测试UP",
    )

    assert len(chunks) == 0


@pytest.mark.asyncio
async def test_extract_chunks_falls_back_on_llm_error(monkeypatch):
    async def _fake_chat(messages, temperature=0.2):
        raise RuntimeError("LLM down")

    monkeypatch.setattr(extractor_mod, "chat", _fake_chat)

    chunks = await extract_chunks(
        segment_text="原始字幕文本",
        time_position="00:10 -> 00:20",
        video_title="每日复盘",
        up_name="测试UP",
    )

    assert len(chunks) == 1
    assert chunks[0].content == "原始字幕文本"
    assert chunks[0].content_type == "叙事"
    assert chunks[0].time_position == "00:10 -> 00:20"
