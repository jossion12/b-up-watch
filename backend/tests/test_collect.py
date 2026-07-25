"""采集层测试：mock B站 nav + space/wbi/arc/search，跑 fetch_uploader_videos。"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest
import respx

from app.bilibili import wbi
from app.collect.fetch_uploader import fetch_uploader_videos
from app.models import Uploader, Video


def _now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp())


@respx.mock
@pytest.mark.asyncio
async def test_fetch_uploader_inserts_new_videos(db_session_factory, reset_wbi_cache):
    # 准备：mock nav 接口返回 wbi_img
    respx.get("https://api.bilibili.com/x/web-interface/nav").mock(
        return_value=httpx.Response(200, json={
            "code": 0,
            "data": {
                "wbi_img": {
                    "img_url": "https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077f.png",
                    "sub_url": "https://i0.hdslb.com/bfs/wbi/4932caff0ff746eab6f01bf08b70ac45.png",
                }
            },
        })
    )

    # mock 第一页：2 条新视频 + 1 条超老（应被 cutoff 跳过）
    old_ts = int((datetime.now(timezone.utc).timestamp())) - 40 * 86400
    page1 = {
        "code": 0,
        "data": {
            "list": {
                "vlist": [
                    {"bvid": "BV1new001", "title": "新视频1", "pic": "https://x/1.jpg",
                     "length": "10:23", "created": _now_ts(), "play": 100, "video_review": 5, "like": 10, "tag": ["AI"]},
                    {"bvid": "BV1new002", "title": "新视频2", "pic": "https://x/2.jpg",
                     "length": "05:00", "created": _now_ts() - 86400, "play": 50, "video_review": 1, "like": 2, "tag": []},
                    {"bvid": "BV1old001", "title": "老视频", "pic": "https://x/3.jpg",
                     "length": "01:00", "created": old_ts, "play": 1, "video_review": 0, "like": 0, "tag": []},
                ]
            }
        },
    }
    # 第二页：空（让循环终止）
    page2_empty = {"code": 0, "data": {"list": {"vlist": []}}}

    # 按 pn 参数分别 mock（respx 用 url+query 匹配）
    respx.get("https://api.bilibili.com/x/space/wbi/arc/search", params__contains={"pn": "1"}).mock(
        return_value=httpx.Response(200, json=page1)
    )
    respx.get("https://api.bilibili.com/x/space/wbi/arc/search", params__contains={"pn": "2"}).mock(
        return_value=httpx.Response(200, json=page2_empty)
    )

    # 准备：插入一个 UP主
    with db_session_factory() as db:
        up = Uploader(
            id="up_test1",
            user_id="default",
            bilibili_uid="946974",
            name="测试UP",
            unread_count=0,
            notify_enabled=True,
        )
        db.add(up)
        db.commit()
        db.refresh(up)

        new_count = await fetch_uploader_videos(db, up)
        assert new_count == 2

        db.refresh(up)
        assert up.unread_count == 2
        assert up.last_video_at is not None

        rows = db.query(Video).filter(Video.uploader_id == up.id).order_by(Video.published_at.desc()).all()
        assert len(rows) == 2
        bvids = {r.bvid for r in rows}
        assert bvids == {"BV1new001", "BV1new002"}
        assert all(r.status == "new" for r in rows)
        assert rows[0].tags == ["AI"]


@respx.mock
@pytest.mark.asyncio
async def test_fetch_uploader_dedup_existing(db_session_factory, reset_wbi_cache):
    respx.get("https://api.bilibili.com/x/web-interface/nav").mock(
        return_value=httpx.Response(200, json={
            "code": 0,
            "data": {
                "wbi_img": {
                    "img_url": "https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077f.png",
                    "sub_url": "https://i0.hdslb.com/bfs/wbi/4932caff0ff746eab6f01bf08b70ac45.png",
                }
            },
        })
    )

    respx.get("https://api.bilibili.com/x/space/wbi/arc/search").mock(
        return_value=httpx.Response(200, json={
            "code": 0,
            "data": {"list": {"vlist": [
                {"bvid": "BV1dup001", "title": "dup", "pic": None,
                 "length": "02:00", "created": _now_ts(), "play": 10, "video_review": 0, "like": 0, "tag": []},
            ]}},
        })
    )

    with db_session_factory() as db:
        up = Uploader(id="up_dup", user_id="default", bilibili_uid="1", name="dup", unread_count=0, notify_enabled=True)
        db.add(up)
        # 预先存在一条同 bvid 的视频
        from app.models import Video
        import uuid
        db.add(Video(
            id=uuid.uuid4().hex[:12], user_id="default", bvid="BV1dup001", uploader_id=up.id,
            title="旧", cover_url=None, duration_sec=120, published_at=datetime.now(timezone.utc),
            views=1, danmaku_count=0, likes=0, tags=[], status="new",
            has_subtitle=False, has_summary=False, is_read=False,
        ))
        db.commit()
        db.refresh(up)
        original_unread = up.unread_count
        original_videos = db.query(Video).count()

        new_count = await fetch_uploader_videos(db, up)
        assert new_count == 0
        db.refresh(up)
        assert up.unread_count == original_unread
        assert db.query(Video).count() == original_videos


@respx.mock
@pytest.mark.asyncio
async def test_fetch_uploader_rate_limited_propagates(db_session_factory, reset_wbi_cache):
    respx.get("https://api.bilibili.com/x/web-interface/nav").mock(
        return_value=httpx.Response(200, json={
            "code": 0,
            "data": {
                "wbi_img": {
                    "img_url": "https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077f.png",
                    "sub_url": "https://i0.hdslb.com/bfs/wbi/4932caff0ff746eab6f01bf08b70ac45.png",
                }
            },
        })
    )
    respx.get("https://api.bilibili.com/x/space/wbi/arc/search").mock(
        return_value=httpx.Response(200, json={"code": -412, "message": "风控触发"})
    )

    from app.errors import BizError

    with db_session_factory() as db:
        up = Uploader(id="up_rl", user_id="default", bilibili_uid="2", name="rl", unread_count=0, notify_enabled=True)
        db.add(up)
        db.commit()
        db.refresh(up)

        with pytest.raises(BizError) as ei:
            await fetch_uploader_videos(db, up)
        assert ei.value.code == "BILIBILI_RATE_LIMITED"


@respx.mock
@pytest.mark.asyncio
async def test_runner_tick_processes_feed_refresh(db_session_factory, reset_wbi_cache):
    """端到端：POST /uploaders → enqueue → runner.tick() → task=success + 视频入库。"""
    respx.get("https://api.bilibili.com/x/web-interface/nav").mock(
        return_value=httpx.Response(200, json={
            "code": 0,
            "data": {
                "wbi_img": {
                    "img_url": "https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077f.png",
                    "sub_url": "https://i0.hdslb.com/bfs/wbi/4932caff0ff746eab6f01bf08b70ac45.png",
                }
            },
        })
    )
    respx.get("https://api.bilibili.com/x/space/wbi/arc/search").mock(
        return_value=httpx.Response(200, json={
            "code": 0,
            "data": {"list": {"vlist": [
                {"bvid": "BV1run001", "title": "r1", "pic": None,
                 "length": "03:00", "created": _now_ts(), "play": 7, "video_review": 0, "like": 0, "tag": []},
            ]}},
        })
    )

    from app.models import Task
    from datetime import datetime, timezone
    from app.tasks.runner import TaskRunner
    import uuid

    with db_session_factory() as db:
        up = Uploader(id="up_run", user_id="default", bilibili_uid="3", name="r", unread_count=0, notify_enabled=True)
        db.add(up)
        t = Task(
            task_id=uuid.uuid4().hex[:12],
            type="feed_refresh", status="pending", progress=0,
            ref_type="uploader", ref_id=up.id,
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
        assert t2.finished_at is not None
        up2 = db.query(Uploader).filter_by(id="up_run").one()
        assert up2.unread_count == 1
        from app.models import Video
        assert db.query(Video).count() == 1


@respx.mock
@pytest.mark.asyncio
async def test_fetch_uploader_refreshes_profile(db_session_factory, reset_wbi_cache):
    """采集时调用用户名片接口回填真实昵称/头像/粉丝数/简介。"""
    respx.get("https://api.bilibili.com/x/web-interface/nav").mock(
        return_value=httpx.Response(200, json={
            "code": 0,
            "data": {
                "wbi_img": {
                    "img_url": "https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077f.png",
                    "sub_url": "https://i0.hdslb.com/bfs/wbi/4932caff0ff746eab6f01bf08b70ac45.png",
                }
            },
        })
    )
    respx.get("https://api.bilibili.com/x/web-interface/card").mock(
        return_value=httpx.Response(200, json={
            "code": 0,
            "data": {
                "card": {
                    "name": "真实昵称",
                    "face": "https://x/avatar.jpg",
                    "fans": 12345,
                    "sign": "这是简介",
                }
            },
        })
    )
    respx.get("https://api.bilibili.com/x/space/wbi/arc/search").mock(
        return_value=httpx.Response(200, json={
            "code": 0,
            "data": {"list": {"vlist": []}},
        })
    )

    with db_session_factory() as db:
        up = Uploader(
            id="up_profile",
            user_id="default",
            bilibili_uid="123456",
            name="UID:123456",
            unread_count=0,
            notify_enabled=True,
        )
        db.add(up)
        db.commit()
        db.refresh(up)

        new_count = await fetch_uploader_videos(db, up)
        assert new_count == 0

        db.refresh(up)
        assert up.name == "真实昵称"
        assert up.avatar_url == "https://x/avatar.jpg"
        assert up.fans_count == 12345
        assert up.description == "这是简介"


@respx.mock
@pytest.mark.asyncio
async def test_fetch_uploader_profile_fallback_from_videos(db_session_factory, reset_wbi_cache):
    """用户名片接口失败时，从投稿列表的作者字段回填昵称/头像。"""
    respx.get("https://api.bilibili.com/x/web-interface/nav").mock(
        return_value=httpx.Response(200, json={
            "code": 0,
            "data": {
                "wbi_img": {
                    "img_url": "https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077f.png",
                    "sub_url": "https://i0.hdslb.com/bfs/wbi/4932caff0ff746eab6f01bf08b70ac45.png",
                }
            },
        })
    )
    # 名片接口失败
    respx.get("https://api.bilibili.com/x/web-interface/card").mock(
        return_value=httpx.Response(200, json={"code": -404, "message": "账号未登录"})
    )
    respx.get("https://api.bilibili.com/x/space/wbi/arc/search").mock(
        return_value=httpx.Response(200, json={
            "code": 0,
            "data": {"list": {"vlist": [
                {"bvid": "BV1fb001", "title": "视频1", "pic": "https://x/1.jpg",
                 "length": "05:00", "created": _now_ts(), "play": 10, "video_review": 0, "like": 1,
                 "author": "真实昵称", "face": "https://x/avatar.jpg", "tag": []},
            ]}},
        })
    )

    with db_session_factory() as db:
        up = Uploader(
            id="up_fallback",
            user_id="default",
            bilibili_uid="123456",
            name="UID:123456",
            unread_count=0,
            notify_enabled=True,
        )
        db.add(up)
        db.commit()
        db.refresh(up)

        new_count = await fetch_uploader_videos(db, up)
        assert new_count == 1

        db.refresh(up)
        assert up.name == "真实昵称"
        assert up.avatar_url == "https://x/avatar.jpg"


@respx.mock
@pytest.mark.asyncio
async def test_fetch_uploader_does_not_crash_on_naive_last_video_at(
    db_session_factory, reset_wbi_cache
):
    """SQLite 读出的 last_video_at 可能丢失时区；与 aware 的 latest_pub 比较不应抛异常。"""
    respx.get("https://api.bilibili.com/x/web-interface/nav").mock(
        return_value=httpx.Response(200, json={
            "code": 0,
            "data": {
                "wbi_img": {
                    "img_url": "https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077f.png",
                    "sub_url": "https://i0.hdslb.com/bfs/wbi/4932caff0ff746eab6f01bf08b70ac45.png",
                }
            },
        })
    )
    respx.get("https://api.bilibili.com/x/web-interface/card").mock(
        return_value=httpx.Response(200, json={
            "code": 0,
            "data": {"card": {"name": "naive", "face": "", "fans": 0, "sign": ""}},
        })
    )
    respx.get("https://api.bilibili.com/x/space/wbi/arc/search").mock(
        return_value=httpx.Response(200, json={
            "code": 0,
            "data": {"list": {"vlist": [
                {"bvid": "BV1tz001", "title": "new", "pic": None,
                 "length": "04:00", "created": _now_ts(), "play": 9, "video_review": 0, "like": 0, "tag": []},
            ]}},
        })
    )

    with db_session_factory() as db:
        original = datetime(2026, 7, 1, 0, 0, 0)  # naive，模拟 SQLite 读出
        up = Uploader(
            id="up_naive",
            user_id="default",
            bilibili_uid="4",
            name="naive",
            unread_count=0,
            notify_enabled=True,
            last_video_at=original,
        )
        db.add(up)
        db.commit()
        db.refresh(up)

        new_count = await fetch_uploader_videos(db, up)
        assert new_count == 1

        db.refresh(up)
        assert up.last_video_at is not None
        assert up.last_video_at > original
        assert up.unread_count == 1


@pytest.mark.asyncio
async def test_runner_tick_no_pending_returns_none(db_session_factory):
    from app.tasks.runner import TaskRunner
    runner = TaskRunner()
    assert await runner.tick() is None