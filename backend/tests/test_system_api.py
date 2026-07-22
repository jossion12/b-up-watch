"""3.7.1 系统状态。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.models import Task


def test_system_status_shape(client, db_session_factory):
    r = client.get("/api/v1/system/status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "last_refresh_at" in body
    assert "refresh_interval_sec" in body
    assert body["running_tasks"] == 0
    assert body["queued_tasks"] == 0
    assert body["llm"]["provider"] == "openai-compatible"
    assert "db_mb" in body["storage"]
    assert body["storage"]["subtitles_count"] == 0


def test_system_status_counts_tasks(client, db_session_factory):
    with db_session_factory() as db:
        for i in range(3):
            db.add(Task(
                task_id=uuid.uuid4().hex[:12], type="feed_refresh", status="pending",
                progress=0, created_at=datetime.now(timezone.utc),
            ))
        for i in range(2):
            db.add(Task(
                task_id=uuid.uuid4().hex[:12], type="feed_refresh", status="running",
                progress=10, created_at=datetime.now(timezone.utc),
            ))
        db.commit()

    r = client.get("/api/v1/system/status")
    body = r.json()
    assert body["queued_tasks"] == 3
    assert body["running_tasks"] == 2

def test_update_system_config(client, db_session_factory):
    r = client.patch("/api/v1/system/config", json={
        "refresh_interval_sec": 300,
        "summary_model": "new-model",
        "auto_summarize": True,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["refresh_interval_sec"] == 300
    assert body["summary_model"] == "new-model"
    assert body["auto_summarize"] is True
    assert body["summary_template_id"] == "tpl_default"


def test_update_system_config_invalid_template(client):
    r = client.patch("/api/v1/system/config", json={"summary_template_id": "not_exist"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "TEMPLATE_NOT_FOUND"
