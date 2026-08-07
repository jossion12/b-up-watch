"""生成 RAGFlow 可用的语料文档（无 LLM，只做清洗和格式化）。

把字幕按停顿切分为话题段，清洗口语噪音后输出为结构化 Markdown，方便 RAGFlow
直接摄取、chunk 和检索。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from app.config import get_settings
from app.rag.parser import segments_from_subtitle_lines

if TYPE_CHECKING:
    from app.models import Video

log = __import__("logging").getLogger(__name__)


# 常见口语填充词，可根据实际语料扩展。
FILLER_WORDS = [
    "呃",
    "啊",
    "嗯",
    "哎",
    "那个",
    "这个",
    "然后",
    "就是",
    "对吧",
    "是吧",
    "是吧",
    "那么",
    "所以",
    "其实",
    "真的",
    "基本上",
    "说白了",
]


def _sanitize_filename(name: str) -> str:
    """把字符串中的非法文件名字符与空白替换为下划线，并截断长度。"""
    name = name.strip()
    name = re.sub(r'[\\\\/:*?"<>|\s]+', "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    if len(name) > 120:
        name = name[:120]
    return name or "untitled"


def _clean_text(text: str) -> str:
    """规则清洗：合并多余空格、去除首尾空白。"""
    return re.sub(r"\s+", " ", text.strip())


def clean_segment_text(text: str) -> str:
    """规则清洗：去掉常见填充词与口语噪音。

    注意：这里只做保守清洗，避免误删有语义的内容。
    """
    text = _clean_text(text)
    for w in FILLER_WORDS:
        # 仅删除作为独立填充词出现的情况（前后为空格或标点）
        text = re.sub(rf"(?<![^\s，。、！？；：]){re.escape(w)}(?![^\s，。、！？；：])", "", text)
    # 去掉清洗后可能残留的多余空格和句首标点
    text = _clean_text(text)
    text = re.sub(r"^[，。、！？；：\s]+", "", text)
    return text


def format_time(seconds: float) -> str:
    """把秒数转成 HH:MM:SS 或 MM:SS 格式。"""
    secs = max(0.0, float(seconds))
    hours = int(secs // 3600)
    minutes = int((secs % 3600) // 60)
    s = int(secs % 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{s:02d}"
    return f"{minutes:02d}:{s:02d}"


def build_ragflow_corpus(
    video: "Video",
    lines: list[dict],
    source: str = "unknown",
    video_url: str = "",
) -> str:
    """把字幕行转成 RAGFlow 友好的 Markdown 语料。

    输出格式：
    - YAML front matter：视频元数据
    - 一级标题：视频标题
    - 二级标题：每个话题段的时间范围
    - 正文：清洗后的段文本
    """
    segments = segments_from_subtitle_lines(lines)

    published = video.published_at
    published_str = published.strftime("%Y-%m-%d") if published else ""

    front_matter = f"""---
title: {video.title}
uploader: {video.uploader.name}
uploader_id: {video.uploader_id}
video_id: {video.id}
bvid: {video.bvid}
published_at: {published_str}
source: {source}
url: {video_url}
---

"""

    body = f"# {video.title}\n\n"
    body += f"> UP主：{video.uploader.name} | 发布时间：{published_str} | 来源：{source}\n\n"

    for seg in segments:
        start_fmt = format_time(seg.start_seconds)
        end_fmt = format_time(seg.end_seconds)
        cleaned = clean_segment_text(seg.text)
        if not cleaned:
            continue
        body += f"## {start_fmt} - {end_fmt}\n\n{cleaned}\n\n"

    return front_matter + body


def get_corpus_dir() -> Path:
    """返回语料根目录。"""
    settings = get_settings()
    return Path(settings.ragflow_corpus_dir).expanduser()


def save_ragflow_corpus(
    video: "Video",
    lines: list[dict],
    source: str = "unknown",
) -> Path:
    """把视频字幕保存为 RAGFlow 可摄取的 Markdown 语料文件。

    文件路径：{ragflow_corpus_dir}/{up_name}/YYYYMMDD-{video_title}.md
    """
    settings = get_settings()
    if not settings.ragflow_corpus_enabled:
        log.debug("ragflow corpus generation disabled for video=%s", video.id)
        return Path()

    corpus_dir = get_corpus_dir()
    uploader_name = _sanitize_filename(video.uploader.name)
    published = video.published_at or datetime.now(timezone.utc)
    date_prefix = published.strftime("%Y%m%d")
    video_name = _sanitize_filename(video.title)
    file_name = f"{date_prefix}-{video_name}.md"

    path = corpus_dir / uploader_name / file_name
    path.parent.mkdir(parents=True, exist_ok=True)

    video_url = f"https://www.bilibili.com/video/{video.bvid}"
    content = build_ragflow_corpus(video, lines, source=source, video_url=video_url)
    path.write_text(content, encoding="utf-8")
    log.info("saved ragflow corpus to %s", path)
    return path


def clear_ragflow_corpus(up_name: str) -> int:
    """删除指定 UP 主的全部语料文件，返回删除数量。"""
    corpus_dir = get_corpus_dir()
    up_dir = corpus_dir / _sanitize_filename(up_name)
    if not up_dir.exists():
        return 0

    count = 0
    for p in up_dir.glob("*.md"):
        p.unlink()
        count += 1
    log.info("cleared %d ragflow corpus files for %s", count, up_name)
    return count
