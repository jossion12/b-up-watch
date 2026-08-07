"""B站登录状态检测。

通过 /x/web-interface/nav 的 data.isLogin 判断当前 Cookie 是否有效，
结果缓存 60 秒，避免前端轮询 status 时频繁调用 B站接口。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from app.bilibili.client import get_client

log = logging.getLogger(__name__)

_CACHE_TTL_SEC = 60


class _LoginCache:
    def __init__(self) -> None:
        self.is_login: Optional[bool] = None
        self.checked_at: float = 0.0
        self.lock = asyncio.Lock()


_cache = _LoginCache()


async def check_bilibili_login(force: bool = False) -> Optional[bool]:
    """检查当前 B站 Cookie 是否已登录。

    Returns:
        True:  已登录
        False: 未登录（或 Cookie 失效）
        None:  接口调用失败，状态未知
    """
    now = time.time()
    if not force and _cache.is_login is not None and (now - _cache.checked_at) < _CACHE_TTL_SEC:
        return _cache.is_login

    async with _cache.lock:
        if not force and _cache.is_login is not None and (time.time() - _cache.checked_at) < _CACHE_TTL_SEC:
            return _cache.is_login

        try:
            data = await get_client().get("/x/web-interface/nav", raise_on_business_error=False)
        except Exception as e:
            log.warning("check bilibili login failed: %s", e)
            _cache.is_login = None
            _cache.checked_at = time.time()
            return None

        is_login = bool(data.get("isLogin"))
        _cache.is_login = is_login
        _cache.checked_at = time.time()
        log.info("bilibili login status: is_login=%s", is_login)
        return is_login


def reset_login_cache_for_test() -> None:
    """仅供测试：清空缓存。"""
    _cache.is_login = None
    _cache.checked_at = 0.0
