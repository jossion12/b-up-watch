"""B站 wbi 签名。

参考 B站公开算法：
1. 调用 https://api.bilibili.com/x/web-interface/nav 取 wbi_img.img_url / sub_url
2. 从 URL 文件名提取 img_key / sub_key（去掉扩展名）
3. 按固定顺序混排 32 字符 mixin_key
4. 请求参数按 key 排序 → 加 wts → 用 mixin_key 做 md5 得 w_rid
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any, Mapping
from urllib.parse import urlencode

import httpx

from app.bilibili.client import _build_headers
from app.errors import BizError

# img_key 与 sub_key 混排表（B站公开常量）
_MIXIN_TABLE = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
]
_MIXIN_LEN = 32


class _WbiCache:
    def __init__(self) -> None:
        self.img_key: str | None = None
        self.sub_key: str | None = None
        self.mixin_key: str | None = None
        self.fetched_at: float = 0.0
        self.lock = asyncio.Lock()


_cache = _WbiCache()
_TTL_SEC = 24 * 3600

# 可在测试中替换
_async_client_factory = lambda: httpx.AsyncClient(headers=_build_headers(), timeout=10.0)


def _extract_key(url: str) -> str:
    # url 形如 https://i0.hdslb.com/bfs/wbi/xxxxxxxxxxxxxxxxxxxxxxxxxxxxx.png
    name = url.rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[0]


def _build_mixin_key(img_key: str, sub_key: str) -> str:
    raw = img_key + sub_key
    # 索引超出 raw 长度时按 B站实现截断取余
    return "".join(raw[i % len(raw)] for i in _MIXIN_TABLE)[:_MIXIN_LEN]


async def _fetch_keys(force: bool = False) -> str:
    """返回 mixin_key。"""
    now = time.time()
    if not force and _cache.mixin_key and (now - _cache.fetched_at) < _TTL_SEC:
        return _cache.mixin_key

    async with _cache.lock:
        if not force and _cache.mixin_key and (time.time() - _cache.fetched_at) < _TTL_SEC:
            return _cache.mixin_key

        async with _async_client_factory() as client:
            resp = await client.get("https://api.bilibili.com/x/web-interface/nav")

        if resp.status_code in {412, -412}:
            raise BizError(
                "BILIBILI_RATE_LIMITED",
                "B站触发风控限流，请稍后重试或配置 SESSDATA",
                http_status=429,
                details={"upstream_status": resp.status_code},
            )
        if resp.status_code != 200:
            raise BizError(
                "BILIBILI_API_ERROR",
                f"B站 nav 接口返回 {resp.status_code}",
                http_status=502,
                details={"upstream_status": resp.status_code, "body": resp.text[:200]},
            )

        try:
            data = resp.json()
        except ValueError as exc:
            raise BizError(
                "BILIBILI_BAD_RESPONSE",
                "B站响应非 JSON",
                http_status=502,
                details={"body": resp.text[:200]},
            ) from exc

        code = data.get("code")
        if code != 0:
            raise BizError(
                "BILIBILI_API_ERROR",
                data.get("message") or "B站 nav 接口错误",
                http_status=502,
                details={"upstream_code": code},
            )

        wbi_img = (data.get("data") or {}).get("wbi_img") or {}
        img_url = wbi_img.get("img_url") or ""
        sub_url = wbi_img.get("sub_url") or ""
        if not img_url or not sub_url:
            raise RuntimeError(f"nav 接口未返回 wbi_img: {data}")

        _cache.img_key = _extract_key(img_url)
        _cache.sub_key = _extract_key(sub_url)
        _cache.mixin_key = _build_mixin_key(_cache.img_key, _cache.sub_key)
        _cache.fetched_at = time.time()
        return _cache.mixin_key


def _md5(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def _sign_params(params: Mapping[str, Any], mixin_key: str) -> dict[str, Any]:
    """对参数做 wbi 签名：排序 + 加 wts + 计算 w_rid。"""
    signed: dict[str, Any] = {}
    # 1) 排序
    for k in sorted(params):
        v = params[k]
        if v is None:
            continue
        # 去除特殊字符
        if isinstance(v, str):
            v = v.replace("!", "").replace("'", "").replace("(", "").replace(
                ")", "").replace("*", "").replace("'", ""
            )
        signed[k] = v
    # 2) 加 wts
    signed["wts"] = int(time.time())
    # 3) 计算 w_rid
    query = urlencode(sorted(signed.items()))
    signed["w_rid"] = _md5(query + mixin_key)
    return signed


async def sign(params: Mapping[str, Any]) -> dict[str, Any]:
    """外部入口：取/刷新 mixin_key 后签名。"""
    mixin_key = await _fetch_keys()
    return _sign_params(params, mixin_key)


def reset_for_test() -> None:
    """仅供测试：清空缓存。"""
    _cache.img_key = None
    _cache.sub_key = None
    _cache.mixin_key = None
    _cache.fetched_at = 0.0