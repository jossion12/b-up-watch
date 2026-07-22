"""yt-dlp 封装：从 B站视频拉取音轨到本地临时目录。

只用一次：转写完即删，不在数据库/磁盘上留存视频文件（接口文档 v0.2 已确认）。
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)


def download_bilibili_audio(
    bvid: str,
    out_dir: Path,
    cookiefile: str | None = None,
    user_agent: str | None = None,
) -> Path:
    """下载 B站视频音轨（mp3）到 out_dir，返回音频文件路径。

    Args:
        bvid: B站视频 BV 号
        out_dir: 临时输出目录（调用方负责清理）
        cookiefile: 可选 yt-dlp 格式 cookie 文件路径（用于登录态）
        user_agent: 可选自定义 User-Agent

    Raises:
        RuntimeError: yt-dlp 不可用或下载失败
    """
    try:
        import yt_dlp  # 延迟导入
    except ImportError as e:
        raise RuntimeError("yt-dlp 未安装，请 pip install yt-dlp") from e

    out_dir.mkdir(parents=True, exist_ok=True)

    ydl_opts = {
        "format": "bestaudio/best",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "0",
        }],
        "outtmpl": str(out_dir / "%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }
    if cookiefile:
        ydl_opts["cookiefile"] = cookiefile
    if user_agent:
        ydl_opts["http_headers"] = {
            "User-Agent": user_agent,
            "Referer": "https://www.bilibili.com/",
        }

    url = f"https://www.bilibili.com/video/{bvid}"
    log.info("yt-dlp download audio: bvid=%s", bvid)
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        # 找输出文件：实际文件名是 bvid + .mp3
        candidate = out_dir / f"{info['id']}.mp3"
        if candidate.exists():
            return candidate
        # 兜底：扫目录里的 mp3
        matches = list(out_dir.glob("*.mp3"))
        if matches:
            return matches[0]
        raise RuntimeError(f"yt-dlp 未产出音频文件: {bvid}")