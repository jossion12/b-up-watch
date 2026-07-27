"""summarize_video orchestrator 集成测试：mock LLM + 真实 SQLite。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.collect import fetch_summary
from app.llm import prompts as llm_prompts
from app.models import Subtitle, SummaryTemplate, Video, Uploader


def _make_uploader(db):
    up = Uploader(
        id="up_001",
        user_id="default",
        bilibili_uid="11111",
        name="测试UP",
        fans_count=0,
        unread_count=0,
        created_at=datetime.now(timezone.utc),
    )
    db.add(up)
    db.commit()
    db.refresh(up)
    return up


def _make_video(db, uploader_id):
    v = Video(
        id="v_001",
        user_id="default",
        bvid="BV1xxx",
        uploader_id=uploader_id,
        title="测试视频标题：AI Agent 的现状",
        duration_sec=754,
        published_at=datetime.now(timezone.utc),
        views=0,
        danmaku_count=0,
        likes=0,
        tags=["AI", "Agent"],
        status="subtitled",
        has_subtitle=True,
        has_summary=False,
        created_at=datetime.now(timezone.utc),
    )
    db.add(v)
    db.commit()
    db.refresh(v)
    return v


def _make_subtitle(db, video_id):
    sub = Subtitle(
        video_id=video_id,
        language="zh-CN",
        source="bilibili_ai",
        lines=[
            {"start_sec": 0.0, "end_sec": 2.0, "text": "大家好"},
            {"start_sec": 2.0, "end_sec": 5.0, "text": "今天聊 Agent"},
        ],
        fetched_at=datetime.now(timezone.utc),
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


def _make_template(db, prompt=None, *, is_default=True):
    prompt = prompt or (
        "标题: {{title}}\nUP主: {{uploader}}\n"
        "时长: {{duration}}\n标签: {{tags}}\n字幕: {{subtitle}}\n"
    )
    t = SummaryTemplate(
        id="tpl_test",
        name="测试模板",
        is_default=is_default,
        prompt=prompt,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _valid_llm_json():
    return {
        "brief": "本视频讨论 AI Agent 现状",
        "points": ["p1", "p2", "p3"],
        "stance": {"label": "积极", "sentiment": "positive", "detail": "看好"},
        "topics": ["AI", "Agent", "趋势"],
        "quote": "Agent 很有趣",
    }


@pytest.mark.asyncio
async def test_summarize_video_writes_summary(db_session_factory, monkeypatch):
    from app.errors import BizError
    db = db_session_factory()
    try:
        up = _make_uploader(db)
        v = _make_video(db, up.id)
        _make_subtitle(db, v.id)
        _make_template(db)

        async def fake_chat(messages, **_kwargs):
            return _valid_llm_json(), {"prompt_tokens": 100, "completion_tokens": 50}

        monkeypatch.setattr(fetch_summary.llm_client, "chat", fake_chat)

        # AI 总结功能已暂停
        with pytest.raises(BizError) as excinfo:
            await fetch_summary.summarize_video(db, v)
        assert excinfo.value.code == "AI_SUMMARY_DISABLED"
    finally:
        db.close()


@pytest.mark.asyncio
async def test_summarize_video_missing_subtitle(db_session_factory):
    from app.errors import BizError
    db = db_session_factory()
    try:
        up = _make_uploader(db)
        v = _make_video(db, up.id)
        # 故意不加 Subtitle
        _make_template(db)
        with pytest.raises(BizError) as excinfo:
            await fetch_summary.summarize_video(db, v)
        # AI 总结功能已暂停：优先返回禁用错误
        assert excinfo.value.code == "AI_SUMMARY_DISABLED"
    finally:
        db.close()


@pytest.mark.asyncio
async def test_summarize_video_bad_llm_json(db_session_factory, monkeypatch):
    from app.errors import BizError
    db = db_session_factory()
    try:
        up = _make_uploader(db)
        v = _make_video(db, up.id)
        _make_subtitle(db, v.id)
        _make_template(db)

        async def fake_chat(messages, **_kwargs):
            return {"brief": "缺字段"}, {}  # 缺 points/stance/topics/quote

        monkeypatch.setattr(fetch_summary.llm_client, "chat", fake_chat)

        # AI 总结功能已暂停：直接返回禁用错误，不再调用 LLM 校验
        with pytest.raises(BizError) as excinfo:
            await fetch_summary.summarize_video(db, v)
        assert excinfo.value.code == "AI_SUMMARY_DISABLED"
    finally:
        db.close()


def test_render_with_duration_format():
    """通过 render_template 检查 _format_duration 内部逻辑。"""
    rendered = llm_prompts.render_template(
        "时长: {{duration}}",
        {"duration": "12:34", "title": "x", "uploader": "y", "tags": "", "subtitle": ""},
    )
    assert rendered == "时长: 12:34"


def test_validate_summary_output_fills_missing_stance_label():
    """stance.label 缺失或为空时，默认填充为 '未明确'。"""
    raw = {
        "brief": "brief",
        "points": ["p1"],
        "stance": {"label": "", "sentiment": "positive", "detail": "detail"},
        "topics": ["t1"],
        "quote": "quote",
    }
    obj = llm_prompts.validate_summary_output(raw)
    assert obj["stance"]["label"] == "未明确"


def test_validate_summary_output_normalizes_chinese_sentiment():
    """sentiment 为中文情感词时，映射为英文枚举。"""
    raw = {
        "brief": "brief",
        "points": ["p1"],
        "stance": {"label": "看好", "sentiment": "乐观", "detail": "detail"},
        "topics": ["t1"],
        "quote": "quote",
    }
    obj = llm_prompts.validate_summary_output(raw)
    assert obj["stance"]["sentiment"] == "positive"


def test_validate_summary_output_defaults_invalid_sentiment():
    """sentiment 无法识别时，默认使用 neutral。"""
    raw = {
        "brief": "brief",
        "points": ["p1"],
        "stance": {"label": "x", "sentiment": "unknown", "detail": "detail"},
        "topics": ["t1"],
        "quote": "quote",
    }
    obj = llm_prompts.validate_summary_output(raw)
    assert obj["stance"]["sentiment"] == "neutral"


def test_validate_summary_output_accepts_fewer_points_and_truncates_topics():
    """points/topics 数量在 1-5 之间均可，超过 5 条时截断。"""
    raw = {
        "brief": "brief",
        "points": ["p1"],
        "stance": {"label": "x", "sentiment": "neutral", "detail": "detail"},
        "topics": ["t1", "t2", "t3", "t4", "t5", "t6"],
        "quote": "quote",
    }
    obj = llm_prompts.validate_summary_output(raw)
    assert len(obj["points"]) == 1
    assert len(obj["topics"]) == 5
