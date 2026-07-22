"""B站 UP主空间投稿列表采集。

底层：`x/space/wbi/arc/search`（需要 wbi 签名）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.bilibili.client import BilibiliClient, get_client
from app.bilibili.wbi import sign

log = logging.getLogger(__name__)


async def fetch_space_archive(
    mid: str,
    pn: int = 1,
    ps: int = 30,
    client: Optional[BilibiliClient] = None,
) -> dict[str, Any]:
    """拉取一页空间投稿。返回 B站响应 data 字段（包含 list.vlist）。"""
    params = {
        "mid": mid,
        "pn": pn,
        "ps": ps,
        "order": "pubdate",
        "tid": 0,
        "keyword": "",
    }
    signed = await sign(params)
    cli = client or get_client()
    data = await cli.get("/x/space/wbi/arc/search", params=signed)
    log.info(
        "fetch_space_archive mid=%s pn=%s response data_keys=%s list_type=%s",
        mid,
        pn,
        list(data.keys()) if isinstance(data, dict) else type(data).__name__,
        type((data or {}).get("list")).__name__,
    )
    return data


async def fetch_user_card(
    mid: str,
    client: Optional[BilibiliClient] = None,
) -> Optional[dict[str, Any]]:
    """获取用户名片信息。返回 B站 card 字段（含 name/face/fans/sign 等）。"""
    cli = client or get_client()
    try:
        data = await cli.get("/x/web-interface/card", params={"mid": mid})
    except Exception:
        log.warning("fetch_user_card failed for mid=%s", mid, exc_info=True)
        return None
    card = (data or {}).get("card")
    if not isinstance(card, dict):
        log.warning("fetch_user_card mid=%s no card field, data_keys=%s", mid, list(data.keys()) if isinstance(data, dict) else type(data).__name__)
        return None
    return card


def parse_pubdate(unix_ts: int | None) -> Optional[datetime]:
    if not unix_ts:
        return None
    try:
        return datetime.fromtimestamp(int(unix_ts), tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None