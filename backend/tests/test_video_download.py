"""视频下载：sanitize_filename + download_bilibili_video format 选择器 + 端点契约。

yt-dlp 集成通过 monkeypatch 注入 fake，避免真实网络请求；
端点测试只覆盖 404 与鉴权短路分支，真实下载走 e2e 手动验证。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.api.videos import _parse_cookie_pairs, sanitize_filename
from app.models import Uploader, Video
from app.transcriber import audio_fetcher


# ---------- sanitize_filename ----------

@pytest.mark.parametrize(
    "title,fallback,expected",
    [
        # 普通标题
        ("正常的视频标题", "BV_FALLBACK", "正常的视频标题"),
        # Windows 非法字符替换
        ('a/b\\c:d*e?f"g<h>i|j', "BV_FALLBACK", "a_b_c_d_e_f_g_h_i_j"),
        # 控制字符删除
        ("line1\nline2\tline3\x00line4", "BV_FALLBACK", "line1line2line3line4"),
        # emoji 保留
        ("测试 🚀 视频", "BV_FALLBACK", "测试 🚀 视频"),
        # 纯特殊字符 → fallback
        ('/\\:*?"<>|', "BV_FALLBACK", "BV_FALLBACK"),
        # 空字符串 → fallback
        ("", "BV_FALLBACK", "BV_FALLBACK"),
        # 纯空白 → fallback
        ("   \t\n  ", "BV_FALLBACK", "BV_FALLBACK"),
        # 末尾 . / 空格 / _ 去除
        ("title.  _ ", "BV_FALLBACK", "title"),
        # 长度超限截断（默认 150）
        ("a" * 200, "BV_FALLBACK", "a" * 150),
        # 截断后末尾的点/空格/_ 再清理
        ("a" * 148 + "...", "BV_FALLBACK", "a" * 148),
        # 含前后缀 ._ 但内部有合法字符时，保留内部
        (".hidden.", "BV_FALLBACK", "hidden"),
        # None 输入 → fallback
        (None, "BV_FALLBACK", "BV_FALLBACK"),
    ],
)
def test_sanitize_filename(title, fallback, expected):
    assert sanitize_filename(title, fallback) == expected


def test_sanitize_filename_respects_custom_max_length():
    assert sanitize_filename("a" * 50, "F", max_length=10) == "a" * 10


# ---------- download_bilibili_video 形式契约 ----------


def _make_fake_ydl(captured: dict):
    class _FakeYDL:
        def __init__(self, opts):
            captured["opts"] = opts

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=True):
            # fake 不展开 outtmpl 模板；直接把 .webm 写到模板旁，路径避开 %(ext)s
            tmpl = Path(captured["opts"]["outtmpl"])
            target = tmpl.with_suffix(".webm")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"\x00")
            return {
                "requested_downloads": [{"filepath": str(target)}],
                "id": "BV_FAKE",
                "ext": "webm",
            }

    return _FakeYDL


def test_download_bilibili_video_uses_webm_format(tmp_path, monkeypatch):
    """format 选择器必须包含 webm 优先分支与 height<=720 约束。"""
    captured: dict = {}

    fake_dir = tmp_path / "out"
    fake_dir.mkdir()
    import tempfile
    import sys
    monkeypatch.setattr(tempfile, "mkdtemp", lambda prefix="": str(fake_dir))
    # yt_dlp 在函数内延迟 import，需要 patch sys.modules 让 import yt_dlp 拿到 fake
    monkeypatch.setitem(sys.modules, "yt_dlp", type("_M", (), {"YoutubeDL": _make_fake_ydl(captured)}))

    result = audio_fetcher.download_bilibili_video(
        "BV_TEST", tmp_path, max_height=720,
    )
    assert result.suffix == ".webm"  # fake 写的是 webm
    fmt = captured["opts"]["format"]
    assert "webm" in fmt  # webm 必须保留为优先分支
    assert "height<=720" in fmt
    # 不再强制 merge_output_format=webm（B 站绝大多数视频是 mp4 容器）


def test_download_bilibili_video_default_height_is_720(monkeypatch, tmp_path):
    """默认 max_height=720 写死在调用处，端点不传时仍走 ≤720。"""
    captured: dict = {}

    fake_dir = tmp_path / "out"
    fake_dir.mkdir()
    import tempfile
    import sys
    monkeypatch.setattr(tempfile, "mkdtemp", lambda prefix="": str(fake_dir))
    monkeypatch.setitem(sys.modules, "yt_dlp", type("_M", (), {"YoutubeDL": _make_fake_ydl(captured)}))

    audio_fetcher.download_bilibili_video("BV1", tmp_path)
    assert "height<=720" in captured["opts"]["format"]


def test_download_bilibili_video_custom_height(monkeypatch, tmp_path):
    """max_height 可覆盖。"""
    captured: dict = {}

    fake_dir = tmp_path / "out"
    fake_dir.mkdir()
    import tempfile
    import sys
    monkeypatch.setattr(tempfile, "mkdtemp", lambda prefix="": str(fake_dir))
    monkeypatch.setitem(sys.modules, "yt_dlp", type("_M", (), {"YoutubeDL": _make_fake_ydl(captured)}))

    audio_fetcher.download_bilibili_video("BV1", tmp_path, max_height=480)
    assert "height<=480" in captured["opts"]["format"]


def test_download_bilibili_video_format_falls_back_to_mp4(monkeypatch, tmp_path):
    """format 选择器必须能降级到任意 ≤max_height 容器（不仅 webm）。

    B 站绝大多数视频不提供 webm 流；只有 webm 分支会让大量视频下不下来。
    """
    captured: dict = {}

    fake_dir = tmp_path / "out"
    fake_dir.mkdir()
    import tempfile
    import sys
    monkeypatch.setattr(tempfile, "mkdtemp", lambda prefix="": str(fake_dir))
    monkeypatch.setitem(sys.modules, "yt_dlp", type("_M", (), {"YoutubeDL": _make_fake_ydl(captured)}))

    audio_fetcher.download_bilibili_video("BV1", tmp_path, max_height=720)
    fmt = captured["opts"]["format"]
    # 必须包含 webm 优先分支 + 通用兜底分支
    assert "webm" in fmt
    assert "height<=720" in fmt
    # 不应再强制 merge_output_format=webm（会让 MP4 视频强制走 ffmpeg 转码）
    assert "merge_output_format" not in captured["opts"]


def test_download_bilibili_video_prefers_hevc(monkeypatch, tmp_path):
    """format 选择器必须把 H.265 (HEVC) 放在最优先（B 站同画质小 30-50%）。"""
    captured: dict = {}

    fake_dir = tmp_path / "out"
    fake_dir.mkdir()
    import tempfile
    import sys
    monkeypatch.setattr(tempfile, "mkdtemp", lambda prefix="": str(fake_dir))
    monkeypatch.setitem(sys.modules, "yt_dlp", type("_M", (), {"YoutubeDL": _make_fake_ydl(captured)}))

    audio_fetcher.download_bilibili_video("BV1", tmp_path, max_height=720)
    fmt = captured["opts"]["format"]
    # B 站 HEVC 流 vcodec 形如 "hvc1.1.6.L120.90"，用 vcodec*=hv 或 ^hvc1 匹配
    assert "vcodec" in fmt, "format 选择器必须包含 vcodec 过滤"
    hevc_idx = fmt.find("vcodec")
    # HEVC 分支必须出现在 webm 分支之前
    webm_idx = fmt.find("webm")
    assert hevc_idx != -1
    if webm_idx != -1:
        assert hevc_idx < webm_idx, "HEVC 优先于 WebM"


def test_download_bilibili_video_sends_browser_like_headers(monkeypatch, tmp_path):
    """412 反爬修复：必须带 Origin/Referer/Accept-Language 与 Cookie header。

    SESSDATA 应同时通过 cookiefile + Cookie header 注入，避免 B站风控。
    """
    captured: dict = {}

    fake_dir = tmp_path / "out"
    fake_dir.mkdir()
    import tempfile
    import sys
    monkeypatch.setattr(tempfile, "mkdtemp", lambda prefix="": str(fake_dir))
    monkeypatch.setitem(sys.modules, "yt_dlp", type("_M", (), {"YoutubeDL": _make_fake_ydl(captured)}))

    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text("placeholder")

    audio_fetcher.download_bilibili_video(
        "BV1",
        tmp_path,
        cookiefile=str(cookie_file),
        user_agent="UA-TEST",
        sessdata="abc123",
    )

    opts = captured["opts"]
    assert opts["cookiefile"] == str(cookie_file)
    headers = opts["http_headers"]
    assert headers["User-Agent"] == "UA-TEST"
    assert headers["Referer"] == "https://www.bilibili.com/"
    assert headers["Origin"] == "https://www.bilibili.com"
    assert headers["Accept-Language"] == "zh-CN,zh;q=0.9,en;q=0.8"
    assert headers["Cookie"] == "SESSDATA=abc123"


def test_download_bilibili_video_omits_cookie_when_no_sessdata(monkeypatch, tmp_path):
    """未传 sessdata 时，headers 中不能有 Cookie 键（避免空值污染）。"""
    captured: dict = {}

    fake_dir = tmp_path / "out"
    fake_dir.mkdir()
    import tempfile
    import sys
    monkeypatch.setattr(tempfile, "mkdtemp", lambda prefix="": str(fake_dir))
    monkeypatch.setitem(sys.modules, "yt_dlp", type("_M", (), {"YoutubeDL": _make_fake_ydl(captured)}))

    audio_fetcher.download_bilibili_video("BV1", tmp_path, user_agent="UA")
    headers = captured["opts"]["http_headers"]
    assert "Cookie" not in headers
    # 即使没 UA 也要有 Origin/Referer，避免部分 fetch 路径裸奔被风控
    assert headers["Referer"] == "https://www.bilibili.com/"
    assert headers["Origin"] == "https://www.bilibili.com"


def test_download_bilibili_audio_also_sends_sessdata_cookie(monkeypatch, tmp_path):
    """audio 函数同样要支持 Cookie header 注入（一致性）。"""
    captured: dict = {}

    fake_dir = tmp_path / "out"
    fake_dir.mkdir()
    import tempfile
    import sys
    monkeypatch.setattr(tempfile, "mkdtemp", lambda prefix="": str(fake_dir))
    monkeypatch.setitem(sys.modules, "yt_dlp", type("_M", (), {"YoutubeDL": _make_fake_ydl(captured)}))

    audio_fetcher.download_bilibili_audio(
        "BV1",
        tmp_path,
        user_agent="UA",
        sessdata="xyz789",
    )
    headers = captured["opts"]["http_headers"]
    assert headers["Cookie"] == "SESSDATA=xyz789"
    assert headers["Origin"] == "https://www.bilibili.com"


def test_download_bilibili_video_propagates_missing_yt_dlp(monkeypatch, tmp_path):
    """若 yt-dlp 未安装，应抛 RuntimeError（与 audio 版本行为一致）。"""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **kw):
        if name == "yt_dlp":
            raise ImportError("yt_dlp not installed")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RuntimeError, match="yt-dlp 未安装"):
        audio_fetcher.download_bilibili_video("BV1", tmp_path)


# ---------- 端点契约（仅验证短路分支，避免真实网络） ----------


def test_download_video_endpoint_404_on_missing_video(client):
    """不存在的 video_id 必须返回 404 VIDEO_NOT_FOUND，不触发 yt-dlp。"""
    r = client.get("/api/v1/videos/nonexistent_id/video/download")
    assert r.status_code == 404
    body = r.json()
    # BizError 序列化形如 {"error": {"code": ..., "message": ...}}
    assert body["error"]["code"] == "VIDEO_NOT_FOUND"


def test_download_video_endpoint_404_on_other_user_video(client, db_session_factory):
    """属于其他 user_id 的视频也必须 404（防止越权枚举）。"""
    with db_session_factory() as db:
        up = Uploader(
            id="u1", user_id="default", bilibili_uid="1", name="A",
            unread_count=0, notify_enabled=True,
        )
        db.add(up)
        v = Video(
            id=uuid.uuid4().hex[:12],
            user_id="OTHER_USER",  # 非 default
            bvid="BVxOtherUser",
            uploader_id="u1",
            title="secret",
            cover_url=None,
            duration_sec=60,
            published_at=datetime.now(timezone.utc),
            views=0, danmaku_count=0, likes=0, tags=[],
            status="new", has_subtitle=False, has_summary=False, is_read=False,
        )
        db.add(v)
        db.commit()
        target_id = v.id

    r = client.get(f"/api/v1/videos/{target_id}/video/download")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "VIDEO_NOT_FOUND"


def test_download_video_endpoint_does_not_call_ytdlp_on_404(client, monkeypatch):
    """404 短路不应触发 yt-dlp（性能与日志清洁）。"""
    import sys
    import app.api.videos as videos_api
    called = {"n": 0}

    def _boom(*a, **kw):
        called["n"] += 1
        raise AssertionError("yt-dlp should not be invoked on 404")

    fake = type("_F", (), {"download_bilibili_video": staticmethod(_boom)})
    monkeypatch.setitem(sys.modules, "yt_dlp", fake)
    monkeypatch.setattr(videos_api, "download_bilibili_video", _boom)

    r = client.get("/api/v1/videos/nonexistent_id/video/download")
    assert r.status_code == 404
    assert called["n"] == 0


def test_download_video_endpoint_requires_sessdata(client, db_session_factory, monkeypatch):
    """成功分支必须能正常调用 get_settings()，不应被 SESSDATA 失败分支里的
    局部 import 遮蔽成 UnboundLocalError。

    不实际跑 yt-dlp（会触发真实网络）；拦截 download_bilibili_video 让其
    返回一个伪 webm 文件，验证端点能走到 settings = get_settings() 之后。
    """
    import uuid
    import tempfile
    from datetime import datetime, timezone
    from app.models import Uploader, Video

    # 强制让 _current_sessdata() 返回非空
    from app.config import set_bilibili_sessdata
    monkeypatch.setattr(
        "app.api.videos._current_sessdata", lambda: "fake-sess"
    )

    # monkey-patch download_bilibili_video 避免真实网络
    import app.api.videos as videos_api
    fake_webm = Path(tempfile.mkdtemp()) / "fake.webm"
    fake_webm.write_bytes(b"\x00")
    monkeypatch.setattr(
        videos_api, "download_bilibili_video",
        lambda bvid, out_dir, **kw: fake_webm,
    )

    with db_session_factory() as db:
        up = Uploader(
            id="u_ok", user_id="default", bilibili_uid="1", name="OK",
            unread_count=0, notify_enabled=True,
        )
        db.add(up)
        v = Video(
            id=uuid.uuid4().hex[:12], user_id="default",
            bvid="BV_OK", uploader_id="u_ok", title="好的标题",
            cover_url=None, duration_sec=60,
            published_at=datetime.now(timezone.utc),
            views=0, danmaku_count=0, likes=0, tags=[],
            status="new", has_subtitle=False, has_summary=False, is_read=False,
        )
        db.add(v)
        db.commit()
        target_id = v.id

    r = client.get(f"/api/v1/videos/{target_id}/video/download")
    assert r.status_code == 200, r.text
    # 文件名应来自标题，扩展名跟 fake 文件一致
    cd = r.headers.get("Content-Disposition", "")
    assert "好的标题" in cd
    assert ".webm" in cd
    assert r.headers["Content-Type"].startswith("video/webm")


def test_download_video_endpoint_requires_sessdata(client, db_session_factory, monkeypatch):
    """未配置 SESSDATA 时必须返回 400 SESSDATA_REQUIRED，不触发 yt-dlp。

    B 站风控对 datacenter IP + 匿名请求一律 412，与其让 yt-dlp 走完整流程
    再撞墙，不如在端点入口直接拒绝并给出明确指引。
    """
    import app.api.videos as videos_api
    called = {"n": 0}

    def _boom(*a, **kw):
        called["n"] += 1
        raise AssertionError("yt-dlp should not be invoked when SESSDATA missing")

    monkeypatch.setattr(videos_api, "download_bilibili_video", _boom)
    monkeypatch.setattr(
        "app.config.get_bilibili_sessdata", lambda: ""
    )
    monkeypatch.setattr(
        "app.config.get_bilibili_cookie", lambda: ""
    )

    import uuid
    from datetime import datetime, timezone
    from app.models import Uploader, Video
    with db_session_factory() as db:
        up = Uploader(
            id="u_sess", user_id="default", bilibili_uid="1", name="X",
            unread_count=0, notify_enabled=True,
        )
        db.add(up)
        v = Video(
            id=uuid.uuid4().hex[:12], user_id="default",
            bvid="BV_NEED_SESS", uploader_id="u_sess", title="需要登录",
            cover_url=None, duration_sec=60,
            published_at=datetime.now(timezone.utc),
            views=0, danmaku_count=0, likes=0, tags=[],
            status="new", has_subtitle=False, has_summary=False, is_read=False,
        )
        db.add(v)
        db.commit()
        target_id = v.id

    r = client.get(f"/api/v1/videos/{target_id}/video/download")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "SESSDATA_REQUIRED"
    assert called["n"] == 0


# ---------- 完整 Cookie 注入（412 风控修复） ----------


def test_parse_cookie_pairs_basic():
    """标准 ; 分隔格式逐字段解析。"""
    pairs = _parse_cookie_pairs("SESSDATA=abc; bili_jct=xyz; DedeUserID=42")
    assert pairs == [("SESSDATA", "abc"), ("bili_jct", "xyz"), ("DedeUserID", "42")]


def test_parse_cookie_pairs_strips_devtools_artifacts():
    """DevTools 复制常带的 'cookie:' 前缀 / 引号 / 换行都容忍。"""
    pairs = _parse_cookie_pairs(
        "Cookie: SESSDATA=\"abc\";\n  bili_jct= 'xyz' ;\nDedeUserID=42"
    )
    # 引号/前缀/换行被剥掉，key 保留大小写
    assert ("SESSDATA", "abc") in pairs
    assert ("bili_jct", "xyz") in pairs
    assert ("DedeUserID", "42") in pairs


def test_parse_cookie_pairs_drops_empty_values():
    """name= 或空 value 都丢弃，避免污染 cookie 文件。"""
    pairs = _parse_cookie_pairs("SESSDATA=abc; empty=; =novalue; bili_jct=ok")
    assert pairs == [("SESSDATA", "abc"), ("bili_jct", "ok")]


def test_parse_cookie_pairs_handles_none_and_empty():
    """None / 空字符串应返回空列表，不抛异常。"""
    assert _parse_cookie_pairs(None) == []
    assert _parse_cookie_pairs("") == []


def test_download_bilibili_video_sends_full_cookie_header(monkeypatch, tmp_path):
    """传入完整 cookie 字符串时，Cookie header 必须是完整串（而非仅 SESSDATA）。"""
    captured: dict = {}

    fake_dir = tmp_path / "out"
    fake_dir.mkdir()
    import tempfile
    import sys
    monkeypatch.setattr(tempfile, "mkdtemp", lambda prefix="": str(fake_dir))
    monkeypatch.setitem(sys.modules, "yt_dlp", type("_M", (), {"YoutubeDL": _make_fake_ydl(captured)}))

    full = "SESSDATA=abc123; bili_jct=jct456; DedeUserID=42; buvid3=xyz"
    audio_fetcher.download_bilibili_video(
        "BV1", tmp_path, user_agent="UA", sessdata="abc123", cookie=full,
    )
    headers = captured["opts"]["http_headers"]
    # 完整 cookie 串应原样塞入 Cookie header
    assert headers["Cookie"] == full
    # 不应再被改写成 "SESSDATA=xxx"
    assert "bili_jct" in headers["Cookie"]
    assert "DedeUserID" in headers["Cookie"]


def test_download_bilibili_video_cookie_takes_precedence_over_sessdata(monkeypatch, tmp_path):
    """同时传入 cookie 和 sessdata 时，cookie 胜出（多字段更安全）。"""
    captured: dict = {}

    fake_dir = tmp_path / "out"
    fake_dir.mkdir()
    import tempfile
    import sys
    monkeypatch.setattr(tempfile, "mkdtemp", lambda prefix="": str(fake_dir))
    monkeypatch.setitem(sys.modules, "yt_dlp", type("_M", (), {"YoutubeDL": _make_fake_ydl(captured)}))

    audio_fetcher.download_bilibili_video(
        "BV1", tmp_path,
        sessdata="only-this",
        cookie="SESSDATA=full; bili_jct=jct",
    )
    assert captured["opts"]["http_headers"]["Cookie"] == "SESSDATA=full; bili_jct=jct"


def test_prepare_bilibili_cookiefile_writes_full_cookie_multi_line(tmp_path):
    """完整 cookie 字符串必须写入多行 Netscape 格式（每条 cookie 一行）。"""
    from app.api.videos import _prepare_bilibili_cookiefile

    full = "SESSDATA=abc123; bili_jct=jct456; DedeUserID=42"
    cookie_file = _prepare_bilibili_cookiefile(tmp_path, cookie=full)
    assert cookie_file is not None
    content = cookie_file.read_text(encoding="utf-8")
    # 必须是 Netscape 头部
    assert content.startswith("# Netscape HTTP Cookie File")
    # 每条 cookie 一行（行尾 \n）
    lines = [l for l in content.splitlines() if l and not l.startswith("#")]
    assert len(lines) == 3
    # 关键字段都写入
    assert "SESSDATA\tabc123" in content
    assert "bili_jct\tjct456" in content
    assert "DedeUserID\t42" in content
    # 所有行都落到 .bilibili.com 域
    for line in lines:
        assert line.startswith(".bilibili.com")


def test_prepare_bilibili_cookiefile_returns_none_when_no_cookie(tmp_path):
    """cookie 与 sessdata 都为空时返回 None（保持匿名下载行为）。"""
    from app.api.videos import _prepare_bilibili_cookiefile

    # 两个全局来源都置空
    import app.config as cfg
    cfg._live_bilibili_cookie = ""
    cfg._live_bilibili_sessdata = ""
    assert _prepare_bilibili_cookiefile(tmp_path, cookie=None) is None
    assert _prepare_bilibili_cookiefile(tmp_path, cookie="") is None