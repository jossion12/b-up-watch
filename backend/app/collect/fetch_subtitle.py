"""字幕获取主流程：view → player/v2 → 下载 → upsert。"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.bilibili import subtitle as bili_sub
from app.collect.corpus import save_ragflow_corpus
from app.config import get_settings
from app.errors import BizError
from app.models import Subtitle, Video

log = logging.getLogger(__name__)

# 字幕本地归档根目录（与 SQLite 文件同目录，保持项目约定）
_SUBTITLE_DATA_DIR = Path("data")


def _subtitle_span_seconds(lines: list[dict]) -> float:
    """取字幕首尾时间戳的跨度（秒）。"""
    if not lines:
        return 0.0
    starts = [float(line.get("start_sec", 0)) for line in lines]
    ends = [float(line.get("end_sec", 0)) for line in lines]
    return max(ends) - min(starts)


def _is_placeholder_subtitle(lines: list[dict]) -> bool:
    """检测 B 站占位字幕：所有非空文本均为「啥都木有」时视为无实质内容。"""
    non_empty = [str(line.get("text") or "").strip() for line in lines if str(line.get("text") or "").strip()]
    if not non_empty:
        return False
    return all(text == "啥都木有" for text in non_empty)


def _is_video_unavailable_error(exc: BizError) -> bool:
    """检测 B 站接口是否返回「啥都木有」（code=-404），表示视频已不可用。"""
    if exc.code != "BILIBILI_API_ERROR":
        return False
    details = exc.details or {}
    return details.get("upstream_code") == -404 and "啥都木有" in (exc.message or "")


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


def _sanitize_filename(name: str) -> str:
    """把字符串中的非法文件名字符与空白替换为下划线，并截断长度。"""
    name = name.strip()
    # Windows / POSIX 非法字符：\ / : * ? " < > |，以及空白字符
    name = re.sub(r'[\\\\/:*?"<>|\s]+', "_", name)
    # 去除连续下划线与首尾下划线
    name = re.sub(r"_+", "_", name).strip("_")
    # 限制长度，避免路径过长
    if len(name) > 120:
        name = name[:120]
    return name or "untitled"


def _subtitle_to_markdown(lines: list[dict]) -> str:
    """把标准字幕 lines 转为 Markdown：每条一句，带时间戳。"""
    def _fmt(sec: float) -> str:
        m = int(sec // 60)
        s = int(sec % 60)
        ms = int(round((sec - int(sec)) * 1000))
        return f"{m:02d}:{s:02d}.{ms:03d}"

    parts: list[str] = []
    for item in lines:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        start = float(item.get("start_sec", 0))
        end = float(item.get("end_sec", 0))
        parts.append(f"[{_fmt(start)} -> {_fmt(end)}] {text}")
    return "\n\n".join(parts)


def _subtitle_file_path(video: Video) -> Path:
    """生成本地归档路径：data/{up主名称}/YYYYMMDD-{视频名称}.md。"""
    uploader_name = _sanitize_filename(video.uploader.name)
    published = video.published_at
    if published is None:
        published = datetime.now(timezone.utc)
    date_prefix = published.strftime("%Y%m%d")
    video_name = _sanitize_filename(video.title)
    file_name = f"{date_prefix}-{video_name}.md"
    return _SUBTITLE_DATA_DIR / uploader_name / file_name


def _upsert_subtitle(
    db: Session, video: Video, language: str, source: str, lines: list[dict]
) -> Subtitle:
    """根据 video_id 创建或更新字幕记录。"""
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
    return sub


def save_subtitle_to_file(video: Video, lines: list[dict]) -> Path:
    """将字幕内容写入本地 Markdown 文件，返回最终路径。"""
    path = _subtitle_file_path(video)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = _subtitle_to_markdown(lines)
    path.write_text(content, encoding="utf-8")
    log.info("saved subtitle to %s", path)
    return path


async def fetch_video_subtitle(db: Session, video: Video) -> Subtitle:
    """按 UP主上传 → B站 AI字幕 优先级获取并写入 DB。

    无字幕 → 抛 SUBTITLE_UNAVAILABLE；字幕时长与视频严重不符 → 抛
    SUBTITLE_DURATION_MISMATCH（调用方可自动 fallback 到 Whisper）。

    同时利用同一次 `x/web-interface/view` 请求回填真实点赞数（空间列表接口
    返回的 like 经常为 null）。
    """
    log.info("[bili subtitle] bvid=%s, fetching video info", video.bvid)
    try:
        info = await bili_sub.get_video_info(video.bvid)
    except BizError as e:
        if _is_video_unavailable_error(e):
            log.info("[bili subtitle] bvid=%s, video unavailable on bilibili, treating as complete", video.bvid)
            raise BizError(
                "VIDEO_UNAVAILABLE",
                "该视频在 B 站已不可用（啥都木有），视为已完成",
                http_status=404,
                details=e.details,
            )
        raise
    cid = info.get("cid")
    if not cid:
        log.warning("[bili subtitle] bvid=%s, cid missing in video info", video.bvid)
        raise BizError("VIDEO_NOT_FOUND", "视频不存在或 cid 缺失", http_status=404)
    log.info("[bili subtitle] bvid=%s, cid=%s", video.bvid, cid)

    # 回填真实点赞数
    stat = info.get("stat") or {}
    real_likes = stat.get("like")
    if real_likes is not None:
        video.likes = int(real_likes)
        log.info("[bili subtitle] bvid=%s, backfilled likes=%s", video.bvid, real_likes)

    log.info("[bili subtitle] bvid=%s, fetching subtitle tracks", video.bvid)
    tracks = await bili_sub.get_player_subtitles(video.bvid, int(cid))
    log.info("[bili subtitle] bvid=%s, got %d subtitle tracks", video.bvid, len(tracks))
    track = bili_sub.pick_preferred_subtitle(tracks)
    if track is None:
        log.warning("[bili subtitle] bvid=%s, no preferred subtitle track available", video.bvid)
        raise BizError(
            "SUBTITLE_UNAVAILABLE",
            "该视频无字幕（可尝试 Whisper 转写兜底）",
            http_status=422,
        )
    log.info("[bili subtitle] bvid=%s, picked track: ai_type=%s, lan=%s, url=%s", video.bvid, track.get("ai_type"), track.get("lan"), track.get("subtitle_url"))

    lines = await bili_sub.download_subtitle_json(track["subtitle_url"])
    log.info("[bili subtitle] bvid=%s, downloaded %d subtitle lines", video.bvid, len(lines))

    ai_type = int(track.get("ai_type", 0))
    source = "uploader" if ai_type == 0 else "bilibili_ai"
    language = track.get("lan") or "zh-CN"

    # 占位字幕视为「已完成」，直接写入后返回，不再做时长校验、不再尝试 Whisper fallback
    if _is_placeholder_subtitle(lines):
        sub = _upsert_subtitle(db, video, language, source, lines)
        log.info("[bili subtitle] bvid=%s, placeholder subtitle detected, treating as complete", video.bvid)
        video.has_subtitle = True
        if video.status == "new":
            video.status = "subtitled"
        db.commit()
        try:
            save_subtitle_to_file(video, lines)
            save_ragflow_corpus(video, lines, source=source)
        except Exception as e:
            log.warning("[bili subtitle] bvid=%s, failed to save placeholder subtitle/corpus file: %s", video.bvid, e)
        return sub

    # 时长校验必须在写入字幕前完成；
    # 若校验失败走 Whisper fallback，session 中不能残留待写入的 B 站字幕，
    # 否则 fallback 会尝试再写一条同 video_id 的字幕，触发唯一约束冲突。
    _check_subtitle_duration(lines, video.duration_sec)

    sub = _upsert_subtitle(db, video, language, source, lines)
    video.has_subtitle = True
    if video.status == "new":
        video.status = "subtitled"

    db.commit()

    # 本地归档：data/{up主名称}/YYYYMMDD-{视频名称}.md
    try:
        save_subtitle_to_file(video, lines)
        save_ragflow_corpus(video, lines, source=source)
    except Exception as e:
        # 文件归档/RAGFlow 语料生成失败不影响 DB 写入，仅记录日志
        log.warning("[bili subtitle] bvid=%s, failed to save subtitle/corpus file: %s", video.bvid, e)

    log.info(
        "[bili subtitle] bvid=%s, success: %d lines, source=%s, lang=%s",
        video.bvid, len(lines), source, language,
    )
    return sub