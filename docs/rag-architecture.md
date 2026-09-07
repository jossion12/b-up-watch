# RAG 架构说明

> 本文档描述 UP 雷达后端 RAG（Retrieval-Augmented Generation）模块的数据流、模块职责、配置与 API。
> 相关代码位于 `backend/app/rag/`。

## 1. 数据流

```text
B站官方字幕 / B站 AI 字幕 / Whisper 转写
              │
              ▼
    backend/app/collect/fetch_subtitle.py
              │ 写入 subtitles 表 + save_subtitle_to_file()
              │
              ▼
    backend/app/collect/corpus.py  生成 RAGFlow 语料（无 LLM）
              │
              ▼
    data/corpus/{up_name}/...md    ← 当前默认：RAGFlow 摄取源
              │
              ▼
    RAGFlow（外部）                chunking / 检索 / 对话

（原 Milvus 路径已暂停）
    SQLite: subtitles.lines
              │
              ▼
    backend/app/rag/parser.py      解析字幕行 / Markdown + 停顿切分
              │
              ▼
    backend/app/rag/extractor.py   LLM 提取结构化观点卡片
              │
              ▼
    backend/app/rag/milvus_store.py  Embedding + Milvus 存储
              │
              ▼
    Milvus Collection: upwatch_review_chunks
```

说明：
- 字幕获取主流程会把字幕写入 `subtitles` 表，同时归档成本地 Markdown 文件（`data/{up_name}/...`）。
- **当前默认方案**：字幕获取成功后生成 **RAGFlow 语料文件**（`data/corpus/{up_name}/YYYYMMDD-{title}.md`），无 LLM 提取、无 Milvus 写入，后续 chunking/检索/对话由 RAGFlow 负责。
- 原 Milvus + LLM 观点卡片提取路径已暂停（`rag_auto_ingest_enabled=false`，`ingest_video` / `ingest_uploader` 调用已注释）。
- 全量重建入口 `/up/{uploader_id}/ingest` 现在会批量重新生成该 UP 主下所有有字幕视频的 RAGFlow 语料文件。
- 向量库使用**共享 Collection**，通过 `video_id` / `uploader_id` 等 metadata 做过滤，既支持按 UP 主查，也支持跨 UP 主全局查。

## 2. 模块职责

| 文件 | 职责 |
|---|---|
| `backend/app/rag/parser.py` | 解析 Markdown 复盘文件；从文件名提取 `date` 与 `title`；也支持从 `subtitles.lines` 直接切分话题段。 |
| `backend/app/rag/extractor.py` | 对每个话题段调用 LLM，输出结构化的 `ArgumentChunk`（观点、事实、预测等）。 |
| `backend/app/rag/milvus_store.py` | 封装 Milvus Lite / 服务器；负责 embedding 生成、collection 管理、写入、检索、清空、统计；新增关键词检索、RRF 混合检索与可选的交叉编码器重排序。 |
| `backend/app/rag/service.py` | 业务编排：`ingest_video`（按视频增量）、`ingest_uploader`（按 UP 主全量重建）、`search_reviews`（按 UP 主）、`search_global_reviews`（全局）、`search_videos`（视频聚合）、`chat_reviews`（按 UP 主）、`chat_global_reviews`（全局/限定视频）。 |
| `backend/app/api/rag.py` | 暴露 REST 端点：`/up/{id}/ingest`、`/up/{id}/search`、`/up/{id}/chat`、`/up/{id}/stats`、`/search`、`/videos/search`、`/chat`。 |

## 3. 观点卡片 Schema

一个 `ArgumentChunk` 包含以下字段，最终作为 metadata 存入 Milvus：

| 字段 | 说明 |
|---|---|
| `content` | 清洗后的观点陈述文本 |
| `content_type` | 观点 / 事实 / 预测 / 叙事 / 引用 / 假设 / 反驳 / 过渡 / 广告 / 口误 / 情感 / 方法论 |
| `argument_role` | 主论点 / 子论点 / 论据 / 结论 / 反驳 / 让步 / 类比 / 个人经验 / 方法论-教训 / 背景铺垫 / 无 |
| `core_topic` | 核心主题，如 "股票异动偏离值计算" |
| `sub_topics` | 子主题标签列表 |
| `stance_type` | 支持 / 反对 / 中立 / 预测 / 判断 / 建议 / 经验 / 无 |
| `confidence` | 强 / 中 / 弱 / 未论证 |
| `verifiability` | 可验证 / 待验证 / 不可验证 / 主观经验 |
| `source_type` | UP主本人 / 引用他人 / 未知来源 |
| `original_arguments` | 支撑该观点的原始论据列表 |
| `video_id` | 视频数据库 ID，用于精确过滤/链接 |
| `uploader_id` | UP 主数据库 ID |
| `published_at` | 视频发布时间（ISO 8601），用于时间排序 |
| `time_position` | 时间位置，如 `00:27-00:55` |

## 4. 配置

在 `backend/.env` 中配置：

```env
# Markdown 归档根目录
REVIEW_BASE_DIR=./data

# Embedding 后端：sentence_transformers 或 ollama
EMBEDDING_PROVIDER=sentence_transformers
EMBEDDING_MODEL=BAAI/bge-large-zh-v1.5
EMBEDDING_DIM=1024
OLLAMA_BASE_URL=http://localhost:11434

# 重排序（交叉编码器），默认关闭
RERANK_ENABLED=false
# RERANK_MODEL 支持 HuggingFace 模型名或本地路径；RERANK_MODEL_PATH 优先
RERANK_MODEL=BAAI/bge-reranker-base
RERANK_MODEL_PATH=
RERANK_TOP_K=20

# Milvus 向量库
# 以 .db 结尾为 Milvus Lite 本地模式；否则按 host:port 连接服务器
MILVUS_URI=./data/milvus/upwatch.db
MILVUS_HOST=localhost
MILVUS_PORT=19530
MILVUS_COLLECTION=upwatch_review_chunks
```

## 5. API 清单

Base path: `/api/v1/rag`

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/up/{uploader_id}/ingest` | 重建该 UP 主下所有有字幕视频的 RAG 索引 |
| GET | `/up/{uploader_id}/search?q={query}&n={n}&mode={vector\|keyword\|hybrid}` | 检索该 UP 主的观点卡片 |
| POST | `/up/{uploader_id}/chat` | 与该 UP 主检索结果做 RAG 对话 |
| GET | `/up/{uploader_id}/stats` | 该 UP 主已导入的卡片数量 |
| GET | `/search?q={query}&n={n}&mode={vector\|keyword\|hybrid}` | 跨所有 UP 主检索观点卡片 |
| GET | `/videos/search?q={query}&n={n}&mode={vector\|keyword\|hybrid}` | 按话题检索相关视频（返回视频级聚合） |
| POST | `/chat` | 跨 UP 主/限定视频的 RAG 对话，请求体可传 `video_ids` |

## 6. 已知限制与后续方向

1. **已自动联动字幕任务**：`subtitle_fetch` 成功后自动调用 `ingest_video()` 增量入库；失败不影响字幕任务。
2. **向量库 Schema 自动重建**：启动或首次请求时，`MilvusReviewStore` 会检查 collection 字段；若缺失 `video_id` / `uploader_id` / `published_at` 等新字段，会自动删除并重建 collection，随后需要重新触发 `/up/{id}/ingest` 恢复数据。
3. **关键词检索精度**：当前基于 Milvus `like` 表达式做子串匹配，对长句查询不够精细；未来可接入全文索引（BM25）或分词器。
4. **跨 UP 主隔离**：小范围阶段使用共享 collection + metadata 过滤；UP 主数量显著增加后可按 `uploader_id` 做 Milvus partition，接口层保持不变。
