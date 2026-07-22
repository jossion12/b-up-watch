"""字幕模块测试：解析、获取流程、API 3.3.1/3.3.2/3.3.3。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import httpx
import pytest
import respx

from app.bilibili import subtitle as bili_sub
from app.collect.fetch_subtitle import fetch_video_subtitle
from app.models import Subtitle, Task, Uploader, Video


# ============== 纯函数 ==============

def test_pick_preferred_uploader_first():
    tracks = [
        {"id": 2, "ai_type": 1, "subtitle_url": "//a/ai.json", "lan": "zh-CN"},
        {"id": 1, "ai_type": 0, "subtitle_url": "//a/up.json", "lan": "zh-CN"},
    ]
    picked = bili_sub.pick_preferred_subtitle(tracks)
    assert picked["id"] == 1


def test_pick_preferred_fallback_to_ai():
    tracks = [{"id": 2, "ai_type": 1, "subtitle_url": "//a/ai.json", "lan": "zh-CN"}]
    picked = bili_sub.pick_preferred_subtitle(tracks)
    assert picked["id"] == 2


def test_pick_preferred_empty():
    assert bili_sub.pick_preferred_subtitle([]) is None


def test_pick_preferred_unknown_ai_type():
    """ai_type 缺失或非 0/1 时按列表顺序兜底取首条。"""
    tracks = [{"id": 9, "subtitle_url": "//x.json"}]
    picked = bili_sub.pick_preferred_subtitle(tracks)
    assert picked["id"] == 9


@respx.mock
@pytest.mark.asyncio
async def test_download_subtitle_json_converts():
    respx.get("https://aisubtitle.hdslb.com/x.json").mock(
        return_value=httpx.Response(200, json={
            "body": [
                {"from": 0.0, "to": 3.5, "content": "你好"},
                {"from": 3.5, "to": 7.0, "content": "世界"},
            ]
        })
    )
    lines = await bili_sub.download_subtitle_json("https://aisubtitle.hdslb.com/x.json")
    assert lines == [
        {"start_sec": 0.0, "end_sec": 3.5, "text": "你好"},
        {"start_sec": 3.5, "end_sec": 7.0, "text": "世界"},
    ]


@respx.mock
@pytest.mark.asyncio
async def test_download_subtitle_json_protocol_relative_url():
    """// 开头的 URL 应自动补 https: 前缀。"""
    respx.get("https://aisubtitle.hdslb.com/y.json").mock(
        return_value=httpx.Response(200, json={"body": [{"from": 1.0, "to": 2.0, "content": "ok"}]})
    )
    lines = await bili_sub.download_subtitle_json("//aisubtitle.hdslb.com/y.json")
    assert lines[0]["text"] == "ok"


# ============== 时长校验 ==============

def test_subtitle_span_seconds():
    from app.collect.fetch_subtitle import _subtitle_span_seconds

    lines = [
        {"start_sec": 5.0, "end_sec": 8.0, "text": "a"},
        {"start_sec": 10.0, "end_sec": 15.0, "text": "b"},
    ]
    assert _subtitle_span_seconds(lines) == 10.0


def test_subtitle_span_seconds_empty():
    from app.collect.fetch_subtitle import _subtitle_span_seconds

    assert _subtitle_span_seconds([]) == 0.0


def test_check_subtitle_duration_mismatch():
    from app.collect.fetch_subtitle import _check_subtitle_duration
    from app.errors import BizError

    lines = [{"start_sec": 0.0, "end_sec": 5.0, "text": "短字幕"}]
    with pytest.raises(BizError) as ei:
        _check_subtitle_duration(lines, video_duration_sec=60)
    assert ei.value.code == "SUBTITLE_DURATION_MISMATCH"
    assert "字幕时长" in ei.value.message


def test_check_subtitle_duration_ok():
    from app.collect.fetch_subtitle import _check_subtitle_duration

    # 60s 视频，58s 字幕：diff=2，ratio<15% 且 abs<10s，不应触发
    lines = [{"start_sec": 0.0, "end_sec": 58.0, "text": "正常字幕"}]
    _check_subtitle_duration(lines, video_duration_sec=60)


@pytest.mark.asyncio
async def test_fetch_video_subtitle_mismatch_not_persisted(db_session_factory, monkeypatch):
    from app.collect.fetch_subtitle import fetch_video_subtitle
    from app.bilibili import subtitle as bili_sub
    from app.errors import BizError

    async def _fake_info(bvid, client=None):
        return {"cid": 1, "stat": {"like": 10}}

    async def _fake_tracks(bvid, cid, client=None):
        return [{"id": 1, "lan": "zh-CN", "ai_type": 0, "subtitle_url": "//x/up.json"}]

    async def _fake_download(url):
        return [{"start_sec": 0.0, "end_sec": 3.0, "text": "对不上的字幕"}]

    monkeypatch.setattr(bili_sub, "get_video_info", _fake_info)
    monkeypatch.setattr(bili_sub, "get_player_subtitles", _fake_tracks)
    monkeypatch.setattr(bili_sub, "download_subtitle_json", _fake_download)

    with db_session_factory() as db:
        up = Uploader(id="u1", user_id="default", bilibili_uid="1", name="A", unread_count=0, notify_enabled=True)
        db.add(up)
        v = Video(
            id="v_mismatch", user_id="default", bvid="BV1mismatch", uploader_id="u1",
            title="t", cover_url=None, duration_sec=60,
            published_at=datetime.now(timezone.utc),
            views=0, danmaku_count=0, likes=0, tags=[],
            status="new", has_subtitle=False, has_summary=False, is_read=False,
        )
        db.add(v)
        db.commit()
        db.refresh(v)

        with pytest.raises(BizError) as ei:
            await fetch_video_subtitle(db, v)
        assert ei.value.code == "SUBTITLE_DURATION_MISMATCH"
        assert db.get(Subtitle, v.id) is None


# ============== 采集流程 ==============

@respx.mock
@pytest.mark.asyncio
async def test_fetch_video_subtitle_uploader_source(db_session_factory):
    respx.get("https://api.bilibili.com/x/web-interface/view").mock(
        return_value=httpx.Response(200, json={
            "code": 0,
            "data": {"cid": 12345, "stat": {"like": 799}},
        })
    )
    respx.get("https://api.bilibili.com/x/player/v2").mock(
        return_value=httpx.Response(200, json={
            "code": 0,
            "data": {"subtitle": {"subtitles": [
                {"id": 1, "lan": "zh-CN", "ai_type": 0, "subtitle_url": "//x/up.json"},
                {"id": 2, "lan": "zh-CN", "ai_type": 1, "subtitle_url": "//x/ai.json"},
            ]}},
        })
    )
    respx.get("https://x/up.json").mock(
        return_value=httpx.Response(200, json={
            "body": [{"from": 0.0, "to": 58.0, "content": "上传字幕测试"}]
        })
    )

    with db_session_factory() as db:
        up = Uploader(id="u1", user_id="default", bilibili_uid="1", name="A", unread_count=0, notify_enabled=True)
        db.add(up)
        v = Video(
            id="v1", user_id="default", bvid="BV1sub01", uploader_id="u1",
            title="t", cover_url=None, duration_sec=60,
            published_at=datetime.now(timezone.utc),
            views=0, danmaku_count=0, likes=0, tags=[],
            status="new", has_subtitle=False, has_summary=False, is_read=False,
        )
        db.add(v)
        db.commit()
        db.refresh(v)

        sub = await fetch_video_subtitle(db, v)
        assert sub.source == "uploader"
        assert sub.language == "zh-CN"
        assert len(sub.lines) == 1
        assert sub.lines[0]["text"] == "上传字幕测试"

        db.refresh(v)
        assert v.has_subtitle is True
        assert v.status == "subtitled"
        assert v.likes == 799  # 从 view 接口 stat.like 回填


@respx.mock
@pytest.mark.asyncio
async def test_fetch_video_subtitle_falls_back_to_ai(db_session_factory):
    respx.get("https://api.bilibili.com/x/web-interface/view").mock(
        return_value=httpx.Response(200, json={"code": 0, "data": {"cid": 99}})
    )
    respx.get("https://api.bilibili.com/x/player/v2").mock(
        return_value=httpx.Response(200, json={
            "code": 0,
            "data": {"subtitle": {"subtitles": [
                {"id": 3, "lan": "zh-CN", "ai_type": 1, "subtitle_url": "//x/ai.json"},
            ]}},
        })
    )
    respx.get("https://x/ai.json").mock(
        return_value=httpx.Response(200, json={
            "body": [{"from": 0.0, "to": 58.0, "content": "AI字幕"}]
        })
    )

    with db_session_factory() as db:
        up = Uploader(id="u1", user_id="default", bilibili_uid="1", name="A", unread_count=0, notify_enabled=True)
        db.add(up)
        v = Video(
            id="v2", user_id="default", bvid="BV1sub02", uploader_id="u1",
            title="t", cover_url=None, duration_sec=60,
            published_at=datetime.now(timezone.utc),
            views=0, danmaku_count=0, likes=0, tags=[],
            status="new", has_subtitle=False, has_summary=False, is_read=False,
        )
        db.add(v)
        db.commit()
        db.refresh(v)

        sub = await fetch_video_subtitle(db, v)
        assert sub.source == "bilibili_ai"


@respx.mock
@pytest.mark.asyncio
async def test_fetch_video_subtitle_no_tracks_returns_unavailable(db_session_factory):
    from app.errors import BizError

    respx.get("https://api.bilibili.com/x/web-interface/view").mock(
        return_value=httpx.Response(200, json={"code": 0, "data": {"cid": 99}})
    )
    respx.get("https://api.bilibili.com/x/player/v2").mock(
        return_value=httpx.Response(200, json={"code": 0, "data": {"subtitle": {"subtitles": []}}})
    )

    with db_session_factory() as db:
        up = Uploader(id="u1", user_id="default", bilibili_uid="1", name="A", unread_count=0, notify_enabled=True)
        db.add(up)
        v = Video(
            id="v3", user_id="default", bvid="BV1sub03", uploader_id="u1",
            title="t", cover_url=None, duration_sec=60,
            published_at=datetime.now(timezone.utc),
            views=0, danmaku_count=0, likes=0, tags=[],
            status="new", has_subtitle=False, has_summary=False, is_read=False,
        )
        db.add(v)
        db.commit()
        db.refresh(v)

        with pytest.raises(BizError) as ei:
            await fetch_video_subtitle(db, v)
        assert ei.value.code == "SUBTITLE_UNAVAILABLE"


@respx.mock
@pytest.mark.asyncio
async def test_runner_subtitle_fetch_end_to_end(db_session_factory):
    respx.get("https://api.bilibili.com/x/web-interface/view").mock(
        return_value=httpx.Response(200, json={"code": 0, "data": {"cid": 1}})
    )
    respx.get("https://api.bilibili.com/x/player/v2").mock(
        return_value=httpx.Response(200, json={
            "code": 0,
            "data": {"subtitle": {"subtitles": [
                {"id": 1, "lan": "zh-CN", "ai_type": 0, "subtitle_url": "//x/up.json"},
            ]}},
        })
    )
    respx.get("https://x/up.json").mock(
        return_value=httpx.Response(200, json={"body": [{"from": 0, "to": 58, "content": "ok"}]})
    )

    from app.tasks.runner import TaskRunner

    with db_session_factory() as db:
        up = Uploader(id="u1", user_id="default", bilibili_uid="1", name="A", unread_count=0, notify_enabled=True)
        db.add(up)
        v = Video(
            id="v_e2e", user_id="default", bvid="BV1e2e", uploader_id="u1",
            title="t", cover_url=None, duration_sec=60,
            published_at=datetime.now(timezone.utc),
            views=0, danmaku_count=0, likes=0, tags=[],
            status="new", has_subtitle=False, has_summary=False, is_read=False,
        )
        db.add(v)
        t = Task(
            task_id=uuid.uuid4().hex[:12], type="subtitle_fetch", status="pending",
            progress=0, ref_type="video", ref_id="v_e2e",
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
        assert db.query(Subtitle).count() == 1
        v2 = db.query(Video).filter_by(id="v_e2e").one()
        assert v2.has_subtitle is True
        assert v2.status == "subtitled"


@respx.mock
@pytest.mark.asyncio
async def test_runner_video_stats_refresh_end_to_end(db_session_factory):
    """video_stats_refresh 任务从 view 接口回填真实点赞数。"""
    respx.get("https://api.bilibili.com/x/web-interface/view").mock(
        return_value=httpx.Response(200, json={
            "code": 0,
            "data": {"cid": 123, "stat": {"like": 8848}},
        })
    )

    from app.tasks.runner import TaskRunner

    with db_session_factory() as db:
        up = Uploader(id="u1", user_id="default", bilibili_uid="1", name="A", unread_count=0, notify_enabled=True)
        db.add(up)
        v = Video(
            id="v_stats", user_id="default", bvid="BV1stats", uploader_id="u1",
            title="t", cover_url=None, duration_sec=60,
            published_at=datetime.now(timezone.utc),
            views=100, danmaku_count=5, likes=0, tags=[],
            status="new", has_subtitle=False, has_summary=False, is_read=False,
        )
        db.add(v)
        t = Task(
            task_id=uuid.uuid4().hex[:12], type="video_stats_refresh", status="pending",
            progress=0, ref_type="video", ref_id="v_stats",
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
        v2 = db.query(Video).filter_by(id="v_stats").one()
        assert v2.likes == 8848


# ============== API ==============

def _seed_video_with_subtitle(db, *, lines=None):
    up = Uploader(id="u1", user_id="default", bilibili_uid="1", name="A", unread_count=0, notify_enabled=True)
    db.add(up)
    v = Video(
        id="v_api", user_id="default", bvid="BVapi01", uploader_id="u1",
        title="t", cover_url=None, duration_sec=60,
        published_at=datetime.now(timezone.utc),
        views=0, danmaku_count=0, likes=0, tags=[],
        status="subtitled", has_subtitle=True, has_summary=False, is_read=False,
    )
    db.add(v)
    sub = Subtitle(
        video_id="v_api",
        language="zh-CN",
        source="uploader",
        lines=lines or [
            {"start_sec": 0.0, "end_sec": 3.5, "text": "第一句"},
            {"start_sec": 3.5, "end_sec": 7.25, "text": "第二句"},
        ],
        fetched_at=datetime.now(timezone.utc),
    )
    db.add(sub)
    db.commit()


def test_api_get_subtitle_success(client, db_session_factory):
    with db_session_factory() as db:
        _seed_video_with_subtitle(db)

    r = client.get("/api/v1/videos/v_api/subtitle")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["video_id"] == "v_api"
    assert body["source"] == "uploader"
    assert body["language"] == "zh-CN"
    assert len(body["lines"]) == 2


def test_api_get_subtitle_404_no_subtitle(client, db_session_factory):
    with db_session_factory() as db:
        up = Uploader(id="u1", user_id="default", bilibili_uid="1", name="A", unread_count=0, notify_enabled=True)
        db.add(up)
        v = Video(
            id="v_no", user_id="default", bvid="BVno", uploader_id="u1",
            title="t", cover_url=None, duration_sec=60,
            published_at=datetime.now(timezone.utc),
            views=0, danmaku_count=0, likes=0, tags=[],
            status="new", has_subtitle=False, has_summary=False, is_read=False,
        )
        db.add(v)
        db.commit()

    r = client.get("/api/v1/videos/v_no/subtitle")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "SUBTITLE_NOT_FOUND"


def test_api_get_subtitle_404_video_not_found(client):
    r = client.get("/api/v1/videos/nonexistent/subtitle")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "VIDEO_NOT_FOUND"


def test_api_fetch_subtitle_creates_task(client, db_session_factory):
    with db_session_factory() as db:
        up = Uploader(id="u1", user_id="default", bilibili_uid="1", name="A", unread_count=0, notify_enabled=True)
        db.add(up)
        v = Video(
            id="v_fetch", user_id="default", bvid="BVfetch", uploader_id="u1",
            title="t", cover_url=None, duration_sec=60,
            published_at=datetime.now(timezone.utc),
            views=0, danmaku_count=0, likes=0, tags=[],
            status="new", has_subtitle=False, has_summary=False, is_read=False,
        )
        db.add(v)
        db.commit()

    r = client.post("/api/v1/videos/v_fetch/subtitle/fetch")
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["type"] == "subtitle_fetch"
    assert body["task_id"]


def test_api_fetch_subtitle_409_conflict(client, db_session_factory):
    from datetime import datetime, timezone
    with db_session_factory() as db:
        up = Uploader(id="u1", user_id="default", bilibili_uid="1", name="A", unread_count=0, notify_enabled=True)
        db.add(up)
        v = Video(
            id="v_conf", user_id="default", bvid="BVconf", uploader_id="u1",
            title="t", cover_url=None, duration_sec=60,
            published_at=datetime.now(timezone.utc),
            views=0, danmaku_count=0, likes=0, tags=[],
            status="new", has_subtitle=False, has_summary=False, is_read=False,
        )
        db.add(v)
        t = Task(
            task_id=uuid.uuid4().hex[:12], type="subtitle_fetch", status="pending",
            progress=0, ref_type="video", ref_id="v_conf",
            created_at=datetime.now(timezone.utc),
        )
        db.add(t)
        db.commit()

    r = client.post("/api/v1/videos/v_conf/subtitle/fetch")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "TASK_CONFLICT"


def test_api_fetch_subtitle_404_video(client):
    r = client.post("/api/v1/videos/nonexistent/subtitle/fetch")
    assert r.status_code == 404


# ---------- 导出 ----------

def test_api_export_srt(client, db_session_factory):
    with db_session_factory() as db:
        _seed_video_with_subtitle(db, lines=[
            {"start_sec": 0.0, "end_sec": 3.5, "text": "第一句"},
            {"start_sec": 3.5, "end_sec": 7.25, "text": "第二句"},
        ])

    r = client.get("/api/v1/videos/v_api/subtitle/export?format=srt")
    assert r.status_code == 200
    assert "application/x-subrip" in r.headers["content-type"]
    assert 'attachment; filename="BVapi01.srt"' in r.headers["content-disposition"]
    body = r.text
    assert "1\n00:00:00,000 --> 00:00:03,500\n第一句" in body
    assert "2\n00:00:03,500 --> 00:00:07,250\n第二句" in body


def test_api_export_txt(client, db_session_factory):
    with db_session_factory() as db:
        _seed_video_with_subtitle(db, lines=[
            {"start_sec": 0, "end_sec": 1, "text": "甲"},
            {"start_sec": 1, "end_sec": 2, "text": "乙"},
        ])

    r = client.get("/api/v1/videos/v_api/subtitle/export?format=txt")
    assert r.status_code == 200
    assert r.text == "甲\n乙"
    assert 'filename="BVapi01.txt"' in r.headers["content-disposition"]


def test_api_export_json(client, db_session_factory):
    with db_session_factory() as db:
        _seed_video_with_subtitle(db)

    r = client.get("/api/v1/videos/v_api/subtitle/export?format=json")
    assert r.status_code == 200
    data = r.json()
    assert data["video_id"] == "v_api"
    assert data["source"] == "uploader"
    assert data["language"] == "zh-CN"
    assert len(data["lines"]) == 2


def test_api_export_invalid_format(client, db_session_factory):
    with db_session_factory() as db:
        _seed_video_with_subtitle(db)
    r = client.get("/api/v1/videos/v_api/subtitle/export?format=pdf")
    assert r.status_code == 400


def test_api_export_no_subtitle(client, db_session_factory):
    with db_session_factory() as db:
        up = Uploader(id="u1", user_id="default", bilibili_uid="1", name="A", unread_count=0, notify_enabled=True)
        db.add(up)
        v = Video(
            id="v_nosub", user_id="default", bvid="BVnosub", uploader_id="u1",
            title="t", cover_url=None, duration_sec=60,
            published_at=datetime.now(timezone.utc),
            views=0, danmaku_count=0, likes=0, tags=[],
            status="new", has_subtitle=False, has_summary=False, is_read=False,
        )
        db.add(v)
        db.commit()
    r = client.get("/api/v1/videos/v_nosub/subtitle/export?format=srt")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "SUBTITLE_NOT_FOUND"