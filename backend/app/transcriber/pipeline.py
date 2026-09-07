"""ASR 转写流水线：拉音轨 → ffmpeg 规范化 → 分片 → Qwen3-ASR 推理 → 时间锚点拼接 → 清理。

移植自 local-mp4-voice/mp3_to_md.py（保留分片策略与 ffmpeg 参数），但：
- 不落 md 文件，内存中返回标准 lines（start_sec / end_sec / text）
- 时间锚点：按 chunk 起止时间 + 文本长度按字符数比例分配（粗略但足够区分）
- 失败抛 BizError，便于上层任务状态映射
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from app.config import get_bilibili_sessdata, get_settings
from app.errors import BizError
from app.transcriber import asr as asr_mod
from app.transcriber import audio_fetcher

log = logging.getLogger(__name__)

DEFAULT_CHUNK_SEC = 120


class _DaemonThreadPoolExecutor(concurrent.futures.ThreadPoolExecutor):
    """ThreadPoolExecutor，但工作线程为 daemon。

    这样 uvicorn 收到停止信号后，即使 ASR 推理线程仍在运行，
    主进程也能直接退出，不会被长时间阻塞。
    """

    def _adjust_thread_count(self):
        # 复用父类逻辑，但在 start() 前把线程设为 daemon
        if self._idle_semaphore.acquire(timeout=0):
            return
        num_threads = len(self._threads)
        if num_threads < self._max_workers:
            thread_name = "%s_%d" % (self._thread_name_prefix or self, num_threads)

            def weakref_cb(_, q=self._work_queue):
                q.put(None)

            t = threading.Thread(
                name=thread_name,
                target=concurrent.futures.thread._worker,
                args=(__import__("weakref").ref(self, weakref_cb), self._work_queue, self._initializer, self._initargs),
            )
            t.daemon = True
            t.start()
            self._threads.add(t)
            concurrent.futures.thread._threads_queues[t] = self._work_queue


# 单线程 ASR 执行器（与 runner 单 worker 策略一致）
_asr_executor = _DaemonThreadPoolExecutor(max_workers=1, thread_name_prefix="upwatch-asr")


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
        "-vn",  # 只取音频，避免视频流干扰
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

def _transcribe_video_sync(bvid: str) -> list[dict]:
    """下载 + 转写 + 拼接，返回标准 lines（同步实现，应在线程池中运行）。"""
    import time
    settings = get_settings()
    model_path = settings.qwen_asr_model_path
    device = settings.qwen_asr_device or "cpu"
    log.info("[ASR start] bvid=%s, model_path=%s, device=%s", bvid, model_path, device)

    if not asr_mod.is_available(model_path):
        raise BizError(
            "ASR_NOT_AVAILABLE",
            "本地 ASR 不可用：未安装 qwen_asr 或未配置 QWEN_ASR_MODEL_PATH",
            http_status=501,
        )

    work = Path(tempfile.mkdtemp(prefix="upwatch_asr_"))
    log.info("[ASR workdir] bvid=%s, workdir=%s", bvid, work)
    cookie_file: Path | None = None
    try:
        # 1. 准备 B 站登录态（如有）
        sessdata = get_bilibili_sessdata()
        if sessdata:
            cookie_file = work / "bilibili_cookies.txt"
            cookie_file.write_text(
                "# Netscape HTTP Cookie File\n"
                ".bilibili.com\tTRUE\t/\tFALSE\t0\tSESSDATA\t" + sessdata + "\n",
                encoding="utf-8",
            )
            log.info("[ASR cookie] bvid=%s, cookie file prepared", bvid)

        # 2. 下载音轨
        log.info("[ASR download] bvid=%s, starting audio download", bvid)
        t0 = time.monotonic()
        audio = audio_fetcher.download_bilibili_audio(
            bvid,
            work,
            cookiefile=str(cookie_file) if cookie_file else None,
            user_agent=settings.bilibili_user_agent or None,
            sessdata=sessdata or None,
        )
        log.info("[ASR download] bvid=%s, audio=%s, size=%d bytes, elapsed=%.2fs", bvid, audio, audio.stat().st_size, time.monotonic() - t0)

        # 3. 测时长
        duration = get_audio_duration(audio)
        log.info("[ASR duration] bvid=%s, duration=%.1fs", bvid, duration)

        # 4. 规范化
        log.info("[ASR normalize] bvid=%s, normalizing to 16kHz mono wav", bvid)
        t0 = time.monotonic()
        wav = work / "normalized.wav"
        normalize_to_wav(audio, wav)
        log.info("[ASR normalize] bvid=%s, normalized wav=%s, elapsed=%.2fs", bvid, wav, time.monotonic() - t0)

        # 5. 分片
        log.info("[ASR split] bvid=%s, splitting wav into chunks", bvid)
        t0 = time.monotonic()
        chunk_dir = work / "chunks"
        chunk_dir.mkdir(exist_ok=True)
        chunks = split_wav(wav, chunk_dir, DEFAULT_CHUNK_SEC)
        if not chunks:
            raise BizError("ASR_NO_CHUNKS", "ffmpeg 未产出任何分片", http_status=500)
        log.info("[ASR split] bvid=%s, chunks=%d, elapsed=%.2fs", bvid, len(chunks), time.monotonic() - t0)

        # 6. 加载模型（首次会较慢）
        log.info("[ASR model] bvid=%s, loading ASR model", bvid)
        t0 = time.monotonic()
        model = asr_mod.load_model(model_path, device=device)
        log.info("[ASR model] bvid=%s, model ready, elapsed=%.2fs", bvid, time.monotonic() - t0)

        # 7. 逐片推理 → 时间锚点
        all_lines: list[dict] = []
        for idx, chunk in enumerate(chunks):
            offset = idx * DEFAULT_CHUNK_SEC
            # 取 chunk 实际时长（最后一片可能不足）
            try:
                chunk_dur = get_audio_duration(chunk)
            except BizError:
                chunk_dur = DEFAULT_CHUNK_SEC
            chunk_dur = min(chunk_dur, DEFAULT_CHUNK_SEC)

            log.info("[ASR inference] bvid=%s, chunk=%d/%d, offset=%.0fs", bvid, idx + 1, len(chunks), offset)
            try:
                import torch  # noqa: F401
                with _no_grad():
                    results = model.transcribe(audio=str(chunk), language=None)
            except Exception as e:
                log.error("[ASR inference] bvid=%s, chunk=%d/%d failed: %s", bvid, idx + 1, len(chunks), e)
                raise BizError("ASR_INFERENCE_FAILED", f"chunk {idx+1} 推理失败: {e}", http_status=500) from e

            if not results:
                log.info("[ASR inference] bvid=%s, chunk=%d/%d returned empty results", bvid, idx + 1, len(chunks))
                continue
            text = (results[0].text or "").strip()
            if not text:
                log.info("[ASR inference] bvid=%s, chunk=%d/%d returned empty text", bvid, idx + 1, len(chunks))
                continue
            lines = _split_text_proportional(text, offset, offset + chunk_dur)
            log.info("[ASR inference] bvid=%s, chunk=%d/%d produced %d lines", bvid, idx + 1, len(chunks), len(lines))
            all_lines.extend(lines)

        log.info("[ASR done] bvid=%s, lines=%d, chunks=%d", bvid, len(all_lines), len(chunks))
        return all_lines
    except audio_fetcher.AudioUnavailableError as e:
        log.warning("[ASR audio unavailable] bvid=%s, %s", bvid, e)
        raise BizError(
            "AUDIO_UNAVAILABLE",
            str(e),
            http_status=422,
        ) from e
    except Exception as e:
        log.error("[ASR error] bvid=%s, error=%s", bvid, e)
        raise
    finally:
        log.info("[ASR cleanup] bvid=%s, removing workdir=%s", bvid, work)
        shutil.rmtree(work, ignore_errors=True)


async def transcribe_video(bvid: str) -> list[dict]:
    """下载 + 转写 + 拼接，返回标准 lines（异步入口，底层在 daemon 线程池中执行）。"""
    log.info("[ASR async] bvid=%s, submitting to ASR thread pool", bvid)
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(_asr_executor, _transcribe_video_sync, bvid)
        log.info("[ASR async] bvid=%s, thread pool completed", bvid)
        return result
    except Exception as e:
        log.error("[ASR async] bvid=%s, thread pool failed: %s", bvid, e)
        raise


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