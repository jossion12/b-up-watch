"""B站 HTTP 客户端：Cookie 注入、UA、错误码映射。"""

from __future__ import annotations

import logging
from typing import Any, Mapping

import httpx

from app.config import get_bilibili_cookie, get_bilibili_sessdata, get_settings
from app.errors import BizError

log = logging.getLogger(__name__)

_API_BASE = "https://api.bilibili.com"
_RATE_LIMITED_CODES = {-352, -412, -799, -509, -1200}


def _build_headers(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    s = get_settings()
    headers = {
        "User-Agent": s.bilibili_user_agent,
        "Referer": "https://www.bilibili.com",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    cookie = get_bilibili_cookie()
    if cookie:
        headers["Cookie"] = cookie
    else:
        sessdata = get_bilibili_sessdata()
        if sessdata:
            headers["Cookie"] = f"SESSDATA={sessdata}"
    if extra:
        headers.update(extra)
    return headers


class BilibiliClient:
    def __init__(self, timeout: float = 10.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=_API_BASE,
            timeout=timeout,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "BilibiliClient":
        return self

    async def __aexit__(self, *_exc) -> None:
        await self.close()

    async def get(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> dict:
        try:
            resp = await self._client.get(path, params=params, headers=_build_headers(extra_headers))
        except httpx.HTTPError as exc:
            log.warning("bilibili http error path=%s err=%s", path, exc)
            raise BizError("BILIBILI_UNREACHABLE", "B站接口不可达", http_status=502) from exc

        try:
            data = resp.json()
        except ValueError as exc:
            log.warning(
                "bilibili non-json response path=%s status=%s body=%s",
                path,
                resp.status_code,
                resp.text[:500],
            )
            raise BizError("BILIBILI_BAD_RESPONSE", "B站响应非 JSON", http_status=502) from exc

        code = data.get("code")
        message = data.get("message")
        log.info(
            "bilibili api response path=%s http_status=%s code=%s message=%s",
            path,
            resp.status_code,
            code,
            message,
        )
        if code in _RATE_LIMITED_CODES:
            log.warning("bilibili rate limited path=%s code=%s message=%s", path, code, message)
            raise BizError(
                "BILIBILI_RATE_LIMITED",
                "B站触发风控限流，请稍后重试",
                http_status=429,
                details={"upstream_code": code, "message": message},
            )
        if code != 0:
            log.warning(
                "bilibili api error path=%s code=%s message=%s data=%s",
                path,
                code,
                message,
                str(data)[:500],
            )
            raise BizError(
                "BILIBILI_API_ERROR",
                message or "B站接口错误",
                http_status=502,
                details={"upstream_code": code, "message": message, "data_preview": str(data)[:200]},
            )
        return data.get("data") or {}


_default_client: BilibiliClient | None = None


def get_client() -> BilibiliClient:
    global _default_client
    if _default_client is None:
        _default_client = BilibiliClient()
    return _default_client


async def close_client() -> None:
    global _default_client
    if _default_client is not None:
        await _default_client.close()
        _default_client = None