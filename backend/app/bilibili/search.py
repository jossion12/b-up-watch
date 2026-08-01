"""B站 UP主搜索（接口文档 3.1.2）。

底层：`x/web-interface/wbi/search/all/v2`（需要 wbi 签名）。
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

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
        "from_source": "websuggest_search",
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


async def search_bili_video(
    keyword: str, page: int = 1, order: str = ""
) -> tuple[list[dict], bool]:
    """返回 (raw_items, has_more)。raw_items 元素为 B 站原 JSON 中的 video 条目。"""
    if not keyword:
        return [], False

    params = {
        "__refresh__": "true",
        "_extra": "",
        "context": "",
        "page": page,
        "page_size": 20,
        "order": order,
        "pubtime_begin_s": 0,
        "pubtime_end_s": 0,
        "duration": "",
        "from_source": "websuggest_search",
        "from_spmid": "333.337",
        "platform": "pc",
        "highlight": 1,
        "single_column": 0,
        "keyword": keyword,
    }
    signed = await sign(params)
    log.info("search_bili_video keyword=%s page=%s", keyword, page)

    data = await get_client().get("/x/web-interface/wbi/search/all/v2", params=signed)
    raw_items = _extract_video_items(data)
    total_page = int(data.get("numPages") or 0)
    has_more = page < total_page
    log.info(
        "search_bili_video raw_count=%s total_page=%s has_more=%s",
        len(raw_items),
        total_page,
        has_more,
    )
    return raw_items, has_more


def _extract_video_items(data: dict) -> list[dict]:
    """从 search/all/v2 的 data 中抽取 video 条目。"""
    result = data.get("result") or []
    if not isinstance(result, list):
        log.warning(
            "search_bili_video result is not a list, got %s: %s",
            type(result).__name__,
            str(result)[:200],
        )
        return []
    if not result:
        return []

    if all(isinstance(r, dict) and "result_type" in r for r in result):
        video_groups = [r for r in result if r.get("result_type") in {"video", "bili_video"}]
        if not video_groups:
            log.warning(
                "search_bili_video no video group found, result_types=%s",
                [r.get("result_type") for r in result],
            )
            return []
        group = video_groups[0]
        items = group.get("data") or []
        return list(items) if isinstance(items, list) else []

    if all(isinstance(r, dict) and "type" in r for r in result):
        items = [r for r in result if r.get("type") in {"video", "bili_video"}]
        return items

    log.warning("search_bili_video unknown result structure, first item=%s", str(result[0])[:200])
    return []


def _strip_html_tags(text: str | None) -> str:
    if not text:
        return ""
    import re
    return re.sub(r"<[^>]+>", "", text).strip()


def _normalize_url(url: str | None) -> str | None:
    if not url:
        return None
    url = str(url).strip()
    if url.startswith("//"):
        return "https:" + url
    if not url.lower().startswith(("http://", "https://")):
        return "https://" + url
    return url


def _parse_video_duration(raw: Any) -> int:
    """解析视频时长：可能是纯秒数或 'MM:SS' / 'HH:MM:SS' 字符串。"""
    if not raw:
        return 0
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw)
    parts = str(raw).split(":")
    if len(parts) == 1:
        try:
            return int(float(parts[0]))
        except (TypeError, ValueError):
            return 0
    try:
        nums = [int(float(p)) for p in parts]
    except (TypeError, ValueError):
        return 0
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    if len(nums) == 3:
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    return 0


def _parse_int_or_zero(raw: Any) -> int:
    if raw is None:
        return 0
    if isinstance(raw, (int, float)):
        return int(raw)
    # 处理带单位的字符串（如 "1.2万"）时先尝试纯数字
    s = str(raw).replace(",", "").strip()
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return 0


def parse_video_items(raw: Iterable[dict]) -> list[dict]:
    """从 B站原始条目抽取视频搜索所需字段。"""
    raw_list = list(raw)
    items: list[dict] = []
    skipped = 0
    for r in raw_list:
        bvid = r.get("bvid") or r.get("id")
        if not bvid or not str(bvid).startswith("BV"):
            skipped += 1
            continue
        mid = r.get("mid")
        title = _strip_html_tags(r.get("title"))
        if not title:
            title = _strip_html_tags(r.get("description")) or str(bvid)
        items.append({
            "bvid": str(bvid),
            "title": title,
            "cover_url": _normalize_url(r.get("pic") or r.get("cover")),
            "duration_sec": _parse_video_duration(r.get("duration") or r.get("length")),
            "published_at": _parse_int_or_zero(r.get("pubdate") or r.get("senddate")),
            "views": _parse_int_or_zero(r.get("play")),
            "danmaku_count": _parse_int_or_zero(r.get("video_review") or r.get("danmaku")),
            "likes": _parse_int_or_zero(r.get("like") or r.get("likes")),
            "uploader_mid": str(mid) if mid is not None else None,
            "uploader_name": str(r.get("author") or r.get("uname") or ""),
            "uploader_avatar_url": _normalize_url(r.get("face") or r.get("upic")),
        })
    log.info("parse_video_items input=%s output=%s skipped=%s", len(raw_list), len(items), skipped)
    return items
