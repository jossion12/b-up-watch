"""3.2.1 时间线 / 3.2.3 手动刷新。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.models import Uploader, Video


def _seed(db, *, days_offset: int = 0, status: str = "new", uploader_id: str = "u1"):
    v = Video(
        id=uuid.uuid4().hex[:12],
        user_id="default",
        bvid=f"BV{uuid.uuid4().hex[:10]}",
        uploader_id=uploader_id,
        title="t",
        cover_url=None,
        duration_sec=60,
        published_at=datetime.now(timezone.utc) + timedelta(days=days_offset),
        views=10, danmaku_count=0, likes=1, tags=[], status=status,
        has_subtitle=False, has_summary=False, is_read=False,
    )
    db.add(v)
    return v


def test_videos_timeline_basic(client, db_session_factory):
    with db_session_factory() as db:
        up = Uploader(id="u1", user_id="default", bilibili_uid="1", name="A", unread_count=0, notify_enabled=True)
        db.add(up)
        _seed(db, days_offset=-1)
        _seed(db, days_offset=-3)
        db.commit()

    today = datetime.now(timezone.utc).date().isoformat()
    yesterday = (datetime.now(timezone.utc).date() - timedelta(days=5)).isoformat()
    r = client.get(f"/api/v1/videos?start_date={yesterday}&end_date={today}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2
    assert body["range"] == {"start_date": yesterday, "end_date": today}
    assert len(body["items"]) == 2


def test_videos_timeline_filter_status_and_uploader(client, db_session_factory):
    with db_session_factory() as db:
        up1 = Uploader(id="u1", user_id="default", bilibili_uid="1", name="A", unread_count=0, notify_enabled=True)
        up2 = Uploader(id="u2", user_id="default", bilibili_uid="2", name="B", unread_count=0, notify_enabled=True)
        db.add_all([up1, up2])
        _seed(db, status="new", uploader_id="u1")
        _seed(db, status="summarized", uploader_id="u2")
        _seed(db, status="new", uploader_id="u2")
        db.commit()

    today = datetime.now(timezone.utc).date().isoformat()
    week_ago = (datetime.now(timezone.utc).date() - timedelta(days=7)).isoformat()

    r = client.get(f"/api/v1/videos?start_date={week_ago}&end_date={today}&status=new&up_ids=u2")
    assert r.status_code == 200
    assert r.json()["total"] == 1


def test_videos_timeline_invalid_date(client):
    r = client.get("/api/v1/videos?start_date=bad&end_date=2026-01-01")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "INVALID_PARAM"


def test_videos_timeline_limit_clamped(client, db_session_factory):
    # limit 上限 500，下限 1
    r = client.get("/api/v1/videos?start_date=2026-07-01&end_date=2026-07-19&limit=10000")
    assert r.status_code == 400

    r2 = client.get("/api/v1/videos?start_date=2026-07-01&end_date=2026-07-19&limit=0")
    assert r2.status_code == 400


def test_refresh_creates_pending_task(client):
    r = client.post("/api/v1/videos/refresh")
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["type"] == "feed_refresh"
    assert body["task_id"]

    # 查询任务详情
    r2 = client.get(f"/api/v1/tasks/{body['task_id']}")
    assert r2.status_code == 200
    assert r2.json()["status"] == "pending"  # 测试环境 worker 已关闭

def test_video_detail(client, db_session_factory):
    with db_session_factory() as db:
        up = Uploader(id="u1", user_id="default", bilibili_uid="1", name="A", unread_count=0, notify_enabled=True)
        db.add(up)
        v = _seed(db, uploader_id="u1")
        db.commit()
        vid = v.id

    r = client.get(f"/api/v1/videos/{vid}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == vid
    assert body["uploader"]["id"] == "u1"
    assert body["uploader"]["name"] == "A"


def test_video_detail_404(client):
    r = client.get("/api/v1/videos/does_not_exist")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "VIDEO_NOT_FOUND"


def test_mark_videos_read(client, db_session_factory):
    with db_session_factory() as db:
        up = Uploader(id="u1", user_id="default", bilibili_uid="1", name="A", unread_count=5, notify_enabled=True)
        db.add(up)
        v1 = _seed(db, uploader_id="u1", status="new")
        v2 = _seed(db, uploader_id="u1", status="new")
        db.commit()
        ids = [v1.id, v2.id]

    r = client.patch("/api/v1/videos/read", json={"video_ids": ids})
    assert r.status_code == 204

    with db_session_factory() as db:
        up2 = db.get(Uploader, "u1")
        assert up2.unread_count == 3
        assert db.get(Video, v1.id).is_read is True
        assert db.get(Video, v2.id).is_read is True


def test_mark_videos_read_partial(client, db_session_factory):
    with db_session_factory() as db:
        up = Uploader(id="u1", user_id="default", bilibili_uid="1", name="A", unread_count=2, notify_enabled=True)
        db.add(up)
        v1 = _seed(db, uploader_id="u1", status="new")
        v1.is_read = True
        v2 = _seed(db, uploader_id="u1", status="new")
        db.commit()

    r = client.patch("/api/v1/videos/read", json={"video_ids": [v1.id, v2.id]})
    assert r.status_code == 204

    with db_session_factory() as db:
        up2 = db.get(Uploader, "u1")
        assert up2.unread_count == 1


def test_backfill_likes_by_video(client, db_session_factory):
    with db_session_factory() as db:
        up = Uploader(id="u1", user_id="default", bilibili_uid="1", name="A", unread_count=0, notify_enabled=True)
        db.add(up)
        v = _seed(db, uploader_id="u1")
        db.commit()
        vid = v.id

    r = client.post("/api/v1/videos/backfill-likes", json={"video_id": vid})
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["type"] == "video_stats_refresh"
    assert body["task_id"]

    r2 = client.get(f"/api/v1/tasks/{body['task_id']}")
    assert r2.status_code == 200
    assert r2.json()["status"] == "pending"
    assert r2.json()["ref_type"] == "video"
    assert r2.json()["ref_id"] == vid


def test_backfill_likes_by_uploader(client, db_session_factory):
    with db_session_factory() as db:
        up = Uploader(id="u1", user_id="default", bilibili_uid="1", name="A", unread_count=0, notify_enabled=True)
        db.add(up)
        db.commit()

    r = client.post("/api/v1/videos/backfill-likes", json={"up_id": "u1"})
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["type"] == "video_stats_refresh"

    r2 = client.get(f"/api/v1/tasks/{body['task_id']}")
    assert r2.json()["ref_type"] == "uploader"
    assert r2.json()["ref_id"] == "u1"


def test_backfill_likes_requires_param(client):
    r = client.post("/api/v1/videos/backfill-likes", json={})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_PARAM"


def test_backfill_likes_video_not_found(client):
    r = client.post("/api/v1/videos/backfill-likes", json={"video_id": "not_exist"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "VIDEO_NOT_FOUND"
