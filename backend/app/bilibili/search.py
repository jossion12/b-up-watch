"""B站 UP主搜索（接口文档 3.1.2）。

底层：`x/web-interface/wbi/search/all/v2`（需要 wbi 签名）。
"""

from __future__ import annotations

import logging
from typing import Iterable

from app.bilibili.client import get_client
from app.bilibili.wbi import sign

log = logging.getLogger(__name__)


async def search_bili_user(keyword: str, page: int = 1) -> tuple[list[dict], bool]:
    """返回 (raw_items, has_more)。raw_items 元素为 B 站原 JSON 中的 result 条目。"""
    if not keyword:
        return [], False

    params = {
        "__refresh__": "true",
        "_extra": "",
        "context": "",
        "page": page,
        "page_size": 42,
        "order": "",
        "pubtime_begin_s": 0,
        "pubtime_end_s": 0,
        "duration": "",
        "from_source": "web_search",
        "from_spmid": "333.337",
        "platform": "pc",
        "highlight": 1,
        "single_column": 0,
        "keyword": keyword,
    }
    signed = await sign(params)
    log.info("search_bili_user keyword=%s page=%s signed_keys=%s", keyword, page, list(signed.keys()))

    data = await get_client().get("/x/web-interface/wbi/search/all/v2", params=signed)
    log.info(
        "search_bili_user raw response keys=%s numPages=%s numResults=%s result_type=%s",
        list(data.keys()),
        data.get("numPages"),
        data.get("numResults"),
        type(data.get("result")).__name__,
    )

    raw_items = _extract_user_items(data)
    # numResults / total / pages 等字段
    total_page = int(data.get("numPages") or 0)
    has_more = page < total_page
    log.info("search_bili_user raw_count=%s total_page=%s has_more=%s", len(raw_items), total_page, has_more)
    return raw_items, has_more


def _extract_user_items(data: dict) -> list[dict]:
    """从 search/all/v2 的 data 中抽取 bili_user 条目，兼容多种可能的结构。"""
    result = data.get("result") or []
    if not isinstance(result, list):
        log.warning(
            "search_bili_user result is not a list, got %s: %s",
            type(result).__name__,
            str(result)[:200],
        )
        return []

    if not result:
        return []

    # 结构 A：result 是按类型分组的列表，每项含 result_type + data
    if all(isinstance(r, dict) and "result_type" in r for r in result):
        user_groups = [r for r in result if r.get("result_type") in {"bili_user", "upuser", "user"}]
        if not user_groups:
            log.warning(
                "search_bili_user no user group found, result_types=%s",
                [r.get("result_type") for r in result],
            )
            return []
        group = user_groups[0]
        items = group.get("data") or []
        log.info(
            "search_bili_user grouped result_type=%s items_type=%s",
            group.get("result_type"),
            type(items).__name__,
        )
        return list(items) if isinstance(items, list) else []

    # 结构 B：result 是扁平列表，每项含 type
    if all(isinstance(r, dict) and "type" in r for r in result):
        items = [r for r in result if r.get("type") in {"bili_user", "upuser", "user"}]
        log.info("search_bili_user flat result types=%s user_count=%s", [r.get("type") for r in result], len(items))
        return items

    log.warning("search_bili_user unknown result structure, first item=%s", str(result[0])[:200])
    return []


def parse_search_items(raw: Iterable[dict]) -> list[dict]:
    """从 B站原始条目抽取接口文档 3.1.2 所需字段。"""
    raw_list = list(raw)
    items: list[dict] = []
    skipped = 0
    for r in raw_list:
        # B站字段：mid, uname, upic, fans, usign, ...
        mid = r.get("mid")
        if mid is None:
            skipped += 1
            continue
        items.append({
            "bilibili_uid": str(mid),
            "name": r.get("uname") or "",
            "avatar_url": r.get("upic") or None,
            "fans_count": int(r.get("fans") or 0),
            "description": r.get("usign") or None,
        })
    log.info("parse_search_items input=%s output=%s skipped_no_mid=%s", len(raw_list), len(items), skipped)
    return items
