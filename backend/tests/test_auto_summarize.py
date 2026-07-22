"""auto_summarize 开关触发测试。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import httpx
import pytest
import respx

from app.bilibili import wbi
from app.models import SystemConfig, Task, Uploader, Video
from app.tasks.runner import TaskRunner


def _nav_mock():
    return httpx.Response(200, json={
        "code": 0,
        "data": {
            "wbi_img": {
                "img_url": "https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077f.png",
                "sub_url": "https://i0.hdslb.com/bfs/wbi/4932caff0ff746eab6f01bf08b70ac45.png",
            }
        },
    })


@respx.mock
@pytest.mark.asyncio
async def test_auto_summarize_enqueues_summary_tasks(db_session_factory, reset_wbi_cache):
    respx.get("https://api.bilibili.com/x/web-interface/nav").mock(return_value=_nav_mock())

    now_ts = int(datetime.now(timezone.utc).timestamp())
    respx.get("https://api.bilibili.com/x/space/wbi/arc/search").mock(
        return_value=httpx.Response(200, json={
            "code": 0,
            "data": {"list": {"vlist": [
                {"bvid": "BV1auto001", "title": "auto", "pic": None,
                 "length": "03:00", "created": now_ts, "play": 7, "video_review": 0, "like": 0, "tag": []},
            ]}},
        })
    )

    with db_session_factory() as db:
        up = Uploader(id="up_auto", user_id="default", bilibili_uid="3", name="r", unread_count=0, notify_enabled=True)
        db.add(up)
        cfg = db.get(SystemConfig, 1)
        if cfg is None:
            cfg = SystemConfig(
                id=1,
                refresh_interval_sec=600,
                summary_model="qwen3-235b-a22b-instruct",
                summary_template_id="tpl_default",
                auto_summarize=False,
            )
            db.add(cfg)
        cfg.auto_summarize = True
        t = Task(
            task_id=uuid.uuid4().hex[:12],
            type="feed_refresh",
            status="pending",
            ref_type="uploader",
            ref_id=up.id,
            created_at=datetime.now(timezone.utc),
        )
        db.add(t)
        db.commit()

    runner = TaskRunner()
    processed = await runner.tick()
    assert processed is not None

    with db_session_factory() as db:
        tasks = db.query(Task).filter(Task.type == "ai_summary").all()
        assert len(tasks) == 1
        assert tasks[0].ref_id is not None
        video = db.get(Video, tasks[0].ref_id)
        assert video is not None
        assert video.bvid == "BV1auto001"
