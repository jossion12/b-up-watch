"""字幕获取主流程：view → player/v2 → 下载 → upsert。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.bilibili import subtitle as bili_sub
from app.config import get_settings
from app.errors import BizError
from app.models import Subtitle, Video

log = logging.getLogger(__name__)


def _subtitle_span_seconds(lines: list[dict]) -> float:
    """取字幕首尾时间戳的跨度（秒）。"""
    if not lines:
        return 0.0
    starts = [float(line.get("start_sec", 0)) for line in lines]
    ends = [float(line.get("end_sec", 0)) for line in lines]
    return max(ends) - min(starts)


def _check_subtitle_duration(lines: list[dict], video_duration_sec: int) -> None:
    """校验字幕时长与视频时长是否匹配；不匹配则抛 SUBTITLE_DURATION_MISMATCH。

    同时满足相对偏差和绝对偏差阈值才触发，避免短视频/静音片段误判。
    """
    if video_duration_sec <= 0:
        return
    span = _subtitle_span_seconds(lines)
    diff = abs(span - video_duration_sec)
    settings = get_settings()
    ratio_ok = diff / video_duration_sec >= settings.subtitle_duration_mismatch_ratio
    abs_ok = diff >= settings.subtitle_duration_mismatch_abs_sec
    if ratio_ok and abs_ok:
        raise BizError(
            "SUBTITLE_DURATION_MISMATCH",
            f"字幕时长（{span:.1f}s）与视频时长（{video_duration_sec}s）不一致，将尝试 Whisper 转写",
            details={"subtitle_span_sec": span, "video_duration_sec": video_duration_sec},
            http_status=422,
        )


async def fetch_video_subtitle(db: Session, video: Video) -> Subtitle:
    """按 UP主上传 → B站 AI字幕 优先级获取并写入 DB。

    无字幕 → 抛 SUBTITLE_UNAVAILABLE；字幕时长与视频严重不符 → 抛
    SUBTITLE_DURATION_MISMATCH（调用方可自动 fallback 到 Whisper）。

    同时利用同一次 `x/web-interface/view` 请求回填真实点赞数（空间列表接口
    返回的 like 经常为 null）。
    """
    info = await bili_sub.get_video_info(video.bvid)
    cid = info.get("cid")
    if not cid:
        raise BizError("VIDEO_NOT_FOUND", "视频不存在或 cid 缺失", http_status=404)

    # 回填真实点赞数
    stat = info.get("stat") or {}
    real_likes = stat.get("like")
    if real_likes is not None:
        video.likes = int(real_likes)

    tracks = await bili_sub.get_player_subtitles(video.bvid, int(cid))
    track = bili_sub.pick_preferred_subtitle(tracks)
    if track is None:
        raise BizError(
            "SUBTITLE_UNAVAILABLE",
            "该视频无字幕（可尝试 Whisper 转写兜底）",
            http_status=422,
        )

    lines = await bili_sub.download_subtitle_json(track["subtitle_url"])
    _check_subtitle_duration(lines, video.duration_sec)

    ai_type = int(track.get("ai_type", 0))
    source = "uploader" if ai_type == 0 else "bilibili_ai"
    language = track.get("lan") or "zh-CN"

    sub = db.get(Subtitle, video.id)
    now = datetime.now(timezone.utc)
    if sub is None:
        sub = Subtitle(
            video_id=video.id,
            language=language,
            source=source,
            lines=lines,
            fetched_at=now,
        )
        db.add(sub)
    else:
        sub.language = language
        sub.source = source
        sub.lines = lines
        sub.fetched_at = now

    video.has_subtitle = True
    if video.status == "new":
        video.status = "subtitled"

    db.commit()
    log.info(
        "fetched subtitle for video %s: %d lines, source=%s, lang=%s",
        video.bvid, len(lines), source, language,
    )
    return sub