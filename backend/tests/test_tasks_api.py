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
