# B站视频搜索 → 字幕获取 → RAG 复盘：完整实现文档

> 本文档从当前项目提炼，描述如何从零开发一个"根据关键词搜索 B站视频 → 用户选择视频 → 获取字幕 → 生成 RAG 向量知识库"的完整系统。
> 文档覆盖前后端架构、数据流、核心代码实现、数据库设计、环境配置与部署步骤。

---

## 目录

1. [系统概述](#1-系统概述)
2. [技术栈](#2-技术栈)
3. [整体架构与数据流](#3-整体架构与数据流)
4. [数据库设计](#4-数据库设计)
5. [环境搭建](#5-环境搭建)
6. [后端实现详解](#6-后端实现详解)
   - 6.1 [B站视频搜索](#61-b站视频搜索)
   - 6.2 [视频选择与入库](#62-视频选择与入库)
   - 6.3 [字幕获取](#63-字幕获取)
   - 6.4 [RAG 生成](#64-rag-生成)
   - 6.5 [任务队列](#65-任务队列)
7. [前端实现详解](#7-前端实现详解)
8. [API 接口参考](#8-api-接口参考)
9. [部署与运行](#9-部署与运行)
10. [常见问题与扩展](#10-常见问题与扩展)

---

## 1. 系统概述

本系统解决的核心问题：

1. 用户输入关键词，搜索 B站相关视频。
2. 用户在结果列表中选择感兴趣的视频。
3. 系统后台获取选中视频的字幕（官方字幕 / AI 字幕 / 本地 ASR 兜底）。
4. 将字幕解析、切分、提取结构化观点，生成向量 Embedding 存入 Milvus。
5. 用户可通过搜索或对话方式，基于已导入的视频字幕进行 RAG 问答。

系统不保存视频文件本身，只采集视频元数据、字幕文本和向量片段，存储开销极小。

---

## 2. 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | React 19 + TypeScript + Vite + Tailwind CSS + shadcn/ui + react-router |
| 后端 | Python 3.10+ + FastAPI + SQLAlchemy 2.0 + Pydantic 2 |
| 数据库 | SQLite（默认）/ PostgreSQL（可替换） |
| 向量库 | Milvus Lite（本地 `.db`）/ Milvus Server |
| Embedding | sentence-transformers / Ollama |
| ASR 兜底 | Qwen3-ASR（本地） |
| 音视频工具 | yt-dlp + ffmpeg + ffprobe |
| LLM | OpenAI 兼容接口（通义千问 / Ollama 等） |

---

## 3. 整体架构与数据流

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│  前端 React SPA                                                              │
│  /video-search ──► 关键词搜索 ──► 选择视频 ──► 提交获取字幕                       │
│  /jobs ──► 查看任务状态 / 取消任务                                            │
│  /review/:uploaderId ──► RAG 搜索 / 对话                                      │
└─────────────────────────────┬───────────────────────────────────────────────┘
                              │ REST / WebSocket
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  后端 FastAPI                                                                │
│  ├── /videos/search          B站关键词搜索                                     │
│  ├── /videos/search/fetch-subtitles  选择视频后创建字幕任务                     │
│  ├── /videos/{id}/subtitle/fetch     单个视频获取字幕                         │
│  ├── /rag/*                  RAG 导入/搜索/对话/统计                          │
│  └── /tasks/*                任务查询/取消/重试                               │
└─────────────────────────────┬───────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌──────────────┐    ┌─────────────────┐    ┌─────────────────┐
│ Bilibili API │    │  SQLite 数据库   │    │  Milvus 向量库   │
│ 搜索/视频信息 │    │ 视频/字幕/任务   │    │ 观点卡片 chunks │
│ 字幕轨道     │    │                 │    │                 │
└──────────────┘    └─────────────────┘    └─────────────────┘
```

核心流程：

1. **搜索**：前端 `/video-search` 调用 `GET /videos/search`，后端通过 B站 WBI 签名搜索接口获取视频列表。
2. **选择**：用户勾选视频，点击"获取字幕"，前端调用 `POST /videos/search/fetch-subtitles`。
3. **入库**：后端为每个视频创建 `Uploader`（如不存在）和 `Video` 记录，然后创建 `subtitle_fetch` 任务。
4. **字幕**：后台单 worker `TaskRunner` 消费任务，按"UP主上传字幕 → B站 AI 字幕 → 本地 ASR 兜底"的顺序获取字幕。
5. **RAG 增量导入**：字幕获取成功后，自动调用 `ingest_video()`，将字幕切分、提取观点、生成 Embedding、写入 Milvus。
6. **RAG 使用**：用户通过 `GET /rag/search` 或 `POST /rag/chat` 进行搜索/对话。

---

## 4. 数据库设计

使用 SQLAlchemy 2.0 定义，默认 SQLite。所有业务表预留 `user_id` 字段，当前恒为 `"default"`，便于后续扩展多用户。

### 4.1 表结构总览

| 表名 | 说明 |
|------|------|
| `uploaders` | UP主信息 |
| `videos` | 视频元数据 |
| `subtitles` | 字幕文本（与 video 1:1） |
| `summaries` | AI 总结（当前已暂停使用） |
| `summary_templates` | 总结 Prompt 模板 |
| `tasks` | 后台任务队列 |
| `system_config` | 系统配置（单例） |
| `topic_daily_stats` | 洞察聚合：话题每日统计 |
| `topic_opinions` | 洞察聚合：话题观点 |
| `video_stats_snapshot` | 洞察聚合：视频统计快照 |

### 4.2 `uploaders`

```python
class Uploader(Base):
    __tablename__ = "uploaders"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), default="default")
    bilibili_uid: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    avatar_url: Mapped[str] = mapped_column(String(512), nullable=True)
    fans_count: Mapped[int] = mapped_column(Integer, default=0)
    category: Mapped[str] = mapped_column(String(64), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    unread_count: Mapped[int] = mapped_column(Integer, default=0)
    last_video_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    group_id: Mapped[str] = mapped_column(String(32), nullable=True)
    notify_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
```

唯一约束：`(user_id, bilibili_uid)`。

### 4.3 `videos`

```python
VIDEO_STATUS = ("new", "subtitled", "summarizing", "summarized", "failed")

class Video(Base):
    __tablename__ = "videos"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), default="default")
    bvid: Mapped[str] = mapped_column(String(20), nullable=False)
    uploader_id: Mapped[str] = mapped_column(ForeignKey("uploaders.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    cover_url: Mapped[str] = mapped_column(String(512), nullable=True)
    duration_sec: Mapped[int] = mapped_column(Integer, default=0)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    views: Mapped[int] = mapped_column(Integer, default=0)
    danmaku_count: Mapped[int] = mapped_column(Integer, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(Enum(*VIDEO_STATUS), default="new")
    has_subtitle: Mapped[bool] = mapped_column(Boolean, default=False)
    has_summary: Mapped[bool] = mapped_column(Boolean, default=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
```

唯一约束：`(user_id, bvid)`。

### 4.4 `subtitles`

```python
SUBTITLE_SOURCE = ("uploader", "bilibili_ai", "whisper")

class Subtitle(Base):
    __tablename__ = "subtitles"

    video_id: Mapped[str] = mapped_column(ForeignKey("videos.id"), primary_key=True)
    language: Mapped[str] = mapped_column(String(16), default="zh-CN", nullable=False)
    source: Mapped[str] = mapped_column(Enum(*SUBTITLE_SOURCE), nullable=False)
    lines: Mapped[list] = mapped_column(JSON, default=list)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    video: Mapped[Video] = relationship(back_populates="subtitle")
```

`lines` 格式：

```json
[
  {"start_sec": 0.0, "end_sec": 3.5, "text": "第一句话"},
  {"start_sec": 3.5, "end_sec": 7.0, "text": "第二句话"}
]
```

### 4.5 `tasks`

```python
TASK_TYPE = (
    "subtitle_fetch", "ai_summary", "feed_refresh",
    "whisper_transcribe", "video_stats_refresh", "rag_ingest"
)
TASK_STATUS = ("pending", "running", "success", "failed")

class Task(Base):
    __tablename__ = "tasks"

    task_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    type: Mapped[str] = mapped_column(Enum(*TASK_TYPE), nullable=False)
    status: Mapped[str] = mapped_column(Enum(*TASK_STATUS), default="pending")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    ref_type: Mapped[str] = mapped_column(String(16), nullable=True)  # video / uploader
    ref_id: Mapped[str] = mapped_column(String(32), nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, nullable=True)
    error: Mapped[dict] = mapped_column(JSON, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
```

索引：
- `ix_task_status_created` on `(status, created_at)`
- `ix_task_ref` on `(ref_type, ref_id)`

---

## 5. 环境搭建

### 5.1 系统依赖

- Python >= 3.10
- Node.js >= 20
- ffmpeg / ffprobe（ASR 兜底需要）
- Git

### 5.2 后端初始化

```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -e ".[dev]"
# 如需本地 ASR 兜底：
pip install -e ".[asr]"

cp .env.example .env
# 编辑 .env，配置 LLM、B站 Cookie、ASR 模型路径等
```

### 5.3 前端初始化

```bash
cd frontend/app
npm install
```

### 5.4 关键环境变量

```env
# B站
BILIBILI_SESSDATA=
BILIBILI_USER_AGENT=Mozilla/5.0 ...

# LLM（OpenAI 兼容）
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_API_KEY=
LLM_MODEL=qwen3-235b-a22b-instruct
LLM_TIMEOUT_SEC=300
LLM_JSON_MODE=true

# ASR 兜底
QWEN_ASR_MODEL_PATH=
QWEN_ASR_DEVICE=cuda:0

# RAG
REVIEW_BASE_DIR=./data
EMBEDDING_PROVIDER=sentence_transformers
EMBEDDING_MODEL=BAAI/bge-large-zh-v1.5
EMBEDDING_DIM=1024
MILVUS_URI=./data/milvus/upwatch.db
MILVUS_COLLECTION=upwatch_review_chunks

# 数据库
DATABASE_URL=sqlite:///./data/upwatch.db
```

---

## 6. 后端实现详解

### 6.1 B站视频搜索

#### 6.1.1 接口

`GET /api/v1/videos/search`

请求参数：

| 参数 | 类型 | 说明 |
|------|------|------|
| `q` | string | 关键词，1-64 字符 |
| `page` | int | 页码，默认 1 |
| `order` | string | 排序：空=综合，`pubdate`=最新发布，`click`=最多播放 |

响应：

```json
{
  "items": [
    {
      "bvid": "BV1xx411c7mD",
      "title": "视频标题",
      "cover_url": "https://...",
      "duration_sec": 120,
      "published_at": "2026-07-19T10:32:00+08:00",
      "views": 10000,
      "danmaku_count": 200,
      "likes": 500,
      "uploader_mid": "123456",
      "uploader_name": "UP主名称",
      "uploader_avatar_url": "https://..."
    }
  ],
  "page": 1,
  "has_more": true
}
```

#### 6.1.2 后端路由实现

```python
# backend/app/api/videos.py
@router.get("/videos/search", response_model=VideoSearchOut)
async def search_videos(
    q: str = Query(..., min_length=1, max_length=64),
    page: int = Query(1, ge=1, le=50),
    order: str = Query("", description="排序：空=综合，pubdate=最新发布，click=最多播放"),
    db: Session = Depends(get_db),
) -> VideoSearchOut:
    try:
        raw, has_more = await bili_search.search_bili_video(q, page, order)
    except BizError as e:
        if e.code == "BILIBILI_RATE_LIMITED":
            raise
        log.warning("search videos failed: %s", e.message)
        return VideoSearchOut(items=[], page=page, has_more=False)
    except httpx.HTTPError as e:
        log.warning("search videos http error: %s", e)
        return VideoSearchOut(items=[], page=page, has_more=False)

    parsed = bili_search.parse_video_items(raw)
    items = [
        VideoSearchItem(
            bvid=it["bvid"],
            title=it["title"],
            cover_url=it["cover_url"],
            duration_sec=it["duration_sec"],
            published_at=_parse_timestamp(it["published_at"]),
            views=it["views"],
            danmaku_count=it["danmaku_count"],
            likes=it["likes"],
            uploader_mid=it["uploader_mid"],
            uploader_name=it["uploader_name"],
            uploader_avatar_url=it["uploader_avatar_url"],
        )
        for it in parsed
    ]
    return VideoSearchOut(items=items, page=page, has_more=has_more)
```

#### 6.1.3 B站搜索客户端

```python
# backend/app/bilibili/search.py
async def search_bili_video(keyword: str, page: int = 1, order: str = "") -> tuple[list[dict], bool]:
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
    data = await get_client().get("/x/web-interface/wbi/search/all/v2", params=signed)

    total_page = int(data.get("numPages") or 0)
    has_more = page < total_page
    raw = _extract_video_items(data)
    return raw, has_more
```

B站搜索接口需要 WBI 签名。签名流程：

1. 访问 `GET /x/web-interface/nav` 获取 `wbi_img.img_url` 和 `wbi_img.sub_url`。
2. 从 URL 文件名提取 `img_key` 和 `sub_key`。
3. 按 B站公开的 shuffle 表拼接成 `mixin_key`，缓存 24 小时。
4. 请求参数按 key 排序，添加 `wts`（当前时间戳），再计算 `w_rid = md5(query + mixin_key)`。

```python
# backend/app/bilibili/wbi.py
def _sign_params(params: dict, mixin_key: str) -> dict:
    signed = {}
    for k in sorted(params):
        v = params[k]
        if v is None:
            continue
        if isinstance(v, str):
            # B站对特殊字符做了过滤
            v = v.replace("!", "").replace("'", "").replace("(", "").replace(")", "").replace("*", "")
        signed[k] = v
    signed["wts"] = int(time.time())
    query = urlencode(sorted(signed.items()))
    signed["w_rid"] = _md5(query + mixin_key)
    return signed
```

#### 6.1.4 数据清洗

B站返回的字段有多种形态（如 `pic`/`cover`、`author`/`uname`、`play`/`video_review`/`like`/`likes`），需要统一：

```python
def parse_video_items(raw: Iterable[dict]) -> list[dict]:
    items = []
    for r in raw:
        bvid = r.get("bvid")
        title = _strip_html_tags(r.get("title") or "")
        mid = r.get("mid") or r.get("authorid")
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
    return items
```

### 6.2 视频选择与入库

#### 6.2.1 接口

`POST /api/v1/videos/search/fetch-subtitles`

请求体：

```json
{
  "items": [
    {"bvid": "BV1xx411c7mD", "title": "视频标题"}
  ]
}
```

响应：

```json
{
  "task_ids": ["task1"],
  "video_ids": ["vid1"],
  "results": [
    {"bvid": "BV1xx411c7mD", "video_id": "vid1", "task_id": "task1"}
  ]
}
```

#### 6.2.2 后端处理流程

对每个选中的视频：

1. 调用 B站 `x/web-interface/view` 接口获取视频详情（含 `cid`、`owner`、时长等）。
2. 若 UP主不存在，创建占位 `Uploader`。
3. 创建或更新 `Video` 记录。
4. 若该视频没有进行中的 `subtitle_fetch` 任务，则创建新任务。
5. 通知 `TaskRunner` 立即处理。

```python
# backend/app/api/videos.py
@router.post("/videos/search/fetch-subtitles", response_model=VideoSearchFetchOut)
async def fetch_subtitles_from_search(
    payload: VideoSearchFetchIn,
    request: Request,
    db: Session = Depends(get_db),
) -> VideoSearchFetchOut:
    task_ids = []
    video_ids = []
    results = []

    for item in payload.items:
        try:
            info = await bili_sub.get_video_info(item.bvid)
            owner = info.get("owner") or {}
            mid = owner.get("mid")
            up = _ensure_search_uploader(db, str(mid), owner.get("name"), owner.get("face"))
            v = _ensure_search_video(db, item.bvid, info, up.id)

            existing = _active_subtitle_task_exists(db, v.id)
            if existing is None:
                task = create_task(db, "subtitle_fetch", "video", v.id)
                db.commit()
                db.refresh(task)
            else:
                task = existing

            task_ids.append(task.task_id)
            video_ids.append(v.id)
            results.append(VideoSearchFetchResult(bvid=item.bvid, video_id=v.id, task_id=task.task_id))
        except BizError as e:
            results.append(VideoSearchFetchResult(bvid=item.bvid, error={"code": e.code, "message": e.message}))

    runner = getattr(request.app.state, "runner", None)
    if runner is not None:
        runner.notify()

    return VideoSearchFetchOut(task_ids=task_ids, video_ids=video_ids, results=results)
```

创建 UP主和视频的逻辑：

```python
def _ensure_search_uploader(db, mid: str, name: str | None, face: str | None) -> Uploader:
    up = db.execute(select(Uploader).where(Uploader.user_id == DEFAULT_USER_ID, Uploader.bilibili_uid == mid)).scalar_one_or_none()
    if up is None:
        up = Uploader(
            id=uuid.uuid4().hex[:12],
            bilibili_uid=mid,
            name=name or f"UP_{mid}",
            avatar_url=face,
            user_id=DEFAULT_USER_ID,
            created_at=datetime.now(timezone.utc),
        )
        db.add(up)
        db.commit()
        db.refresh(up)
    return up
```

### 6.3 字幕获取

#### 6.3.1 优先级

按以下顺序获取字幕：

1. **UP主上传字幕**：`ai_type == 0`
2. **B站 AI 字幕**：`ai_type == 1`
3. **本地 ASR 兜底**：Qwen3-ASR 转写

#### 6.3.2 B站字幕接口

```python
# backend/app/bilibili/subtitle.py
def pick_preferred_subtitle(tracks: list[dict]) -> Optional[dict]:
    usable = [t for t in tracks if _has_usable_url(t)]
    uploaded = [t for t in usable if int(t.get("ai_type", 0)) == 0]
    if uploaded:
        return uploaded[0]
    ai = [t for t in usable if int(t.get("ai_type", 0)) == 1]
    if ai:
        return ai[0]
    return usable[0] if usable else None
```

调用链：

1. `get_video_info(bvid)` → `x/web-interface/view` → 得到 `cid`。
2. `get_player_subtitles(bvid, cid)` → `x/player/wbi/v2` → 得到字幕轨道列表。
3. `pick_preferred_subtitle()` 选最优轨道。
4. `download_subtitle_json(subtitle_url)` → 下载 JSON 字幕。

#### 6.3.3 字幕任务处理器

```python
# backend/app/tasks/handlers.py
@task_handler("subtitle_fetch")
async def handle_subtitle_fetch(db, task: Task) -> None:
    if task.ref_type != "video" or not task.ref_id:
        raise BizError("TASK_INVALID_REF", "subtitle_fetch 必须绑定 video", http_status=500)
    v = db.get(Video, task.ref_id)
    if v is None or v.user_id != DEFAULT_USER_ID:
        raise BizError("VIDEO_NOT_FOUND", "视频不存在", http_status=404)

    try:
        sub = await collect_subtitle.fetch_video_subtitle(db, v)
        await _ingest_video_subtitle(v, sub.lines, db)
        return
    except BizError as e:
        if e.code not in ("SUBTITLE_UNAVAILABLE", "SUBTITLE_DURATION_MISMATCH"):
            raise
        await _run_whisper_fallback(db, v, task)
```

#### 6.3.4 时长校验

获取字幕后校验字幕总时长是否与视频时长匹配，防止 B站返回错误的字幕轨道：

```python
# backend/app/collect/fetch_subtitle.py
def _check_subtitle_duration(lines: list[dict], video_duration_sec: int) -> None:
    if not lines:
        return
    last_end = max(line.get("end_sec", 0) for line in lines)
    diff = abs(last_end - video_duration_sec)
    ratio = diff / max(video_duration_sec, 1)
    if ratio >= cfg.subtitle_duration_mismatch_ratio and diff >= cfg.subtitle_duration_mismatch_abs_sec:
        raise BizError("SUBTITLE_DURATION_MISMATCH", "字幕时长与视频严重不符")
```

默认阈值：`ratio >= 15%` 且 `diff >= 10秒`。

#### 6.3.5 ASR 兜底流程

当 B站无字幕或时长不匹配时，使用本地 Qwen3-ASR 转写：

```python
# backend/app/transcriber/pipeline.py
async def transcribe_video(bvid: str) -> list[dict]:
    # 1. 准备 cookie
    # 2. yt-dlp 下载最佳音频 → mp3
    # 3. ffprobe 测时长
    # 4. ffmpeg 转 16kHz 单声道 WAV
    # 5. 按 120s 分片
    # 6. Qwen3-ASR 模型推理
    # 7. 按句子+字符比例分配时间戳
    # 8. 清理临时目录
```

ASR 转写结果写入 `subtitles` 表，`source="whisper"`。

#### 6.3.6 本地 Markdown 归档

字幕获取成功后，归档到本地 Markdown 文件：

```python
# backend/app/collect/fetch_subtitle.py
def save_subtitle_to_file(video: Video, lines: list[dict]) -> Path:
    path = _subtitle_file_path(video)  # data/{up_name}/YYYYMMDD-{title}.md
    path.parent.mkdir(parents=True, exist_ok=True)
    content = _subtitle_to_markdown(lines)
    path.write_text(content, encoding="utf-8")
    return path

def _subtitle_to_markdown(lines: list[dict]) -> str:
    parts = []
    for line in lines:
        start = _format_time(line["start_sec"])
        end = _format_time(line["end_sec"])
        parts.append(f"[{start} -> {end}] {line['text']}")
    return "\n\n".join(parts)
```

归档失败不影响 DB 写入，仅记录 warning。

---

### 6.4 RAG 生成

#### 6.4.1 整体流程

```text
字幕来源
  ├── DB subtitle.lines ──► segments_from_subtitle_lines()
  └── 本地 .md 文件 ──────► parse_markdown_file()
              │
              ▼
      TextSegment（按停顿/时长切分）
              │
              ▼
      extract_chunks(segment, video_title, up_name)
              │
              ▼
      ArgumentChunk（LLM 结构化观点卡片）
              │
              ▼
      add_chunks() → _enrich_text() → encode() → Milvus insert
```

#### 6.4.2 切分策略

按相邻字幕行之间的停顿和最大段时长切分：

```python
# backend/app/rag/parser.py
def segment_by_pause(
    entries: list[SubtitleEntry],
    pause_threshold: float = 2.5,
    max_segment_duration_sec: float = 60.0,
) -> list[TextSegment]:
    segments = []
    current = []
    current_duration = 0.0

    for entry in entries:
        if current:
            gap = entry.start_seconds - current[-1].end_seconds
            would_exceed = current_duration + (entry.end_seconds - entry.start_seconds) > max_segment_duration_sec
            if gap > pause_threshold or would_exceed:
                segments.append(_build_segment(current))
                current = []
                current_duration = 0.0
        current.append(entry)
        current_duration += entry.end_seconds - entry.start_seconds

    if current:
        segments.append(_build_segment(current))
    return segments
```

默认参数：停顿阈值 `2.5秒`，最大段时长 `60秒`。

#### 6.4.3 观点卡片提取

使用 LLM 将每个话题段转换为结构化观点卡片：

```python
# backend/app/rag/extractor.py
class ArgumentChunk(BaseModel):
    content: str
    content_type: str
    argument_role: str
    core_topic: str
    sub_topics: list[str]
    stance_type: str
    confidence: str
    verifiability: str
    source_type: str
    original_arguments: list[str]
    time_position: str
    discard_reason: Optional[str] = None

class ExtractionResult(BaseModel):
    chunks: list[ArgumentChunk]
```

字段说明：

| 字段 | 说明 |
|------|------|
| `content` | 清洗后的观点陈述文本 |
| `content_type` | 观点/事实/预测/叙事/引用/假设/反驳/过渡/广告/口误/情感/方法论 |
| `argument_role` | 主论点/子论点/论据/结论/反驳/让步/类比/个人经验/方法论-教训/背景铺垫/无 |
| `core_topic` | 核心主题 |
| `sub_topics` | 子主题标签 |
| `stance_type` | 支持/反对/中立/预测/判断/建议/经验/无 |
| `confidence` | 强/中/弱/未论证 |
| `verifiability` | 可验证/待验证/不可验证/主观经验 |
| `source_type` | UP主本人/引用他人/未知来源 |
| `original_arguments` | 支撑观点的原始论据 |
| `time_position` | 时间段，如 `00:27 -> 00:55` |

Prompt 结构：

- System Prompt：定义角色、输出 JSON Schema、清洗规则、置信度判断标准。
- User Prompt：传入视频标题、UP主、时间段、字幕文本，要求输出 `{"chunks": [...]}`。

调用示例：

```python
parsed, _ = await chat(
    messages=[
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ],
    temperature=0.2,
)
result = ExtractionResult.model_validate(parsed)
```

若 LLM 失败，返回一个 `content_type="叙事"` 的兜底 chunk，避免整条视频丢失。

#### 6.4.4 写入 Milvus

```python
# backend/app/rag/service.py
def _build_chunks_from_segments(segments, uploader_id, video_id, video_title, up_name, date, published_at):
    chunks = []
    for seg_idx, seg in enumerate(segments):
        for c_idx, c in enumerate(seg.chunks):
            chunk_id = f"{file_slug}_{seg_idx:03d}_{c_idx:03d}_{uuid.uuid4().hex[:8]}"
            chunks.append({
                "chunk_id": chunk_id,
                "content": c.content,
                "metadata": {
                    "uploader_id": uploader_id,
                    "video_id": video_id,
                    "video_title": video_title,
                    "up_name": up_name,
                    "date": date,
                    "published_at": published_at,
                    "time_position": c.time_position,
                    "content_type": c.content_type,
                    "argument_role": c.argument_role,
                    "core_topic": c.core_topic,
                    "sub_topics": c.sub_topics,
                    "stance_type": c.stance_type,
                    "confidence": c.confidence,
                    "verifiability": c.verifiability,
                    "source_type": c.source_type,
                    "original_arguments": c.original_arguments,
                },
            })
    return chunks
```

写入前会对文本做增强，把元信息拼接到 content 以提升检索精度：

```python
# backend/app/rag/milvus_store.py
def _enrich_text(self, content: str, meta: dict) -> str:
    parts = [content]
    if meta.get("core_topic"):
        parts.append(f"主题: {meta['core_topic']}")
    if meta.get("stance_type") and meta["stance_type"] != "无":
        parts.append(f"立场: {meta['stance_type']}")
    if meta.get("argument_role") and meta["argument_role"] != "无":
        parts.append(f"角色: {meta['argument_role']}")
    if meta.get("content_type"):
        parts.append(f"类型: {meta['content_type']}")
    return " | ".join(parts)
```

#### 6.4.5 Milvus Collection Schema

```python
# backend/app/rag/milvus_store.py
schema.add_field(field_name="id", datatype=DataType.VARCHAR, max_length=64, is_primary=True)
schema.add_field(field_name="content", datatype=DataType.VARCHAR, max_length=8192)
schema.add_field(field_name="video_id", datatype=DataType.VARCHAR, max_length=32)
schema.add_field(field_name="uploader_id", datatype=DataType.VARCHAR, max_length=32)
schema.add_field(field_name="video_title", datatype=DataType.VARCHAR, max_length=512)
schema.add_field(field_name="up_name", datatype=DataType.VARCHAR, max_length=128)
schema.add_field(field_name="date", datatype=DataType.VARCHAR, max_length=16)
schema.add_field(field_name="published_at", datatype=DataType.VARCHAR, max_length=64)
schema.add_field(field_name="time_position", datatype=DataType.VARCHAR, max_length=64)
schema.add_field(field_name="content_type", datatype=DataType.VARCHAR, max_length=32)
schema.add_field(field_name="argument_role", datatype=DataType.VARCHAR, max_length=32)
schema.add_field(field_name="core_topic", datatype=DataType.VARCHAR, max_length=256)
schema.add_field(field_name="stance_type", datatype=DataType.VARCHAR, max_length=32)
schema.add_field(field_name="confidence", datatype=DataType.VARCHAR, max_length=16)
schema.add_field(field_name="verifiability", datatype=DataType.VARCHAR, max_length=32)
schema.add_field(field_name="source_type", datatype=DataType.VARCHAR, max_length=32)
schema.add_field(field_name="sub_topics", datatype=DataType.VARCHAR, max_length=1024)
schema.add_field(field_name="original_arguments", datatype=DataType.VARCHAR, max_length=4096)
schema.add_field(field_name="embedding", datatype=DataType.FLOAT_VECTOR, dim=1024)

index_params.add_index(
    field_name="embedding",
    metric_type="L2",
    index_type="IVF_FLAT",
    params={"nlist": 128},
)
```

使用共享 Collection，通过 `up_name` / `video_id` 等 metadata 过滤。

#### 6.4.6 RAG 搜索

支持三种检索模式：

| 模式 | 说明 |
|------|------|
| `vector` | 纯向量检索 |
| `keyword` | Milvus `like` 关键词过滤 |
| `hybrid` | 向量 + 关键词，RRF 融合，可选交叉编码器重排 |

```python
# backend/app/rag/service.py
async def search_reviews(
    query: str,
    up_name: str,
    n_results: int = 5,
    mode: Literal["vector", "keyword", "hybrid"] = "vector",
    video_ids: Optional[list[str]] = None,
) -> list[dict]:
    filter_expr = _milvus_filter_expr(up_name)
    if video_ids:
        filter_expr = _combine_filter_exprs([filter_expr, _video_ids_filter_expr(video_ids)])

    if mode == "vector":
        return await store.search(query, n_results=n_results, filter_expr=filter_expr)
    if mode == "keyword":
        return await store.keyword_search(query, n_results=n_results, filter_expr=filter_expr)
    return await store.hybrid_search(query, n_results=n_results, filter_expr=filter_expr)
```

关键词检索覆盖字段：`content`, `core_topic`, `sub_topics`, `original_arguments`。

RRF 融合公式：

```python
score = sum(1.0 / (k + rank) for each list)
```

#### 6.4.7 RAG 对话

流程：

1. 调用 `search_reviews()` / `search_global_reviews()` 召回 chunks。
2. 用 `_build_context()` 拼接为带来源标注的上下文。
3. 调用 LLM 生成回答。

System Prompt 核心规则：

- 每个观点必须标注来源：日期 + 视频标题 + 时间戳。
- 区分事实陈述与主观观点。
- 资料不足时明确说明。
- 用户追问证据时引用原始论据列表。

返回结构：

```json
{
  "answer": "回答文本",
  "chunks": [...],
  "token_usage": {...}
}
```

### 6.5 任务队列

#### 6.5.1 单 Worker Runner

```python
# backend/app/tasks/runner.py
class TaskRunner:
    def __init__(self, tick_interval_sec: float = 60.0, session_factory=None)
    async def start(self) -> None
    async def stop(self) -> None
    def notify(self) -> None
    def cancel_current_handler(self) -> bool
    async def tick(self) -> str | None
```

核心行为：

- 单 worker 顺序消费 `status='pending'` 任务。
- 排序规则：`priority DESC, created_at ASC`。
- 启动时把上次崩溃遗留的 `running` 任务重置为 `pending`。
- 每轮 `tick()` 处理一条任务，状态流转：`pending → running → success/failed`。
- 任务完成后推送 `task.updated` WebSocket 事件。

#### 6.5.2 任务注册

```python
# backend/app/tasks/registry.py
Handler = Callable[["Session", "Task"], Awaitable[None]]
_REGISTRY: dict[str, Handler] = {}

def task_handler(task_type: str):
    def decorator(fn: Handler) -> Handler:
        _REGISTRY[task_type] = fn
        return fn
    return decorator

def get_handler(task_type: str) -> Handler:
    handler = _REGISTRY.get(task_type)
    if handler is None:
        raise BizError("TASK_TYPE_UNSUPPORTED", f"未知任务类型: {task_type}", http_status=500)
    return handler
```

#### 6.5.3 创建任务

```python
# backend/app/tasks/service.py
def create_task(
    db: Session,
    task_type: str,
    ref_type: Optional[str] = None,
    ref_id: Optional[str] = None,
    meta: Optional[dict] = None,
    priority: int = 0,
) -> Task:
    task = Task(
        task_id=uuid.uuid4().hex[:12],
        type=task_type,
        status="pending",
        progress=0,
        ref_type=ref_type,
        ref_id=ref_id,
        meta=meta,
        priority=priority,
        created_at=datetime.now(timezone.utc),
    )
    db.add(task)
    return task
```

#### 6.5.4 任务调度器

`TaskScheduler` 是任务生产者，定期扫描数据库创建任务：

- `_subtitle_loop`：每 120 秒扫描 `has_subtitle=False` 的视频，创建 `subtitle_fetch` 任务。
- `_summary_loop`：当前已暂停（AI 总结功能暂停）。
- `_backfill_loop`：无字幕/总结任务时，回溯更早视频。

调度器通过 `runner.notify()` 唤醒 Runner 立即处理。

#### 6.5.5 取消任务

`POST /api/v1/tasks/cancel` 支持按一个或多个任务类型取消：

```python
class TaskCancelIn(_Base):
    task_type: str | list[str]

    @field_validator('task_type', mode='before')
    @classmethod
    def _ensure_list(cls, v):
        return [v] if isinstance(v, str) else v
```

行为：

- 删除所有 `pending` 的指定类型任务。
- 若当前运行任务类型在指定列表中，触发 `cancel_current_handler()`。
- 将无活跃 handler 的 `running` 任务标记为 `failed`，`error={"code":"CANCELLED"}`。

---

## 7. 前端实现详解

### 7.1 项目结构

```
frontend/app/
├── src/
│   ├── main.tsx              # React root + HashRouter + Toaster
│   ├── App.tsx               # 路由 + 全局布局
│   ├── lib/
│   │   ├── api.ts            # 后端 API 客户端与类型
│   │   ├── format.ts         # 格式化与映射
│   │   └── utils.ts          # cn() 工具
│   ├── sections/
│   │   ├── VideoSearchPage.tsx
│   │   ├── Jobs.tsx
│   │   ├── ReviewPage.tsx
│   │   └── ...
│   └── components/ui/        # shadcn/ui 组件
├── package.json
└── vite.config.ts
```

### 7.2 视频搜索页面

路由：`/video-search`

核心状态：

```ts
const [query, setQuery] = useState('')
const [order, setOrder] = useState<'default' | 'pubdate' | 'click'>('default')
const [items, setItems] = useState<BackendVideoSearchItem[]>([])
const [hasMore, setHasMore] = useState(false)
const [page, setPage] = useState(1)
const [selected, setSelected] = useState<Set<string>>(new Set())
```

搜索函数：

```ts
const doSearch = async (p = 1, currentOrder = order) => {
  const q = query.trim()
  if (!q) return
  setSearching(true)
  try {
    const apiOrder = currentOrder === 'default' ? '' : currentOrder
    const res = await videosApi.search(q, p, apiOrder)
    if (p === 1) setItems(res.items)
    else setItems((prev) => [...prev, ...res.items])
    setHasMore(res.has_more)
    setPage(res.page)
    setSelected(new Set())
  } catch (e: any) {
    toast.error(e?.error?.message || '搜索失败')
  } finally {
    setSearching(false)
  }
}
```

提交获取字幕：

```ts
const fetchSubtitles = async () => {
  if (selected.size === 0) return
  const selectedItems = items
    .filter((it) => selected.has(it.bvid))
    .map((it) => ({ bvid: it.bvid, title: it.title }))
  setFetching(true)
  try {
    const res = await videosApi.fetchSubtitles(selectedItems)
    const succeeded = res.results.filter((r) => !r.error)
    if (succeeded.length > 0) toast.success(`已为 ${succeeded.length} 个视频排队获取字幕`)
    navigate('/jobs')
  } catch (e: any) {
    toast.error(e?.error?.message || '提交失败')
  } finally {
    setFetching(false)
  }
}
```

### 7.3 任务页面

路由：`/jobs`

- 轮询 `GET /tasks?status=pending,running` 展示字幕任务队列。
- 单独轮询 `GET /tasks?status=pending,running&task_type=rag_ingest` 展示 RAG 任务队列。
- 支持"停止全部"按钮，调用 `POST /tasks/cancel`。

### 7.4 RAG 复盘页面

路由：`/review/:uploaderId`

- 显示 UP主信息和统计。
- 提供"重新导入"按钮，调用 `POST /rag/up/{uploader_id}/ingest`。
- 搜索框调用 `GET /rag/up/{uploader_id}/search`。
- 对话框调用 `POST /rag/up/{uploader_id}/chat`。

### 7.5 API 客户端

统一封装：

```ts
// frontend/app/src/lib/api.ts
const API_BASE = '/api/v1'

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const url = `${API_BASE}${path}`
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  })
  if (!res.ok) {
    let err: any = { status: res.status, message: res.statusText }
    try { err = await res.json() } catch {}
    throw err
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}
```

开发时代理：

```ts
// frontend/app/vite.config.ts
export default defineConfig({
  server: {
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/ws': { target: 'ws://127.0.0.1:8000', ws: true },
    },
  },
})
```

---

## 8. API 接口参考

### 8.1 视频搜索

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/videos/search` | B站关键词搜索 |
| POST | `/videos/search/fetch-subtitles` | 选中视频后创建字幕任务 |
| POST | `/videos/{id}/subtitle/fetch` | 单个视频获取字幕 |

### 8.2 RAG

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/rag/up/{uploader_id}/ingest` | 全量重建某 UP主的 RAG 索引 |
| GET | `/rag/up/{uploader_id}/search` | 按 UP主搜索 |
| POST | `/rag/up/{uploader_id}/chat` | 按 UP主对话 |
| GET | `/rag/up/{uploader_id}/stats` | 某 UP主已导入 chunk 数 |
| GET | `/rag/search` | 跨 UP主搜索 |
| GET | `/rag/videos/search` | 按话题搜索相关视频 |
| POST | `/rag/chat` | 跨 UP主/限定视频对话 |

### 8.3 任务

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/tasks` | 任务列表，支持 `status` 和 `task_type` 过滤 |
| GET | `/tasks/{task_id}` | 任务详情 |
| POST | `/tasks/{task_id}/retry` | 重试失败任务 |
| POST | `/tasks/cancel` | 按类型取消任务 |
| GET | `/tasks/stats` | 任务统计 |

### 8.4 统一错误格式

```json
{
  "error": {
    "code": "VIDEO_NOT_FOUND",
    "message": "视频不存在",
    "details": {}
  }
}
```

常见错误码：

| HTTP | 业务码 | 说明 |
|------|--------|------|
| 400 | INVALID_PARAM | 参数错误 |
| 404 | VIDEO_NOT_FOUND / UPLOADER_NOT_FOUND / TASK_NOT_FOUND | 资源不存在 |
| 409 | TASK_CONFLICT | 同类任务已在进行中 |
| 422 | SUBTITLE_UNAVAILABLE | 无可用字幕 |
| 429 | BILIBILI_RATE_LIMITED | B站风控限流 |
| 502 | LLM_ERROR / BILIBILI_API_ERROR | 外部服务错误 |

---

## 9. 部署与运行

### 9.1 开发模式

后端：

```bash
cd backend
.venv\Scripts\activate  # 或 source .venv/bin/activate
uvicorn app.main:app --reload
```

前端：

```bash
cd frontend/app
npm run dev
```

访问：`http://localhost:3000/#/video-search`

### 9.2 生产构建

前端：

```bash
cd frontend/app
npm run build
```

产物在 `frontend/app/dist/`，可用 Nginx 或 Vite preview 托管。

后端：

```bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 9.3 数据目录

```
backend/data/
├── upwatch.db              # SQLite 数据库
├── milvus/
│   └── upwatch.db          # Milvus Lite 向量库
└── {up主名称}/
    └── YYYYMMDD-{标题}.md  # 字幕 Markdown 归档
```

### 9.4 运行测试

后端：

```bash
cd backend
pytest tests -q
```

前端类型检查与构建：

```bash
cd frontend/app
npm run build
```

---

## 10. 常见问题与扩展

### 10.1 如何避免 B站风控？

- 配置 `BILIBILI_SESSDATA`（登录 Cookie）。
- 单 worker 顺序执行，避免并发请求。
- 点赞回填等批量操作加入 0.6 秒睡眠。
- 搜索/字幕接口返回 `-352`/`-412`/`-509`/`-799`/`-1200` 时自动转换为 429，前端提示稍后重试。

### 10.2 ASR 兜底不工作？

- 确认已安装 ASR 依赖：`pip install -e ".[asr]"`。
- 确认 `QWEN_ASR_MODEL_PATH` 指向有效模型目录。
- 确认 ffmpeg/ffprobe 在 PATH 中。
- 确认磁盘有足够空间存放临时音频文件。

### 10.3 RAG 检索效果不佳？

- 尝试更换 Embedding 模型（如 `BAAI/bge-large-zh-v1.5` → `Ollama qwen3-embedding`）。
- 开启重排序：`RERANK_ENABLED=true`。
- 使用 hybrid 模式替代纯 vector。
- 检查字幕切分参数 `pause_threshold` 和 `max_segment_duration_sec`。

### 10.4 多用户扩展

- 所有业务表已预留 `user_id`。
- 增加认证中间件，从 JWT/Session 获取当前用户 ID。
- 在查询时追加 `user_id == current_user_id` 过滤。
- 接口路径和响应结构保持不变。

### 10.5 可扩展方向

- **AI 总结**：当前已暂停，可恢复 `ai_summary` 任务处理器。
- **批量导入**：支持上传本地 Markdown 目录直接导入 RAG。
- **定时采集**：通过 `feed_refresh` 任务自动跟踪 UP主更新。
- **WebSocket 实时通知**：任务状态更新已推送，可扩展更多事件类型。

---

## 附录：核心文件索引

| 用途 | 路径 |
|------|------|
| 前端搜索页 | `frontend/app/src/sections/VideoSearchPage.tsx` |
| 前端任务页 | `frontend/app/src/sections/Jobs.tsx` |
| 前端 API 客户端 | `frontend/app/src/lib/api.ts` |
| 后端视频 API | `backend/app/api/videos.py` |
| 后端 RAG API | `backend/app/api/rag.py` |
| 后端任务 API | `backend/app/api/tasks.py` |
| B站搜索 | `backend/app/bilibili/search.py` |
| B站 WBI 签名 | `backend/app/bilibili/wbi.py` |
| B站 HTTP 客户端 | `backend/app/bilibili/client.py` |
| 字幕获取 | `backend/app/collect/fetch_subtitle.py` |
| ASR 转写 | `backend/app/transcriber/pipeline.py` |
| RAG 服务编排 | `backend/app/rag/service.py` |
| RAG 解析 | `backend/app/rag/parser.py` |
| RAG 提取 | `backend/app/rag/extractor.py` |
| RAG 向量存储 | `backend/app/rag/milvus_store.py` |
| 任务 Runner | `backend/app/tasks/runner.py` |
| 任务处理器 | `backend/app/tasks/handlers.py` |
| 任务注册 | `backend/app/tasks/registry.py` |
| 数据模型 | `backend/app/models.py` |
| 数据库初始化 | `backend/app/db.py` |
| 应用入口 | `backend/app/main.py` |
| 配置 | `backend/app/config.py` |

---

> 本文档完。开发者可依据以上架构、接口与代码实现，重新构建一个具备"B站视频搜索 → 字幕获取 → RAG 复盘"能力的完整项目。
