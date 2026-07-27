"""AI 总结接口测试：3.4.1 / 3.4.2 / 3.4.3 / 3.4.4。"""

from __future__ import annotations

from datetime import datetime, timezone

from app.errors import BizError
from app.models import Subtitle, Summary, SummaryTemplate, Uploader, Video


# ---------- helpers ----------

def _seed_video(db, *, with_subtitle=True, with_summary=False):
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
    db.flush()
    v = Video(
        id="v_001",
        user_id="default",
        bvid="BV1xxx",
        uploader_id=up.id,
        title="视频",
        duration_sec=60,
        published_at=datetime.now(timezone.utc),
        views=0, danmaku_count=0, likes=0,
        tags=[],
        status="subtitled",
        has_subtitle=with_subtitle,
        has_summary=with_summary,
        created_at=datetime.now(timezone.utc),
    )
    db.add(v)
    if with_subtitle:
        db.add(Subtitle(
            video_id=v.id, language="zh-CN", source="bilibili_ai",
            lines=[{"start_sec": 0.0, "end_sec": 2.0, "text": "x"}],
            fetched_at=datetime.now(timezone.utc),
        ))
    if with_summary:
        db.add(Summary(
            video_id=v.id,
            template_id="tpl_default",
            brief="已有摘要",
            points=["p1", "p2", "p3"],
            stance={"label": "L", "sentiment": "positive", "detail": "D"},
            topics=["t1", "t2", "t3"],
            quote="Q",
            model="x",
            token_usage={},
            created_at=datetime.now(timezone.utc),
        ))
        v.has_summary = True
    # 默认模板在 lifespan 中已 seed，避免 UNIQUE 冲突
    if db.get(SummaryTemplate, "tpl_default") is None:
        db.add(SummaryTemplate(
            id="tpl_default", name="default", is_default=True, prompt="...",
            created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        ))
    db.commit()
    return v


# ---------- 3.4.1 ----------

def test_create_summary_returns_disabled(client, db_session_factory, monkeypatch):
    db = db_session_factory()
    v = _seed_video(db)
    # 关掉 runner.notify 副作用
    class FakeRunner:
        def notify(self): pass
    monkeypatch.setattr(client.app.state, "runner", FakeRunner())

    # AI 总结功能已暂停
    resp = client.post("/api/v1/videos/v_001/summary", json={})
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "AI_SUMMARY_DISABLED"


def test_create_summary_returns_existing_when_no_force(client, db_session_factory):
    # AI 总结功能已暂停：即使已有总结，创建接口也返回 503
    _seed_video(db_session_factory(), with_summary=True)
    resp = client.post("/api/v1/videos/v_001/summary", json={"force": False})
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "AI_SUMMARY_DISABLED"


def test_create_summary_with_force_returns_disabled(client, db_session_factory, monkeypatch):
    _seed_video(db_session_factory(), with_summary=True)
    class FakeRunner:
        def notify(self): pass
    monkeypatch.setattr(client.app.state, "runner", FakeRunner())

    # AI 总结功能已暂停
    resp = client.post("/api/v1/videos/v_001/summary", json={"force": True})
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "AI_SUMMARY_DISABLED"


def test_create_summary_disabled_even_when_video_missing(client, db_session_factory):
    # AI 总结功能已暂停：创建接口直接返回 503，不再校验视频是否存在
    db = db_session_factory()
    db.commit()
    resp = client.post("/api/v1/videos/nope/summary", json={})
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "AI_SUMMARY_DISABLED"


def test_create_summary_disabled_even_when_template_missing(client, db_session_factory):
    # AI 总结功能已暂停：创建接口直接返回 503，不再校验模板
    _seed_video(db_session_factory())
    resp = client.post("/api/v1/videos/v_001/summary", json={"template_id": "nope"})
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "AI_SUMMARY_DISABLED"


def test_create_summary_disabled_when_no_subtitle(client, db_session_factory):
    # AI 总结功能已暂停：不再级联创建字幕任务
    _seed_video(db_session_factory(), with_subtitle=False)
    resp = client.post("/api/v1/videos/v_001/summary", json={})
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "AI_SUMMARY_DISABLED"


def test_create_summary_disabled_even_on_dup_task(client, db_session_factory):
    from app.models import Task
    _seed_video(db_session_factory())
    db = db_session_factory()
    db.add(Task(
        task_id="dup_task", type="ai_summary", status="running",
        progress=0, ref_type="video", ref_id="v_001",
        created_at=datetime.now(timezone.utc),
    ))
    db.commit()
    # AI 总结功能已暂停：不再进行任务冲突检查
    resp = client.post("/api/v1/videos/v_001/summary", json={})
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "AI_SUMMARY_DISABLED"


# ---------- 3.4.2 ----------

def test_get_summary_success(client, db_session_factory):
    _seed_video(db_session_factory(), with_summary=True)
    resp = client.get("/api/v1/videos/v_001/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["video_id"] == "v_001"
    assert body["stance"]["sentiment"] == "positive"


def test_get_summary_404_when_missing(client, db_session_factory):
    _seed_video(db_session_factory())  # 无 summary
    resp = client.get("/api/v1/videos/v_001/summary")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "SUMMARY_NOT_FOUND"


def test_get_summary_404_when_video_missing(client, db_session_factory):
    resp = client.get("/api/v1/videos/nope/summary")
    assert resp.status_code == 404


# ---------- 3.4.3 ----------

def test_regenerate_returns_disabled(client, db_session_factory):
    # AI 总结功能已暂停
    _seed_video(db_session_factory(), with_summary=True)
    resp = client.post("/api/v1/videos/v_001/summary/regenerate", json={})
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "AI_SUMMARY_DISABLED"


def test_regenerate_disabled_even_when_template_missing(client, db_session_factory):
    # AI 总结功能已暂停
    _seed_video(db_session_factory())
    resp = client.post(
        "/api/v1/videos/v_001/summary/regenerate",
        json={"template_id": "nope"},
    )
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "AI_SUMMARY_DISABLED"


# ---------- 3.4.4 ----------

def test_batch_summarize_returns_disabled(client, db_session_factory):
    # AI 总结功能已暂停
    _seed_video(db_session_factory())
    db = db_session_factory()
    v2 = Video(
        id="v_002", user_id="default", bvid="BV2", uploader_id="up_001",
        title="v2", duration_sec=10,
        published_at=datetime.now(timezone.utc),
        views=0, danmaku_count=0, likes=0, tags=[],
        status="subtitled", has_subtitle=True, has_summary=False,
        created_at=datetime.now(timezone.utc),
    )
    db.add(v2)
    db.commit()

    resp = client.post("/api/v1/summaries/batch", json={
        "video_ids": ["v_001", "v_002", "nope"],
        "template_id": "tpl_default",
    })
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "AI_SUMMARY_DISABLED"


def test_batch_summarize_disabled_even_when_template_missing(client, db_session_factory):
    # AI 总结功能已暂停
    _seed_video(db_session_factory())
    resp = client.post("/api/v1/summaries/batch", json={
        "video_ids": ["v_001"], "template_id": "nope",
    })
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "AI_SUMMARY_DISABLED"
