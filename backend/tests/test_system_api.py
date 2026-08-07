"""3.7.1 系统状态。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import httpx
import pytest
import respx

from app.models import Task


def _nav_logged_in() -> httpx.Response:
    return httpx.Response(200, json={
        "code": 0,
        "data": {
            "isLogin": True,
            "wbi_img": {
                "img_url": "https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077f.png",
                "sub_url": "https://i0.hdslb.com/bfs/wbi/4932caff0ff746eab6f01bf08b70ac45.png",
            },
        },
    })


@pytest.fixture()
def reset_bilibili_login_cache():
    from app.bilibili.login import reset_login_cache_for_test
    reset_login_cache_for_test()
    yield
    reset_login_cache_for_test()


@respx.mock
def test_system_status_shape(client, db_session_factory, reset_bilibili_login_cache):
    respx.get("https://api.bilibili.com/x/web-interface/nav").mock(return_value=_nav_logged_in())
    r = client.get("/api/v1/system/status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "last_refresh_at" in body
    assert "refresh_interval_sec" in body
    assert body["running_tasks"] == 0
    assert body["queued_tasks"] == 0
    assert body["llm"]["provider"] == "openai-compatible"
    assert "db_mb" in body["storage"]
    assert body["storage"]["subtitles_count"] == 0
    assert body["bilibili_login"] is True


@respx.mock
def test_system_status_counts_tasks(client, db_session_factory, reset_bilibili_login_cache):
    respx.get("https://api.bilibili.com/x/web-interface/nav").mock(return_value=_nav_logged_in())
    with db_session_factory() as db:
        for i in range(3):
            db.add(Task(
                task_id=uuid.uuid4().hex[:12], type="feed_refresh", status="pending",
                progress=0, created_at=datetime.now(timezone.utc),
            ))
        for i in range(2):
            db.add(Task(
                task_id=uuid.uuid4().hex[:12], type="feed_refresh", status="running",
                progress=10, created_at=datetime.now(timezone.utc),
            ))
        db.commit()

    r = client.get("/api/v1/system/status")
    body = r.json()
    assert body["queued_tasks"] == 3
    assert body["running_tasks"] == 2
    assert body["bilibili_login"] is True


@respx.mock
def test_system_status_bilibili_not_logged_in(client, db_session_factory, reset_bilibili_login_cache):
    respx.get("https://api.bilibili.com/x/web-interface/nav").mock(return_value=httpx.Response(200, json={
        "code": -101,
        "message": "账号未登录",
        "data": {"isLogin": False},
    }))
    r = client.get("/api/v1/system/status")
    assert r.status_code == 200, r.text
    assert r.json()["bilibili_login"] is False

def test_update_system_config(client, db_session_factory):
    r = client.patch("/api/v1/system/config", json={
        "refresh_interval_sec": 300,
        "summary_model": "new-model",
        "auto_summarize": True,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["refresh_interval_sec"] == 300
    assert body["summary_model"] == "new-model"
    assert body["auto_summarize"] is True
    assert body["summary_template_id"] == "tpl_default"


def test_update_system_config_invalid_template(client):
    r = client.patch("/api/v1/system/config", json={"summary_template_id": "not_exist"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "TEMPLATE_NOT_FOUND"


def test_update_system_config_bilibili_sessdata(client):
    r = client.patch("/api/v1/system/config", json={"bilibili_sessdata": "test-sessdata-value"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["bilibili_sessdata"] == "test-sessdata-value"

    r = client.get("/api/v1/system/config")
    assert r.status_code == 200, r.text
    assert r.json()["bilibili_sessdata"] == "test-sessdata-value"


def test_clear_system_config_bilibili_sessdata(client):
    client.patch("/api/v1/system/config", json={"bilibili_sessdata": "to-clear"})
    r = client.patch("/api/v1/system/config", json={"bilibili_sessdata": ""})
    assert r.status_code == 200, r.text
    assert r.json()["bilibili_sessdata"] is None
