"""转写层单元测试：audio_fetcher / asr / pipeline 内部纯函数 / runner fallback。"""

from __future__ import annotations

import sys
import tempfile
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.models import Subtitle, Task, Uploader, Video
from app.transcriber import asr as asr_mod
from app.transcriber import audio_fetcher, pipeline


# ============== audio_fetcher ==============

def test_download_audio_calls_ytdlp(monkeypatch):
    tmp = Path(tempfile.mkdtemp(prefix="upwatch_test_"))
    try:
        (tmp / "BV1abc.mp3").write_bytes(b"fake")

        fake_ydl = MagicMock()
        fake_ydl.extract_info.return_value = {"id": "BV1abc"}

        class _YDL:
            def __init__(self, opts):
                self.opts = opts
            def __enter__(self):
                return fake_ydl
            def __exit__(self, *exc):
                return False

        monkeypatch.setitem(sys.modules, "yt_dlp", MagicMock(YoutubeDL=_YDL))

        out = audio_fetcher.download_bilibili_audio("BV1abc", tmp)
        assert out.name == "BV1abc.mp3"
        call_url = fake_ydl.extract_info.call_args[0][0]
        assert call_url == "https://www.bilibili.com/video/BV1abc"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_download_audio_ytdlp_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "yt_dlp", None)
    with pytest.raises(RuntimeError, match="yt-dlp 未安装"):
        audio_fetcher.download_bilibili_audio("BV1x", Path("/tmp"))


def test_download_audio_rejects_no_audio_stream(monkeypatch):
    tmp = Path(tempfile.mkdtemp(prefix="upwatch_test_"))
    try:
        (tmp / "BV1noaudio.mp4").write_bytes(b"fake")

        fake_ydl = MagicMock()
        fake_ydl.extract_info.return_value = {"id": "BV1noaudio", "ext": "mp4"}

        class _YDL:
            def __init__(self, opts):
                self.opts = opts
            def __enter__(self):
                return fake_ydl
            def __exit__(self, *exc):
                return False

        monkeypatch.setitem(sys.modules, "yt_dlp", MagicMock(YoutubeDL=_YDL))
        # ffprobe 返回空，表示没有音轨
        monkeypatch.setattr(
            "app.transcriber.audio_fetcher.subprocess.run",
            lambda *a, **kw: MagicMock(returncode=0, stdout=""),
        )

        with pytest.raises(audio_fetcher.AudioUnavailableError, match="没有可识别音轨"):
            audio_fetcher.download_bilibili_audio("BV1noaudio", tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_has_audio_stream_detects_audio(monkeypatch):
    monkeypatch.setattr(
        "app.transcriber.audio_fetcher.subprocess.run",
        lambda *a, **kw: MagicMock(returncode=0, stdout="audio\n"),
    )
    assert audio_fetcher._has_audio_stream(Path("x.m4a")) is True


def test_has_audio_stream_detects_missing_audio(monkeypatch):
    monkeypatch.setattr(
        "app.transcriber.audio_fetcher.subprocess.run",
        lambda *a, **kw: MagicMock(returncode=0, stdout=""),
    )
    assert audio_fetcher._has_audio_stream(Path("x.mp4")) is False


def test_has_audio_stream_treats_ffprobe_failure_as_true(monkeypatch):
    monkeypatch.setattr(
        "app.transcriber.audio_fetcher.subprocess.run",
        lambda *a, **kw: MagicMock(returncode=1, stderr="ffprobe boom"),
    )
    assert audio_fetcher._has_audio_stream(Path("x.m4a")) is True


# ============== asr ==============

def test_asr_is_available_no_path():
    assert asr_mod.is_available("") is False


def test_asr_load_model_no_path(monkeypatch):
    """未配置路径时应在 import 成功后命中「未配置 QWEN_ASR_MODEL_PATH」。"""
    asr_mod.reset_for_test()

    class _FakeMod:
        Qwen3ASRModel = MagicMock()
    monkeypatch.setitem(sys.modules, "qwen_asr", _FakeMod())
    monkeypatch.setitem(sys.modules, "torch", MagicMock())

    with pytest.raises(RuntimeError, match="未配置 QWEN_ASR_MODEL_PATH"):
        asr_mod.load_model("", device="cpu")


def test_asr_load_model_missing_qwen_asr(monkeypatch):
    """qwen_asr 未装时 load_model 抛 RuntimeError。"""
    asr_mod.reset_for_test()
    # 用一个 ensure 抛 ImportError 的 fake 模块
    class _BrokenMod:
        def __getattr__(self, name):
            raise ImportError("simulated missing")
    monkeypatch.setitem(sys.modules, "qwen_asr", _BrokenMod())
    with pytest.raises(RuntimeError, match="qwen_asr 未安装"):
        asr_mod.load_model("/fake/path", device="cpu")


def test_asr_singleton(monkeypatch):
    """重复调用 load_model 只应触发一次真正的加载。"""
    asr_mod.reset_for_test()
    fake_model = MagicMock(name="QwenModel")
    fake_cls = MagicMock()
    fake_cls.from_pretrained.return_value = fake_model

    class _FakeQwenMod:
        Qwen3ASRModel = fake_cls

    monkeypatch.setitem(sys.modules, "qwen_asr", _FakeQwenMod())
    monkeypatch.setitem(sys.modules, "torch", MagicMock())

    m1 = asr_mod.load_model("/fake/path", device="cpu")
    m2 = asr_mod.load_model("/fake/path", device="cpu")
    assert m1 is m2 is fake_model
    assert fake_cls.from_pretrained.call_count == 1
    asr_mod.reset_for_test()


def test_asr_load_model_cuda_fallback_when_unavailable(monkeypatch):
    """CUDA 不可用时自动降级到 CPU，避免 Torch not compiled with CUDA enabled。"""
    asr_mod.reset_for_test()
    fake_model = MagicMock(name="QwenModel")
    fake_cls = MagicMock()
    fake_cls.from_pretrained.return_value = fake_model

    class _FakeQwenMod:
        Qwen3ASRModel = fake_cls

    monkeypatch.setitem(sys.modules, "qwen_asr", _FakeQwenMod())

    fake_torch = MagicMock()
    fake_torch.cuda.is_available.return_value = False
    fake_torch.float32 = "float32"
    fake_torch.bfloat16 = "bfloat16"
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    m = asr_mod.load_model("/fake/path", device="cuda:0")
    assert m is fake_model
    call_kwargs = fake_cls.from_pretrained.call_args[1]
    assert call_kwargs["device_map"] == "cpu"
    assert call_kwargs["dtype"] == "float32"
    asr_mod.reset_for_test()


# ============== pipeline 内部纯函数 ==============

def test_get_audio_duration_parses_ffprobe(monkeypatch):
    fake = MagicMock(return_value=MagicMock(returncode=0, stdout="123.45\n"))
    monkeypatch.setattr("app.transcriber.pipeline.subprocess.run", fake)
    assert pipeline.get_audio_duration(Path("x.mp3")) == 123.45
    assert "ffprobe" in fake.call_args[0][0]


def test_get_audio_duration_ffprobe_fail(monkeypatch):
    fake = MagicMock(return_value=MagicMock(returncode=1, stderr="err"))
    monkeypatch.setattr("app.transcriber.pipeline.subprocess.run", fake)
    from app.errors import BizError
    with pytest.raises(BizError) as ei:
        pipeline.get_audio_duration(Path("x.mp3"))
    assert ei.value.code == "FFPROBE_FAILED"


def test_normalize_to_wav_calls_ffmpeg(monkeypatch):
    fake = MagicMock(return_value=MagicMock(returncode=0))
    monkeypatch.setattr("app.transcriber.pipeline.subprocess.run", fake)
    pipeline.normalize_to_wav(Path("in.mp3"), Path("out.wav"))
    cmd = fake.call_args[0][0]
    assert cmd[0] == "ffmpeg"
    assert "-ar" in cmd and "16000" in cmd
    assert "-ac" in cmd and "1" in cmd


def test_normalize_to_wav_fail(monkeypatch):
    fake = MagicMock(return_value=MagicMock(returncode=1, stderr="boom"))
    monkeypatch.setattr("app.transcriber.pipeline.subprocess.run", fake)
    from app.errors import BizError
    with pytest.raises(BizError) as ei:
        pipeline.normalize_to_wav(Path("in.mp3"), Path("out.wav"))
    assert ei.value.code == "FFMPEG_NORMALIZE_FAILED"


def test_split_text_proportional_basic():
    lines = pipeline._split_text_proportional("你好。世界！", 0.0, 10.0)
    assert [l["text"] for l in lines] == ["你好。", "世界！"]
    assert lines[0]["start_sec"] == 0.0
    assert lines[-1]["end_sec"] == pytest.approx(10.0)


def test_split_text_proportional_empty():
    assert pipeline._split_text_proportional("", 0.0, 5.0) == []
    assert pipeline._split_text_proportional("   ", 0.0, 5.0) == []


def test_split_text_proportional_no_punct():
    lines = pipeline._split_text_proportional("abcdef", 0.0, 6.0)
    assert len(lines) == 1
    assert lines[0]["text"] == "abcdef"


# ============== transcribe_video 主流程（mock 全链） ==============

@pytest.mark.asyncio
async def test_transcribe_video_end_to_end(monkeypatch):
    tmp = Path(tempfile.mkdtemp(prefix="upwatch_test_"))
    try:
        fake_mp3 = tmp / "BV1fake.mp3"
        fake_mp3.write_bytes(b"x")
        monkeypatch.setattr(audio_fetcher, "download_bilibili_audio", lambda *a, **kw: fake_mp3)

        proc_results = iter([
            MagicMock(returncode=0, stdout="240.0\n"),
            MagicMock(returncode=0),
            MagicMock(returncode=0, stdout="120.0\n"),
            MagicMock(returncode=0, stdout="120.0\n"),
        ])
        monkeypatch.setattr("app.transcriber.pipeline.subprocess.run", lambda *a, **kw: next(proc_results))

        chunks = []
        for i in (1, 2):
            c = tmp / f"chunk_{i:03d}.wav"
            c.write_bytes(b"x")
            chunks.append(c)
        monkeypatch.setattr(pipeline, "split_wav", lambda *a, **kw: chunks)

        fake_model = MagicMock()
        fake_model.transcribe.side_effect = [
            [MagicMock(text="第一句。第二句！", language="zh")],
            [MagicMock(text="第三句。", language="zh")],
        ]
        monkeypatch.setattr(asr_mod, "load_model", lambda *a, **kw: fake_model)
        monkeypatch.setattr(asr_mod, "is_available", lambda *a, **kw: True)

        from app.config import Settings
        monkeypatch.setattr(pipeline, "get_settings", lambda: Settings(qwen_asr_model_path="/fake", qwen_asr_device="cpu"))

        lines = await pipeline.transcribe_video("BV1fake")
        assert len(lines) == 3
        assert lines[0]["text"] == "第一句。"
        assert lines[0]["start_sec"] == 0.0
        assert lines[1]["text"] == "第二句！"
        assert lines[2]["text"] == "第三句。"
        assert lines[2]["start_sec"] == 120.0
        assert fake_model.transcribe.call_count == 2
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.mark.asyncio
async def test_transcribe_video_no_asr(monkeypatch):
    monkeypatch.setattr(asr_mod, "is_available", lambda *a, **kw: False)
    from app.config import Settings
    monkeypatch.setattr(pipeline, "get_settings", lambda: Settings(qwen_asr_model_path="/x"))
    from app.errors import BizError
    with pytest.raises(BizError) as ei:
        await pipeline.transcribe_video("BV1x")
    assert ei.value.code == "ASR_NOT_AVAILABLE"


@pytest.mark.asyncio
async def test_transcribe_video_audio_unavailable(monkeypatch):
    """download_bilibili_audio 抛出 AudioUnavailableError 时，应转换为 AUDIO_UNAVAILABLE。"""
    def _fake_download(*a, **kw):
        raise audio_fetcher.AudioUnavailableError("没有可识别音轨")

    monkeypatch.setattr(audio_fetcher, "download_bilibili_audio", _fake_download)
    monkeypatch.setattr(asr_mod, "is_available", lambda *a, **kw: True)
    from app.config import Settings
    monkeypatch.setattr(pipeline, "get_settings", lambda: Settings(qwen_asr_model_path="/fake", qwen_asr_device="cpu"))

    from app.errors import BizError
    with pytest.raises(BizError) as ei:
        await pipeline.transcribe_video("BV1noaudio")
    assert ei.value.code == "AUDIO_UNAVAILABLE"


# ============== runner fallback ==============

@pytest.mark.asyncio
async def test_runner_subtitle_fetch_falls_back_to_whisper(db_session_factory, monkeypatch):
    """B站无字幕 → 自动级联 ASR，写入 Subtitle(source=whisper)。"""
    from app.tasks.runner import TaskRunner
    from app.bilibili import subtitle as bili_sub

    # 让 player/v2 返回空字幕，view 返回 cid
    async def _fake_info(bvid, client=None):
        return {"cid": 1, "stat": {"like": 10}}
    async def _fake_tracks(bvid, cid, client=None):
        return []
    monkeypatch.setattr(bili_sub, "get_video_info", _fake_info)
    monkeypatch.setattr(bili_sub, "get_player_subtitles", _fake_tracks)

    # pipeline 转写返回固定 lines
    fake_lines = [
        {"start_sec": 0.0, "end_sec": 60.0, "text": "你好"},
        {"start_sec": 60.0, "end_sec": 120.0, "text": "世界"},
    ]
    async def _fake_transcribe(bvid):
        return fake_lines
    monkeypatch.setattr("app.transcriber.pipeline.transcribe_video", _fake_transcribe)

    with db_session_factory() as db:
        up = Uploader(id="u1", user_id="default", bilibili_uid="1", name="A", unread_count=0, notify_enabled=True)
        db.add(up)
        v = Video(
            id="v_wh", user_id="default", bvid="BVwh01", uploader_id="u1",
            title="t", cover_url=None, duration_sec=180,
            published_at=datetime.now(timezone.utc),
            views=0, danmaku_count=0, likes=0, tags=[],
            status="new", has_subtitle=False, has_summary=False, is_read=False,
        )
        db.add(v)
        t = Task(
            task_id=uuid.uuid4().hex[:12], type="subtitle_fetch", status="pending",
            progress=0, ref_type="video", ref_id="v_wh",
            created_at=datetime.now(timezone.utc),
        )
        db.add(t)
        db.commit()

    runner = TaskRunner()
    processed = await runner.tick()
    assert processed is not None

    with db_session_factory() as db:
        t2 = db.query(Task).filter_by(task_id=processed).one()
        assert t2.status == "success"
        sub = db.query(Subtitle).filter_by(video_id="v_wh").one()
        assert sub.source == "whisper"
        assert len(sub.lines) == 2
        v2 = db.query(Video).filter_by(id="v_wh").one()
        assert v2.has_subtitle is True
        assert v2.status == "subtitled"


@pytest.mark.asyncio
async def test_runner_subtitle_fetch_mismatch_falls_back_to_whisper(db_session_factory, monkeypatch):
    """B站字幕时长与视频不符 → 自动级联 ASR，写入 Subtitle(source=whisper)。"""
    from app.tasks.runner import TaskRunner
    from app.collect import fetch_subtitle as collect_subtitle
    from app.errors import BizError

    async def _bad_fetch(db, v):
        raise BizError(
            "SUBTITLE_DURATION_MISMATCH",
            "字幕时长不匹配",
            details={"subtitle_span_sec": 5.0, "video_duration_sec": 60.0},
            http_status=422,
        )

    monkeypatch.setattr(collect_subtitle, "fetch_video_subtitle", _bad_fetch)

    fake_lines = [
        {"start_sec": 0.0, "end_sec": 30.0, "text": "你好"},
        {"start_sec": 30.0, "end_sec": 60.0, "text": "世界"},
    ]

    async def _fake_transcribe(bvid):
        return fake_lines

    monkeypatch.setattr("app.transcriber.pipeline.transcribe_video", _fake_transcribe)

    with db_session_factory() as db:
        up = Uploader(id="u1", user_id="default", bilibili_uid="1", name="A", unread_count=0, notify_enabled=True)
        db.add(up)
        v = Video(
            id="v_wh_mismatch", user_id="default", bvid="BVwh02", uploader_id="u1",
            title="t", cover_url=None, duration_sec=60,
            published_at=datetime.now(timezone.utc),
            views=0, danmaku_count=0, likes=0, tags=[],
            status="new", has_subtitle=False, has_summary=False, is_read=False,
        )
        db.add(v)
        t = Task(
            task_id=uuid.uuid4().hex[:12], type="subtitle_fetch", status="pending",
            progress=0, ref_type="video", ref_id="v_wh_mismatch",
            created_at=datetime.now(timezone.utc),
        )
        db.add(t)
        db.commit()

    runner = TaskRunner()
    processed = await runner.tick()
    assert processed is not None

    with db_session_factory() as db:
        t2 = db.query(Task).filter_by(task_id=processed).one()
        assert t2.status == "success"
        sub = db.query(Subtitle).filter_by(video_id="v_wh_mismatch").one()
        assert sub.source == "whisper"
        assert len(sub.lines) == 2
        v2 = db.query(Video).filter_by(id="v_wh_mismatch").one()
        assert v2.has_subtitle is True
        assert v2.status == "subtitled"


@pytest.mark.asyncio
async def test_runner_subtitle_fetch_audio_unavailable_marks_complete(db_session_factory, monkeypatch):
    """B站无字幕 → ASR fallback → 音频不可用时直接标记完成，不重复任务。"""
    from app.tasks.runner import TaskRunner
    from app.bilibili import subtitle as bili_sub
    from app.errors import BizError

    async def _fake_info(bvid, client=None):
        return {"cid": 1, "stat": {"like": 10}}

    async def _fake_tracks(bvid, cid, client=None):
        return []

    monkeypatch.setattr(bili_sub, "get_video_info", _fake_info)
    monkeypatch.setattr(bili_sub, "get_player_subtitles", _fake_tracks)

    async def _fake_transcribe_unavailable(bvid):
        raise BizError("AUDIO_UNAVAILABLE", "没有可识别音轨", http_status=422)

    monkeypatch.setattr("app.transcriber.pipeline.transcribe_video", _fake_transcribe_unavailable)

    with db_session_factory() as db:
        up = Uploader(id="u1", user_id="default", bilibili_uid="1", name="A", unread_count=0, notify_enabled=True)
        db.add(up)
        v = Video(
            id="v_wh_no_audio", user_id="default", bvid="BVwhNoAudio", uploader_id="u1",
            title="t", cover_url=None, duration_sec=180,
            published_at=datetime.now(timezone.utc),
            views=0, danmaku_count=0, likes=0, tags=[],
            status="new", has_subtitle=False, has_summary=False, is_read=False,
        )
        db.add(v)
        t = Task(
            task_id=uuid.uuid4().hex[:12], type="subtitle_fetch", status="pending",
            progress=0, ref_type="video", ref_id="v_wh_no_audio",
            created_at=datetime.now(timezone.utc),
        )
        db.add(t)
        db.commit()

    runner = TaskRunner()
    processed = await runner.tick()
    assert processed is not None

    with db_session_factory() as db:
        t2 = db.query(Task).filter_by(task_id=processed).one()
        assert t2.status == "success"
        # 音频不可用时不应创建 Subtitle 记录
        assert db.query(Subtitle).filter_by(video_id="v_wh_no_audio").first() is None
        v2 = db.query(Video).filter_by(id="v_wh_no_audio").one()
        assert v2.has_subtitle is True
        assert v2.status == "subtitled"