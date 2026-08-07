# 字幕获取与语料生成逻辑

本文档说明项目在获取字幕后，如何持久化字幕、生成 RAGFlow 语料，以及异常时的兜底策略。

## 1. 整体流程

```text
调度器扫描 (scheduler.py:105)
    │
    ▼
创建 subtitle_fetch 任务
    │
    ▼
TaskRunner 执行 handle_subtitle_fetch (handlers.py:82)
    │
    ├── 成功 ──► fetch_video_subtitle (fetch_subtitle.py:124)
    │              │
    │              ├── B 站有字幕 ──► 写 DB / 归档 / 生成 corpus
    │              │
    │              └── 无字幕或时长不符 ──► _run_whisper_fallback (handlers.py:109)
    │                                         │
    │                                         └── Whisper ASR ──► 写 DB / 归档 / 生成 corpus
    │
    └── 视频不可用 ──► 直接标记完成
```

## 2. 字幕获取成功后的处理

入口：`backend/app/collect/fetch_subtitle.py:124`

### 2.1 写入数据库

- 写入/更新 `Subtitle` 表：`language`、`source`（`uploader` 或 `bilibili_ai`）、`lines`、`fetched_at`（`fetch_subtitle.py:179-194`）。
- 回填真实点赞数：从 `x/web-interface/view` 的 `stat.like` 回填到 `video.likes`（`fetch_subtitle.py:152-157`）。
- 更新视频状态：`video.has_subtitle = True`，若原状态为 `new` 则改为 `subtitled`（`fetch_subtitle.py:212-214`）。

### 2.2 占位字幕处理

如果字幕内容全部为 `啥都木有`，视为已完成，不再尝试 Whisper fallback，也不再重复拉取（`fetch_subtitle.py:196-208`）。

### 2.3 时长校验

对比字幕时间跨度与视频时长，若同时满足相对偏差和绝对偏差阈值，则抛出 `SUBTITLE_DURATION_MISMATCH`，由外层 fallback 到 Whisper（`fetch_subtitle.py:210`、`fetch_subtitle.py:49-67`）。

### 2.4 本地归档

将字幕保存为 Markdown 文件：

```text
data/{up主名称}/YYYYMMDD-{视频标题}.md
```

实现见 `fetch_subtitle.py:219-221` 与 `save_subtitle_to_file`（`fetch_subtitle.py:114`）。

### 2.5 RAGFlow 语料生成

调用 `save_ragflow_corpus(video, lines, source=source)`（`corpus.py:138`）。

> 开关：`settings.ragflow_corpus_enabled`，关闭时直接跳过。

语料文件路径：

```text
{ragflow_corpus_dir}/{up主名称}/YYYYMMDD-{视频标题}.md
```

## 3. 任务处理器中的二次兜底

`backend/app/tasks/handlers.py:82`

- B 站字幕成功：调用 `_ingest_video_subtitle` 再次执行归档和语料生成（`handlers.py:92`）。
- `VIDEO_UNAVAILABLE`：直接标记完成（`handlers.py:97-101`）。
- `SUBTITLE_UNAVAILABLE` / `SUBTITLE_DURATION_MISMATCH`：进入 Whisper fallback（`handlers.py:105-106`）。
- 其它错误：抛出异常，由 runner 重试。

### 3.1 Whisper Fallback

`_run_whisper_fallback`（`handlers.py:109`）：

1. 拉取音频并用本地 ASR（Whisper 流水线）转写。
2. `AUDIO_UNAVAILABLE`：直接标记完成（`handlers.py:116-122`）。
3. 写入 `Subtitle(source='whisper')`。
4. 更新视频状态。
5. 本地归档 + 生成 RAGFlow 语料。

## 4. 语料内容生成细节

入口：`backend/app/collect/corpus.py:86`

### 4.1 分段策略

`segments_from_subtitle_lines`（`parser.py:189`）将字幕按停顿切分为话题段：

- 两条字幕间隔 `> 2.5s` 切分；
- 单段累计时长 `> 60s` 强制切分；
- 每段合并为一段连续文本。

### 4.2 文本清洗

`clean_segment_text`（`corpus.py:60`）：

- 合并多余空格；
- 删除常见口语填充词：呃、啊、嗯、那个、然后、就是、对吧、是吧等；
- 只删除作为独立词出现的填充词，避免误删语义内容；
- 去除句首残留标点。

### 4.3 输出格式

```markdown
---
title: 视频标题
uploader: UP主名称
uploader_id: ...
video_id: ...
bvid: ...
published_at: 2026-01-11
source: bilibili_ai
url: https://www.bilibili.com/video/BVxxxxx
---

# 视频标题

> UP主：UP主名称 | 发布时间：2026-01-11 | 来源：bilibili_ai

## 00:12 - 00:34

清洗后的第一段文本...

## 00:35 - 01:10

清洗后的第二段文本...
```

## 5. 调度与触发

`backend/app/tasks/scheduler.py:105` 的 `_subtitle_loop` 会周期扫描数据库，为 `has_subtitle=False` 且没有 pending/running 任务的视频创建 `subtitle_fetch` 任务。

AI 自动总结任务当前已暂停：`handle_ai_summary` 直接返回，`_summary_loop` 空转。

## 6. 核心代码片段参考

> 以下片段可直接用于在其他项目中复刻该逻辑，语言为 Python。ORM/配置/工具类可按你的技术栈替换。

### 6.1 调度器：为无字幕视频生成任务

```python
# backend/app/tasks/scheduler.py:157
async def _enqueue_subtitle_tasks(self) -> int:
    with self._session_factory() as db:
        active_subtitle = (
            select(Task)
            .where(
                Task.type == "subtitle_fetch",
                Task.ref_type == "video",
                Task.ref_id == Video.id,
                Task.status.in_(["pending", "running"]),
            )
            .exists()
        )
        recent_failed = self._recent_failed_task("subtitle_fetch")
        videos = db.execute(
            select(Video)
            .where(
                Video.user_id == DEFAULT_USER_ID,
                Video.has_subtitle.is_(False),
                ~active_subtitle,
                ~recent_failed,
            )
            .order_by(Video.published_at.desc())
            .limit(self.batch_size)
        ).scalars().all()

        created = 0
        for v in videos:
            create_task(db, "subtitle_fetch", "video", v.id)
            created += 1
        if created:
            db.commit()
        return created
```

### 6.2 任务处理器入口

```python
# backend/app/tasks/handlers.py:82
@task_handler("subtitle_fetch")
async def handle_subtitle_fetch(db, task: Task) -> None:
    if task.ref_type != "video" or not task.ref_id:
        raise BizError("TASK_INVALID_REF", "subtitle_fetch 必须绑定 video", http_status=500)
    v = db.get(Video, task.ref_id)
    if v is None or v.user_id != DEFAULT_USER_ID:
        raise BizError("VIDEO_NOT_FOUND", "视频不存在", http_status=404)

    try:
        sub = await collect_subtitle.fetch_video_subtitle(db, v)
        await _ingest_video_subtitle(v, sub.lines, db, source=sub.source)
        return
    except BizError as e:
        if e.code == "VIDEO_UNAVAILABLE":
            v.has_subtitle = True
            if v.status == "new":
                v.status = "subtitled"
            db.commit()
            return
        if e.code not in ("SUBTITLE_UNAVAILABLE", "SUBTITLE_DURATION_MISMATCH"):
            raise
        await _run_whisper_fallback(db, v, task)
```

### 6.3 B 站字幕获取与持久化

```python
# backend/app/collect/fetch_subtitle.py:124
async def fetch_video_subtitle(db: Session, video: Video) -> Subtitle:
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
        raise BizError("SUBTITLE_UNAVAILABLE", "该视频无字幕", http_status=422)

    lines = await bili_sub.download_subtitle_json(track["subtitle_url"])

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

    save_subtitle_to_file(video, lines)
    save_ragflow_corpus(video, lines, source=source)
    return sub
```

### 6.4 字幕时长校验

```python
# backend/app/collect/fetch_subtitle.py:49
def _check_subtitle_duration(lines: list[dict], video_duration_sec: int) -> None:
    if video_duration_sec <= 0:
        return
    span = _subtitle_span_seconds(lines)
    diff = abs(span - video_duration_sec)
    ratio_ok = diff / video_duration_sec >= settings.subtitle_duration_mismatch_ratio
    abs_ok = diff >= settings.subtitle_duration_mismatch_abs_sec
    if ratio_ok and abs_ok:
        raise BizError(
            "SUBTITLE_DURATION_MISMATCH",
            f"字幕时长（{span:.1f}s）与视频时长（{video_duration_sec}s）不一致",
            details={"subtitle_span_sec": span, "video_duration_sec": video_duration_sec},
            http_status=422,
        )
```

### 6.5 Whisper Fallback

```python
# backend/app/tasks/handlers.py:109
async def _run_whisper_fallback(db, v: Video, task: Task | None = None) -> None:
    task_id = task.task_id if task else None
    lines = await asr_pipeline.transcribe_video(v.bvid)

    sub = db.get(Subtitle, v.id)
    now = datetime.now(timezone.utc)
    if sub is None:
        sub = Subtitle(
            video_id=v.id,
            language="zh-CN",
            source="whisper",
            lines=lines,
            fetched_at=now,
        )
        db.add(sub)
    else:
        sub.language = "zh-CN"
        sub.source = "whisper"
        sub.lines = lines
        sub.fetched_at = now

    v.has_subtitle = True
    if v.status == "new":
        v.status = "subtitled"
    db.commit()

    await _ingest_video_subtitle(v, lines, db, source="whisper")
```

### 6.6 本地归档

```python
# backend/app/collect/fetch_subtitle.py:102
def _subtitle_file_path(video: Video) -> Path:
    uploader_name = _sanitize_filename(video.uploader.name)
    published = video.published_at or datetime.now(timezone.utc)
    date_prefix = published.strftime("%Y%m%d")
    video_name = _sanitize_filename(video.title)
    file_name = f"{date_prefix}-{video_name}.md"
    return Path("data") / uploader_name / file_name

# backend/app/collect/fetch_subtitle.py:83
def _subtitle_to_markdown(lines: list[dict]) -> str:
    def _fmt(sec: float) -> str:
        m = int(sec // 60)
        s = int(sec % 60)
        ms = int(round((sec - int(sec)) * 1000))
        return f"{m:02d}:{s:02d}.{ms:03d}"

    parts = []
    for item in lines:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        start = float(item.get("start_sec", 0))
        end = float(item.get("end_sec", 0))
        parts.append(f"[{_fmt(start)} -> {_fmt(end)}] {text}")
    return "\n\n".join(parts)
```

### 6.7 语料分段

```python
# backend/app/rag/parser.py:131
def segment_by_pause(
    entries: List[SubtitleEntry],
    pause_threshold: float = 2.5,
    max_segment_duration_sec: float = 60.0,
) -> List[TextSegment]:
    segments: List[TextSegment] = []
    current: List[SubtitleEntry] = []

    for e in entries:
        if not current:
            current.append(e)
        else:
            gap = e.start_seconds - current[-1].end_seconds
            projected_duration = e.end_seconds - current[0].start_seconds
            if gap > pause_threshold or projected_duration > max_segment_duration_sec:
                segments.append(_make_segment(current))
                current = [e]
            else:
                current.append(e)

    if current:
        segments.append(_make_segment(current))

    return segments

# backend/app/rag/parser.py:189
def segments_from_subtitle_lines(
    lines: List[dict],
    pause_threshold: float = 2.5,
    max_segment_duration_sec: float = 60.0,
) -> List[TextSegment]:
    entries = []
    for idx, line in enumerate(lines, 1):
        text = re.sub(r"\s+", " ", str(line.get("text") or "").strip())
        if not text:
            continue
        start = float(line.get("start_sec", 0.0))
        end = float(line.get("end_sec", start))
        entries.append(SubtitleEntry(
            index=idx,
            start_time=_seconds_to_time_str(start),
            end_time=_seconds_to_time_str(end),
            start_seconds=start,
            end_seconds=end,
            text=text,
        ))
    return segment_by_pause(entries, pause_threshold, max_segment_duration_sec)
```

### 6.8 语料文本清洗

```python
# backend/app/collect/corpus.py:60
FILLER_WORDS = ["呃", "啊", "嗯", "哎", "那个", "这个", "然后", "就是", "对吧", "是吧", "那么", "所以", "其实", "真的", "基本上", "说白了"]

def clean_segment_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text.strip())
    for w in FILLER_WORDS:
        # 仅删除作为独立填充词出现的情况
        text = re.sub(rf"(?<![^\s，。、！？；：]){re.escape(w)}(?![^\s，。、！？；：])", "", text)
    text = re.sub(r"\s+", " ", text.strip())
    text = re.sub(r"^[，。、！？；：\s]+", "", text)
    return text
```

### 6.9 语料 Markdown 组装

```python
# backend/app/collect/corpus.py:86
def build_ragflow_corpus(
    video: Video,
    lines: list[dict],
    source: str = "unknown",
    video_url: str = "",
) -> str:
    segments = segments_from_subtitle_lines(lines)
    published_str = video.published_at.strftime("%Y-%m-%d") if video.published_at else ""

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
        cleaned = clean_segment_text(seg.text)
        if not cleaned:
            continue
        body += f"## {format_time(seg.start_seconds)} - {format_time(seg.end_seconds)}\n\n{cleaned}\n\n"

    return front_matter + body
```

### 6.10 保存语料文件

```python
# backend/app/collect/corpus.py:138
def save_ragflow_corpus(
    video: Video,
    lines: list[dict],
    source: str = "unknown",
) -> Path:
    settings = get_settings()
    if not settings.ragflow_corpus_enabled:
        return Path()

    corpus_dir = Path(settings.ragflow_corpus_dir).expanduser()
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
    return path
```

## 7. 关键文件索引

| 文件 | 说明 |
|------|------|
| `backend/app/tasks/scheduler.py` | 周期生成字幕任务 |
| `backend/app/tasks/handlers.py` | 任务处理器、Whisper fallback |
| `backend/app/collect/fetch_subtitle.py` | B 站字幕抓取、校验、归档 |
| `backend/app/collect/corpus.py` | RAGFlow 语料生成 |
| `backend/app/rag/parser.py` | 字幕分段与解析 |
| `backend/app/api/subtitles.py` | 字幕查询/创建/导出接口 |
