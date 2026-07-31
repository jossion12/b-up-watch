"""UP 复盘 Markdown 字幕解析器。

源文件格式：
    [00:00.000 -> 00:08.024] 严重移动偏离值，绕移动具体的计算...
文件名格式：
    20260111-股票绕异动怎么算_详细.md
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class SubtitleEntry:
    """单条字幕条目。"""

    index: int
    start_time: str
    end_time: str
    start_seconds: float
    end_seconds: float
    text: str


@dataclass
class TextSegment:
    """按停顿切分后的话题段。"""

    start_time: str
    end_time: str
    start_seconds: float
    end_seconds: float
    text: str
    time_position: str


@dataclass
class ParsedReview:
    """一个 Markdown 复盘文件的解析结果。"""

    file_name: str
    title: str
    date: Optional[str]
    segments: List[TextSegment]


_TIME_RE = re.compile(
    r"^\[(\d{2}:\d{2}\.\d{3})\s*(?:->|→)\s*(\d{2}:\d{2}\.\d{3})\]\s*(.*)$"
)


def _time_to_seconds(time_str: str) -> float:
    """把 00:00.000 或 00:00:00.000 转为秒。"""
    time_str = time_str.strip()
    parts = time_str.split(":")
    if len(parts) == 2:
        m, s = parts
        return float(m) * 60 + float(s)
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    raise ValueError(f"无法解析时间: {time_str}")


def _format_time(seconds: float) -> str:
    """把秒转回 MM:SS.mmm 格式。"""
    m = int(seconds // 60)
    s = seconds - m * 60
    return f"{m:02d}:{s:06.3f}"


def _clean_text(text: str) -> str:
    """简单清洗：去掉首尾空白和多余空格。"""
    return re.sub(r"\s+", " ", text.strip())


def parse_markdown_file(file_path: str | Path) -> ParsedReview:
    """解析单个 Markdown 复盘文件。"""
    path = Path(file_path)
    content = path.read_text(encoding="utf-8")

    # 从文件名解析标题和日期
    stem = path.stem
    date_match = re.match(r"^(\d{8})-(.+)$", stem)
    if date_match:
        date_str = date_match.group(1)
        title = date_match.group(2)
        date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    else:
        title = stem
        date = None

    entries: List[SubtitleEntry] = []
    for idx, raw_line in enumerate(content.splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue
        m = _TIME_RE.match(line)
        if not m:
            # 某些行可能没有正确时间戳，尝试把整行当文本追加到上一条
            if entries and line:
                entries[-1].text += " " + line
            continue
        start, end, text = m.groups()
        text = _clean_text(text)
        if not text:
            continue
        entries.append(
            SubtitleEntry(
                index=idx,
                start_time=start,
                end_time=end,
                start_seconds=_time_to_seconds(start),
                end_seconds=_time_to_seconds(end),
                text=text,
            )
        )

    return ParsedReview(
        file_name=path.name,
        title=title,
        date=date,
        segments=segment_by_pause(entries),
    )


def segment_by_pause(
    entries: List[SubtitleEntry], pause_threshold: float = 2.5
) -> List[TextSegment]:
    """按时间间隔将字幕切分为话题段。"""
    segments: List[TextSegment] = []
    current: List[SubtitleEntry] = []

    for e in entries:
        if not current:
            current.append(e)
        else:
            gap = e.start_seconds - current[-1].end_seconds
            if gap > pause_threshold:
                segments.append(_make_segment(current))
                current = [e]
            else:
                current.append(e)

    if current:
        segments.append(_make_segment(current))

    return segments


def _make_segment(entries: List[SubtitleEntry]) -> TextSegment:
    text = " ".join([e.text for e in entries])
    start = entries[0].start_time
    end = entries[-1].end_time
    start_sec = entries[0].start_seconds
    end_sec = entries[-1].end_seconds
    return TextSegment(
        start_time=start,
        end_time=end,
        start_seconds=start_sec,
        end_seconds=end_sec,
        text=text,
        time_position=f"{start} -> {end}",
    )
