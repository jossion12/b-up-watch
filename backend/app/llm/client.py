"""OpenAI 兼容 LLM 客户端。

复用：默认用 settings.llm_base_url / llm_api_key / llm_model；调用方可临时覆盖 model。
返回：解析后的 JSON 内容（dict），以及 token_usage。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

import httpx

from app.config import get_settings
from app.errors import BizError

log = logging.getLogger(__name__)


async def chat(
    messages: list[dict],
    *,
    model: Optional[str] = None,
    temperature: float = 0.2,
    timeout: Optional[float] = None,
) -> tuple[dict, dict]:
    """调用 OpenAI 兼容 /chat/completions，返回 (parsed_json, usage)。"""
    settings = get_settings()
    base_url = settings.llm_base_url.rstrip("/")
    api_key = settings.llm_api_key
    use_model = model or settings.llm_model
    use_timeout = timeout if timeout is not None else settings.llm_timeout_sec or 300.0

    if not base_url:
        raise BizError(
            "LLM_NOT_CONFIGURED",
            "未配置 LLM_BASE_URL",
            http_status=501,
        )
    if not use_model:
        raise BizError("LLM_MODEL_MISSING", "未指定 LLM 模型", http_status=400)

    headers: dict[str, str] = {
        "Content-Type": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "model": use_model,
        "messages": messages,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
        "max_tokens": settings.llm_max_tokens,
    }

    try:
        async with httpx.AsyncClient(timeout=use_timeout) as c:
            resp = await c.post(f"{base_url}/chat/completions", json=payload, headers=headers)
    except httpx.HTTPError as e:
        raise BizError("LLM_UNREACHABLE", f"LLM 不可达: {e}", http_status=502) from e

    if resp.status_code >= 400:
        # 透出上游错误（截断）
        snippet = (resp.text or "")[:300]
        raise BizError(
            "LLM_ERROR",
            f"LLM 返回 {resp.status_code}: {snippet}",
            http_status=502,
        )

    data = resp.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise BizError("LLM_BAD_RESPONSE", f"LLM 响应结构异常: {e}", http_status=502) from e

    usage = data.get("usage") or {}
    parsed = _extract_json(content)
    if parsed is None:
        log.warning("LLM output is not valid JSON, preview: %r", content[:500])
        raise BizError(
            "LLM_BAD_JSON",
            "LLM 输出无法解析为 JSON",
            http_status=502,
            details={"raw_preview": content[:500]},
        )
    return parsed, usage


_CODE_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _extract_json(content: str) -> Optional[dict]:
    """从 LLM 输出中尽力提取 JSON 对象；必要时做简单修复。"""
    if not content:
        return None
    s = content.strip()

    # 1) 整体就是 JSON
    if s.startswith("{"):
        obj = _try_load_json(s)
        if obj is not None:
            return obj

    # 2) ```json ... ``` 代码块
    m = _CODE_FENCE.search(content)
    if m:
        obj = _try_load_json(m.group(1))
        if obj is not None:
            return obj

    # 3) 第一个 { 到最后一个 } 之间的内容
    start = s.find("{")
    end = s.rfind("}")
    if start >= 0 and end > start:
        obj = _try_load_json(s[start : end + 1])
        if obj is not None:
            return obj
    return None


def _try_load_json(s: str) -> Optional[dict]:
    """尝试解析 JSON；失败时尝试常见修复后再解析。"""
    s = s.strip()
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass

    # 常见修复：移除尾逗号、把单引号转成双引号
    repaired = _repair_json(s)
    try:
        obj = json.loads(repaired)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    return None


def _repair_json(s: str) -> str:
    """对常见 LLM JSON 错误做轻量修复。"""
    # 去掉注释（简单处理）
    s = re.sub(r"//[^\n]*", "", s)
    # 去掉行尾多余逗号：," 或 ,}
    s = re.sub(r",(\s*[}\]])", r"\1", s)
    # 尝试把单引号统一替换成双引号（简单场景）
    return s.replace("'", '"')