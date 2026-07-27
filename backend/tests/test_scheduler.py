"""任务调度器测试。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import DEFAULT_USER_ID, Task, Uploader, Video
from app.tasks.scheduler import TaskScheduler


def _make_uploader(db_session_factory, bilibili_uid: str = "10086", **kwargs) -> Uploader:
    with db_session_factory() as db:
        up = Uploader(
            id=uuid.uuid4().hex[:12],
            user_id=DEFAULT_USER_ID,
            bilibili_uid=bilibili_uid,
            name=f"UP:{bilibili_uid}",
            unread_count=0,
            notify_enabled=True,
            **kwargs,
        )
        db.add(up)
        db.commit()
        db.refresh(up)
        return up


def _make_video(db_session_factory, uploader: Uploader, *, has_subtitle=False, has_summary=False, days_ago: int = 0) -> Video:
    with db_session_factory() as db:
        # 重新 attach uploader 到当前 session
        up = db.merge(uploader)
        v = Video(
            id=uuid.uuid4().hex[:12],
            user_id=DEFAULT_USER_ID,
            bvid=f"BV{uuid.uuid4().hex[:8]}",
            uploader_id=up.id,
            title="test video",
            duration_sec=120,
            published_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
            has_subtitle=has_subtitle,
            has_summary=has_summary,
        )
        db.add(v)
        db.commit()
        db.refresh(v)
        return v


class _FakeRunner:
    def __init__(self):
        self.notified = 0

    def notify(self):
        self.notified += 1


@pytest.mark.asyncio
async def test_scheduler_enqueues_subtitle_tasks(db_session_factory):
    runner = _FakeRunner()
    scheduler = TaskScheduler(runner, session_factory=db_session_factory, batch_size=5)

    up = _make_uploader(db_session_factory)
    v1 = _make_video(db_session_factory, up, has_subtitle=False)
    v2 = _make_video(db_session_factory, up, has_subtitle=False)

    created = await scheduler._enqueue_subtitle_tasks()
    assert created == 2

    with db_session_factory() as db:
        tasks = db.execute(
            select(Task).where(Task.type == "subtitle_fetch").order_by(Task.created_at)
        ).scalars().all()
        assert len(tasks) == 2
        assert {t.ref_id for t in tasks} == {v1.id, v2.id}

    assert runner.notified == 0  # 由 loop 调用 notify，单个方法不通知


@pytest.mark.asyncio
async def test_scheduler_skips_videos_with_active_subtitle_task(db_session_factory):
    runner = _FakeRunner()
    scheduler = TaskScheduler(runner, session_factory=db_session_factory)

    up = _make_uploader(db_session_factory)
    v = _make_video(db_session_factory, up, has_subtitle=False)

    with db_session_factory() as db:
        db.add(
            Task(
                task_id=uuid.uuid4().hex[:12],
                type="subtitle_fetch",
                status="pending",
                ref_type="video",
                ref_id=v.id,
                created_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

    created = await scheduler._enqueue_subtitle_tasks()
    assert created == 0


@pytest.mark.asyncio
async def test_scheduler_skips_videos_with_recent_failed_subtitle_task(db_session_factory):
    runner = _FakeRunner()
    scheduler = TaskScheduler(
        runner,
        session_factory=db_session_factory,
        failed_task_backoff_sec=600,
    )

    up = _make_uploader(db_session_factory)
    v = _make_video(db_session_factory, up, has_subtitle=False)

    with db_session_factory() as db:
        db.add(
            Task(
                task_id=uuid.uuid4().hex[:12],
                type="subtitle_fetch",
                status="failed",
                ref_type="video",
                ref_id=v.id,
                finished_at=datetime.now(timezone.utc) - timedelta(seconds=30),
                created_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            )
        )
        db.commit()

    created = await scheduler._enqueue_subtitle_tasks()
    assert created == 0


@pytest.mark.asyncio
async def test_scheduler_enqueues_subtitle_after_failed_backoff(db_session_factory):
    runner = _FakeRunner()
    scheduler = TaskScheduler(
        runner,
        session_factory=db_session_factory,
        failed_task_backoff_sec=60,
    )

    up = _make_uploader(db_session_factory)
    v = _make_video(db_session_factory, up, has_subtitle=False)

    with db_session_factory() as db:
        db.add(
            Task(
                task_id=uuid.uuid4().hex[:12],
                type="subtitle_fetch",
                status="failed",
                ref_type="video",
                ref_id=v.id,
                finished_at=datetime.now(timezone.utc) - timedelta(seconds=120),
                created_at=datetime.now(timezone.utc) - timedelta(minutes=10),
            )
        )
        db.commit()

    created = await scheduler._enqueue_subtitle_tasks()
    assert created == 1


@pytest.mark.asyncio
async def test_scheduler_enqueues_summary_tasks_only_when_subtitle_ready(db_session_factory):
    runner = _FakeRunner()
    scheduler = TaskScheduler(runner, session_factory=db_session_factory)

    up = _make_uploader(db_session_factory)
    _make_video(db_session_factory, up, has_subtitle=False, has_summary=False)
    ready = _make_video(db_session_factory, up, has_subtitle=True, has_summary=False)

    created = await scheduler._enqueue_summary_tasks()
    assert created == 1

    with db_session_factory() as db:
        tasks = db.execute(select(Task).where(Task.type == "ai_summary")).scalars().all()
        assert len(tasks) == 1
        assert tasks[0].ref_id == ready.id


@pytest.mark.asyncio
async def test_scheduler_skips_videos_with_active_summary_task(db_session_factory):
    runner = _FakeRunner()
    scheduler = TaskScheduler(runner, session_factory=db_session_factory)

    up = _make_uploader(db_session_factory)
    v = _make_video(db_session_factory, up, has_subtitle=True, has_summary=False)

    with db_session_factory() as db:
        db.add(
            Task(
                task_id=uuid.uuid4().hex[:12],
                type="ai_summary",
                status="running",
                ref_type="video",
                ref_id=v.id,
                created_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

    created = await scheduler._enqueue_summary_tasks()
    assert created == 0


@pytest.mark.asyncio
async def test_scheduler_skips_videos_with_recent_failed_summary_task(db_session_factory):
    runner = _FakeRunner()
    scheduler = TaskScheduler(
        runner,
        session_factory=db_session_factory,
        failed_task_backoff_sec=600,
    )

    up = _make_uploader(db_session_factory)
    v = _make_video(db_session_factory, up, has_subtitle=True, has_summary=False)

    with db_session_factory() as db:
        db.add(
            Task(
                task_id=uuid.uuid4().hex[:12],
                type="ai_summary",
                status="failed",
                ref_type="video",
                ref_id=v.id,
                finished_at=datetime.now(timezone.utc) - timedelta(seconds=30),
                created_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            )
        )
        db.commit()

    created = await scheduler._enqueue_summary_tasks()
    assert created == 0


@pytest.mark.asyncio
async def test_backfill_does_nothing_when_pending_subtitle_work_exists(db_session_factory):
    runner = _FakeRunner()
    scheduler = TaskScheduler(runner, session_factory=db_session_factory)

    up = _make_uploader(db_session_factory)
    _make_video(db_session_factory, up, has_subtitle=False, has_summary=False)

    created = await scheduler._enqueue_backfill_task()
    assert created is False

    with db_session_factory() as db:
        assert db.execute(select(Task).where(Task.type == "feed_refresh")).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_backfill_does_nothing_when_pending_summary_work_exists(db_session_factory):
    runner = _FakeRunner()
    scheduler = TaskScheduler(runner, session_factory=db_session_factory)

    up = _make_uploader(db_session_factory)
    _make_video(db_session_factory, up, has_subtitle=True, has_summary=False)

    created = await scheduler._enqueue_backfill_task()
    assert created is False


@pytest.mark.asyncio
async def test_backfill_creates_feed_refresh_when_idle(db_session_factory):
    runner = _FakeRunner()
    scheduler = TaskScheduler(
        runner,
        session_factory=db_session_factory,
        backfill_extra_days=30,
        backfill_max_pages=10,
    )

    up = _make_uploader(db_session_factory)
    _make_video(db_session_factory, up, has_subtitle=True, has_summary=True, days_ago=60)
    _make_video(db_session_factory, up, has_subtitle=True, has_summary=True, days_ago=10)

    created = await scheduler._enqueue_backfill_task()
    assert created is True

    with db_session_factory() as db:
        task = db.execute(select(Task).where(Task.type == "feed_refresh")).scalar_one()
        assert task.ref_type == "uploader"
        assert task.ref_id == up.id
        assert task.meta is not None
        assert task.meta.get("mode") == "backfill"
        assert task.meta.get("max_pages") == 10
        days_back = task.meta.get("days_back")
        assert isinstance(days_back, int)
        assert days_back >= 90  # 60 + 30


@pytest.mark.asyncio
async def test_backfill_uses_default_days_when_uploader_has_no_videos(db_session_factory):
    runner = _FakeRunner()
    scheduler = TaskScheduler(runner, session_factory=db_session_factory)

    _make_uploader(db_session_factory)

    created = await scheduler._enqueue_backfill_task()
    assert created is True

    with db_session_factory() as db:
        task = db.execute(select(Task).where(Task.type == "feed_refresh")).scalar_one()
        assert task.meta.get("days_back") == 90


@pytest.mark.asyncio
async def test_backfill_skips_when_feed_refresh_already_pending(db_session_factory):
    runner = _FakeRunner()
    scheduler = TaskScheduler(runner, session_factory=db_session_factory)

    up = _make_uploader(db_session_factory)
    _make_video(db_session_factory, up, has_subtitle=True, has_summary=True)

    with db_session_factory() as db:
        db.add(
            Task(
                task_id=uuid.uuid4().hex[:12],
                type="feed_refresh",
                status="pending",
                ref_type="uploader",
                ref_id=up.id,
                created_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

    created = await scheduler._enqueue_backfill_task()
    assert created is False
