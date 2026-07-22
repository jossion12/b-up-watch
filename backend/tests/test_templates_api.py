"""总结模板接口测试：3.4.5 / 3.4.6 / 3.4.7 / 3.4.8。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models import SummaryTemplate


# ---------- helpers ----------

def _valid_prompt():
    return (
        "标题: {{title}}\nUP主: {{uploader}}\n"
        "时长: {{duration}}\n标签: {{tags}}\n字幕: {{subtitle}}\n"
    )


def _seed_default(db):
    # lifespan 已 seed 默认模板，避免 UNIQUE 冲突
    if db.get(SummaryTemplate, "tpl_default") is not None:
        return
    db.add(SummaryTemplate(
        id="tpl_default", name="通用", is_default=True, prompt=_valid_prompt(),
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    ))
    db.commit()


async def _fake_chat_valid(messages, **_):
    return {
        "brief": "测试摘要",
        "points": ["p1", "p2", "p3"],
        "stance": {"label": "积极", "sentiment": "positive", "detail": "好"},
        "topics": ["t1", "t2", "t3"],
        "quote": "金句",
    }, {"prompt_tokens": 1, "completion_tokens": 1}


async def _fake_chat_bad_json(messages, **_):
    return {"brief": "缺字段"}, {}


async def _fake_chat_raises_unconfigured(messages, **_):
    from app.errors import BizError
    raise BizError("LLM_NOT_CONFIGURED", "no api key", http_status=501)


# ---------- 3.4.5 列表 ----------

def test_list_templates_includes_default(client, db_session_factory):
    """lifespan 已 seed 默认模板；多 seed 一个非默认的确认排序。"""
    _seed_default(db_session_factory())
    db = db_session_factory()
    if db.get(SummaryTemplate, "tpl_extra") is None:
        db.add(SummaryTemplate(
            id="tpl_extra", name="extra", is_default=False, prompt=_valid_prompt(),
            created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        ))
        db.commit()

    resp = client.get("/api/v1/summary/templates")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) >= 1
    # 默认排第一
    assert items[0]["is_default"] is True


# ---------- 3.4.6 新建 ----------

def test_create_template_invalid_missing_subtitle(client, db_session_factory):
    resp = client.post("/api/v1/summary/templates", json={
        "name": "X",
        "prompt": "{{title}} {{uploader}} {{duration}} {{tags}}",
        "is_default": False,
    })
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "TEMPLATE_INVALID"


def test_create_template_400_when_trial_fails(client, db_session_factory, monkeypatch):
    _seed_default(db_session_factory())
    from app.api import templates as tpl_api
    monkeypatch.setattr(tpl_api.llm_client, "chat", _fake_chat_bad_json)

    resp = client.post("/api/v1/summary/templates", json={
        "name": "X", "prompt": _valid_prompt(), "is_default": False,
    })
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] in ("SUMMARY_BAD_OUTPUT", "TEMPLATE_TRIAL_FAILED")


def test_create_template_success(client, db_session_factory, monkeypatch):
    _seed_default(db_session_factory())
    from app.api import templates as tpl_api
    monkeypatch.setattr(tpl_api.llm_client, "chat", _fake_chat_valid)

    resp = client.post("/api/v1/summary/templates", json={
        "name": "新模板", "prompt": _valid_prompt(), "is_default": False,
    })
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "新模板"
    assert body["is_default"] is False


def test_create_template_default_unsets_other(client, db_session_factory, monkeypatch):
    _seed_default(db_session_factory())
    from app.api import templates as tpl_api
    monkeypatch.setattr(tpl_api.llm_client, "chat", _fake_chat_valid)

    resp = client.post("/api/v1/summary/templates", json={
        "name": "新默认", "prompt": _valid_prompt(), "is_default": True,
    })
    assert resp.status_code == 201
    new_id = resp.json()["id"]

    # 旧默认应被覆盖
    db = db_session_factory()
    old = db.get(SummaryTemplate, "tpl_default")
    assert old.is_default is False
    new = db.get(SummaryTemplate, new_id)
    assert new.is_default is True


def test_create_template_502_unconfigured_is_forwarded(client, db_session_factory, monkeypatch):
    _seed_default(db_session_factory())
    from app.api import templates as tpl_api
    monkeypatch.setattr(tpl_api.llm_client, "chat", _fake_chat_raises_unconfigured)
    resp = client.post("/api/v1/summary/templates", json={
        "name": "X", "prompt": _valid_prompt(),
    })
    # LLM_NOT_CONFIGURED 透传为原 http_status (501)
    assert resp.status_code == 501


# ---------- 3.4.7 更新 ----------

def test_update_template_success(client, db_session_factory, monkeypatch):
    _seed_default(db_session_factory())
    from app.api import templates as tpl_api
    monkeypatch.setattr(tpl_api.llm_client, "chat", _fake_chat_valid)

    resp = client.put("/api/v1/summary/templates/tpl_default", json={
        "name": "改名", "prompt": _valid_prompt(), "is_default": True,
    })
    assert resp.status_code == 200
    assert resp.json()["name"] == "改名"


def test_update_template_404(client, db_session_factory):
    resp = client.put("/api/v1/summary/templates/nope", json={
        "name": "X", "prompt": _valid_prompt(), "is_default": False,
    })
    assert resp.status_code == 404


def test_update_template_400_bad(client, db_session_factory, monkeypatch):
    _seed_default(db_session_factory())
    from app.api import templates as tpl_api
    monkeypatch.setattr(tpl_api.llm_client, "chat", _fake_chat_bad_json)
    resp = client.put("/api/v1/summary/templates/tpl_default", json={
        "name": "X", "prompt": _valid_prompt(), "is_default": True,
    })
    assert resp.status_code == 400


# ---------- 3.4.8 删除 ----------

def test_delete_template_success(client, db_session_factory):
    db = db_session_factory()
    db.add(SummaryTemplate(
        id="tpl_extra", name="副", is_default=False, prompt=_valid_prompt(),
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    ))
    db.commit()
    resp = client.delete("/api/v1/summary/templates/tpl_extra")
    assert resp.status_code == 204


def test_delete_template_404(client, db_session_factory):
    resp = client.delete("/api/v1/summary/templates/nope")
    assert resp.status_code == 404


def test_delete_default_400(client, db_session_factory):
    _seed_default(db_session_factory())
    resp = client.delete("/api/v1/summary/templates/tpl_default")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "DEFAULT_TEMPLATE_NOT_DELETABLE"
