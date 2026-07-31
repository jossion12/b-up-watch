"""LLM 客户端单元测试：JSON 提取与修复。"""

from __future__ import annotations

import pytest

from app.llm import client as llm_client


def test_extract_json_plain_object():
    obj = llm_client._extract_json('{"brief": "test", "points": ["a"]}')
    assert obj == {"brief": "test", "points": ["a"]}


def test_extract_json_code_fence():
    raw = '```json\n{"brief": "x", "points": ["a"]}\n```'
    obj = llm_client._extract_json(raw)
    assert obj == {"brief": "x", "points": ["a"]}


def test_extract_json_with_extra_text():
    raw = '好的，这是结果：\n{"brief": "x", "points": ["a"]}\n希望对你有帮助。'
    obj = llm_client._extract_json(raw)
    assert obj == {"brief": "x", "points": ["a"]}


def test_extract_json_repairs_trailing_comma():
    raw = '{"brief": "x", "points": ["a",],}'
    obj = llm_client._extract_json(raw)
    assert obj == {"brief": "x", "points": ["a"]}


def test_extract_json_repairs_single_quotes():
    raw = "{'brief': 'x', 'points': ['a']}"
    obj = llm_client._extract_json(raw)
    assert obj == {"brief": "x", "points": ["a"]}


def test_extract_json_invalid_returns_none():
    assert llm_client._extract_json("not json at all") is None
    assert llm_client._extract_json("") is None
    assert llm_client._extract_json("{broken") is None


@pytest.mark.asyncio
async def test_chat_retries_empty_content(monkeypatch):
    """第一次返回空内容时，应追加提醒并重试一次。"""

    class FakeSettings:
        llm_base_url = "http://test"
        llm_api_key = ""
        llm_model = "test-model"
        llm_timeout_sec = 10.0
        llm_max_tokens = 100
        llm_json_mode = True

    monkeypatch.setattr(llm_client, "get_settings", lambda: FakeSettings())

    call_count = 0
    captured_payloads = []

    class FakeResponse:
        status_code = 200

        def json(self):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"choices": [{"message": {"content": ""}}], "usage": {}}
            return {"choices": [{"message": {"content": '{"ok": true}'}}], "usage": {}}

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def post(self, url, json=None, headers=None):
            captured_payloads.append(json)
            return FakeResponse()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(llm_client.httpx, "AsyncClient", FakeClient)

    parsed, _ = await llm_client.chat([{"role": "user", "content": "hi"}])

    assert parsed == {"ok": True}
    assert call_count == 2
    assert len(captured_payloads) == 2
    assert captured_payloads[0]["response_format"] == {"type": "json_object"}
    assert captured_payloads[1]["messages"][-1]["content"] == (
        "请只输出合法 JSON，不要添加任何解释或 markdown 代码块。"
    )


@pytest.mark.asyncio
async def test_chat_json_mode_false_omits_response_format(monkeypatch):
    """json_mode=False 时不应发送 response_format。"""

    class FakeSettings:
        llm_base_url = "http://test"
        llm_api_key = ""
        llm_model = "test-model"
        llm_timeout_sec = 10.0
        llm_max_tokens = 100
        llm_json_mode = True

    monkeypatch.setattr(llm_client, "get_settings", lambda: FakeSettings())

    captured_payloads = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": '{"ok": true}'}}], "usage": {}}

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def post(self, url, json=None, headers=None):
            captured_payloads.append(json)
            return FakeResponse()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(llm_client.httpx, "AsyncClient", FakeClient)

    parsed, _ = await llm_client.chat([{"role": "user", "content": "hi"}], json_mode=False)

    assert parsed == {"ok": True}
    assert captured_payloads
    assert "response_format" not in captured_payloads[0]
