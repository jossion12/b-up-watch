# UP雷达 · 后端接口文档

> 版本：v0.3  
> 更新日期：2026-07-22  
> 适用对象：后端开发、联调前端

## 变更记录

| 版本 | 变更 |
|---|---|
| v0.3 | UP主新增 `category` 类型字段；添加/更新时可设置类型；UP主列表与视频时间线支持按类型过滤 |
| v0.2 | ① 确认单用户先行，预留多用户扩展；② **移除视频文件下载/存储**（系统只处理字幕与总结）；③ 新增总结 Prompt 模板管理接口；④ 日报/周报功能移入未来规划 |
| v0.1 | 初版 |

## 已确认的产品决策

1. **单用户先行**：当前版本无需登录认证，但数据模型预留 `user_id`，接口路径不变，后续可平滑扩展多用户
2. **不保存视频文件**：系统只采集视频元数据、获取字幕文本、生成 AI 总结；存储开销极小
3. **Prompt 模板可配置**：总结的提示词通过模板接口管理，可在不同模板间切换、对比效果
4. **日报/周报**：本期不做，列入未来规划（见附录 A）

---

## 1. 系统概述

### 1.1 架构与数据流

```
┌──────────┐   REST/WS   ┌───────────┐   采集   ┌──────────────┐
│ React SPA │ ◄────────► │  API 服务  │ ──────► │ B站数据源     │
└──────────┘             └───────────┘         │（元数据+字幕）│
                               │               └──────────────┘
                               │ 调用          ┌──────────────┐
                               ▼           ──► │  LLM 服务     │
                         ┌───────────┐         └──────────────┘
                         │ 任务队列   │
                         └───────────┘
                    存储：视频元数据 + 字幕文本 + 总结（SQLite/PG 即可，无大文件）
```

核心数据流：

1. **采集**：定时任务（或手动触发）拉取关注 UP 主的最新投稿元数据，写入视频库，状态 = `new`
2. **字幕**：用户触发（或总结任务级联触发）获取字幕文本
3. **总结**：字幕文本 → LLM（按指定 Prompt 模板）→ 结构化总结，状态 = `summarized`
4. **聚合**：总结完成后增量更新聚合表（话题热度、热词、观点聚类），供洞察页查询

### 1.2 通用约定

| 项目 | 约定 |
|---|---|
| Base URL | `/api/v1` |
| 数据格式 | JSON（请求与响应均 `application/json`） |
| 时间格式 | ISO 8601，如 `2026-07-19T10:32:00+08:00` |
| 分页方式 | 时间线类接口用日期区间，列表类接口用 page/page_size |
| 认证 | 单用户版本默认关闭；如需暴露到公网，可开启单一访问令牌 `Authorization: Bearer <token>` |
| 多用户扩展路径 | 所有业务表预留 `user_id`（当前恒为默认值）；扩展时增加用户体系 + 认证中间件，**接口路径与响应结构不变** |

### 1.3 统一错误格式

```json
{
  "error": {
    "code": "VIDEO_NOT_FOUND",
    "message": "视频不存在或已被删除",
    "details": {}
  }
}
```

| HTTP | 业务码 | 说明 |
|---|---|---|
| 400 | `INVALID_PARAM` | 参数错误 |
| 401 | `UNAUTHORIZED` | 未认证（开启访问令牌后） |
| 404 | `VIDEO_NOT_FOUND` / `UPLOADER_NOT_FOUND` / `TASK_NOT_FOUND` / `TEMPLATE_NOT_FOUND` | 资源不存在 |
| 409 | `TASK_CONFLICT` | 同类任务已在进行中（重复点击防护） |
| 422 | `SUBTITLE_UNAVAILABLE` | 视频无可用字幕（无法生成总结） |
| 429 | `BILIBILI_RATE_LIMITED` | B 站侧触发风控限流 |
| 502 | `LLM_ERROR` | 大模型调用失败 |

---

## 2. 数据模型

> 与前端 `src/types/index.ts` 对齐，后端响应字段使用 snake_case。

### 2.1 Uploader（UP主）

```json
{
  "id": "u1",
  "bilibili_uid": "946974",
  "name": "林亦LYi",
  "avatar_url": "https://i2.hdslb.com/bfs/face/xxx.jpg",
  "fans_count": 1286000,
  "category": "AI·编程",
  "description": "AI应用与开源项目实战",
  "unread_count": 2,
  "last_video_at": "2026-07-19T10:32:00+08:00",
  "group_id": "g1",
  "notify_enabled": true,
  "created_at": "2026-07-01T08:00:00+08:00"
}
```

### 2.2 Video（视频，仅存元数据）

```json
{
  "id": "v1",
  "bvid": "BV1xK4y1A7Cd",
  "uploader_id": "u1",
  "title": "我花72小时复刻了开源版Manus，Agent真的能干活了吗",
  "cover_url": "https://i0.hdslb.com/bfs/archive/xxx.jpg",
  "duration_sec": 1934,
  "published_at": "2026-07-19T10:32:00+08:00",
  "views": 865000,
  "danmaku_count": 12000,
  "likes": 98000,
  "tags": ["AI Agent", "开源", "实测"],
  "status": "summarized",
  "has_subtitle": true,
  "has_summary": true,
  "created_at": "2026-07-19T10:35:00+08:00"
}
```

**status 状态机**（v0.2 简化，无视频下载态）：

```
new ──获取字幕──► subtitled ──总结任务──► summarizing ──► summarized
                    │                          │
                    ▼                          ▼
                  failed                     failed（可重试）
```

> `new` 与 `subtitled` 可跳过：直接发起总结任务时，系统自动级联完成字幕获取，中途不落 `subtitled` 展示态。

| 状态 | 含义 | 前端表现 |
|---|---|---|
| `new` | 新采集，未处理 | 粉色状态点 |
| `subtitled` | 字幕已获取，未总结 | 蓝色状态点 |
| `summarizing` | LLM 总结中 | 按钮 loading + 骨架屏 |
| `summarized` | 总结完成 | 绿色状态点 |
| `failed` | 任务失败 | 详情页提示可重试 |

### 2.3 SubtitleLine（字幕）

```json
{
  "video_id": "v1",
  "language": "zh-CN",
  "source": "bilibili_ai",
  "lines": [
    { "start_sec": 12, "end_sec": 18, "text": "上个月Manus邀请码被炒到五万块..." }
  ],
  "fetched_at": "2026-07-19T11:00:00+08:00"
}
```

`source` 枚举：`uploader`（UP主上传字幕）/ `bilibili_ai`（B站AI字幕）/ `whisper`（本地语音识别兜底）

### 2.4 Summary（AI总结）

```json
{
  "video_id": "v1",
  "template_id": "tpl_default",
  "brief": "UP主用72小时基于开源框架复刻了类Manus的通用Agent...",
  "points": [
    "基于开源框架搭建多Agent系统：规划层负责任务拆解...",
    "实测30个任务，成功率约70%..."
  ],
  "stance": {
    "label": "谨慎乐观",
    "sentiment": "mixed",
    "detail": "认可Agent已跨过「能用」门槛，但强调营销热度高于实际能力..."
  },
  "topics": ["AI Agent", "多Agent框架", "Manus", "Token成本"],
  "quote": "Agent不是不能干活，是你得像带实习生一样带它。",
  "model": "qwen3-235b",
  "token_usage": { "prompt": 8200, "completion": 640 },
  "created_at": "2026-07-19T11:02:30+08:00"
}
```

`sentiment` 枚举：`positive` / `neutral` / `negative` / `mixed`  
记录的 `template_id` 便于追溯每份总结用的模板版本。

### 2.5 SummaryTemplate（总结模板）

```json
{
  "id": "tpl_default",
  "name": "通用深度总结",
  "is_default": true,
  "prompt": "你是视频内容分析助手。请根据以下字幕，输出 JSON：\n1. brief：150字内摘要\n2. points：3-5条关键要点\n3. stance：UP主观点（label 短语 + sentiment 四选一 + detail 详述）\n4. topics：3-5个话题标签\n5. quote：一句金句\n\n视频标题：{{title}}\nUP主：{{uploader}}\n字幕：\n{{subtitle}}",
  "created_at": "2026-07-01T08:00:00+08:00",
  "updated_at": "2026-07-10T09:00:00+08:00"
}
```

**可用变量**：`{{title}}`、`{{uploader}}`、`{{duration}}`、`{{tags}}`、`{{subtitle}}`  
**输出契约**：无论模板如何改，必须输出包含 `brief / points / stance{label,sentiment,detail} / topics / quote` 的 JSON —— 这是前端渲染与洞察聚合的固定结构，模板校验时由服务端强制检查。

### 2.6 Task（异步任务）

字幕获取、AI 总结、刷新等耗时操作统一抽象为任务：

```json
{
  "task_id": "t_01J4ZXYZ",
  "type": "ai_summary",
  "status": "running",
  "progress": 62,
  "ref_id": "v1",
  "error": null,
  "created_at": "2026-07-19T11:00:00+08:00",
  "finished_at": null
}
```

`type` 枚举：`subtitle_fetch` / `ai_summary` / `feed_refresh` / `whisper_transcribe`  
`status` 枚举：`pending` / `running` / `success` / `failed`

---

## 3. 接口明细

### 3.1 UP主管理

#### 3.1.1 获取关注的UP主列表

```
GET /uploaders
```

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| group_id | string | 否 | 按分组过滤 |
| category | string | 否 | 按类型过滤，支持逗号分隔多选，如 `AI,财经` |
| keyword | string | 否 | 按名称模糊搜索 |

**响应** `200`

```json
{
  "items": [ { "id": "u1", "name": "林亦LYi", "...": "..." } ],
  "total": 12
}
```

> 前端使用处：泳道行标签、筛选弹层、统计卡片。

#### 3.1.2 搜索B站UP主（添加前检索）

```
GET /uploaders/search?q={keyword}&page={n}
```

代理调用 B 站搜索接口，返回候选账号（uid、昵称、头像、粉丝数、简介），用于「添加UP主」对话框。

**响应** `200`

```json
{
  "items": [
    {
      "bilibili_uid": "946974",
      "name": "林亦LYi",
      "avatar_url": "https://...",
      "fans_count": 1286000,
      "description": "...",
      "already_followed": true
    }
  ],
  "page": 1,
  "has_more": false
}
```

#### 3.1.3 添加关注

```
POST /uploaders
Content-Type: application/json

{ "bilibili_uid": "946974", "group_id": "g1", "category": "AI", "notify_enabled": true }
```

服务端行为：写入关注表 → 立即创建一次该 UP 主的历史投稿拉取任务（建议默认回溯 30 天）。

**响应** `201`：Uploader 对象 + 首个采集任务的 `task_id`

#### 3.1.4 取消关注

```
DELETE /uploaders/{id}
```

| 参数 | 类型 | 说明 |
|---|---|---|
| keep_history | query bool | `true` 保留历史视频与总结（默认）；`false` 级联删除 |

**响应** `204`

#### 3.1.5 更新UP主设置

```
PATCH /uploaders/{id}

{ "group_id": "g2", "category": "财经", "notify_enabled": false }
```

**响应** `200`：更新后的 Uploader 对象

---

### 3.2 视频与时间线

#### 3.2.1 获取视频时间线

```
GET /videos
```

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| start_date | date | 是 | 起始日期（含），如 `2026-07-10` |
| end_date | date | 是 | 结束日期（含），如 `2026-07-19` |
| up_ids | string[] | 否 | 逗号分隔的UP主ID，缺省为全部 |
| category | string | 否 | 按UP主类型过滤，支持逗号分隔多选，如 `AI,财经` |
| status | string | 否 | `new` / `subtitled` / `summarized`，可多选 |
| limit | int | 否 | 默认 200，最大 500 |

**响应** `200`

```json
{
  "items": [ { "id": "v1", "...": "..." } ],
  "range": { "start_date": "2026-07-10", "end_date": "2026-07-19" },
  "total": 23
}
```

> 前端使用处：泳道时间轴（拖动加载更早日期时前移 `start_date` 重新请求）、列表视图。  
> 排序：服务端按 `published_at` 升序返回，前端自行分组。

#### 3.2.2 获取视频详情

```
GET /videos/{id}
```

**响应** `200`：Video 对象 + `uploader` 内联信息

```json
{
  "id": "v1",
  "...": "...",
  "uploader": { "id": "u1", "name": "林亦LYi", "fans_count": 1286000, "category": "AI·编程" }
}
```

#### 3.2.3 手动刷新

```
POST /videos/refresh
```

立即对所有关注的 UP 主执行一次更新检查（正常由定时任务每 N 分钟执行，此接口为手动触发）。

**响应** `202`

```json
{ "task_id": "t_01J4ZABC", "type": "feed_refresh" }
```

#### 3.2.4 标记已读

```
PATCH /videos/read

{ "video_ids": ["v1", "v2"] }
```

清除对应 UP 主的未读计数。**响应** `204`。

---

### 3.3 字幕

#### 3.3.1 获取字幕

```
GET /videos/{id}/subtitle
```

**响应** `200`：SubtitleLine 对象（见 2.3）  
**响应** `404`：字幕尚未获取 —— 前端此时应先调用 3.3.2

> 前端使用处：详情页「字幕原文」Tab。

#### 3.3.2 创建字幕获取任务

```
POST /videos/{id}/subtitle/fetch
```

服务端策略（按优先级）：UP 主上传字幕 → B 站 AI 字幕 → 下载音轨用本地 Whisper 转写（兜底，`whisper_transcribe` 任务，音频处理后即删，不落库存储）。

**响应** `202`：`{ "task_id": "...", "type": "subtitle_fetch" }`  
**任务失败时**：`error.code = SUBTITLE_UNAVAILABLE`

#### 3.3.3 导出字幕文件

```
GET /videos/{id}/subtitle/export?format=srt
```

| 参数 | 说明 |
|---|---|
| format | `srt` / `txt` / `json` |

**响应** `200`：文件流（`Content-Disposition: attachment`）

---

### 3.4 AI 总结

#### 3.4.1 创建总结任务

```
POST /videos/{id}/summary
```

| 参数 | 类型 | 说明 |
|---|---|---|
| template_id | body string | 可选，缺省用默认模板 |
| model | body string | 可选，指定 LLM 模型，缺省用系统默认 |
| force | body bool | 已有总结时是否重新生成（默认 false，返回已有） |

前置条件：字幕已就绪。若字幕不存在，服务端自动级联创建 `subtitle_fetch` 任务，完成后再执行总结 —— 响应中包含任务链：

**响应** `202`

```json
{
  "task_id": "t_01J4Z777",
  "type": "ai_summary",
  "chain": [
    { "task_id": "t_01J4Z776", "type": "subtitle_fetch" }
  ]
}
```

#### 3.4.2 获取总结结果

```
GET /videos/{id}/summary
```

**响应** `200`：Summary 对象（见 2.4）  
**响应** `404`：尚未生成

> 前端使用处：详情页「AI总结」Tab、洞察页聚合。

#### 3.4.3 重新生成总结

```
POST /videos/{id}/summary/regenerate

{ "template_id": "tpl_v2" }
```

用于切换模板/模型后重跑。**响应** `202`：新任务 ID

#### 3.4.4 批量总结（可选）

```
POST /summaries/batch

{ "video_ids": ["v3", "v6", "v9"], "template_id": "tpl_default" }
```

**响应** `202`

```json
{ "batch_id": "b_01J4Z999", "task_ids": ["t_...", "t_..."] }
```

> 支撑「过夜批量处理队列」场景：配合 3.7.2 的 `auto_summarize`，新视频采集后自动排队生成总结。

#### 3.4.5 获取模板列表

```
GET /summary/templates
```

**响应** `200`

```json
{
  "items": [
    { "id": "tpl_default", "name": "通用深度总结", "is_default": true, "prompt": "...", "updated_at": "..." }
  ]
}
```

#### 3.4.6 新建模板

```
POST /summary/templates

{ "name": "只看观点", "prompt": "...{{subtitle}}...", "is_default": false }
```

服务端校验：prompt 必须包含 `{{subtitle}}` 变量；首次保存时用一个样例字幕试跑，验证 LLM 输出能解析为规定 JSON 结构（2.5 输出契约），失败返回 `400` 并附原因。

**响应** `201`：模板对象

#### 3.4.7 更新模板

```
PUT /summary/templates/{id}

{ "name": "只看观点 v2", "prompt": "...", "is_default": true }
```

**响应** `200`：更新后的模板对象

#### 3.4.8 删除模板

```
DELETE /summary/templates/{id}
```

默认模板不可删除（`400`）。**响应** `204`

---

### 3.5 任务与实时推送

#### 3.5.1 查询任务状态

```
GET /tasks/{task_id}
```

**响应** `200`：Task 对象（见 2.6）。前端轮询建议：进行中每 2s 一次，成功后停止。

#### 3.5.2 任务列表

```
GET /tasks?status=running,pending&limit=20
```

用于顶栏任务队列指示器 / 任务管理页。

#### 3.5.3 WebSocket 事件推送（推荐）

```
WS /ws
```

服务端推送事件：

| 事件 | 载荷 | 时机 |
|---|---|---|
| `video.new` | Video 对象 | 采集到新投稿 |
| `task.updated` | Task 对象 | 任务进度/状态变化 |
| `summary.completed` | `{ video_id, summary }` | 总结完成 |
| `uploader.unread` | `{ uploader_id, unread_count }` | 未读数变化 |

> 用 WebSocket 替代轮询可显著降低请求量；若暂不做，前端按 3.5.1 轮询亦可跑通全流程。

---

### 3.6 洞察分析

> 洞察数据基于已完成的总结做预聚合（总结完成时增量写入聚合表），查询接口直接读聚合结果，避免实时计算。

#### 3.6.1 总览统计

```
GET /insights/overview
```

**响应** `200`

```json
{
  "monitored_uploaders": 12,
  "week_new_videos": 23,
  "week_new_videos_delta": 4,
  "summarized_count": 8,
  "summary_coverage": 0.35,
  "hot_topic_count": 4,
  "rising_topic_count": 2
}
```

#### 3.6.2 话题热度趋势

```
GET /insights/topic-trend?days=7
```

**响应** `200`

```json
{
  "series": [
    { "date": "2026-07-13", "AI Agent": 2, "华为·芯片": 1, "A股·投资": 1, "影像·硬件": 2 }
  ],
  "topics": ["AI Agent", "华为·芯片", "A股·投资", "影像·硬件"]
}
```

> 统计口径：每日发布的视频中，其总结话题标签的命中次数（Top N 话题，N 默认 6）。

#### 3.6.3 热词榜

```
GET /insights/hot-words?days=7&limit=20
```

**响应** `200`

```json
{
  "items": [
    { "word": "AI Agent", "heat": 98, "mention_count": 9, "trend": "up" }
  ]
}
```

`trend` 枚举：`up` / `down` / `flat`（环比前一周期）。

#### 3.6.4 观点聚类

```
GET /insights/topic-clusters?days=7
```

**响应** `200`

```json
{
  "items": [
    {
      "topic": "AI Agent 是否迎来爆发期",
      "heat": 98,
      "video_count": 5,
      "opinions": [
        {
          "uploader_id": "u9",
          "uploader_name": "老师好我叫何同学",
          "sentiment": "positive",
          "stance": "乐观",
          "opinion": "个人AI硬件两年内爆发，DIY社区会成为创新源头",
          "video_id": "v10",
          "video_title": "我做了一个会自己写代码的桌面机器人"
        }
      ]
    }
  ]
}
```

> 聚类方式建议：对全部总结的 `topics` 做语义聚类（embedding + 聚类算法）或人工预定义话题看板，观点文本取自各视频总结的 `stance.detail` 的二次压缩。

#### 3.6.5 播放 Top 视频

```
GET /insights/top-videos?days=7&by=views&limit=5
```

| 参数 | 说明 |
|---|---|
| by | `views` / `likes` / `danmaku` |

**响应** `200`：Video 数组（含 uploader 内联）。

---

### 3.7 系统

#### 3.7.1 系统状态

```
GET /system/status
```

**响应** `200`

```json
{
  "last_refresh_at": "2026-07-19T10:50:00+08:00",
  "refresh_interval_sec": 600,
  "running_tasks": 2,
  "queued_tasks": 1,
  "llm": { "provider": "openai-compatible", "model": "qwen3.5:9b", "available": true },
  "storage": { "db_mb": 48.2, "subtitles_count": 156 }
}
```

| 字段 | 说明 |
|---|---|
| llm.model | 实际使用的 LLM 模型，取自 `.env` 的 `LLM_MODEL` |
| llm.available | 是否配置了 `LLM_API_KEY` |
| refresh_interval_sec | 当前数据库中的采集间隔（与 `.env` 独立） |

#### 3.7.2 查询/更新监控设置

```
GET /system/config

{
  "refresh_interval_sec": 600,
  "summary_model": "qwen3-235b",
  "summary_template_id": "tpl_default",
  "auto_summarize": false,
  "bilibili_sessdata": "xxx"
}
```

```
PATCH /system/config

{
  "refresh_interval_sec": 300,
  "summary_model": "qwen3-235b",
  "summary_template_id": "tpl_default",
  "auto_summarize": true,
  "bilibili_sessdata": "xxx"
}
```

| 字段 | 说明 |
|---|---|
| refresh_interval_sec | 定时采集间隔 |
| summary_model | 默认使用的 LLM 模型 |
| summary_template_id | 默认总结模板 |
| auto_summarize | 新视频采集后自动排队生成总结（「过夜批量处理」开关） |
| bilibili_sessdata | B 站登录 Cookie，保存后即时生效；传空字符串可清空 |

---

---

### 3.8 RAG 复盘问答

Base path: `/rag`

#### 3.8.1 重建某位 UP 主的 RAG 索引

```
POST /rag/up/{uploader_id}/ingest
```

遍历该 UP 主下所有有字幕的视频，重新生成观点卡片并写入向量库。

**响应** `200`

```json
{ "files": 12, "segments": 156, "chunks": 420 }
```

#### 3.8.2 检索指定 UP 主的观点卡片

```
GET /rag/up/{uploader_id}/search?q=华为&n=5&mode=hybrid
```

| 参数 | 类型 | 说明 |
|---|---|---|
| q | string | 查询文本 |
| n | int | 返回数量，默认 5，最大 20 |
| mode | string | `vector` / `keyword` / `hybrid` |

**响应** `200`

```json
{
  "items": [
    {
      "chunk_id": "...",
      "content": "...",
      "distance": 0.12,
      "metadata": {
        "video_id": "v1",
        "video_title": "...",
        "up_name": "...",
        "date": "2026-07-19",
        "time_position": "00:12 -> 00:45",
        "content_type": "观点",
        "core_topic": "华为"
      }
    }
  ]
}
```

#### 3.8.3 与指定 UP 主做 RAG 对话

```
POST /rag/up/{uploader_id}/chat

{
  "question": "他怎么看华为？",
  "n_results": 5,
  "mode": "hybrid"
}
```

**响应** `200`

```json
{
  "answer": "...",
  "chunks": [...],
  "token_usage": { "prompt": 1200, "completion": 180 }
}
```

#### 3.8.4 跨 UP 主检索观点卡片

```
GET /rag/search?q=华为&n=5&mode=hybrid
```

与 3.8.2 类似，但不限定 UP 主。

#### 3.8.5 按话题检索视频

```
GET /rag/videos/search?q=华为&n=10&mode=hybrid
```

返回相关视频列表（按命中 chunk 数排序）。

**响应** `200`

```json
{
  "videos": [
    {
      "video_id": "v1",
      "video_title": "...",
      "up_name": "...",
      "uploader_id": "u1",
      "date": "2026-07-19",
      "published_at": "2026-07-19T10:32:00+08:00",
      "chunk_count": 5,
      "top_chunk": "...",
      "best_distance": 0.08
    }
  ]
}
```

#### 3.8.6 跨 UP 主/限定视频的 RAG 对话

```
POST /rag/chat

{
  "question": "这些视频里对华为的观点有什么异同？",
  "n_results": 5,
  "mode": "hybrid",
  "video_ids": ["v1", "v2"]
}
```

`video_ids` 为空时做全局检索；传入视频 ID 时只在这些视频内检索作答。

## 4. 页面 ↔ 接口映射

| 页面区域 | 交互 | 调用接口 |
|---|---|---|
| 顶栏 | 上次更新时间 / 刷新按钮 | `GET /system/status` / `POST /videos/refresh` |
| 顶栏 | 筛选UP主弹层 | `GET /uploaders` |
| 顶栏 | 通知红点 | `WS /ws`（`video.new`） |
| 时间轴 | 泳道行与节点渲染 | `GET /uploaders` + `GET /videos?start_date&end_date` |
| 时间轴 | 向左拖动加载更早 | `GET /videos`（前移 start_date 重新请求） |
| 时间轴 | 悬停信息卡 | 已加载数据，无需请求 |
| 时间轴 | 状态点（粉/蓝/绿） | Video.status 字段（new/subtitled/summarized） |
| 列表视图 | 卡片与日期分组 | 同时间轴 |
| 详情页 | 页面数据 | `GET /videos/{id}` |
| 详情页 | 获取字幕按钮 | `POST /videos/{id}/subtitle/fetch` → 轮询任务 → `GET /videos/{id}/subtitle` |
| 详情页 | AI总结按钮 | `POST /videos/{id}/summary` → 轮询任务 → `GET /videos/{id}/summary` |
| 详情页 | 字幕原文 Tab | `GET /videos/{id}/subtitle` |
| 详情页 | 导出字幕 | `GET /videos/{id}/subtitle/export?format=srt` |
| 详情页 | 总结模板切换（设置项） | `GET /summary/templates` + `POST /videos/{id}/summary/regenerate` |
| 洞察页 | 统计卡片 | `GET /insights/overview` |
| 洞察页 | 话题热度趋势图 | `GET /insights/topic-trend?days=7` |
| 洞察页 | 本周热词 | `GET /insights/hot-words?days=7` |
| 洞察页 | 观点聚类卡片 | `GET /insights/topic-clusters?days=7` |
| 洞察页 | 播放 Top5 | `GET /insights/top-videos?days=7` |
| RAG 页 | 话题搜索视频 | `GET /rag/videos/search?q=...` |
| RAG 页 | 按 UP 主问答 | `POST /rag/up/{uploader_id}/chat` |
| RAG 页 | 跨 UP 主/限定视频问答 | `POST /rag/chat` |
| 顶栏设置 | B 站 SESSDATA / 监控设置 | `GET /system/config`、`PATCH /system/config` |
| 设置页（待做） | 模板管理 / 监控设置 | `GET/POST/PUT/DELETE /summary/templates`、`PATCH /system/config` |
| 添加UP主（待做） | 搜索+添加 | `GET /uploaders/search` → `POST /uploaders` |

---

## 5. 关键设计说明

### 5.1 为什么字幕获取和总结必须是异步任务

- LLM 总结一个 30 分钟视频的字幕（约 1 万 token）通常需要 20–60 秒；Whisper 兜底转写更慢
- 统一 Task 抽象后，前端只需一套「创建 → 轮询/推送 → 渲染」逻辑，且天然支持 409 防重复点击

### 5.2 任务链：字幕 → 总结

`POST /videos/{id}/summary` 内部自动级联字幕获取，前端无需关心顺序。无字幕视频（如纯音乐、无口播）在任务结果中返回 `SUBTITLE_UNAVAILABLE`，前端可提示「该视频无可用字幕，可尝试 Whisper 转写」。

### 5.3 洞察数据的生成时机

- 总结完成 → 增量更新三张聚合表：`topic_daily_stats`（趋势/热词）、`topic_opinions`（观点聚类）、`video_stats_snapshot`（Top 榜快照）
- 聚合在写入侧完成，洞察页查询是纯读操作，毫秒级返回

### 5.4 B 站数据采集注意事项

- 投稿列表：UP 主空间投稿接口（`x/space/wbi/arc/search`，wbi 签名）
- 字幕：播放器接口返回字幕轨道，AI 字幕需登录 Cookie
- **v0.2 起不下载视频文件**：采集层只拉元数据与字幕文本，请求量与风控压力大幅降低；Whisper 兜底场景才临时拉取音轨，转写完即删
- 风控：需控制请求频率、维护 Cookie；触发 `BILIBILI_RATE_LIMITED` 时前端提示稍后重试
- 建议采集层与业务层解耦（如 bilibili-api 等成熟库做底层），便于替换

### 5.5 多用户扩展路径（预留）

- 业务表均已预留 `user_id`，单用户版本写入默认值
- 扩展步骤：新增 `users` 表与认证（账号密码 / OAuth）→ 中间件解析用户并注入查询过滤 → 关注表、视频、总结按 `user_id` 隔离
- **接口路径与响应结构保持不变**，前端仅需增加登录页与 token 管理

---

## 附录 A · 未来规划（本期不实现）

| 功能 | 设想 |
|---|---|
| 每日/每周摘要报告 | 基于观点聚类与热词，定时生成图文报告（接口形如 `GET /reports/daily?date=`），支持邮件/ webhook 推送 |
| 多用户 | 按 5.5 路径扩展 |
| 话题订阅提醒 | 指定关键词（如「华为」），命中新总结时推送通知 |
