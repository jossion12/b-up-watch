# 视频详情页：WebM 视频下载按钮

**日期**：2026-08-28
**作者**：brainstorming 输出
**目标**：在视频详情页提供一个按钮，让用户把当前视频下载为 WebM 文件，文件名按视频标题命名。

---

## 决策摘要

| 决策点 | 选择 | 备注 |
|---|---|---|
| 交互模式 | 同步流式下载 | 类似现有字幕导出，点按钮即触发浏览器下载 |
| WebM 画质 | ≤720p | B 站多数视频有 720p WebM，文件体积与画质平衡 |
| 登录态 | 复用现有 SESSDATA | 已在 `bilibili/login.py` 集成 |
| 文件名 | `<清洗后的标题>.webm` | Windows/macOS 不安全字符 → `_`；emoji 控制字符剥离；空标题 fallback 到 bvid |

---

## 架构

后端用 yt-dlp 把 B 站视频拉到临时目录，通过 `FileResponse` 流回浏览器，下载完成后清理临时文件。前端复用 `subtitlesApi.export` 的 `window.open` 触发模式。

```
[浏览器] -- window.open --> [FastAPI /videos/{id}/video/download]
                                │
                                ├─ 校验视频存在（DB）
                                ├─ 取登录 cookie/UA（config）
                                ├─ tempfile.mkdtemp()
                                ├─ yt-dlp 拉 WebM (≤720p)
                                ├─ FileResponse(media_type=video/webm,
                                │               filename=<title>.webm,
                                │               background=rmtree)
                                └─ 浏览器下载完成后自动清理 tmp_dir
```

---

## 修改/新增文件

| 层 | 文件 | 动作 |
|---|---|---|
| 后端 | `backend/app/transcriber/audio_fetcher.py` | 新增 `download_bilibili_video()` 函数 |
| 后端 | `backend/app/api/videos.py` | 新增 `GET /videos/{id}/video/download` 端点 + `sanitize_filename()` 工具函数 |
| 前端 | `frontend/app/src/lib/api.ts` | `videosApi` 新增 `downloadWebm(id)` |
| 前端 | `frontend/app/src/sections/VideoPage.tsx` | 操作栏新增 "WebM" 按钮；清理无用的 `onDownloadVideo` prop |
| 前端 | `frontend/app/src/App.tsx` | 删除 `onDownloadVideo` prop 的传参 |
| 测试 | `backend/tests/test_video_download.py` | 新增 sanitize_filename + format 选择器单测 |

---

## 实现要点

### 后端：`download_bilibili_video()`

与 `download_bilibili_audio()` 并列，复用 `_resolve_downloaded_audio()` 路径定位逻辑。

```python
def download_bilibili_video(
    bvid: str,
    out_dir: Path,
    cookiefile: str | None = None,
    user_agent: str | None = None,
    max_height: int = 720,
) -> Path:
    """下载 B 站视频为 ≤max_height 的 WebM 格式。

    format 选择器：
        bestvideo[ext=webm][height<=N]+bestaudio[ext=webm]
        / best[ext=webm][height<=N]
        / best[height<=N]
    配合 merge_output_format=webm 确保合并输出为 WebM。
    """
```

yt-dlp 参数要点：
- `merge_output_format="webm"`：双流（视频+音频）合并后输出 WebM
- `format` 选择器确保视频+音频都尽量选 WebM 编码
- 复用 audio_fetcher 中的 cookiefile / user_agent / Referer 注入逻辑

### 后端：API 端点

```python
@router.get("/videos/{video_id}/video/download")
def download_video(
    video_id: str,
    db: Session = Depends(get_db),
) -> FileResponse:
    v = db.get(Video, video_id)
    if v is None or v.user_id != DEFAULT_USER_ID:
        raise BizError("VIDEO_NOT_FOUND", "视频不存在", http_status=404)

    settings = get_settings()
    tmp_dir = Path(tempfile.mkdtemp(prefix="b-up-watch-video-"))
    try:
        video_path = download_bilibili_video(
            v.bvid,
            tmp_dir,
            cookiefile=settings.bilibili_cookiefile_path or None,
            user_agent=settings.bilibili_user_agent or None,
            max_height=720,
        )
        filename = sanitize_filename(v.title, fallback=v.bvid)
        return FileResponse(
            path=video_path,
            media_type="video/webm",
            filename=f"{filename}.webm",
            background=BackgroundTask(_cleanup_tmp, tmp_dir),
        )
    except BizError:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        log.exception("video download failed: bvid=%s", v.bvid)
        raise BizError(
            "VIDEO_DOWNLOAD_FAILED",
            f"视频下载失败: {e}",
            http_status=502,
        ) from e
```

### 后端：`sanitize_filename()`

```python
_INVALID_FN_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]')
_CTRL_CHARS = re.compile(r'[\x00-\x1f\x7f]')

def sanitize_filename(title: str, fallback: str, max_length: int = 150) -> str:
    s = _CTRL_CHARS.sub("", title or "")
    s = _INVALID_FN_CHARS.sub("_", s).strip(" ._")
    if not s:
        return fallback
    if len(s) > max_length:
        s = s[:max_length].rstrip(" ._")
    return s
```

行为：
- 空标题 / 纯特殊字符 → `fallback`（即 bvid）
- 控制字符 `\x00-\x1f\x7f` 全删除
- `\\/:*?"<>|` 与 `\r\n\t` 替换为 `_`
- 开头/结尾的空格与 `.` `_` 去除（Windows 规则）
- 截断到 150 字符

### 前端：API 客户端

```ts
// frontend/app/src/lib/api.ts
export const videosApi = {
  // ... 既有方法
  downloadWebm: (videoId: string) =>
    window.open(`${API_BASE}/videos/${videoId}/video/download`, '_blank'),
}
```

### 前端：按钮

```tsx
// VideoPage.tsx 操作栏（在"获取字幕"按钮之后）
<Button
  variant="outline"
  size="sm"
  className="gap-1"
  onClick={() => id && videosApi.downloadWebm(id)}
>
  <Download className="h-3.5 w-3.5" /> WebM
</Button>
```

按钮**始终可见**，不需要前置数据（不像 SRT/TXT 要等字幕）。

### 清理 `onDownloadVideo` 遗留

`Props.onDownloadVideo` 当前仅在字幕获取成功后被调用，但没有任何实际下载动作，是历史误命名。本次一并清理：

- `VideoPage.tsx` 的 `Props` 接口：删除 `onDownloadVideo`
- `useTaskPoller` 成功回调：删除 `if (id) onDownloadVideo(id)` 一行
- `App.tsx`：删除 `<VideoPage onDownloadVideo={...} />` 传参

---

## 错误处理

| 场景 | 后端响应 | 前端处理 |
|---|---|---|
| 视频不存在 | 404 `VIDEO_NOT_FOUND` | 浏览器原生错误页（与现有字幕导出行为一致） |
| yt-dlp 失败（网络/解析/格式不可用） | 502 `VIDEO_DOWNLOAD_FAILED` | 同上 |
| 登录态缺失 | 不报错，yt-dlp 走匿名模式 | 同上（公开画质可下载） |
| 反向代理超时（大文件） | 504 | 浏览器停止等待，用户重试 |

不显示 toast：`window.open` 模式无法解析 JSON 错误体。

---

## 测试

### 单元测试 `backend/tests/test_video_download.py`

1. `sanitize_filename` 用例：
   - 普通标题 → 原样
   - 含 `/\:*?"<>|` → 替换为 `_`
   - 含控制字符 `\n\t\x00` → 删除
   - 含 emoji → 保留（现代文件系统支持）
   - 纯特殊字符 → fallback
   - 空字符串 → fallback
   - 长度 > 150 → 截断
   - 末尾 `.` 或空格 → 去除

2. yt-dlp format 选择器断言（mock）：
   - `extract_info` 返回时 `ydl_opts["format"]` 包含 `webm` 和 `height<=720`
   - `merge_output_format="webm"`

### 手动 e2e

1. 启动 backend + frontend
2. 进入任一视频详情页
3. 点击 "WebM" 按钮
4. 验证：
   - 浏览器开始下载
   - 文件名 = `<清洗后的标题>.webm`
   - 文件可在 VLC / ffplay 播放
   - 文件扩展名为 `.webm`

---

## 不做的事（YAGNI）

- 下载历史/管理界面
- 下载进度条（同步模式无中间态）
- 画质选择器（已固定 ≤720p WebM）
- 多格式切换（mp4/flv）—— 仅 WebM
- 断点续传（yt-dlp Range 不友好）
- 下载队列（用户按需点击，无并发场景）