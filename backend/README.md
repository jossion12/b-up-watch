# UP雷达 · 后端

UP雷达 后端服务（FastAPI + SQLite）。对应接口文档 `docs/UP雷达-接口文档.md` v0.2。

## 当前进度

**已实现接口**

- 3.1 UP主管理（5 个）
- 3.2.1 视频时间线 / 3.2.3 全局刷新
- 3.3.1 / 3.3.2 / 3.3.3 字幕（获取 / 任务 / srt/txt/json 导出）
- 3.5.1 任务状态
- 3.7.1 系统状态

**已实现底层能力**

- FastAPI 骨架 + SQLite 六张表 + 统一错误格式
- B 站 wbi 签名 / 搜索代理 / 空间投稿采集（含去重入库）
- 字幕三级获取：UP主上传 → B站 AI → **本地 ASR 兜底**（自动级联）
- 后台任务 Runner（单 worker 顺序、通知唤醒、tick 单元）

## 启动

```bash
cd backend
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
# source .venv/bin/activate

pip install -e ".[dev]"
cp .env.example .env  # 填入 BILIBILI_SESSDATA 可选

uvicorn app.main:app --reload
```

默认监听 `http://127.0.0.1:8000`，OpenAPI 文档在 `/docs`。
SQLite 文件首次启动自动建在 `backend/data/upwatch.db`。

## 测试

```bash
cd backend
pytest
```

## 已知事项

- **本地 ASR 依赖**：兜底转写需本机装有 `ffmpeg`/`ffprobe`（PATH 可调用）、`qwen_asr` 包与 Qwen3-ASR-1.7B 模型。未配置时无字幕视频返回 `SUBTITLE_UNAVAILABLE`，不会报错。
- 搜索接口需有效 wbi 签名；若 SESSDATA 缺失或过期，B站可能返回 `-352`/`-412` 风控，前端会收到 `429 BILIBILI_RATE_LIMITED`。
- 字幕导出三种格式：srt（带时间轴）、txt（纯文本）、json（结构化）。
- ASR 转写结果时间锚点为粗略值（按 120s 分片按字符数比例分配），仅用于前端渲染区分，不适合做精确剪辑定位。