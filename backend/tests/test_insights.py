"""洞察聚合与查询接口测试。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models import Summary, Uploader, Video


def _seed_uploader_video(db, *, bvid: str | None = None, days_offset: int = 0):
    up = Uploader(
        id="u1", user_id="default", bilibili_uid="1", name="A",
        unread_count=0, notify_enabled=True,
    )
    db.add(up)
    v = Video(
        id=uuid.uuid4().hex[:12],
        user_id="default",
        bvid=bvid or f"BV{uuid.uuid4().hex[:10]}",
        uploader_id="u1",
        title="t",
        cover_url=None,
        duration_sec=60,
        published_at=datetime.now(timezone.utc) + timedelta(days=days_offset),
        views=100, danmaku_count=5, likes=10, tags=["AI"],
        status="summarized",
        has_subtitle=True, has_summary=True, is_read=False,
    )
    db.add(v)
    return up, v


def test_update_insights_on_summary(client, db_session_factory):
    from app.insights.aggregator import update_insights_for_summary
    from app.models import TopicDailyStat, TopicOpinion, VideoStatsSnapshot

    with db_session_factory() as db:
        up, v = _seed_uploader_video(db, days_offset=-1)
        summary = Summary(
            video_id=v.id,
            template_id="tpl_default",
            brief="brief",
            points=["p1", "p2", "p3"],
            stance={"label": "谨慎乐观", "sentiment": "mixed", "detail": "观点详情"},
            topics=["AI Agent", "开源"],
            quote="q",
            model="m",
            token_usage={"prompt": 1, "completion": 1},
            created_at=datetime.now(timezone.utc),
        )
        db.add(summary)
        db.commit()

        update_insights_for_summary(db, v, summary)

        assert db.query(TopicDailyStat).filter_by(video_id=v.id).count() == 2
        assert db.query(TopicOpinion).filter_by(video_id=v.id).count() == 2
        assert db.query(VideoStatsSnapshot).filter_by(video_id=v.id).count() == 1


def test_insights_overview(client, db_session_factory):
    from app.insights.aggregator import update_insights_for_summary

    with db_session_factory() as db:
        up, v = _seed_uploader_video(db, days_offset=-1)
        summary = Summary(
            video_id=v.id, template_id="tpl_default", brief="b",
            points=["p1", "p2", "p3"],
            stance={"label": "l", "sentiment": "positive", "detail": "d"},
            topics=["AI Agent"],
            quote="q", model="m", token_usage={},
            created_at=datetime.now(timezone.utc),
        )
        db.add(summary)
        db.commit()
        update_insights_for_summary(db, v, summary)

    r = client.get("/api/v1/insights/overview?days=7")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["monitored_uploaders"] == 1
    assert body["week_new_videos"] == 1
    assert body["summarized_count"] == 1
    assert body["summary_coverage"] == 1.0
    assert body["hot_topic_count"] == 1


def test_insights_topic_trend(client, db_session_factory):
    from app.insights.aggregator import update_insights_for_summary

    with db_session_factory() as db:
        up, v = _seed_uploader_video(db, days_offset=-1)
        summary = Summary(
            video_id=v.id, template_id="tpl_default", brief="b",
            points=["p1", "p2", "p3"],
            stance={"label": "l", "sentiment": "positive", "detail": "d"},
            topics=["AI Agent"],
            quote="q", model="m", token_usage={},
            created_at=datetime.now(timezone.utc),
        )
        db.add(summary)
        db.commit()
        update_insights_for_summary(db, v, summary)

    r = client.get("/api/v1/insights/topic-trend?days=7")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "series" in body
    assert "AI Agent" in body["topics"]


def test_insights_hot_words(client, db_session_factory):
    from app.insights.aggregator import update_insights_for_summary

    with db_session_factory() as db:
        up, v = _seed_uploader_video(db, days_offset=-1)
        summary = Summary(
            video_id=v.id, template_id="tpl_default", brief="b",
            points=["p1", "p2", "p3"],
            stance={"label": "l", "sentiment": "positive", "detail": "d"},
            topics=["AI Agent"],
            quote="q", model="m", token_usage={},
            created_at=datetime.now(timezone.utc),
        )
        db.add(summary)
        db.commit()
        update_insights_for_summary(db, v, summary)

    r = client.get("/api/v1/insights/hot-words?days=7")
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["word"] == "AI Agent"
    assert body["items"][0]["trend"] == "up"


def test_insights_topic_clusters(client, db_session_factory):
    from app.insights.aggregator import update_insights_for_summary

    with db_session_factory() as db:
        up, v = _seed_uploader_video(db, days_offset=-1)
        summary = Summary(
            video_id=v.id, template_id="tpl_default", brief="b",
            points=["p1", "p2", "p3"],
            stance={"label": "l", "sentiment": "positive", "detail": "观点详情"},
            topics=["AI Agent"],
            quote="q", model="m", token_usage={},
            created_at=datetime.now(timezone.utc),
        )
        db.add(summary)
        db.commit()
        update_insights_for_summary(db, v, summary)

    r = client.get("/api/v1/insights/topic-clusters?days=7")
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["topic"] == "AI Agent"
    assert body["items"][0]["video_count"] == 1
    assert len(body["items"][0]["opinions"]) == 1


def test_insights_top_videos(client, db_session_factory):
    from app.insights.aggregator import update_insights_for_summary

    with db_session_factory() as db:
        up, v = _seed_uploader_video(db, days_offset=-1)
        summary = Summary(
            video_id=v.id, template_id="tpl_default", brief="b",
            points=["p1", "p2", "p3"],
            stance={"label": "l", "sentiment": "positive", "detail": "d"},
            topics=["AI Agent"],
            quote="q", model="m", token_usage={},
            created_at=datetime.now(timezone.utc),
        )
        db.add(summary)
        db.commit()
        update_insights_for_summary(db, v, summary)

    r = client.get("/api/v1/insights/top-videos?days=7&by=views")
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["views"] == 100
