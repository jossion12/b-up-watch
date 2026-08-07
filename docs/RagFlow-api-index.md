# RagFlow API 目录索引

> 基于 [`RagFlow-api.md`](./RagFlow-api.md) 整理的 API 索引,按业务域分组,列出每个端点的路径、HTTP 方法与用途摘要。
>
> - **基地址**:`http://{address}`(后端服务地址)
> - **认证**:除系统健康检查外,所有接口需 `Authorization: Bearer <YOUR_API_KEY>`,TTS/ASR/MindMap/相关问题等部分端点使用登录态 `Bearer <YOUR_LOGIN_TOKEN>`(24h 过期)
> - **响应约定**:`{"code": 0, "data": ..., "message": "..."}`,`code != 0` 表示失败
> - **路径段说明**:`{dataset_id}` / `{document_id}` / `{chat_id}` / `{session_id}` / `{agent_id}` / `{memory_id}` / `{message_id}` / `{file_id}` / `{folder_id}` / `{commit_id}` / `{attachment_id}` / `{search_id}` 均为资源 ID 占位

---

## 目录

1. [DATASET MANAGEMENT — 数据集管理](#1-dataset-management--数据集管理)
2. [FILE MANAGEMENT WITHIN DATASET — 数据集内文件管理](#2-file-management-within-dataset--数据集内文件管理)
3. [CHUNK MANAGEMENT WITHIN DATASET — 数据集内 Chunk 管理](#3-chunk-management-within-dataset--数据集内-chunk-管理)
4. [CHAT ASSISTANT MANAGEMENT — 聊天助手管理](#4-chat-assistant-management--聊天助手管理)
5. [SESSION MANAGEMENT — 会话管理](#5-session-management--会话管理)
6. [AGENT MANAGEMENT — Agent 管理](#6-agent-management--agent-管理)
7. [MEMORY MANAGEMENT — 记忆管理](#7-memory-management--记忆管理)
8. [System — 系统](#8-system--系统)
9. [FILE MANAGEMENT — 文件管理](#9-file-management--文件管理)
10. [SEARCH APP MANAGEMENT — 搜索应用管理](#10-search-app-management--搜索应用管理)

---

## 1. DATASET MANAGEMENT — 数据集管理

知识库(也叫 dataset / KB)生命周期管理,以及 GraphRAG / RAPTOR 索引构建。

| # | Method | Endpoint | 用途 |
|---|--------|----------|------|
| 1.1 | `POST`   | `/api/v1/datasets` | **创建数据集**。指定 `name`、嵌入模型、分块方法(`chunk_method`)或 ingestion pipeline(`parse_type` + `pipeline_id`,二选一) |
| 1.2 | `DELETE` | `/api/v1/datasets` | **批量删除数据集**。通过 `ids` 指定,或 `delete_all: true` 删除当前用户全部 |
| 1.3 | `PUT`    | `/api/v1/datasets/{dataset_id}` | **覆盖式更新数据集**配置(名称、嵌入模型、分块方式、权限、pagerank 等) |
| 1.4 | `GET`    | `/api/v1/datasets` | **列出数据集**,支持分页/排序/名称/ID 过滤,`include_parsing_status=true` 时附带解析进度统计 |
| 1.5 | `GET`    | `/api/v1/datasets/{dataset_id}/knowledge_graph` | **获取知识图谱**的节点、边、mind_map |
| 1.6 | `DELETE` | `/api/v1/datasets/{dataset_id}/knowledge_graph` | **删除知识图谱** |
| 1.7 | `POST`   | `/api/v1/datasets/{dataset_id}/run_graphrag` | **构建知识图谱**(GraphRAG),返回 `graphrag_task_id` |
| 1.8 | `GET`    | `/api/v1/datasets/{dataset_id}/trace_graphrag` | **查询 GraphRAG 构建状态**与进度 |
| 1.9 | `POST`   | `/api/v1/datasets/{dataset_id}/run_raptor` | **构建 RAPTOR 树形摘要**,返回 `raptor_task_id` |
| 1.10 | `GET`   | `/api/v1/datasets/{dataset_id}/trace_raptor` | **查询 RAPTOR 构建状态**与进度 |

---

## 2. FILE MANAGEMENT WITHIN DATASET — 数据集内文件管理

数据集内文档的上传、配置、下载、列出、删除与解析控制。

| # | Method | Endpoint | 用途 |
|---|--------|----------|------|
| 2.1 | `POST`   | `/api/v1/datasets/{dataset_id}/documents` | **上传文档**。`type=local` 多文件上传、`type=web` 抓取网页、`type=empty` 创建空白虚拟文档 |
| 2.2 | `PUT`    | `/api/v1/datasets/{dataset_id}/documents/{document_id}` | **更新文档**的名称、解析方法、`parser_config`、`meta_fields`、启用状态 |
| 2.3 | `GET`    | `/api/v1/datasets/{dataset_id}/documents/{document_id}` | **下载文档**原始文件 |
| 2.4 | `GET`    | `/api/v1/datasets/{dataset_id}/documents` | **列出数据集内文档**。支持分页、按名称/后缀/状态/创建时间/`metadata_condition` 过滤 |
| 2.5 | `DELETE` | `/api/v1/datasets/{dataset_id}/documents` | **批量删除文档**。按 `ids` 或 `delete_all` |
| 2.6 | `POST`   | `/api/v1/datasets/{dataset_id}/chunks` | **解析文档**(启动内置 chunk 流水线,用于 built-in chunking pipeline 的数据集) |
| 2.7 | `POST`   | `/api/v1/documents/ingest` | **摄取文档**(用于 ingestion pipeline 的数据集)。`run: "1"` 启动 / `"2"` 取消,`delete: true` 先清空旧任务与 chunk |
| 2.8 | `DELETE` | `/api/v1/datasets/{dataset_id}/chunks` | **停止文档解析**(按 `document_ids` 取消) |

---

## 3. CHUNK MANAGEMENT WITHIN DATASET — 数据集内 Chunk 管理

对分块结果进行增删改查,以及元数据管理、跨数据集检索。

| # | Method | Endpoint | 用途 |
|---|--------|----------|------|
| 3.1 | `POST`   | `/api/v1/datasets/{dataset_id}/documents/{document_id}/chunks` | **新增 chunk**。指定 `content`、关键词、问题、关联图片(`image_base64`) |
| 3.2 | `GET`    | `/api/v1/datasets/{dataset_id}/documents/{document_id}/chunks` | **列出文档内 chunk**,按关键词/分页/`id` 过滤 |
| 3.3 | `GET`    | `/api/v1/datasets/{dataset_id}/documents/{document_id}/chunks/{chunk_id}` | **获取单个 chunk**详情(不返回向量/运行时字段) |
| 3.4 | `DELETE` | `/api/v1/datasets/{dataset_id}/documents/{document_id}/chunks` | **批量删除 chunk**。按 `chunk_ids` 或 `delete_all` |
| 3.5 | `PATCH`  | `/api/v1/datasets/{dataset_id}/documents/{document_id}/chunks/{chunk_id}` | **更新 chunk**的内容、关键词、问题、可用性、图片(替代已废弃的 `PUT` 同路径) |
| 3.6 | `PATCH`  | `/api/v1/datasets/{dataset_id}/documents/{document_id}/chunks` | **批量更新 chunk 可用性**(`available_int` / `available`),控制是否参与检索 |
| 3.7 | `GET`    | `/api/v1/datasets/{dataset_id}/metadata/summary` | **聚合数据集内所有文档的元数据**值与出现次数 |
| 3.8 | `POST`   | `/api/v1/datasets/{dataset_id}/metadata/update` | **批量更新/删除文档级元数据**。通过 `selector`(`document_ids` / `metadata_condition`)选定目标,`updates` / `deletes` 修改 |
| 3.9 | `POST`   | `/api/v1/retrieval` | **跨数据集检索 chunk**。支持向量 + 关键词混合、`metadata_condition`、知识图谱(`use_kg`)、TOC 增强(`toc_enhance`)、重排序(`rerank_id`)、跨语言 |

---

## 4. CHAT ASSISTANT MANAGEMENT — 聊天助手管理

基于数据集的 RAG 聊天助手(也叫 chat)配置管理。

| # | Method | Endpoint | 用途 |
|---|--------|----------|------|
| 4.1 | `POST`   | `/api/v1/chats` | **创建聊天助手**。`name` 必填,可绑定数据集、LLM、`llm_setting`、`prompt_config` |
| 4.2 | `PUT`    | `/api/v1/chats/{chat_id}` | **覆盖式更新聊天助手**。未提供的字段会重置为默认值,需传完整配置 |
| 4.3 | `GET`    | `/api/v1/chats/{chat_id}` | **获取聊天助手**详情 |
| 4.4 | `PATCH`  | `/api/v1/chats/{chat_id}` | **局部更新聊天助手**。未指定字段保持不变,嵌套对象深度合并(推荐用于改名) |
| 4.5 | `DELETE` | `/api/v1/chats/{chat_id}` | **删除单个聊天助手** |
| 4.6 | `DELETE` | `/api/v1/chats` | **批量删除聊天助手**。按 `ids` 或 `delete_all`(原 `chat_id` 入参已废弃) |
| 4.7 | `GET`    | `/api/v1/chats` | **列出聊天助手**,支持分页/排序/owner/名称/ID 过滤 |

---

## 5. SESSION MANAGEMENT — 会话管理

聊天助手与 Agent 的会话生命周期、消息管理、对话发起及多模态辅助。

| # | Method | Endpoint | 用途 |
|---|--------|----------|------|
| 5.1  | `POST`   | `/api/v1/chats/{chat_id}/sessions` | **创建聊天助手会话**。可附带 `user_id` |
| 5.2  | `PATCH`  | `/api/v1/chats/{chat_id}/sessions/{session_id}` | **重命名会话**(替代已废弃的 `PUT` 同路径) |
| 5.3  | `GET`    | `/api/v1/chats/{chat_id}/sessions` | **列出会话**,支持分页/排序/`user_id` |
| 5.4  | `GET`    | `/api/v1/chats/{chat_id}/sessions/{session_id}` | **获取单个会话**(含消息、引用、头像) |
| 5.5  | `DELETE` | `/api/v1/chats/{chat_id}/sessions/{session_id}/messages/{msg_id}` | **删除会话中的一条消息**(user + assistant 配对) |
| 5.6  | `PUT`    | `/api/v1/chats/{chat_id}/sessions/{session_id}/messages/{msg_id}/feedback` | **更新消息反馈**(`thumbup` / `feedback` 文本) |
| 5.7  | `DELETE` | `/api/v1/chats/{chat_id}/sessions` | **批量删除会话**。按 `ids` 或 `delete_all` |
| 5.8  | `POST`   | `/api/v1/chat/completions` | **与聊天助手对话**(统一入口,替代 `POST /chats/{chat_id}/completions`)。支持三种模式:无 `chat_id` 直接走默认模型、给 `chat_id` 但无 `session_id` 自动开新会话、`chat_id` + `session_id` 续接。SSE 流式或非流式 |
| 5.9  | `POST`   | `/api/v1/agents/{agent_id}/sessions` | **创建 Agent 会话**(已废弃,建议直接用 5.10,会自动生成 session) |
| 5.10 | `POST`   | `/api/v1/agents/chat/completions` | **与 Agent 对话**(统一入口,替代 `POST /agents/{agent_id}/completions`)。支持标准模式 + OpenAI 兼容模式,流式事件包括 `message` / `message_end` / `node_finished` |
| 5.11 | `GET`    | `/api/v1/agents/{agent_id}/sessions` | **列出 Agent 会话**。`dsl=true` 包含 DSL 定义 |
| 5.12 | `DELETE` | `/api/v1/agents/{agent_id}/sessions` | **批量删除 Agent 会话**。按 `ids` 或 `delete_all` |
| 5.13 | `POST`   | `/api/v1/chat/audio/speech` | **文字转语音**(TTS),使用租户默认 TTS 模型,SSE 流式音频 |
| 5.14 | `POST`   | `/api/v1/chat/audio/transcription` | **语音转文字**(ASR),使用租户默认 ASR 模型,支持 SSE 流式分片 |
| 5.15 | `POST`   | `/api/v1/chat/mindmap` | **生成思维导图**。给定中心问题 + 知识库 ID,返回树形结构 |
| 5.16 | `POST`   | `/api/v1/chat/recommandation` | **生成相关问题**(5-10 个改写,提升检索召回;已废弃,推荐 `/api/v1/sessions/related_questions`) |

---

## 6. AGENT MANAGEMENT — Agent 管理

RAGFlow Canvas 上的 Agent(工作流)配置管理。

| # | Method | Endpoint | 用途 |
|---|--------|----------|------|
| 6.1 | `GET`    | `/api/v1/agents` | **列出 Agent**,支持分页/排序/标题/ID 过滤 |
| 6.2 | `POST`   | `/api/v1/agents` | **创建 Agent**。`title` + Canvas DSL(`dsl`) 必填 |
| 6.3 | `PUT`    | `/api/v1/agents/{agent_id}` | **更新 Agent**。只传需要修改的字段 |
| 6.4 | `DELETE` | `/api/v1/agents/{agent_id}` | **删除 Agent** |

---

## 7. MEMORY MANAGEMENT — 记忆管理

长期记忆(Memory)及其消息(Message)的管理与检索。

| # | Method | Endpoint | 用途 |
|---|--------|----------|------|
| 7.1  | `POST`   | `/api/v1/memories` | **创建 Memory**。`name` / `memory_type`(raw/semantic/episodic/procedural)/ 嵌入模型 / LLM 必填 |
| 7.2  | `PUT`    | `/api/v1/memories/{memory_id}` | **更新 Memory** 配置(名称、权限、LLM、容量上限、遗忘策略、温度、prompt 等) |
| 7.3  | `GET`    | `/api/v1/memories` | **列出 Memory**,按 `tenant_id` / `memory_type` / 存储类型 / 关键词过滤 |
| 7.4  | `GET`    | `/api/v1/memories/{memory_id}/config` | **获取 Memory 完整配置** |
| 7.5  | `DELETE` | `/api/v1/memories/{memory_id}` | **删除 Memory** |
| 7.6  | `GET`    | `/api/v1/memories/{memory_id}` | **列出 Memory 内消息**,按 `agent_id` / `session_id` 过滤 |
| 7.7  | `POST`   | `/api/v1/messages` | **添加消息到指定 Memory**(多对多),返回异步任务状态 |
| 7.8  | `DELETE` | `/api/v1/messages/{memory_id}:{message_id}` | **软删除(忘记)消息**。被忘消息不再被检索,并按遗忘策略优先清理 |
| 7.9  | `PUT`    | `/api/v1/messages/{memory_id}:{message_id}` | **启用/禁用消息**。`status: true/false`,禁用后不参与检索 |
| 7.10 | `GET`    | `/api/v1/messages/search` | **检索 Memory 消息**。支持 `query` 关键词、多 `memory_id`、`similarity_threshold`、语义权重 `keywords_similarity_weight`、`top_n` |
| 7.11 | `GET`    | `/api/v1/messages` | **获取最近 N 条消息**(`limit` 控制) |
| 7.12 | `GET`    | `/api/v1/messages/{memory_id}:{message_id}/content` | **获取单条消息的完整内容**与嵌入向量 |

> 路径段 `{memory_id}:{message_id}` 是冒号拼接的复合 ID。

---

## 8. System — 系统

| # | Method | Endpoint | 用途 |
|---|--------|----------|------|
| 8.1 | `GET` | `/api/v1/system/healthz` | **系统健康检查**。报告 DB、Redis、文档引擎、对象存储状态,任一不健康返回 500(替代已废弃的 `/v1/system/healthz`) |

---

## 9. FILE MANAGEMENT — 文件管理

工作区文件系统(文件夹/文件/附件)的 CRUD、版本控制与提交记录。

### 9.1 文件与文件夹

| # | Method | Endpoint | 用途 |
|---|--------|----------|------|
| 9.1.1 | `POST`   | `/api/v1/files` | **上传文件**到指定 `parent_id` 文件夹(替代已废弃的 `/api/v1/file/upload`) |
| 9.1.2 | `POST`   | `/api/v1/documents/upload` | **上传文件并创建为 document 附件**。支持 multipart 文件或 `?url=...` 抓取(替代已废弃的 `/v1/document/upload_info` 等) |
| 9.1.3 | `GET`    | `/api/v1/agents/attachments/{attachment_id}/download` | **下载 Agent 运行时附件**。支持 markdown/html/pdf/docx/xlsx/csv 等格式 |
| 9.1.4 | `POST`   | `/api/v1/files` | **创建文件或文件夹**。`type: "folder"` 或 `"virtual"`(替代已废弃的 `/api/v1/file/create`) |
| 9.1.5 | `GET`    | `/api/v1/files` | **列出文件夹下的文件/子文件夹**。支持分页、关键词、排序(替代已废弃的 `/api/v1/file/list`) |
| 9.1.6 | `GET`    | `/api/v1/files/{file_id}/parent` | **获取文件的直接父目录** |
| 9.1.7 | `GET`    | `/api/v1/files/{file_id}/ancestors` | **获取文件的所有祖先目录** |
| 9.1.8 | `DELETE` | `/api/v1/files` | **批量删除文件/文件夹**。按 `ids` |
| 9.1.9 | `GET`    | `/api/v1/files/{file_id}` | **下载文件**原始内容 |
| 9.1.10| `POST`   | `/api/v1/files/move` | **移动/重命名文件或文件夹**(Linux `mv` 语义,至少给一个 `dest_file_id` 或 `new_name`)。`src_file_ids` 必填;改后缀不支持(替代已废弃的 `/file/mv` 与 `/file/rename`) |
| 9.1.11| `POST`   | `/api/v1/files/link-to-datasets` | **链接文件到数据集并转换为 document**(支持传入文件夹 ID 批量转换) |

### 9.2 版本控制(Commit / Diff / Tree)

> 全部接口同时支持三种路径别名:`/folders/{folder_id}/...`、`/workspace/{workspace_id}/...`、`/datasets/{dataset_id}/...`(后两者将 dataset/workspace 解析为对应 folder)

| # | Method | Endpoint | 用途 |
|---|--------|----------|------|
| 9.2.1 | `POST` | `/api/v1/folders/{folder_id}/commits` | **创建快照提交**。`message` + `files` 必填,`operation`: add / modify / delete / rename |
| 9.2.2 | `GET`  | `/api/v1/folders/{folder_id}/commits` | **列出文件夹的所有提交**(分页) |
| 9.2.3 | `GET`  | `/api/v1/folders/{folder_id}/commits/{commit_id}` | **获取单个提交详情**(含文件变更列表) |
| 9.2.4 | `GET`  | `/api/v1/folders/{folder_id}/commits/{commit_id}/files` | **列出某次提交的文件变更** |
| 9.2.5 | `GET`  | `/api/v1/folders/{folder_id}/commits/diff?from=&to=` | **对比两次提交的差异** |
| 9.2.6 | `GET`  | `/api/v1/folders/{folder_id}/changes` | **获取未提交变更**(类似 `git status`) |
| 9.2.7 | `GET`  | `/api/v1/folders/{folder_id}/commits/{commit_id}/tree` | **获取某次提交的目录树快照** |
| 9.2.8 | `GET`  | `/api/v1/folders/{folder_id}/commits/{commit_id}/files/{file_id}/content` | **获取某次提交中指定文件的内容** |
| 9.2.9 | `GET`  | `/api/v1/files/{file_id}/versions` | **获取单个文件的全部版本历史** |

---

## 10. SEARCH APP MANAGEMENT — 搜索应用管理

预置的搜索应用(Search App),把数据集、检索配置、LLM 配置封装为可复用的问答服务。

| # | Method | Endpoint | 用途 |
|---|--------|----------|------|
| 10.1 | `POST`   | `/api/v1/searches` | **创建搜索应用**。`name` 必填,`description` 可选 |
| 10.2 | `GET`    | `/api/v1/searches` | **列出搜索应用**,支持分页/关键词/`owner_ids` 过滤 |
| 10.3 | `GET`    | `/api/v1/searches/{search_id}` | **获取搜索应用详情**(含 `search_config`) |
| 10.4 | `PUT`    | `/api/v1/searches/{search_id}` | **更新搜索应用**(名称 + `search_config` 合并) |
| 10.5 | `DELETE` | `/api/v1/searches/{search_id}` | **删除搜索应用** |
| 10.6 | `POST`   | `/api/v1/searches/{search_id}/completions` | **使用搜索应用进行问答**,SSE 流式返回 |

---

## 附录:统计与速查

- **接口总数**:共 10 大类、约 60 个端点
- **认证方式**:
  - API Key(`Authorization: Bearer <YOUR_API_KEY>`)— 绝大多数 CRUD/检索接口
  - Login Token(`Authorization: Bearer <YOUR_LOGIN_TOKEN>`,24h 过期)— TTS、ASR、MindMap、相关问题、Search App Completions
  - 无认证 — `/api/v1/system/healthz`
- **已废弃/替换**(使用新版本即可,旧版本仍可能可用):
  - `POST /api/v1/file/upload` → `POST /api/v1/files`
  - `POST /v1/document/upload_info` / `POST /api/v1/file/upload_info` → `POST /api/v1/documents/upload`
  - `GET /v1/document/download/{doc_id}` / `GET /api/v1/document/download/{doc_id}` → `GET /api/v1/agents/attachments/{attachment_id}/download`
  - `POST /api/v1/file/create` → `POST /api/v1/files`
  - `GET /api/v1/file/list` → `GET /api/v1/files`
  - `GET /api/v1/file/parent_folder?file_id=...` → `GET /api/v1/files/{file_id}/parent`
  - `GET /api/v1/file/all_parent_folder?file_id=...` → `GET /api/v1/files/{file_id}/ancestors`
  - `POST /api/v1/file/rm` → `DELETE /api/v1/files`
  - `GET /api/v1/file/get/{file_id}` → `GET /api/v1/files/{file_id}`
  - `POST /api/v1/file/mv` / `POST /api/v1/file/rename` → `POST /api/v1/files/move`
  - `POST /api/v1/file/convert` → `POST /api/v1/files/link-to-datasets`
  - `PUT /api/v1/datasets/{dataset_id}/documents/{document_id}/chunks/{chunk_id}` → `PATCH` 同路径
  - `PUT /api/v1/chats/{chat_id}` 的 `chat_id` 字段 → `ids` 列表(`DELETE /api/v1/chats`)
  - `PUT /api/v1/chats/{chat_id}/sessions/{session_id}` → `PATCH` 同路径
  - `POST /api/v1/chats/{chat_id}/completions` → `POST /api/v1/chat/completions`
  - `POST /api/v1/agents/{agent_id}/sessions` → 直接用 `POST /api/v1/agents/chat/completions`,自动生成 session
  - `POST /api/v1/agents/{agent_id}/completions` → `POST /api/v1/agents/chat/completions`
  - `GET /v1/system/healthz` → `GET /api/v1/system/healthz`
  - `POST /api/v1/sessions/related_questions` → `POST /api/v1/chat/recommandation`(也已被标 DEPRECATED,新接入请关注后续替换)
- **跨数据集检索**:`POST /api/v1/retrieval` 是核心入口,支持向量+关键词混合、metadata 过滤、GraphRAG、TOC 增强、rerank、跨语言
- **统一对话入口**:
  - Chat 助手:`POST /api/v1/chat/completions`
  - Agent:`POST /api/v1/agents/chat/completions`(同时支持 OpenAI 兼容模式 `openai-compatible: true`)

> 完整字段说明、请求/响应示例与错误码请参考 [`RagFlow-api.md`](./RagFlow-api.md)。
