"""3.5.1 任务查询。"""

import uuid
from datetime import datetime, timezone

from app.models import Task


def test_get_task_success(client, db_session_factory):
    with db_session_factory() as db:
        t = Task(
            task_id=uuid.uuid4().hex[:12], type="feed_refresh", status="success",
            progress=100, ref_type=None, ref_id=None,
            created_at=datetime.now(timezone.utc), finished_at=datetime.now(timezone.utc),
        )
        db.add(t)
        db.commit()

    r = client.get(f"/api/v1/tasks/{t.task_id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["task_id"] == t.task_id
    assert body["status"] == "success"
    assert body["progress"] == 100


def test_get_task_404(client):
    r = client.get("/api/v1/tasks/nonexistent")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "TASK_NOT_FOUND"

def test_list_tasks(client, db_session_factory):
    import uuid
    with db_session_factory() as db:
        for i, status in enumerate(["pending", "running", "success", "failed"]):
            db.add(Task(
                task_id=uuid.uuid4().hex[:12], type="feed_refresh", status=status,
                progress=0, created_at=datetime.now(timezone.utc),
            ))
        db.commit()

    r = client.get("/api/v1/tasks?status=pending,running")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2
    assert all(t["status"] in ("pending", "running") for t in body["items"])


def test_list_tasks_default_limit(client, db_session_factory):
    import uuid
    with db_session_factory() as db:
        for i in range(25):
            db.add(Task(
                task_id=uuid.uuid4().hex[:12], type="feed_refresh", status="pending",
                progress=0, created_at=datetime.now(timezone.utc),
            ))
        db.commit()

    r = client.get("/api/v1/tasks")
    assert r.status_code == 200
    # 默认 limit=20
    assert len(r.json()["items"]) == 20


def test_list_tasks_filter_by_type(client, db_session_factory):
    with db_session_factory() as db:
        db.add(Task(
            task_id=uuid.uuid4().hex[:12], type="rag_ingest", status="pending",
            progress=0, created_at=datetime.now(timezone.utc),
        ))
        db.add(Task(
            task_id=uuid.uuid4().hex[:12], type="subtitle_fetch", status="pending",
            progress=0, created_at=datetime.now(timezone.utc),
        ))
        db.commit()

    r = client.get("/api/v1/tasks?task_type=rag_ingest")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["type"] == "rag_ingest"


def test_task_stats(client, db_session_factory):
    import uuid
    with db_session_factory() as db:
        # subtitle_fetch: 1 pending, 1 success
        db.add(Task(
            task_id=uuid.uuid4().hex[:12], type="subtitle_fetch", status="pending",
            progress=0, created_at=datetime.now(timezone.utc),
        ))
        db.add(Task(
            task_id=uuid.uuid4().hex[:12], type="subtitle_fetch", status="success",
            progress=100, created_at=datetime.now(timezone.utc),
        ))
        # whisper_transcribe: 1 running
        db.add(Task(
            task_id=uuid.uuid4().hex[:12], type="whisper_transcribe", status="running",
            progress=50, created_at=datetime.now(timezone.utc),
        ))
        # ai_summary: 1 pending, 1 failed
        db.add(Task(
            task_id=uuid.uuid4().hex[:12], type="ai_summary", status="pending",
            progress=0, created_at=datetime.now(timezone.utc),
        ))
        db.add(Task(
            task_id=uuid.uuid4().hex[:12], type="ai_summary", status="failed",
            progress=0, created_at=datetime.now(timezone.utc),
        ))
        # feed_refresh should be ignored
        db.add(Task(
            task_id=uuid.uuid4().hex[:12], type="feed_refresh", status="pending",
            progress=0, created_at=datetime.now(timezone.utc),
        ))
        db.commit()

    r = client.get("/api/v1/tasks/stats")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["subtitle_total"] == 3
    assert body["subtitle_pending"] == 2
    assert body["subtitle_completed"] == 1
    assert body["subtitle_failed"] == 0
    assert body["summary_total"] == 2
    assert body["summary_pending"] == 1
    assert body["summary_completed"] == 0
    assert body["summary_failed"] == 1


def test_retry_failed_task(client, db_session_factory):
    task_id = uuid.uuid4().hex[:12]
    with db_session_factory() as db:
        db.add(Task(
            task_id=task_id, type="ai_summary", status="failed",
            progress=0, ref_type="video", ref_id="vid1",
            error={"code": "LLM_ERROR", "message": "模型调用失败"},
            created_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
        ))
        db.commit()

    r = client.post(f"/api/v1/tasks/{task_id}/retry")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["task_id"] == task_id
    assert body["status"] == "pending"
    assert body["progress"] == 0
    assert body["error"] is None
    assert body["finished_at"] is None


def test_retry_task_not_failed(client, db_session_factory):
    task_id = uuid.uuid4().hex[:12]
    with db_session_factory() as db:
        db.add(Task(
            task_id=task_id, type="subtitle_fetch", status="success",
            progress=100, created_at=datetime.now(timezone.utc),
        ))
        db.commit()

    r = client.post(f"/api/v1/tasks/{task_id}/retry")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "TASK_NOT_RETRYABLE"


def test_retry_task_404(client):
    r = client.post("/api/v1/tasks/nonexistent/retry")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "TASK_NOT_FOUND"


def test_cancel_tasks_by_single_type(client, db_session_factory):
    pending_id = uuid.uuid4().hex[:12]
    running_id = uuid.uuid4().hex[:12]
    other_id = uuid.uuid4().hex[:12]
    with db_session_factory() as db:
        db.add(Task(
            task_id=pending_id, type="subtitle_fetch", status="pending",
            progress=0, created_at=datetime.now(timezone.utc),
        ))
        db.add(Task(
            task_id=running_id, type="subtitle_fetch", status="running",
            progress=50, created_at=datetime.now(timezone.utc),
        ))
        db.add(Task(
            task_id=other_id, type="rag_ingest", status="pending",
            progress=0, created_at=datetime.now(timezone.utc),
        ))
        db.commit()

    r = client.post("/api/v1/tasks/cancel", json={"task_type": "subtitle_fetch"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert pending_id in body["deleted_task_ids"]
    assert running_id in body["cancelled_task_ids"]
    assert other_id not in body["deleted_task_ids"] + body["cancelled_task_ids"]

    with db_session_factory() as db:
        assert db.get(Task, pending_id) is None
        running = db.get(Task, running_id)
        assert running.status == "failed"
        assert running.error["code"] == "CANCELLED"
        other = db.get(Task, other_id)
        assert other.status == "pending"


def test_cancel_tasks_by_multiple_types(client, db_session_factory):
    subtitle_id = uuid.uuid4().hex[:12]
    whisper_id = uuid.uuid4().hex[:12]
    rag_id = uuid.uuid4().hex[:12]
    with db_session_factory() as db:
        db.add(Task(
            task_id=subtitle_id, type="subtitle_fetch", status="pending",
            progress=0, created_at=datetime.now(timezone.utc),
        ))
        db.add(Task(
            task_id=whisper_id, type="whisper_transcribe", status="pending",
            progress=0, created_at=datetime.now(timezone.utc),
        ))
        db.add(Task(
            task_id=rag_id, type="rag_ingest", status="pending",
            progress=0, created_at=datetime.now(timezone.utc),
        ))
        db.commit()

    r = client.post(
        "/api/v1/tasks/cancel",
        json={"task_type": ["subtitle_fetch", "whisper_transcribe"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    deleted = body["deleted_task_ids"]
    assert subtitle_id in deleted
    assert whisper_id in deleted
    assert rag_id not in deleted + body["cancelled_task_ids"]

    with db_session_factory() as db:
        assert db.get(Task, subtitle_id) is None
        assert db.get(Task, whisper_id) is None
        assert db.get(Task, rag_id).status == "pending"
