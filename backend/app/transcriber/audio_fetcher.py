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


def download_bilibili_audio(
    bvid: str,
    out_dir: Path,
    cookiefile: str | None = None,
    user_agent: str | None = None,
) -> Path:
    """下载 B站视频音轨到 out_dir，返回媒体文件路径。

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
        # 跳过 FFmpegExtractAudio，避免 ffprobe 读不到 codec 时直接失败。
        # 优先下载含音频的格式；后续 pipeline.normalize_to_wav 会自行用 ffmpeg
        # 转成 16kHz mono WAV。
        "format": "bestaudio/best",
        "outtmpl": str(out_dir / "%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
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
        audio_path = _resolve_downloaded_audio(info, out_dir, bvid)
        if not _has_audio_stream(audio_path):
            raise AudioUnavailableError(
                f"yt-dlp 下载的文件没有可识别音轨，无法转写: {bvid} ({audio_path.name})"
            )
        return audio_path


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