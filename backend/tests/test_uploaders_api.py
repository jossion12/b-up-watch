"""UP主 API 测试。"""

from __future__ import annotations

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