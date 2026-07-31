"""UP主 API 测试。"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch


def test_list_empty(client):
    r = client.get("/api/v1/uploaders")
    assert r.status_code == 200
    assert r.json() == {"items": [], "total": 0}


def test_create_and_list(client):
    r = client.post("/api/v1/uploaders", json={"bilibili_uid": "946974"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["uploader"]["bilibili_uid"] == "946974"
    assert body["uploader"]["id"]
    assert body["task_id"]

    r2 = client.get("/api/v1/uploaders")
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["total"] == 1
    assert body2["items"][0]["bilibili_uid"] == "946974"


def test_create_with_category(client):
    r = client.post("/api/v1/uploaders", json={"bilibili_uid": "946974", "category": "AI"})
    assert r.status_code == 201, r.text
    assert r.json()["uploader"]["category"] == "AI"


def test_patch_category(client):
    create = client.post("/api/v1/uploaders", json={"bilibili_uid": "946974"}).json()
    uid = create["uploader"]["id"]

    r = client.patch(f"/api/v1/uploaders/{uid}", json={"category": "财经"})
    assert r.status_code == 200, r.text
    assert r.json()["category"] == "财经"

    # 空字符串表示清除分类
    r2 = client.patch(f"/api/v1/uploaders/{uid}", json={"category": ""})
    assert r2.status_code == 200, r.text
    assert r2.json()["category"] is None


def test_list_filter_by_category(client):
    client.post("/api/v1/uploaders", json={"bilibili_uid": "111", "category": "AI"})
    client.post("/api/v1/uploaders", json={"bilibili_uid": "222", "category": "财经"})
    client.post("/api/v1/uploaders", json={"bilibili_uid": "333"})

    r = client.get("/api/v1/uploaders?category=AI")
    assert r.status_code == 200
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["category"] == "AI"

    r2 = client.get("/api/v1/uploaders?category=AI,财经")
    assert r2.status_code == 200
    assert r2.json()["total"] == 2


def test_create_duplicate_409(client):
    client.post("/api/v1/uploaders", json={"bilibili_uid": "946974"})
    r = client.post("/api/v1/uploaders", json={"bilibili_uid": "946974"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "UPLOADER_ALREADY_EXISTS"


def test_create_validation_error(client):
    r = client.post("/api/v1/uploaders", json={})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "INVALID_PARAM"


def test_patch_and_get(client):
    create = client.post("/api/v1/uploaders", json={"bilibili_uid": "946974"}).json()
    uid = create["uploader"]["id"]

    r = client.patch(f"/api/v1/uploaders/{uid}", json={"group_id": "g_ai", "notify_enabled": False})
    assert r.status_code == 200, r.text
    assert r.json()["group_id"] == "g_ai"
    assert r.json()["notify_enabled"] is False

    r2 = client.patch("/api/v1/uploaders/does_not_exist", json={"group_id": "x"})
    assert r2.status_code == 404
    assert r2.json()["error"]["code"] == "UPLOADER_NOT_FOUND"


def test_delete_keep_history(client):
    create = client.post("/api/v1/uploaders", json={"bilibili_uid": "1"}).json()
    uid = create["uploader"]["id"]
    r = client.delete(f"/api/v1/uploaders/{uid}?keep_history=true")
    assert r.status_code == 204
    assert client.get("/api/v1/uploaders").json()["total"] == 0


def test_delete_404(client):
    r = client.delete("/api/v1/uploaders/nope")
    assert r.status_code == 404


def test_list_with_keyword(client):
    client.post("/api/v1/uploaders", json={"bilibili_uid": "111"})
    client.post("/api/v1/uploaders", json={"bilibili_uid": "222"})

    # 名称由添加时默认占位，按 uid 模糊
    r = client.get("/api/v1/uploaders?keyword=222")
    assert r.status_code == 200
    assert r.json()["total"] == 1


def test_search_proxy_success(client):
    fake_raw = [
        {"mid": 946974, "uname": "林亦LYi", "upic": "https://x.jpg", "fans": 100, "usign": "AI"},
        {"mid": 123456, "uname": "另一位", "upic": "https://y.jpg", "fans": 50, "usign": None},
    ]

    # 946974 已关注，用于验证 already_followed 标记
    client.post("/api/v1/uploaders", json={"bilibili_uid": "946974"})

    with patch("app.api.uploaders.bili_search.search_bili_user", new=AsyncMock(return_value=(fake_raw, False))):
        r = client.get("/api/v1/uploaders/search?q=test")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["page"] == 1
    assert body["has_more"] is False
    assert len(body["items"]) == 2
    by_uid = {it["bilibili_uid"]: it for it in body["items"]}
    assert by_uid["946974"]["already_followed"] is True
    assert by_uid["123456"]["already_followed"] is False


def test_search_proxy_rate_limited(client):
    from app.errors import BizError

    async def _raise(*_a, **_kw):
        raise BizError("BILIBILI_RATE_LIMITED", "限流", http_status=429)

    with patch("app.api.uploaders.bili_search.search_bili_user", side_effect=_raise):
        r = client.get("/api/v1/uploaders/search?q=test")
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "BILIBILI_RATE_LIMITED"


def test_search_proxy_bad_response_degraded(client):
    from app.errors import BizError

    async def _raise(*_a, **_kw):
        raise BizError("BILIBILI_BAD_RESPONSE", "B站响应非 JSON", http_status=502)

    with patch("app.api.uploaders.bili_search.search_bili_user", side_effect=_raise):
        r = client.get("/api/v1/uploaders/search?q=test")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["items"] == []
    assert body["has_more"] is False
    assert body["page"] == 1


def test_search_validation(client):
    r = client.get("/api/v1/uploaders/search")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "INVALID_PARAM"


def test_extract_user_items_grouped():
    from app.bilibili.search import _extract_user_items

    data = {
        "numPages": 1,
        "numResults": 1,
        "result": [
            {"result_type": "video", "data": [{"bvid": "BV1"}]},
            {
                "result_type": "bili_user",
                "data": [
                    {"mid": 111, "uname": "用户A", "upic": "https://a.jpg", "fans": 10, "usign": "sig"},
                ],
            },
        ],
    }
    items = _extract_user_items(data)
    assert len(items) == 1
    assert items[0]["mid"] == 111


def test_extract_user_items_flat():
    from app.bilibili.search import _extract_user_items

    data = {
        "numPages": 1,
        "result": [
            {"type": "video", "bvid": "BV1"},
            {"type": "bili_user", "mid": 222, "uname": "用户B", "upic": "", "fans": 0},
        ],
    }
    items = _extract_user_items(data)
    assert len(items) == 1
    assert items[0]["mid"] == 222


def test_extract_user_items_empty():
    from app.bilibili.search import _extract_user_items

    assert _extract_user_items({}) == []
    assert _extract_user_items({"result": []}) == []
    assert _extract_user_items({"result": {}}) == []


# ---------- 优先处理最近视频 ----------


def _make_uploader_and_videos(db_session_factory, video_count: int = 3):
    from datetime import datetime, timezone
    from app.models import DEFAULT_USER_ID, Uploader, Video

    with db_session_factory() as db:
        up = Uploader(
            id=uuid.uuid4().hex[:12],
            user_id=DEFAULT_USER_ID,
            bilibili_uid=uuid.uuid4().hex[:8],
            name="TestUP",
            unread_count=0,
            notify_enabled=True,
        )
        db.add(up)
        db.commit()
        db.refresh(up)

        videos = []
        now = datetime.now(timezone.utc)
        for i in range(video_count):
            v = Video(
                id=uuid.uuid4().hex[:12],
                user_id=DEFAULT_USER_ID,
                bvid=f"BV{uuid.uuid4().hex[:8]}",
                uploader_id=up.id,
                title=f"video {i}",
                duration_sec=120,
                published_at=now,
                has_subtitle=False,
                has_summary=False,
            )
            db.add(v)
            videos.append(v)
        db.commit()
        for v in videos:
            db.refresh(v)
        return up, videos


def test_prioritize_latest_enqueues_tasks(client, db_session_factory):
    up, videos = _make_uploader_and_videos(db_session_factory, video_count=3)

    r = client.post(f"/api/v1/uploaders/{up.id}/prioritize-latest?count=10")
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["enqueued_subtitle"] == 3
    # AI 总结功能已暂停：不再排队总结任务
    assert body["enqueued_summary"] == 0
    assert len(body["task_ids"]) == 3

    from app.models import Task

    with db_session_factory() as db:
        tasks = db.query(Task).filter(Task.ref_id.in_([v.id for v in videos])).all()
        assert len(tasks) == 3
        assert all(t.priority == 10 for t in tasks)


def test_prioritize_latest_skips_active_and_done(client, db_session_factory):
    from datetime import datetime, timezone
    from app.models import Task, Video

    up, videos = _make_uploader_and_videos(db_session_factory, video_count=2)

    # 第一个视频：已有字幕
    with db_session_factory() as db:
        v1 = db.get(Video, videos[0].id)
        v1.has_subtitle = True
        db.commit()

    r = client.post(f"/api/v1/uploaders/{up.id}/prioritize-latest?count=10")
    assert r.status_code == 202, r.text
    body = r.json()
    # v1: 已有字幕，跳过；v2: 一个字幕任务
    # AI 总结功能已暂停：不再排队总结任务
    assert body["enqueued_subtitle"] == 1
    assert body["enqueued_summary"] == 0
    assert len(body["task_ids"]) == 1


def test_prioritize_latest_404(client):
    r = client.post("/api/v1/uploaders/does_not_exist/prioritize-latest")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "UPLOADER_NOT_FOUND"


# ---------- 回溯当年视频 ----------


def _current_year_days_back() -> int:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    year_start = now.date().replace(month=1, day=1)
    return (now.date() - year_start).days


def test_backfill_year_creates_feed_refresh(client, db_session_factory):
    from app.models import Task

    up, _ = _make_uploader_and_videos(db_session_factory, video_count=0)
    expected_days = _current_year_days_back()

    r = client.post(f"/api/v1/uploaders/{up.id}/backfill-year")
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["type"] == "feed_refresh"
    assert body["days_back"] == expected_days

    with db_session_factory() as db:
        task = db.get(Task, body["task_id"])
        assert task is not None
        assert task.type == "feed_refresh"
        assert task.ref_type == "uploader"
        assert task.ref_id == up.id
        assert task.meta.get("days_back") == expected_days
        assert task.meta.get("mode") == "backfill-year"


def test_backfill_year_returns_existing_task(client, db_session_factory):
    from datetime import datetime, timezone
    from app.models import Task

    up, _ = _make_uploader_and_videos(db_session_factory, video_count=0)
    expected_days = _current_year_days_back()

    with db_session_factory() as db:
        existing = Task(
            task_id=uuid.uuid4().hex[:12],
            type="feed_refresh",
            status="pending",
            ref_type="uploader",
            ref_id=up.id,
            created_at=datetime.now(timezone.utc),
        )
        db.add(existing)
        db.commit()
        db.refresh(existing)

    r = client.post(f"/api/v1/uploaders/{up.id}/backfill-year")
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["task_id"] == existing.task_id
    assert body["days_back"] == expected_days

    with db_session_factory() as db:
        assert db.query(Task).filter(Task.ref_id == up.id, Task.type == "feed_refresh").count() == 1


def test_backfill_year_404(client):
    r = client.post("/api/v1/uploaders/does_not_exist/backfill-year")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "UPLOADER_NOT_FOUND"