"""ASR 转写流水线：拉音轨 → ffmpeg 规范化 → 分片 → Qwen3-ASR 推理 → 时间锚点拼接 → 清理。

移植自 local-mp4-voice/mp3_to_md.py（保留分片策略与 ffmpeg 参数），但：
- 不落 md 文件，内存中返回标准 lines（start_sec / end_sec / text）
- 时间锚点：按 chunk 起止时间 + 文本长度按字符数比例分配（粗略但足够区分）
- 失败抛 BizError，便于上层任务状态映射
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.config import get_settings
from app.errors import BizError
from app.transcriber import asr as asr_mod
from app.transcriber import audio_fetcher

log = logging.getLogger(__name__)

DEFAULT_CHUNK_SEC = 120


# ---------- ffmpeg/ffprobe 包装 ----------

def get_audio_duration(audio_path: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise BizError("FFPROBE_FAILED", f"ffprobe 失败: {result.stderr.strip()}", http_status=500)
    try:
        return float(result.stdout.strip())
    except ValueError as e:
        raise BizError("FFPROBE_BAD_OUTPUT", f"ffprobe 输出无法解析: {result.stdout!r}") from e


def normalize_to_wav(src: Path, dst: Path) -> None:
    """16kHz 单声道 WAV（与 Qwen3-ASR 期望的输入一致）。"""
    cmd = [
        "ffmpeg", "-y",
        "-err_detect", "ignore_err",
        "-fflags", "+discardcorrupt",
        "-i", str(src),
        "-ar", "16000",
        "-ac", "1",
        str(dst),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise BizError("FFMPEG_NORMALIZE_FAILED", f"ffmpeg 规范化失败: {result.stderr.strip()[-300:]}", http_status=500)


def split_wav(wav_path: Path, out_dir: Path, segment_seconds: int = DEFAULT_CHUNK_SEC) -> list[Path]:
    pattern = out_dir / "chunk_%03d.wav"
    cmd = [
        "ffmpeg", "-y",
        "-i", str(wav_path),
        "-f", "segment",
        "-segment_time", str(segment_seconds),
        "-c", "copy",
        str(pattern),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if result.returncode != 0:
        raise BizError("FFMPEG_SPLIT_FAILED", f"ffmpeg 分片失败: {result.stderr.strip()[-300:]}", http_status=500)
    return sorted(out_dir.glob("chunk_*.wav"))


# ---------- 时间锚点 ----------

_SENT_END = re.compile(r"(?<=[。！？!?])\s*")


def _split_text_proportional(text: str, start_sec: float, end_sec: float) -> list[dict]:
    """把一段文本按句子切分，按字符数比例分配时间窗。"""
    text = text.strip()
    if not text:
        return []
    parts = [p for p in _SENT_END.split(text) if p.strip()]
    if not parts:
        parts = [text]
    duration = max(end_sec - start_sec, 0.001)
    total_len = sum(len(p) for p in parts) or 1
    lines: list[dict] = []
    cursor = start_sec
    for p in parts:
        seg_dur = duration * len(p) / total_len
        lines.append({
            "start_sec": round(cursor, 3),
            "end_sec": round(cursor + seg_dur, 3),
            "text": p.strip(),
        })
        cursor += seg_dur
    return lines


# ---------- 主流程 ----------

async def transcribe_video(bvid: str) -> list[dict]:
    """下载 + 转写 + 拼接，返回标准 lines。"""
    settings = get_settings()
    model_path = settings.qwen_asr_model_path
    device = settings.qwen_asr_device or "cpu"

    if not asr_mod.is_available(model_path):
        raise BizError(
            "ASR_NOT_AVAILABLE",
            "本地 ASR 不可用：未安装 qwen_asr 或未配置 QWEN_ASR_MODEL_PATH",
            http_status=501,
        )

    work = Path(tempfile.mkdtemp(prefix="upwatch_asr_"))
    cookie_file: Path | None = None
    try:
        # 1. 准备 B 站登录态（如有）
        if settings.bilibili_sessdata:
            cookie_file = work / "bilibili_cookies.txt"
            cookie_file.write_text(
                "# Netscape HTTP Cookie File\n"
                ".bilibili.com\tTRUE\t/\tFALSE\t0\tSESSDATA\t" + settings.bilibili_sessdata + "\n",
                encoding="utf-8",
            )

        # 2. 下载音轨
        audio = audio_fetcher.download_bilibili_audio(
            bvid,
            work,
            cookiefile=str(cookie_file) if cookie_file else None,
            user_agent=settings.bilibili_user_agent or None,
        )
        log.info("downloaded audio: %s (%d bytes)", audio, audio.stat().st_size)

        # 2. 测时长
        duration = get_audio_duration(audio)
        log.info("audio duration: %.1fs", duration)

        # 3. 规范化
        wav = work / "normalized.wav"
        normalize_to_wav(audio, wav)

        # 4. 分片
        chunk_dir = work / "chunks"
        chunk_dir.mkdir(exist_ok=True)
        chunks = split_wav(wav, chunk_dir, DEFAULT_CHUNK_SEC)
        if not chunks:
            raise BizError("ASR_NO_CHUNKS", "ffmpeg 未产出任何分片", http_status=500)

        # 5. 加载模型（首次会较慢）
        model = asr_mod.load_model(model_path, device=device)

        # 6. 逐片推理 → 时间锚点
        all_lines: list[dict] = []
        for idx, chunk in enumerate(chunks):
            offset = idx * DEFAULT_CHUNK_SEC
            # 取 chunk 实际时长（最后一片可能不足）
            try:
                chunk_dur = get_audio_duration(chunk)
            except BizError:
                chunk_dur = DEFAULT_CHUNK_SEC
            chunk_dur = min(chunk_dur, DEFAULT_CHUNK_SEC)

            log.info("transcribe chunk %d/%d (offset=%.0fs)", idx + 1, len(chunks), offset)
            try:
                import torch  # noqa: F401
                with _no_grad():
                    results = model.transcribe(audio=str(chunk), language=None)
            except Exception as e:
                raise BizError("ASR_INFERENCE_FAILED", f"chunk {idx+1} 推理失败: {e}", http_status=500) from e

            if not results:
                continue
            text = (results[0].text or "").strip()
            if not text:
                continue
            lines = _split_text_proportional(text, offset, offset + chunk_dur)
            all_lines.extend(lines)

        log.info("transcribed %d lines from %d chunks", len(all_lines), len(chunks))
        return all_lines
    finally:
        shutil.rmtree(work, ignore_errors=True)


class _no_grad:
    """轻量包装：torch 不可用时直接 pass。"""

    def __enter__(self):
        try:
            import torch
            self._ctx = torch.no_grad()
            return self._ctx.__enter__()
        except ImportError:
            self._ctx = None
            return None

    def __exit__(self, *exc):
        if self._ctx is not None:
            return self._ctx.__exit__(*exc)
        return False