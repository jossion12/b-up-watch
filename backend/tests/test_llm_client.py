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
