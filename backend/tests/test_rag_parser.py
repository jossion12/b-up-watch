"""RAG Markdown 复盘解析器测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.rag.parser import (
    SubtitleEntry,
    parse_markdown_file,
    segment_by_pause,
    segments_from_subtitle_lines,
)


def test_parse_markdown_file_extracts_date_and_title(tmp_path: Path):
    path = tmp_path / "20260111-股票异动怎么算_详细.md"
    path.write_text(
        "[00:00.000 -> 00:05.000] 严重移动偏离值\n"
        "[00:08.000 -> 00:10.000] 绕移动具体的计算",
        encoding="utf-8",
    )

    parsed = parse_markdown_file(path)
    assert parsed.file_name == path.name
    assert parsed.title == "股票异动怎么算_详细"
    assert parsed.date == "2026-01-11"
    assert len(parsed.segments) == 2
    assert parsed.segments[0].text == "严重移动偏离值"
    assert parsed.segments[1].text == "绕移动具体的计算"


def test_parse_markdown_file_appends_lines_without_timestamp(tmp_path: Path):
    path = tmp_path / "20260111-test.md"
    path.write_text(
        "[00:00.000 -> 00:05.000] 第一行\n"
        "这行没有正确时间戳，应追加到上一行",
        encoding="utf-8",
    )

    parsed = parse_markdown_file(path)
    assert len(parsed.segments) == 1
    assert "第一行" in parsed.segments[0].text
    assert "这行没有正确时间戳" in parsed.segments[0].text


def test_parse_markdown_file_no_date_prefix(tmp_path: Path):
    path = tmp_path / "some_title.md"
    path.write_text("[00:00.000 -> 00:05.000] hello", encoding="utf-8")

    parsed = parse_markdown_file(path)
    assert parsed.title == "some_title"
    assert parsed.date is None


def test_segment_by_pause_splits_on_threshold():
    entries = [
        SubtitleEntry(1, "00:00.000", "00:02.000", 0.0, 2.0, "A"),
        SubtitleEntry(2, "00:02.500", "00:04.000", 2.5, 4.0, "B"),
        # 间隔 3 秒 > 2.5，应切分
        SubtitleEntry(3, "00:07.000", "00:08.000", 7.0, 8.0, "C"),
    ]

    segments = segment_by_pause(entries, pause_threshold=2.5)
    assert len(segments) == 2
    assert segments[0].text == "A B"
    assert segments[1].text == "C"
    assert segments[0].time_position == "00:00.000 -> 00:04.000"


def test_segment_by_pause_keeps_single_segment():
    entries = [
        SubtitleEntry(1, "00:00.000", "00:02.000", 0.0, 2.0, "A"),
        SubtitleEntry(2, "00:02.100", "00:04.000", 2.1, 4.0, "B"),
    ]

    segments = segment_by_pause(entries, pause_threshold=2.5)
    assert len(segments) == 1
    assert segments[0].text == "A B"


def test_segment_by_pause_splits_on_max_duration():
    entries = [
        SubtitleEntry(1, "00:00.000", "00:30.000", 0.0, 30.0, "A"),
        SubtitleEntry(2, "00:30.100", "00:60.000", 30.1, 60.0, "B"),
        # 加入后话题段将达到 90.1 秒，超过 60 秒上限，应单独成段
        SubtitleEntry(3, "00:60.100", "00:90.100", 60.1, 90.1, "C"),
    ]

    segments = segment_by_pause(entries, pause_threshold=2.5, max_segment_duration_sec=60.0)
    assert len(segments) == 2
    assert segments[0].text == "A B"
    assert segments[1].text == "C"


def test_segments_from_subtitle_lines():
    lines = [
        {"start_sec": 0.0, "end_sec": 2.0, "text": "第一句"},
        {"start_sec": 2.1, "end_sec": 4.0, "text": "第二句"},
        {"start_sec": 8.0, "end_sec": 10.0, "text": "第三句"},
    ]
    segments = segments_from_subtitle_lines(lines, pause_threshold=2.5)
    assert len(segments) == 2
    assert segments[0].text == "第一句 第二句"
    assert segments[1].text == "第三句"
    assert segments[0].time_position == "00:00.000 -> 00:04.000"
