"""B站字幕轨道获取。

调用链：
1. `x/web-interface/view?bvid=...` 取 cid 及视频统计信息
2. `x/player/v2?bvid=...&cid=...` 取字幕轨道列表（含 ai_type 区分上传/AI）
3. 下载字幕 URL（通常在 `aisubtitle.hdslb.com`）的 JSON，转换为标准 lines

依赖：登录 Cookie（SESSDATA）能提高字幕可得率，尤其 AI 字幕。
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from app.bilibili.client import BilibiliClient, get_client
from app.errors import BizError


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
    """返回 player/v2 中的字幕轨道原始列表。"""
    cli = client or get_client()
    data = await cli.get("/x/player/v2", params={"bvid": bvid, "cid": cid})
    subtitle = (data or {}).get("subtitle") or {}
    return list(subtitle.get("subtitles") or [])


def pick_preferred_subtitle(tracks: list[dict]) -> Optional[dict]:
    """优先级：UP主上传(ai_type=0) > AI字幕(ai_type=1)。"""
    if not tracks:
        return None
    uploaded = [t for t in tracks if int(t.get("ai_type", 0)) == 0]
    if uploaded:
        return uploaded[0]
    ai = [t for t in tracks if int(t.get("ai_type", 0)) == 1]
    if ai:
        return ai[0]
    return tracks[0] if tracks else None


async def download_subtitle_json(url: str) -> list[dict]:
    """下载字幕 JSON，转换为标准 lines。

    返回 [{"start_sec":..., "end_sec":..., "text":...}, ...]
    """
    if url.startswith("//"):
        url = "https:" + url
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