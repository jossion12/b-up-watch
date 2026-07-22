# UP雷达 · 后端实现分析（local-mp4-voice 复用评估）

> 日期：2026-07-19
> 对照文档：[UP雷达-接口文档.md](UP雷达-接口文档.md)（v0.2）
> 评估对象：`D:\project\private\new_life\code\local-mp4-voice`

## 背景

`b-up-watch/backend` 当前为空目录，后端从零起步。`local-mp4-voice` 是一套命令行流水线脚本（xlsx 解析 → yt-dlp 下载音频 → ffmpeg 处理 → Qwen3-ASR 转写），**没有 Web 服务层**。本文分析哪些接口逻辑可以从中提取，哪些必须新实现。

## 一、可以从 local-mp4-voice 提取的逻辑

| 来源 | 可提取内容 | 对应接口/模块 |
|---|---|---|
| `download_bilibili_audio.py` | yt-dlp 调用封装：`-x --audio-format mp3` 直接拉音轨、返回码/失败处理 | **3.3.2 `POST /videos/{id}/subtitle/fetch`** 的兜底链路 —— 文档 v0.2 规定 Whisper 兜底时才临时拉音轨、转写完即删，正好对应此用法 |
| `mp3_to_md.py` | 本地 ASR 转写核心：ffprobe 测时长 → ffmpeg 规范化 16kHz 单声道 WAV → 120s 分片 → 逐片推理 → 拼接；模型只加载一次复用 | **任务类型 `whisper_transcribe`**（接口文档 2.6）的实现。该项目用 Qwen3-ASR-1.7B 而非 Whisper，但角色相同（本地 ASR 兜底），`source` 枚举已有 `whisper` 值可直接用 |
| `xlsx_to_url_md.py` | `normalize_bilibili_url()`：BV 号正则提取、URL 清洗 | 后端解析 `bvid` 的工具函数（采集层、手动添加视频时） |
| 其 `docs/prd.md` 的架构思想 | 单 worker 顺序执行（防 B 站反爬）、BV 号全局判重、失败可重试、中间产物自动清理 | 任务队列模块的设计参考（思想可借鉴，代码需新写） |

## 二、提取时的三个 gap（需补的工作）

1. **转写结果没有时间戳**。`mp3_to_md.py` 输出是纯文本，而接口文档 2.3 的 `SubtitleLine` 要求 `start_sec/end_sec` 行级结构。补救方案：利用分片粒度（每片 120s）生成粗略时间锚点，或降级为整段无时间戳文本。
2. **判重逻辑不适用**。`filter_existing()` 按文件名判重；UP 雷达不落盘存文件，判重应靠 DB 中 `bvid` 唯一约束 —— 只复用 yt-dlp 调用，不复用判重。
3. **`extract_audio.py` 基本用不上**。v0.2 不下载视频文件，不存在 mp4 → mp3 的场景。

## 三、无法提取、需要新实现的接口（绝大部分）

### A. B 站 API 采集层（全新，工作量最大）

- 3.1.2 `GET /uploaders/search` —— 代理 B 站搜索接口
- 投稿列表采集 `x/space/wbi/arc/search` + **wbi 签名**（local-mp4-voice 完全没有），支撑：3.1.3 添加关注后的 30 天回溯、3.2.3 `POST /videos/refresh`、定时采集
- **字幕轨道获取**（UP 主上传字幕 + B 站 AI 字幕，需登录 Cookie）—— 字幕的第一、二优先级来源；local-mp4-voice 只走了第三优先级的 ASR 路线
- 视频元数据字段（封面/时长/播放/弹幕/点赞/tags）+ `BILIBILI_RATE_LIMITED` 风控处理

### B. Web 服务与数据层（全新）

- FastAPI/Flask 框架 + SQLite 六张表（Uploader / Video / Subtitle / Summary / SummaryTemplate / Task，均预留 `user_id`）
- 统一错误格式、Task 抽象（409 防重）、任务链（`subtitle_fetch` → `ai_summary` 级联）

### C. LLM 总结（3.4 全部，全新）

- 3.4.1 / 3.4.2 / 3.4.3 总结任务：模板变量渲染（`{{title}}` 等 5 个变量）、输出 JSON 契约校验、`token_usage` 记录
- 3.4.5–3.4.8 模板管理：校验 `{{subtitle}}` 变量、保存时样例试跑
- 3.4.4 批量总结

### D. 查询类接口（新写，均为纯 DB 查询，较简单）

- 3.1.1 / 3.1.3–3.1.5 UP 主管理（含未读计数、分组、`keep_history` 级联）
- 3.2.1 时间线、3.2.2 详情、3.2.4 标记已读
- 3.3.1 取字幕、3.3.3 字幕导出（srt / txt / json 格式化）
- 3.5.1 / 3.5.2 任务查询；3.5.3 WebSocket 推送（可选，轮询亦可跑通）

### E. 洞察聚合（3.6 全部 5 个接口，全新）

- 总结完成时增量写三张聚合表：`topic_daily_stats` / `topic_opinions` / `video_stats_snapshot`
- overview / topic-trend / hot-words / topic-clusters / top-videos

### F. 系统接口（3.7，新写，简单）

- 3.7.1 status、3.7.2 config（含 `auto_summarize` 开关 + 定时调度器）

## 四、结论

**local-mp4-voice 只能覆盖字幕兜底链路（拉音轨 + 本地 ASR，约占整体后端的 15–20%），其余全部要新写。** 其真正价值是提供了验证过的 yt-dlp 调用参数和 ffmpeg/ASR 分片转写代码，可直接改造成后端的一个 `transcriber` 模块。

## 五、建议实现顺序

1. 数据层 + UP 主 CRUD
2. B 站采集层（wbi 签名 + 投稿列表）
3. 字幕获取（官方 / AI 字幕优先）
4. 移植 ASR 兜底（复用 local-mp4-voice 代码）
5. LLM 总结 + 模板管理
6. 任务链调度（级联、定时采集、auto_summarize）
7. 洞察聚合
8. WebSocket 推送
