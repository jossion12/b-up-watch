"""TaskRunner 测试。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.models import DEFAULT_USER_ID, Task, Uploader, Video
from app.tasks import registry
from app.tasks.runner import TaskRunner


def _make_uploader(db_session_factory, bilibili_uid: str = "10086") -> Uploader:
    with db_session_factory() as db:
        up = Uploader(
            id=uuid.uuid4().hex[:12],
            user_id=DEFAULT_USER_ID,
            bilibili_uid=bilibili_uid,
            name=f"UP:{bilibili_uid}",
            unread_count=0,
            notify_enabled=True,
        )
        db.add(up)
        db.commit()
        db.refresh(up)
        return up


def _make_video(db_session_factory, uploader: Uploader) -> Video:
    with db_session_factory() as db:
        up = db.merge(uploader)
        v = Video(
            id=uuid.uuid4().hex[:12],
            user_id=DEFAULT_USER_ID,
            bvid=f"BV{uuid.uuid4().hex[:8]}",
            uploader_id=up.id,
            title="test video",
            duration_sec=120,
            published_at=datetime.now(timezone.utc),
            has_subtitle=False,
            has_summary=False,
        )
        db.add(v)
        db.commit()
        db.refresh(v)
        return v


@pytest.mark.asyncio
async def test_runner_resets_stale_running_tasks_on_start(db_session_factory):
    up = _make_uploader(db_session_factory)
    v = _make_video(db_session_factory, up)

    stale_id = uuid.uuid4().hex[:12]
    with db_session_factory() as db:
        db.add(
            Task(
                task_id=stale_id,
                type="subtitle_fetch",
                status="running",
                progress=0,
                ref_type="video",
                ref_id=v.id,
                created_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

    runner = TaskRunner(session_factory=db_session_factory)
    await runner.start()
    await runner.stop()

    with db_session_factory() as db:
        task = db.get(Task, stale_id)
        assert task.status == "pending"
        assert task.error is None


@pytest.mark.asyncio
async def test_runner_leaves_other_tasks_untouched_on_start(db_session_factory):
    up = _make_uploader(db_session_factory)
    v = _make_video(db_session_factory, up)

    pending_id = uuid.uuid4().hex[:12]
    success_id = uuid.uuid4().hex[:12]
    with db_session_factory() as db:
        db.add(
            Task(
                task_id=pending_id,
                type="subtitle_fetch",
                status="pending",
                progress=0,
                ref_type="video",
                ref_id=v.id,
                created_at=datetime.now(timezone.utc),
            )
        )
        db.add(
            Task(
                task_id=success_id,
                type="ai_summary",
                status="success",
                progress=100,
                ref_type="video",
                ref_id=v.id,
                created_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

    runner = TaskRunner(session_factory=db_session_factory)
    await runner.start()
    await runner.stop()

    with db_session_factory() as db:
        assert db.get(Task, pending_id).status == "pending"
        assert db.get(Task, success_id).status == "success"


@pytest.mark.asyncio
async def test_runner_processes_high_priority_first(db_session_factory):
    up = _make_uploader(db_session_factory)
    v1 = _make_video(db_session_factory, up)
    v2 = _make_video(db_session_factory, up)

    # 普通任务先创建
    normal_id = uuid.uuid4().hex[:12]
    priority_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc)
    with db_session_factory() as db:
        db.add(
            Task(
                task_id=normal_id,
                type="subtitle_fetch",
                status="pending",
                progress=0,
                ref_type="video",
                ref_id=v1.id,
                priority=0,
                created_at=now,
            )
        )
        # 高优先级任务后创建
        db.add(
            Task(
                task_id=priority_id,
                type="subtitle_fetch",
                status="pending",
                progress=0,
                ref_type="video",
                ref_id=v2.id,
                priority=10,
                created_at=now,
            )
        )
        db.commit()

    runner = TaskRunner(session_factory=db_session_factory)
    dispatched = []

    async def _mock_dispatch(_db, task: Task) -> None:
        dispatched.append(task.task_id)

    original = registry._REGISTRY.get("subtitle_fetch")
    registry._REGISTRY["subtitle_fetch"] = _mock_dispatch
    try:
        processed = await runner.tick()
        assert processed == priority_id
        assert dispatched == [priority_id]
    finally:
        if original is not None:
            registry._REGISTRY["subtitle_fetch"] = original
        else:
            registry._REGISTRY.pop("subtitle_fetch", None)
