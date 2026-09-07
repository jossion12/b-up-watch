"""yt-dlp 封装：从 B站视频拉取音轨到本地临时目录。

只用一次：转写完即删，不在数据库/磁盘上留存视频文件（接口文档 v0.2 已确认）。
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


class AudioUnavailableError(RuntimeError):
    """视频没有可识别音轨或无法下载音频，后续无需重试。"""


def _bilibili_http_headers(
    user_agent: str | None,
    sessdata: str | None,
    cookie: str | None = None,
) -> dict[str, str]:
    """构造 yt-dlp 访问 B站所需的浏览器态 HTTP 头。

    B站风控对裸请求返回 412 Precondition Failed：
    - 缺少 Referer：playurl 接口拒绝
    - 缺少 Origin：部分接口拒绝
    - 缺少 Accept-Language：浏览器指纹不完整
    - 仅靠 cookiefile 而不直接传 Cookie：部分请求路径拿不到登录态
    - 仅靠 SESSDATA 单字段不够：风控还需要 bili_jct / DedeUserID / buvid3/4 等

    因此登录态必须同时通过 cookiefile 与 Cookie header 双重注入，且 Cookie
    header 应携带完整字段（而非只塞 SESSDATA=xxx）。
    """
    headers: dict[str, str] = {
        "Referer": "https://www.bilibili.com/",
        "Origin": "https://www.bilibili.com",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    if user_agent:
        headers["User-Agent"] = user_agent
    # 优先完整 Cookie（多字段）；退化路径：sessdata 单字段
    if cookie:
        headers["Cookie"] = cookie
    elif sessdata:
        headers["Cookie"] = f"SESSDATA={sessdata}"
    return headers


def download_bilibili_audio(
    bvid: str,
    out_dir: Path,
    cookiefile: str | None = None,
    user_agent: str | None = None,
    sessdata: str | None = None,
    cookie: str | None = None,
) -> Path:
    """下载 B站视频音轨到 out_dir，返回媒体文件路径。

    Args:
        bvid: B站视频 BV 号
        out_dir: 临时输出目录（调用方负责清理）
        cookiefile: 可选 yt-dlp 格式 cookie 文件路径（用于登录态）
        user_agent: 可选自定义 User-Agent
        sessdata: 可选 B 站 SESSDATA，会作为 Cookie header 直接传给 yt-dlp
        cookie: 可选 B 站完整 Cookie 字符串（多字段），优先于 sessdata

    Raises:
        RuntimeError: yt-dlp 不可用或下载失败
    """
    try:
        import yt_dlp  # 延迟导入
    except ImportError as e:
        raise RuntimeError("yt-dlp 未安装，请 pip install yt-dlp") from e

    out_dir.mkdir(parents=True, exist_ok=True)

    ydl_opts = {
        # 跳过 FFmpegExtractAudio，避免 ffprobe 读不到 codec 时直接失败。
        # 优先下载含音频的格式；后续 pipeline.normalize_to_wav 会自行用 ffmpeg
        # 转成 16kHz mono WAV。
        "format": "bestaudio/best",
        "outtmpl": str(out_dir / "%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "http_headers": _bilibili_http_headers(user_agent, sessdata, cookie),
    }
    if cookiefile:
        ydl_opts["cookiefile"] = cookiefile

    url = f"https://www.bilibili.com/video/{bvid}"
    log.info("yt-dlp download audio: bvid=%s", bvid)
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        audio_path = _resolve_downloaded_audio(info, out_dir, bvid)
        if not _has_audio_stream(audio_path):
            raise AudioUnavailableError(
                f"yt-dlp 下载的文件没有可识别音轨，无法转写: {bvid} ({audio_path.name})"
            )
        return audio_path


def download_bilibili_video(
    bvid: str,
    out_dir: Path,
    cookiefile: str | None = None,
    user_agent: str | None = None,
    sessdata: str | None = None,
    cookie: str | None = None,
    max_height: int = 720,
) -> Path:
    """下载 B站视频为 ≤max_height 的 WebM 文件，返回媒体文件路径。

    format 选择器优先 WebM 视频 + WebM 音频，merge_output_format=webm
    保证双流合并后也是 WebM 容器。失败时逐级降级：合并 WebM → 单文件 WebM →
    任意 ≤max_height 的格式（仍受 merge_output_format 控制，最终落为 WebM）。

    Args:
        bvid: B站视频 BV 号
        out_dir: 临时输出目录（调用方负责清理）
        cookiefile: 可选 yt-dlp 格式 cookie 文件路径（用于登录态）
        user_agent: 可选自定义 User-Agent
        sessdata: 可选 B 站 SESSDATA，会作为 Cookie header 直接传给 yt-dlp
        cookie: 可选 B 站完整 Cookie 字符串（多字段），优先于 sessdata
        max_height: 最大分辨率上限（像素）

    Raises:
        RuntimeError: yt-dlp 不可用或下载失败
    """
    try:
        import yt_dlp  # 延迟导入
    except ImportError as e:
        raise RuntimeError("yt-dlp 未安装，请 pip install yt-dlp") from e

    out_dir.mkdir(parents=True, exist_ok=True)

    # B 站绝大多数视频不提供 webm 流。优先级：
    # 1. H.265/HEVC (vcodec=hvc1) —— 同画质体积比 H.264 小 30-50%（B 站同时提供）
    # 2. WebM（极少数视频有；体积可能更小，但兼容性比 MP4 差）
    # 3. 任意 ≤max_height 视频+音频（兜底，确保能下载）
    # 容器由 yt-dlp 决定（保留原始 ext），调用方按 .suffix 设置 Content-Type。
    format_selector = (
        f"bestvideo[vcodec^=hvc1][height<={max_height}]+bestaudio"
        f"/bestvideo[vcodec^=hev1][height<={max_height}]+bestaudio"
        f"/bestvideo[ext=webm][height<={max_height}]+bestaudio"
        f"/bestvideo[height<={max_height}]+bestaudio"
        f"/best[height<={max_height}]"
    )

    ydl_opts: dict = {
        "format": format_selector,
        "outtmpl": str(out_dir / "%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "http_headers": _bilibili_http_headers(user_agent, sessdata, cookie),
    }
    if cookiefile:
        ydl_opts["cookiefile"] = cookiefile

    url = f"https://www.bilibili.com/video/{bvid}"
    log.info("yt-dlp download video: bvid=%s, max_height=%d", bvid, max_height)
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return _resolve_downloaded_audio(info, out_dir, bvid)


def _has_audio_stream(path: Path) -> bool:
    """用 ffprobe 检查文件是否包含音频流；ffprobe 失败时保守返回 True。"""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a",
        "-show_entries", "stream=codec_type",
        "-of", "csv=p=0",
        str(path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except Exception as e:
        log.warning("ffprobe 检查音轨失败: %s, 假设文件有效: %s", e, path)
        return True
    if result.returncode != 0:
        log.warning("ffprobe 检查音轨失败: %s, 假设文件有效: %s", result.stderr.strip(), path)
        return True
    has_audio = "audio" in result.stdout.lower()
    log.info("ffprobe audio stream check: %s, has_audio=%s", path, has_audio)
    return has_audio


def _resolve_downloaded_audio(info: dict, out_dir: Path, bvid: str) -> Path:
    """根据 yt-dlp 返回的 info 定位已下载的音频/视频文件。"""
    # yt-dlp 最可靠：实际下载文件路径
    for entry in info.get("requested_downloads") or []:
        filepath = entry.get("filepath")
        if filepath:
            p = Path(filepath)
            if p.exists() and p.stat().st_size > 0:
                return p

    video_id = info.get("id") or bvid
    ext = info.get("ext") or "mp3"
    candidate = out_dir / f"{video_id}.{ext}"
    if candidate.exists() and candidate.stat().st_size > 0:
        return candidate

    # 兼容旧调用/测试：也可能已被外部处理为 mp3
    candidate_mp3 = out_dir / f"{video_id}.mp3"
    if candidate_mp3.exists() and candidate_mp3.stat().st_size > 0:
        return candidate_mp3

    # 兜底：按常见媒体扩展名 + 文件大小选最大的
    matches = [
        p for p in out_dir.iterdir()
        if p.is_file() and p.stat().st_size > 0
    ]
    for ext_order in (".m4a", ".mp3", ".mp4", ".webm", ".flac", ".wav", ".ogg", ".aac", ".mkv"):
        for p in matches:
            if p.suffix.lower() == ext_order:
                return p
    # 都没有命中扩展名时，选最大的文件（大概率是媒体文件）
    if matches:
        return max(matches, key=lambda p: p.stat().st_size)

    raise RuntimeError(f"yt-dlp 未产出音频文件: {bvid}")