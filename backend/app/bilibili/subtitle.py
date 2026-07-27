"""B站字幕轨道获取。

调用链：
1. `x/web-interface/view?bvid=...` 取 cid 及视频统计信息
2. `x/player/wbi/v2?bvid=...&cid=...` 取字幕轨道列表（含 ai_type 区分上传/AI）
3. 下载字幕 URL（通常在 `aisubtitle.hdslb.com`）的 JSON，转换为标准 lines

依赖：登录 Cookie（SESSDATA）能提高字幕可得率，尤其 AI 字幕。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from app.bilibili.client import BilibiliClient, get_client
from app.bilibili.wbi import sign
from app.errors import BizError

log = logging.getLogger(__name__)


async def get_video_info(bvid: str, client: Optional[BilibiliClient] = None) -> dict[str, Any]:
    """调用 `x/web-interface/view` 获取视频完整信息（含 cid、stat 等）。"""
    cli = client or get_client()
    return await cli.get("/x/web-interface/view", params={"bvid": bvid})


async def get_video_cid(bvid: str, client: Optional[BilibiliClient] = None) -> int:
    """仅获取 cid；内部复用 get_video_info，避免额外请求。"""
    data = await get_video_info(bvid, client=client)
    cid = data.get("cid")
    if not cid:
        raise BizError("VIDEO_NOT_FOUND", "视频不存在或 cid 缺失", http_status=404)
    return int(cid)


async def get_player_subtitles(
    bvid: str, cid: int, client: Optional[BilibiliClient] = None
) -> list[dict]:
    """返回带 WBI 签名的 player/wbi/v2 中的字幕轨道原始列表。

    B站已对 /x/player/v2 做限制：未签名接口返回的字幕轨道可能带有空
    subtitle_url。使用 /x/player/wbi/v2 才能拿到实际可下载的字幕链接。
    """
    params = {"bvid": bvid, "cid": cid}
    signed = await sign(params)
    cli = client or get_client()
    data = await cli.get("/x/player/wbi/v2", params=signed)
    subtitle = (data or {}).get("subtitle") or {}
    return list(subtitle.get("subtitles") or [])


def _has_usable_url(track: dict) -> bool:
    """字幕轨道是否包含非空可下载 URL。"""
    url = track.get("subtitle_url")
    return bool(url and str(url).strip())


def pick_preferred_subtitle(tracks: list[dict]) -> Optional[dict]:
    """优先级：UP主上传(ai_type=0) > AI字幕(ai_type=1)，跳过无 URL 的轨道。"""
    usable = [t for t in tracks if _has_usable_url(t)]
    if not usable:
        return None
    uploaded = [t for t in usable if int(t.get("ai_type", 0)) == 0]
    if uploaded:
        return uploaded[0]
    ai = [t for t in usable if int(t.get("ai_type", 0)) == 1]
    if ai:
        return ai[0]
    return usable[0]


async def download_subtitle_json(url: str) -> list[dict]:
    """下载字幕 JSON，转换为标准 lines。

    返回 [{"start_sec":..., "end_sec":..., "text":...}, ...]

    B 站返回的 subtitle_url 可能是协议相对 URL（//...）、裸路径或已带协议。
    这里统一补全为 https://，避免 httpx 因缺少协议头而报错。
    """
    raw_url = url
    url = str(url).strip()
    if not url:
        raise BizError(
            "INVALID_SUBTITLE_URL",
            "字幕 URL 为空，无法下载",
            http_status=422,
        )
    if url.startswith("//"):
        url = "https:" + url
    elif not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    log.info("download subtitle url: raw=%r normalized=%s", raw_url, url)
    if not url.lower().startswith(("http://", "https://")):
        raise BizError(
            "INVALID_SUBTITLE_URL",
            f"字幕 URL 格式异常，无法补全协议: {raw_url!r}",
            http_status=422,
        )
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as c:
        resp = await c.get(url)
        resp.raise_for_status()
        raw = resp.json()

    body = raw.get("body") or []
    lines: list[dict] = []
    for item in body:
        try:
            start = round(float(item.get("from", 0)), 3)
            end = round(float(item.get("to", 0)), 3)
        except (TypeError, ValueError):
            continue
        lines.append({
            "start_sec": start,
            "end_sec": end,
            "text": (item.get("content") or "").strip(),
        })
    return lines