# RAG 架构说明

> 本文档描述 UP 雷达后端 RAG（Retrieval-Augmented Generation）模块的数据流、模块职责、配置与 API。
> 相关代码位于 `backend/app/rag/`。

## 1. 数据流

```text
B站官方字幕 / B站 AI 字幕 / Whisper 转写
              │
              ▼
    backend/app/collect/fetch_subtitle.py
              │ save_subtitle_to_file()
              ▼
    data/{up_name}/YYYYMMDD-{video_title}.md   (Markdown 复盘文件)
              │
              ▼
    backend/app/rag/parser.py      解析 Markdown + 停顿切分
              │
              ▼
    backend/app/rag/extractor.py   LLM 提取结构化观点卡片
              │
              ▼
    backend/app/rag/milvus_store.py  Embedding + Milvus 存储
              │
              ▼
    Milvus Collection: taoge_review_chunks
              │
              ▼
    backend/app/rag/service.py     search / chat
              │
              ▼
    backend/app/api/rag.py         REST API
```

说明：
- 字幕获取主流程会把字幕归档成本地 Markdown 文件（`data/{up_name}/...`）。
- RAG 的 `ingest` 默认读取该目录下的 `*.md` 文件，先清空该 UP 主已有向量，再重新写入。
- 当前版本字幕归档后**不会自动触发 ingest**，需要手动调用 `POST /api/v1/rag/up/{uploader_id}/ingest`，或在任务链中主动触发。

## 2. 模块职责

| 文件 | 职责 |
|---|---|
| `backend/app/rag/parser.py` | 解析 Markdown 复盘文件；从文件名提取 `date` 与 `title`；按停顿阈值（默认 2.5s）切分话题段。 |
| `backend/app/rag/extractor.py` | 对每个话题段调用 LLM，输出结构化的 `ArgumentChunk`（观点、事实、预测等）。 |
| `backend/app/rag/milvus_store.py` | 封装 Milvus Lite / 服务器；负责 embedding 生成、collection 管理、写入、检索、清空、统计。 |
| `backend/app/rag/service.py` | 业务编排：`ingest_directory`、`search_reviews`、`chat_reviews`、`get_stats`。 |
| `backend/app/api/rag.py` | 暴露 REST 端点：`ingest`、`search`、`chat`、`stats`。 |

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

# Milvus 向量库
# 以 .db 结尾为 Milvus Lite 本地模式；否则按 host:port 连接服务器
MILVUS_URI=./data/milvus/taoge.db
MILVUS_HOST=localhost
MILVUS_PORT=19530
MILVUS_COLLECTION=taoge_review_chunks
```

## 5. API 清单

Base path: `/api/v1/rag`

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/up/{uploader_id}/ingest` | 扫描该 UP 主的复盘目录，全量导入 Milvus |
| GET | `/up/{uploader_id}/search?q={query}&n={n}` | 语义检索观点卡片 |
| POST | `/up/{uploader_id}/chat` | 基于检索结果的 RAG 对话 |
| GET | `/up/{uploader_id}/stats` | 该 UP 主已导入的卡片数量 |

## 6. 已知限制与后续方向

1. **未与字幕任务自动联动**：新视频字幕后，需要手动触发 ingest。建议后续在 `subtitle_fetch` 任务成功后级联调用 `ingest_directory`。
2. **独立脚本重复**：`docs/subtitle_to_rag.py` 与 `docs/vector_store.py` 是早期原型，逻辑已合并进 `backend/app/rag/`，建议弃用或迁移为调用后端模块的薄脚本。
3. **客户端未复用**：每次 API 调用都会新建 `MilvusReviewStore` 与 `MilvusClient`，可优化为单例。
4. **缺少 RAG 专项测试**：当前测试仅覆盖日志过滤器。
5. **检索方式单一**：目前仅向量相似度检索，未来可补充关键词/混合检索、重排序。
