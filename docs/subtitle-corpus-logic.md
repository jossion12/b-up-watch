# 字幕生成后的下游处理链路

本文档聚焦「字幕成功生成之后会发生什么」：数据库落库、本地 Markdown 归档、RAGFlow 语料生成与同步、异常分支（视频不可用 / 占位字幕 / 时长不符 / Whisper fallback），以及运维脚本与配置项。字幕**获取**侧的细节不在此处展开，详见 `docs/bilibili-rag-workflow.md`。

---

## 1. 整体流程

```text
调度器 _subtitle_loop (scheduler.py:105)
    │
    ▼
为 has_subtitle=false 的视频创建 subtitle_fetch 任务
    │
    ▼
TaskRunner 执行 handle_subtitle_fetch (handlers.py:114)
    │
    ├─ 成功 ─► fetch_video_subtitle (fetch_subtitle.py:147)
    │            │
    │            ├─ B 站字幕 OK ─► 写 DB ─► _ingest_video_subtitle
    │            │                       │
    │            │                       ├─ save_subtitle_to_file  本地 Markdown
    │            │                       ├─ save_ragflow_corpus    RAGFlow 语料
    │            │                       └─ _enqueue_ragflow_sync  排队 rag_ingest
    │            │                                                  │
    │            │                                                  ▼
    │            │                                       handle_rag_ingest
    │            │                                          (handlers.py:347)
    │            │                                          │
    │            │                                          ├─ ensure_dataset
    │            │                                          ├─ upload_or_replace (hash 增量)
    │            │                                          ├─ parse_and_wait
    │            │                                          ├─ ensure_chat
    │            │                                          └─ save_sync_state
    │            │
    │            └─ 占位字幕（啥都木有） ─► 写 DB + 归档 + 语料，不再尝试 fallback
    │
    ├─ VIDEO_UNAVAILABLE ─► 直接标记完成（handlers.py:128）
    ├─ SUBTITLE_UNAVAILABLE ─► _run_whisper_fallback
    ├─ SUBTITLE_DURATION_MISMATCH ─► _run_whisper_fallback
    └─ 其它异常 ─► 抛出，由 runner 走重试 / 退避
```

落库节奏：**先写 DB 提交，再做本地归档与语料生成**，归档/语料失败不影响 DB 状态。

---

## 2. 入口与前置：subtitle_fetch 任务生成

`backend/app/tasks/scheduler.py:105` 的 `_subtitle_loop` 每 `scheduler_subtitle_interval_sec`（默认 120s）扫描一次数据库：

```python
# scheduler.py:157  _enqueue_subtitle_tasks
videos = db.execute(
    select(Video).where(
        Video.user_id == DEFAULT_USER_ID,
        Video.has_subtitle.is_(False),
        ~active_subtitle,        # 没有 pending/running 的 subtitle_fetch
        ~recent_failed,          # 退避窗口内没有 failed 任务
    ).order_by(Video.published_at.desc()).limit(self.batch_size)
).scalars().all()
```

为每个命中视频调用 `create_task(db, "subtitle_fetch", "video", v.id)`，并 `notify_runner()` 唤醒 worker。

> 退避窗口：`scheduler_failed_task_backoff_sec`（默认 1800s）。AI 总结功能已暂停，`_summary_loop` 只空转。

---

## 3. 字幕任务处理：`handle_subtitle_fetch`

入口：`backend/app/tasks/handlers.py:114`

```python
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

异常码分支：

| 异常码 | 触发场景 | 处理 |
|--------|---------|------|
| `VIDEO_UNAVAILABLE` | B 站返回「啥都木有」(code=-404) | 直接标记完成，不尝试 Whisper |
| `SUBTITLE_UNAVAILABLE` | B 站无字幕轨道 | 进入 Whisper fallback |
| `SUBTITLE_DURATION_MISMATCH` | 同时满足相对+绝对偏差阈值 | 进入 Whisper fallback |
| 其它 `BizError` | 上游/API 异常 | 抛出，由 runner 重试 |

### 3.1 `fetch_video_subtitle` 主流程

`backend/app/collect/fetch_subtitle.py:147`

1. `bili_sub.get_video_info(bvid)` 拿 `cid`；同时回填 `video.likes`（`stat.like`，列表接口经常为 null）。
2. `bili_sub.get_player_subtitles(bvid, cid)` 拿轨道列表，`pick_preferred_subtitle` 选最优（UP主上传 → AI 字幕）。
3. `bili_sub.download_subtitle_json(track["subtitle_url"])` 下载字幕 JSON。
4. 决定 `source`：`ai_type==0 → "uploader"`，否则 `"bilibili_ai"`；`language` 取轨道 `lan`，默认 `zh-CN`。
5. **占位字幕**（所有非空文本均为「啥都木有」，`_is_placeholder_subtitle`）：跳过时长校验，写 DB 后直接归档+语料，不走 fallback。
6. **时长校验**：`_check_subtitle_duration`，同时满足相对偏差（默认 15%）与绝对偏差（默认 10s）才抛 `SUBTITLE_DURATION_MISMATCH`。校验**在 DB 写之前**，避免 fallback 再写一条同 `video_id` 字幕触发唯一约束冲突。
7. `_upsert_subtitle`：按 `video_id` 创建或更新 `Subtitle` 记录（`language`/`source`/`lines`/`fetched_at`）。
8. 更新视频状态：`video.has_subtitle = True`；若原状态为 `new` 则改为 `subtitled`。
9. `db.commit()`。
10. 本地归档 + RAGFlow 语料生成（失败仅 `log.warning`，不影响 DB）。

---

## 4. 字幕成功后的二次处理：`_ingest_video_subtitle`

入口：`backend/app/tasks/handlers.py:60`。这是「字幕生成后」链路的真正枢纽：

```python
async def _ingest_video_subtitle(video, lines, db, source="unknown") -> None:
    settings = get_settings()
    try:
        md_path = save_subtitle_to_file(video, lines)

        corpus_path: Optional[Path] = None
        if settings.ragflow_corpus_enabled:
            corpus_path = save_ragflow_corpus(video, lines, source=source)
            log.info("[rag corpus] video=%s, subtitle=%s, corpus=%s",
                     video.id, md_path.name, corpus_path.name if corpus_path else "disabled")

        if settings.ragflow_sync_enabled and corpus_path:
            task = _enqueue_ragflow_sync(db, video.uploader)
            if task is not None:
                log.info("[ragflow sync] enqueued for uploader=%s video=%s task=%s",
                         video.uploader_id, video.id, task.task_id)
    except Exception as e:
        log.warning("[rag corpus] video=%s, failed: %s", video.id, e)
```

三件事按顺序：

| 步骤 | 函数 | 文件 | 行为 |
|------|------|------|------|
| 1 | `save_subtitle_to_file` | `fetch_subtitle.py:137` | 写本地 Markdown 归档 |
| 2 | `save_ragflow_corpus` | `corpus.py:138` | 生成 RAGFlow 语料文件 |
| 3 | `_enqueue_ragflow_sync` | `handlers.py:34` | 启用 RagFlow 同步时为该 UP 主排队 `rag_ingest` 任务 |

> 上述任意一步抛错都会被外层 `try/except` 捕获，**只记 warning，不影响 DB 状态与上游任务标记完成**。

### 4.1 本地归档

`backend/app/collect/fetch_subtitle.py:137`

- 路径：`data/{up主名称}/YYYYMMDD-{视频标题}.md`（`_subtitle_file_path`，`fetch_subtitle.py:102`）。
- 格式：每条字幕一行 `[MM:SS.mmm -> MM:SS.mmm] 文本`，空行分隔（`_subtitle_to_markdown`，`fetch_subtitle.py:83`）。
- 文件名清洗：`_sanitize_filename` 替换 `\\ / : * ? " < > |` 与空白为下划线，限制长度 120。
- 不存在父目录时 `mkdir(parents=True, exist_ok=True)`。

### 4.2 自动排队 RagFlow 同步

`backend/app/tasks/handlers.py:34`

```python
def _enqueue_ragflow_sync(db, up: Uploader) -> Task | None:
    settings = get_settings()
    if not settings.ragflow_sync_enabled:
        return None
    active = db.execute(
        select(Task).where(
            Task.type == "rag_ingest",
            Task.ref_type == "uploader",
            Task.ref_id == up.id,
            Task.status.in_(["pending", "running"]),
        )
    ).scalar_one_or_none()
    if active is not None:
        return active
    task = create_task(
        db, task_type="rag_ingest", ref_type="uploader", ref_id=up.id,
        meta={"up_name": up.name, "trigger": "auto"},
    )
    notify_runner()
    return task
```

去重逻辑：同一 UP 主存在 `pending`/`running` 的 `rag_ingest` 任务时直接复用，不重复排队。`meta.trigger="auto"` 用于在任务列表里区分是字幕触发还是手动触发。

---

## 5. RAGFlow 语料生成（`app/collect/corpus.py`）

入口：`build_ragflow_corpus`（`corpus.py:86`）→ `save_ragflow_corpus`（`corpus.py:138`）。

### 5.1 分段策略

`backend/app/rag/parser.py:131` 的 `segment_by_pause`：

- 两条字幕间隔 `> 2.5s` 切分（`pause_threshold`）；
- 单段累计时长 `> 60s` 强制切分（`max_segment_duration_sec`），避免长独白塞给下游；
- 每段合并为一段连续文本（`TextSegment`）。

`segments_from_subtitle_lines`（`parser.py:189`）从 `lines: [{start_sec, end_sec, text}]` 直接构造 `SubtitleEntry`，跳过空文本行。

### 5.2 文本清洗

`clean_segment_text`（`corpus.py:60`）：

- 合并多余空格；
- 删除常见口语填充词：`呃/啊/嗯/哎/那个/这个/然后/就是/对吧/是吧/那么/所以/其实/真的/基本上/说白了`；
- **仅删除作为独立词出现**（前后为空白或标点），避免误删语义内容；
- 去除句首残留标点。

### 5.3 Markdown 输出格式

```markdown
---
title: 视频标题
uploader: UP主名称
uploader_id: ...
video_id: ...
bvid: ...
published_at: 2026-01-11
source: bilibili_ai    # uploader / bilibili_ai / whisper
url: https://www.bilibili.com/video/BVxxxxx
---

# 视频标题

> UP主：UP主名称 | 发布时间：2026-01-11 | 来源：bilibili_ai

## 00:12 - 00:34

清洗后的第一段文本...

## 00:35 - 01:10

清洗后的第二段文本...
```

### 5.4 文件落盘

`save_ragflow_corpus`（`corpus.py:138`）：

- 路径：`{ragflow_corpus_dir}/{up主名称}/YYYYMMDD-{视频标题}.md`，默认 `data/corpus`。
- `ragflow_corpus_enabled=False` 时直接 `return Path()`，不写盘。
- `path.parent.mkdir(parents=True, exist_ok=True)` 后 `write_text(content, encoding="utf-8")`。

### 5.5 工具方法

| 方法 | 行号 | 用途 |
|------|------|------|
| `get_corpus_dir()` | `corpus.py:132` | 返回 `Path(ragflow_corpus_dir).expanduser()` |
| `clear_ragflow_corpus(up_name)` | `corpus.py:169` | 删除某 UP 主目录下所有 `*.md`，返回删除数量 |

---

## 6. RagFlow 同步：`handle_rag_ingest`

入口：`backend/app/tasks/handlers.py:347`。任务 `ref_type=uploader, ref_id=uploader_id`。当 `ragflow_sync_enabled=False` 时直接返回。

整条链路（`backend/app/rag/ragflow_sync.py:316` 的 `sync_uploader_to_ragflow`）：

| 步骤 | 函数 | 行号 | 行为 |
|------|------|------|------|
| 1 | `_ensure_dataset` | 119 | `client.get_or_create_dataset(name, embedding_model, chunk_method, dataset_id=up.ragflow_dataset_id)`；首次创建时回填 `Uploader.ragflow_dataset_id` |
| 2 | 列出本地与远端文档 | 346-352 | `_find_local_corpus_files(up_dir)`、`client.list_documents(dataset_id)`；加载本地 `.ragflow-sync.json` |
| 3 | 遍历本地文件 → `_upload_or_replace` | 157 | 见 6.1 |
| 4 | 清理孤立文档 | 378 | 本地不存在但远端仍存在的文档删除 |
| 5 | 收集待解析 doc_id | 388-401 | hash 与 state 不一致 → 加入解析队列 |
| 6 | `_parse_and_wait` | 223 | `client.parse_documents` + 轮询 `client.get_document.run` 直到 `DONE`/`FAIL`/`CANCEL`，超时 `ragflow_parse_timeout_sec`（默认 600s） |
| 7 | `_ensure_chat` | 277 | 优先更新现有 chat，否则按名称查找或新建；维护 `Uploader.ragflow_chat_id` / `ragflow_chat_url` |
| 8 | `_save_sync_state` | 88 | 写入 `up_dir/.ragflow-sync.json` |
| 9 | `db.commit()` | 421 | 持久化 Uploader 变更 |

进度回调 `_update_progress`（`handlers.py:365`）按 0→50（上传阶段）→60（解析开始）→90（解析结束）→100（chat 完成）分段推送，并实时通过 `push_task_updated_sync` 推送 WebSocket。

### 6.1 上传/替换：hash 增量

`_upload_or_replace`（`ragflow_sync.py:157`）：

```python
local_hash = _file_hash(local_path)        # sha256
doc = existing_docs.get(file_name)

if doc is None:
    # 本地新文件 → 直接上传
    upload_result = await client.upload_document(dataset_id, local_path)
    result.uploaded += 1
else:
    if not _should_replace(local_path, local_hash, doc, state):
        result.skipped += 1                       # 内容未变
        state[file_name] = local_hash
    else:
        await client.delete_documents(dataset_id, [doc["id"]])
        await client.upload_document(dataset_id, local_path)  # 替换
        result.replaced += 1
```

`_should_replace`（`ragflow_sync.py:135`）：

- `state` 里记录了上次上传 hash：与当前 hash 不同 → 替换。
- 无 state 记录：用文件大小兜底（`local_size != doc.get("size",0)` → 替换）。

### 6.2 同步状态文件

`{ragflow_corpus_dir}/{up主}/.ragflow-sync.json`：

```json
{
  "20260111-视频标题.md": "sha256...",
  "20260112-视频标题.md": "sha256..."
}
```

由 `_load_sync_state`/`_save_sync_state`（`ragflow_sync.py:76/88`）读写。`scripts/rebuild_ragflow_all_ups.py` 会在重建时统一清空。

### 6.3 同步结果统计 `SyncResult`

`ragflow_sync.py:38`：

| 字段 | 含义 |
|------|------|
| `dataset_id` / `chat_id` | 同步后回填到 Uploader 的 ID |
| `uploaded` | 新上传文件数 |
| `replaced` | 替换文件数 |
| `skipped` | hash 一致跳过数 |
| `failed` | 上传/替换失败文件数 |
| `errors` | 失败详情列表 |

`to_meta()` 把上述字段合并进 `Task.meta`，任务列表接口可直接展示。

---

## 7. Whisper Fallback

入口：`backend/app/tasks/handlers.py:142` 的 `_run_whisper_fallback`。

```text
B 站字幕不可用 ─► asr_pipeline.transcribe_video(v.bvid)
                  │
                  ├─ BizError AUDIO_UNAVAILABLE ─► 标记完成
                  ├─ 其它 BizError ─► 抛出（runner 重试）
                  └─ 成功 ─► 写入 Subtitle(source='whisper', language='zh-CN')
                              │
                              └► _ingest_video_subtitle(v, lines, db, source='whisper')
                                  │
                                  ├─ save_subtitle_to_file
                                  ├─ save_ragflow_corpus
                                  └─ _enqueue_ragflow_sync
```

要点：

- Whisper 转写成功后 `source='whisper'`、`language='zh-CN'` 写库，`has_subtitle=True`、状态按需切到 `subtitled`。
- 后续链路与 B 站字幕完全一致：本地归档、语料生成、自动排队 RagFlow 同步。
- `AUDIO_UNAVAILABLE`（如视频无音轨 / 下载失败）直接标记完成，**不**触发 RagFlow 同步。

---

## 8. 兜底策略与异常码

| 触发条件 | 异常码 | 处理路径 |
|---------|--------|---------|
| `x/web-interface/view` 返回 `code=-404` 且含「啥都木有」 | `VIDEO_UNAVAILABLE` | 直接标记完成 |
| B 站字幕轨道列表为空 | `SUBTITLE_UNAVAILABLE` | Whisper fallback |
| 字幕时长偏差同时超过 ratio + abs 阈值 | `SUBTITLE_DURATION_MISMATCH` | Whisper fallback |
| 字幕文本全部为「啥都木有」 | （不抛异常） | 写库 + 归档 + 语料，不走 fallback |
| Whisper 转写无音轨 | `AUDIO_UNAVAILABLE` | 直接标记完成 |
| 归档/RAGFlow 语料写盘失败 | （不抛异常） | 仅 `log.warning` |
| 其它 `BizError` / `Exception` | 原样 | runner 重试 + 退避 |

时长校验阈值（`config.py:102-103`）：

- `subtitle_duration_mismatch_ratio`：默认 `0.15`（相对偏差 15%）
- `subtitle_duration_mismatch_abs_sec`：默认 `10.0`（绝对偏差 10 秒）
- 需**同时满足**才触发，避免短视频/静音片段误判。

任务失败退避：`scheduler_failed_task_backoff_sec`（默认 1800s），退避窗口内不会重新生成任务。

---

## 9. 运维脚本

### 9.1 批量生成语料

`backend/scripts/generate_corpus.py`

```bash
cd backend
python scripts/generate_corpus.py
```

- 扫描所有 `has_subtitle=true` 的视频，按当前 `Subtitle.lines` + `Subtitle.source` 重新生成 RAGFlow 语料。
- 语料文件路径**幂等覆盖**。
- 跳过 `sub is None or not sub.lines` 的视频。
- 失败不影响整体流程，最后输出 `失败列表`。
- 前置：`RAGFLOW_CORPUS_ENABLED=true`。

### 9.2 重建所有 UP 主的 RagFlow 同步

`backend/scripts/rebuild_ragflow_all_ups.py`

```bash
cd backend
python scripts/rebuild_ragflow_all_ups.py
```

执行步骤：

1. `_reset_uploader_ragflow_ids`：清空所有 `Uploader.ragflow_dataset_id` / `ragflow_chat_id`（因为 RagFlow 侧知识库已重建）。
2. `_clear_sync_state_files`：删除 `corpus_dir` 下所有 `.ragflow-sync.json`，强制全量 hash 重算。
3. `_generate_corpus`：调用 `generate_corpus.py` 重新生成所有语料文件。
4. `_sync_all_uploaders`：逐个 UP 主调用 `sync_uploader_to_ragflow`，汇总 `uploaded/replaced/skipped/failed/errors`。

前置：`RAGFLOW_CORPUS_ENABLED=true`、`RAGFLOW_SYNC_ENABLED=true`、`RAGFLOW_BASE_URL` 与 `RAGFLOW_API_KEY` 已配置。注意：**本脚本不会主动删除 RagFlow 侧资源**，运行前请确认 RagFlow 知识库确实已被清空。

---

## 10. 相关配置项

来源：`backend/app/config.py` 与 `.env`。

| 配置项 | 默认值 | 用途 |
|--------|-------|------|
| `scheduler_subtitle_interval_sec` | 120 | subtitle 扫描间隔 |
| `scheduler_batch_size` | 10 | 每轮最多生成的字幕任务数 |
| `scheduler_failed_task_backoff_sec` | 1800 | 同类型失败任务退避窗口 |
| `subtitle_duration_mismatch_ratio` | 0.15 | 时长校验相对偏差阈值 |
| `subtitle_duration_mismatch_abs_sec` | 10.0 | 时长校验绝对偏差阈值 |
| `rag_auto_ingest_enabled` | false | 旧 Milvus 路径，默认关闭 |
| `ragflow_corpus_enabled` | true | 是否生成 RAGFlow 语料文件 |
| `ragflow_corpus_dir` | `./data/corpus` | 语料输出根目录 |
| `ragflow_sync_enabled` | false | 是否自动同步到 RagFlow |
| `ragflow_base_url` / `ragflow_web_url` | — | API / Web 地址（端口分离时分别配置） |
| `ragflow_api_key` | — | API 鉴权 |
| `ragflow_embed_auth` | 默认值 | Web 端 iframe 嵌入鉴权（与 API Key 不同） |
| `ragflow_embedding_model` | — | 创建知识库时的 embedding 模型 |
| `ragflow_chunk_method` | naive | 分块方法 |
| `ragflow_dataset_language` | Chinese | 知识库语言 |
| `ragflow_parse_timeout_sec` | 600 | 文档解析超时 |
| `ragflow_parse_poll_interval_sec` | 3 | 解析轮询间隔 |

`SESSDATA`、完整 Cookie、RagFlow embed auth 支持运行时通过 `SystemConfig` 覆盖（参考 `config.py:14-51` 的 `_live_*` 缓存）。

---

## 11. 关键文件索引

| 文件 | 角色 |
|------|------|
| `backend/app/tasks/scheduler.py` | 周期生成 `subtitle_fetch` 任务 |
| `backend/app/tasks/handlers.py` | `subtitle_fetch` / `rag_ingest` / `whisper_fallback` / `_ingest_video_subtitle` / `_enqueue_ragflow_sync` |
| `backend/app/collect/fetch_subtitle.py` | B 站字幕抓取、时长校验、本地归档 |
| `backend/app/collect/corpus.py` | RAGFlow 语料生成、清洗、分段、Markdown 组装 |
| `backend/app/rag/parser.py` | 字幕分段（`segment_by_pause` / `segments_from_subtitle_lines`） |
| `backend/app/rag/ragflow_sync.py` | 知识库/聊天助手同步、hash 增量、解析等待 |
| `backend/app/rag/ragflow_client.py` | RagFlow HTTP 客户端封装 |
| `backend/app/transcriber/pipeline.py` | Whisper/ASR 兜底转写 |
| `backend/app/config.py` | 全部配置项定义 |
| `backend/scripts/generate_corpus.py` | 批量生成语料 |
| `backend/scripts/rebuild_ragflow_all_ups.py` | 全量重建 RagFlow 同步 |

---

## 12. 核心代码片段参考

> 以下片段可用于在其他项目复刻该链路，语言为 Python。ORM/配置/工具类可按技术栈替换。

### 12.1 字幕成功后的下游三件事

```python
# backend/app/tasks/handlers.py:60
async def _ingest_video_subtitle(video, lines, db, source="unknown"):
    settings = get_settings()
    try:
        md_path = save_subtitle_to_file(video, lines)
        corpus_path = None
        if settings.ragflow_corpus_enabled:
            corpus_path = save_ragflow_corpus(video, lines, source=source)
        if settings.ragflow_sync_enabled and corpus_path:
            _enqueue_ragflow_sync(db, video.uploader)
    except Exception as e:
        log.warning("[rag corpus] video=%s, failed: %s", video.id, e)
```

### 12.2 本地归档路径与写入

```python
# backend/app/collect/fetch_subtitle.py:102
def _subtitle_file_path(video):
    uploader_name = _sanitize_filename(video.uploader.name)
    published = video.published_at or datetime.now(timezone.utc)
    date_prefix = published.strftime("%Y%m%d")
    video_name = _sanitize_filename(video.title)
    file_name = f"{date_prefix}-{video_name}.md"
    return Path("data") / uploader_name / file_name

# backend/app/collect/fetch_subtitle.py:83
def _subtitle_to_markdown(lines):
    def _fmt(sec):
        m = int(sec // 60); s = int(sec % 60)
        ms = int(round((sec - int(sec)) * 1000))
        return f"{m:02d}:{s:02d}.{ms:03d}"
    parts = []
    for item in lines:
        text = str(item.get("text") or "").strip()
        if not text: continue
        parts.append(f"[{_fmt(item['start_sec'])} -> {_fmt(item['end_sec'])}] {text}")
    return "\n\n".join(parts)

# backend/app/collect/fetch_subtitle.py:137
def save_subtitle_to_file(video, lines):
    path = _subtitle_file_path(video)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_subtitle_to_markdown(lines), encoding="utf-8")
    return path
```

### 12.3 语料 Markdown 组装

```python
# backend/app/collect/corpus.py:86
def build_ragflow_corpus(video, lines, source="unknown", video_url=""):
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
    body = f"# {video.title}\n\n> UP主：{video.uploader.name} | 发布时间：{published_str} | 来源：{source}\n\n"
    for seg in segments:
        cleaned = clean_segment_text(seg.text)
        if not cleaned: continue
        body += f"## {format_time(seg.start_seconds)} - {format_time(seg.end_seconds)}\n\n{cleaned}\n\n"
    return front_matter + body

# backend/app/collect/corpus.py:138
def save_ragflow_corpus(video, lines, source="unknown"):
    settings = get_settings()
    if not settings.ragflow_corpus_enabled:
        return Path()
    corpus_dir = Path(settings.ragflow_corpus_dir).expanduser()
    uploader_name = _sanitize_filename(video.uploader.name)
    published = video.published_at or datetime.now(timezone.utc)
    file_name = f"{published.strftime('%Y%m%d')}-{_sanitize_filename(video.title)}.md"
    path = corpus_dir / uploader_name / file_name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        build_ragflow_corpus(video, lines, source=source,
                             video_url=f"https://www.bilibili.com/video/{video.bvid}"),
        encoding="utf-8",
    )
    return path
```

### 12.4 文本清洗与分段

```python
# backend/app/collect/corpus.py:60
FILLER_WORDS = ["呃","啊","嗯","哎","那个","这个","然后","就是",
                "对吧","是吧","那么","所以","其实","真的","基本上","说白了"]

def clean_segment_text(text):
    text = re.sub(r"\s+", " ", text.strip())
    for w in FILLER_WORDS:
        text = re.sub(rf"(?<![^\s，。、！？；：]){re.escape(w)}(?![^\s，。、！？；：])", "", text)
    text = re.sub(r"\s+", " ", text.strip())
    text = re.sub(r"^[，。、！？；：\s]+", "", text)
    return text

# backend/app/rag/parser.py:131
def segment_by_pause(entries, pause_threshold=2.5, max_segment_duration_sec=60.0):
    segments, current = [], []
    for e in entries:
        if not current:
            current.append(e)
        else:
            gap = e.start_seconds - current[-1].end_seconds
            projected = e.end_seconds - current[0].start_seconds
            if gap > pause_threshold or projected > max_segment_duration_sec:
                segments.append(_make_segment(current))
                current = [e]
            else:
                current.append(e)
    if current:
        segments.append(_make_segment(current))
    return segments
```

### 12.5 自动排队 RagFlow 同步

```python
# backend/app/tasks/handlers.py:34
def _enqueue_ragflow_sync(db, up):
    settings = get_settings()
    if not settings.ragflow_sync_enabled:
        return None
    active = db.execute(
        select(Task).where(
            Task.type == "rag_ingest",
            Task.ref_type == "uploader",
            Task.ref_id == up.id,
            Task.status.in_(["pending", "running"]),
        )
    ).scalar_one_or_none()
    if active is not None:
        return active
    task = create_task(
        db, task_type="rag_ingest", ref_type="uploader", ref_id=up.id,
        meta={"up_name": up.name, "trigger": "auto"},
    )
    notify_runner()
    return task
```

### 12.6 RagFlow 同步：upload + parse + chat

```python
# backend/app/rag/ragflow_sync.py:316
async def sync_uploader_to_ragflow(db, up, on_progress=None):
    settings = get_settings()
    if not settings.ragflow_sync_enabled:
        raise BizError("RAGFLOW_SYNC_DISABLED", "RagFlow 同步未启用", http_status=500)
    result = SyncResult()
    async with RagFlowClient() as client:
        # 1) dataset
        dataset_id = await _ensure_dataset(client, up)
        result.dataset_id = dataset_id

        # 2) 列出本地/远端
        up_dir = _up_corpus_dir(up)
        local_files = _find_local_corpus_files(up_dir)
        existing_docs = {d["name"]: d for d in await client.list_documents(dataset_id)}
        state = _load_sync_state(up_dir)

        # 3) 上传/替换
        for i, p in enumerate(local_files):
            await _upload_or_replace(client, dataset_id, p, existing_docs, state, result)
            existing_docs.pop(p.name, None)
            if on_progress and len(local_files):
                on_progress(int((i + 1) / len(local_files) * 50))

        # 4) 清理孤立
        orphans = [d["id"] for d in existing_docs.values() if d.get("id")]
        if orphans:
            await client.delete_documents(dataset_id, orphans)

        # 5) 收集待解析
        remote = {d["name"]: d for d in await client.list_documents(dataset_id)}
        to_parse = []
        for p in local_files:
            h = _file_hash(p)
            if state.get(p.name) != h and remote.get(p.name, {}).get("id"):
                to_parse.append(remote[p.name]["id"])
                state[p.name] = h

        # 6) 解析等待
        if to_parse:
            await _parse_and_wait(client, dataset_id, to_parse, up)

        # 7) chat
        chat_id = await _ensure_chat(client, up, dataset_id)
        result.chat_id = chat_id

    _save_sync_state(up_dir, state)
    db.commit()
    if on_progress: on_progress(100)
    return result
```

### 12.7 Whisper Fallback

```python
# backend/app/tasks/handlers.py:142
async def _run_whisper_fallback(db, v, task=None):
    try:
        lines = await asr_pipeline.transcribe_video(v.bvid)
    except BizError as e:
        if e.code == "AUDIO_UNAVAILABLE":
            v.has_subtitle = True
            if v.status == "new": v.status = "subtitled"
            db.commit()
            return
        raise
    sub = db.get(Subtitle, v.id) or Subtitle(video_id=v.id, language="zh-CN",
                                             source="whisper", lines=lines,
                                             fetched_at=datetime.now(timezone.utc))
    sub.language = "zh-CN"
    sub.source = "whisper"
    sub.lines = lines
    sub.fetched_at = datetime.now(timezone.utc)
    if sub not in db: db.add(sub)
    v.has_subtitle = True
    if v.status == "new": v.status = "subtitled"
    db.commit()
    await _ingest_video_subtitle(v, lines, db, source="whisper")
```

---

## 13. 调用关系速查

```text
scheduler._subtitle_loop ──► Task(subtitle_fetch)
                                   │
                                   ▼
                       handlers.handle_subtitle_fetch
                                   │
        ┌──────────────────────────┼──────────────────────────┐
        ▼                          ▼                          ▼
fetch_video_subtitle      fetch_video_subtitle       _run_whisper_fallback
(B 站字幕成功)            (占位字幕直接返回)         (B 站字幕缺失/时长不符)
        │                          │                          │
        └────────────┬─────────────┘                          │
                     ▼                                        │
           _ingest_video_subtitle ◄───────────────────────────┘
                     │
        ┌────────────┼─────────────────┐
        ▼            ▼                 ▼
save_subtitle_to_file  save_ragflow_corpus  _enqueue_ragflow_sync
(本地 data/{up}/…)     (data/corpus/{up}/…) (Task rag_ingest)
                                                  │
                                                  ▼
                                      handlers.handle_rag_ingest
                                                  │
                                                  ▼
                                      ragflow_sync.sync_uploader_to_ragflow
                                                  │
                       ┌──────────────┬──────────┴──────────┬──────────────┐
                       ▼              ▼                     ▼              ▼
                  ensure_dataset  upload_or_replace   parse_and_wait   ensure_chat
                       │              │                     │              │
                       └──────── 写 sync_state ──────┬───────┴──────────────┘
                                                     ▼
                                              db.commit() + meta 回填
```