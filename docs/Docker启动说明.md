# UP雷达 · Docker 启动说明

本文档说明如何使用 Docker Compose 一键启动 **UP雷达** 的前后端服务。

> 这是 `docs/启动说明.md` 的 Docker 替代方案,适合不想在本地装 Python / Node 的场景。

---

## 一、环境要求

| 依赖 | 版本 |
|------|------|
| Docker Engine | >= 24 |
| Docker Compose | >= 2.20(v2 语法) |

可选(只有启用本地 ASR 时才需要):

- NVIDIA 驱动 + `nvidia-container-toolkit`,用于 GPU 直通。

不需要在宿主机装 `ffmpeg`、`python`、`node` —— 全部内嵌在镜像里。

---

## 二、项目结构

本次新增的 Docker 相关文件:

```
b-up-watch/
├── docker-compose.yml          # 顶层编排
├── .env.docker.example         # 环境变量模板
├── .dockerignore
├── backend/
│   ├── Dockerfile              # 多阶段:base / runtime(默认) / asr
│   └── .dockerignore
└── frontend/app/
    ├── Dockerfile              # 多阶段:builder(node) / runtime(nginx)
    ├── nginx.conf              # 静态托管 + 反代 /api /ws
    └── .dockerignore
```

服务编排:

```
                ┌──────────────────────┐
   宿主机 :8080 │  frontend (nginx)    │  ── /api/*, /ws ──┐
   ─────────▶   │  静态文件 + 反代     │                   │
                └──────────────────────┘                   ▼
                                                ┌──────────────────────┐
                                                │  backend (uvicorn)   │
                                                │  FastAPI on :8000    │
                                                │  data/ 挂载到宿主机  │
                                                └──────────────────────┘
```

---

## 三、启动步骤

### 1. 准备环境变量

```bash
cp .env.docker.example .env.docker
# 编辑 .env.docker,至少填好 LLM_API_KEY(必填)
```

最小必填项:

- `LLM_API_KEY`:通义千问 / 其他 OpenAI 兼容服务的 API Key
- `LLM_BASE_URL`、`LLM_MODEL`:可选,默认值已能用

其余(B站 Cookie、RAGFlow、ASR)都可以留空,后续在 Web 页面右上角「设置」里配置。

### 2. 构建并启动

```bash
docker compose up -d --build
```

第一次构建会比较久(后端要装 `sentence-transformers` + PyTorch CPU ~200MB;前端装 npm 包 + 构建)。

### 3. 验证

```bash
# 查看运行状态
docker compose ps

# 跟踪日志
docker compose logs -f

# 健康检查(等到 STATUS 列出现 "Up (healthy)")
docker compose ps
```

打开浏览器访问 **<http://localhost:8080>**。

### 4. 常用操作

```bash
# 停止(保留数据)
docker compose down

# 停止并清掉数据(SQLite / Milvus / 语料全部删除)
docker compose down -v

# 仅重启后端(改了后端代码后)
docker compose up -d --build backend

# 进入后端容器调试
docker compose exec backend bash
```

---

## 四、启用本地 ASR(可选,需要 GPU)

默认构建目标 `runtime` **不包含** ASR 依赖,镜像更小、启动更快,且不需要 GPU。

如果要让后端在 B 站无字幕时自动本地转写,需要切换到 `asr` 目标:

### 1. 确认宿主机有 NVIDIA GPU

```bash
nvidia-smi
```

并安装 `nvidia-container-toolkit`,Compose 会自动识别。

### 2. 修改 `.env.docker`

```bash
BACKEND_TARGET=asr
QWEN_ASR_MODEL_PATH=/models/Qwen3-ASR-1.7B   # 容器内路径
QWEN_ASR_DEVICE=cuda:0
```

### 3. 重新构建并启动

```bash
docker compose build backend
docker compose up -d
```

### 4. 把 ASR 模型挂进容器

模型不用打进镜像(会非常大),通过 volume 挂载:

在 `docker-compose.yml` 的 `backend.volumes` 里加一行:

```yaml
volumes:
  - ./backend/data:/app/data
  - /path/on/host/Qwen3-ASR-1.7B:/models/Qwen3-ASR-1.7B:ro
```

然后让 `QWEN_ASR_MODEL_PATH=/models/Qwen3-ASR-1.7B`。

---

## 五、数据持久化

通过 volume 挂载到宿主机的 `./backend/data`:

| 容器内路径 | 宿主路径 | 用途 |
|------------|----------|------|
| `/app/data/upwatch.db` | `./backend/data/upwatch.db` | SQLite 主库 |
| `/app/data/milvus/taoge.db` | `./backend/data/milvus/taoge.db` | Milvus Lite 向量库 |
| `/app/data/corpus/` | `./backend/data/corpus/` | RAGFlow 语料输出 |
| `./backend/data/<Uploader名>/` | 同左 | UP 复盘 Markdown |

升级 / 重启容器都不会丢数据;只有 `docker compose down -v` 会清空。

---

## 六、CORS 说明

前端通过 nginx 反代访问后端(`/api/*`、`/ws`),**同源**,所以不会触发浏览器 CORS。

后端代码 `app/main.py` 里 hardcode 的 `allow_origins=["http://localhost:5173", ...]` 仅在本地开发模式生效,
Docker 部署无需关心。

---

## 七、常见问题

1. **`docker compose build` 卡在 pip install sentence-transformers**
   sentence-transformers 会拉 PyTorch CPU,大约 200MB,正常现象。如需换镜像源,
   在 `backend/Dockerfile` 的 `pip install` 前加 `pip config set global.index-url ...`。

2. **`docker compose up` 后前端一直 502**
   多半是后端还没启动起来。`docker compose logs backend` 看启动日志;
   前端 depends_on + healthcheck 会等后端 `/health` 返回 200 后才标 healthy。

3. **Milvus Lite 在 Linux 宿主机上文件锁问题**
   SQLite / Milvus Lite 是单文件本地库,容器已经默认开共享卷。如果发现 `database is locked`,
   不要同时跑本地 `uvicorn` 和容器。

4. **`localhost:8080` 能打开但所有 API 502**
   多半是 `.env.docker` 没填 `LLM_API_KEY`,导致后端启动失败。检查:
   ```bash
   docker compose logs backend | grep -i error
   ```

5. **想本地直接调试后端**
   在 `docker-compose.yml` 里把 `backend.ports` 那段取消注释,然后用 PyCharm / VSCode
   远程解释器连进容器即可。

---

## 八、相关文档

- 本地启动说明:`docs/启动说明.md`
- 接口文档:`docs/UP雷达-接口文档.md`
- 后端实现分析:`docs/UP雷达-后端实现分析.md`