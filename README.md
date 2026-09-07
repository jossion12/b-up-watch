# UP雷达 (b-up-watch)

自用向的 B 站 UP 主监控与内容复盘工具：追踪你关注的 UP 主投稿，自动抓取字幕，用 LLM 生成结构化总结与洞察分析，并支持基于向量检索的复盘问答（RAG）。

## 功能特性

- **UP 主管理**：添加/监控多个 UP 主，自动采集空间投稿并去重入库
- **视频时间线**：按 UP 主 / 分类浏览投稿时间线，全局刷新
- **字幕三级获取**：UP 主上传字幕 → B 站 AI 字幕 → 本地 Qwen3-ASR 兜底转写，自动级联；支持 srt / txt / json 导出
- **AI 总结**：基于可配置模板调用 OpenAI 兼容接口（通义千问 / Ollama 等）生成结构化总结
- **洞察分析**：跨视频聚合观点、主题与趋势
- **RAG 复盘问答**：Milvus Lite 本地向量库 + sentence-transformers Embedding，支持按 UP 主 / 全局的语义检索与对话；可生成 RagFlow 语料并同步到 RagFlow 知识库
- **任务队列**：字幕/总结等异步任务后台调度，WebSocket 实时推送进度
- **视频下载**：基于 yt-dlp 的登录态视频下载

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python ≥ 3.10 · FastAPI · SQLAlchemy · SQLite |
| 前端 | React 19 · Vite · TypeScript · Tailwind CSS · Radix UI |
| RAG | Milvus Lite · sentence-transformers（可选 RagFlow / Ollama） |
| ASR | Qwen3-ASR（可选，需 ffmpeg/ffprobe） |
| 部署 | Docker Compose（前端 nginx + 后端，单容器网络） |

## 项目结构

```
b-up-watch/
├── backend/       # FastAPI + SQLite 后端
│   ├── app/       # api / bilibili / collect / llm / rag / transcriber / tasks ...
│   ├── scripts/   # 语料生成等脚本
│   └── tests/     # pytest 测试
├── frontend/app/  # React + Vite + Tailwind CSS 前端
├── docs/          # 启动说明、接口文档、架构设计
└── docker-compose.yml
```

## 快速开始

### 方式一：Docker（推荐）

```bash
docker compose up -d
```

访问 `http://localhost:8080`（可用 `FRONTEND_PORT` 环境变量改端口）。

- 数据持久化在 `./backend/data`（SQLite + Milvus Lite + 语料）
- 敏感配置（API Key 等）放在 `.env.docker`，不会被提交进镜像
- 启用本地 ASR（需要 GPU）：`BACKEND_TARGET=asr docker compose up -d --build`

### 方式二：本地开发

**后端**（`http://127.0.0.1:8000`，API 文档在 `/docs`）：

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"       # 需要本地 ASR 时: pip install -e ".[asr]"
cp .env.example .env
uvicorn app.main:app --reload
```

**前端**（`http://localhost:5173`）：

```bash
cd frontend/app
npm install
npm run dev
```

## 配置

复制 `backend/.env.example` 为 `backend/.env`，关键配置：

| 配置项 | 说明 |
|--------|------|
| `BILIBILI_SESSDATA` | B 站登录 Cookie；留空也能跑，但搜索/字幕更易触发风控。也可启动后在 Web 页面「设置」中配置，即时生效 |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | OpenAI 兼容接口（默认通义千问兼容模式，可换 Ollama） |
| `QWEN_ASR_MODEL_PATH` | 本地 Qwen3-ASR 模型路径，用于字幕兜底转写；留空则关闭 |
| `MILVUS_URI` | Milvus Lite 本地库路径（`.db` 结尾）或留空走服务器模式 |
| `RAGFLOW_*` | 可选：生成语料并同步到 RagFlow 知识库 |

## 测试

```bash
cd backend
pytest
```

## 常见问题

- **B 站返回 `-352` / `-412` 风控**：在 Web 页面「设置」中配置有效的 `BILIBILI_SESSDATA`。
- **字幕返回 `SUBTITLE_UNAVAILABLE`**：该视频无 UP 主字幕且 AI 字幕不可用；配置 `QWEN_ASR_MODEL_PATH` 可启用本地转写兜底。
- **本地 ASR 不可用**：确认 `ffmpeg` / `ffprobe` 在 PATH 中。

## 文档

- [启动说明](docs/启动说明.md) · [Docker 启动说明](docs/Docker启动说明.md)
- [接口文档](docs/UP雷达-接口文档.md) · [后端实现分析](docs/UP雷达-后端实现分析.md)
- [RAG 架构](docs/rag-architecture.md) · [B站 RAG 工作流](docs/bilibili-rag-workflow.md)
