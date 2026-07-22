"""字幕接口：3.3.1 / 3.3.2 / 3.3.3。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import BizError
from app.models import Subtitle, Task, Video
from app.schemas import SubtitleFetchOut, SubtitleOut

router = APIRouter()


# ---------- 3.3.1 取字幕 ----------

@router.get("/videos/{video_id}/subtitle", response_model=SubtitleOut)
def get_subtitle(video_id: str, db: Session = Depends(get_db)) -> SubtitleOut:
    if db.get(Video, video_id) is None:
        raise BizError("VIDEO_NOT_FOUND", "视频不存在", http_status=404)
    sub = db.get(Subtitle, video_id)
    if sub is None:
        raise BizError("SUBTITLE_NOT_FOUND", "字幕尚未获取", http_status=404)
    return SubtitleOut(
        video_id=video_id,
        language=sub.language,
        source=sub.source,
        lines=sub.lines or [],
        fetched_at=sub.fetched_at,
    )


# ---------- 3.3.2 创建字幕获取任务 ----------

@router.post(
    "/videos/{video_id}/subtitle/fetch",
    response_model=SubtitleFetchOut,
    status_code=202,
)
def fetch_subtitle(
    video_id: str, request: Request, db: Session = Depends(get_db)
) -> SubtitleFetchOut:
    if db.get(Video, video_id) is None:
        raise BizError("VIDEO_NOT_FOUND", "视频不存在", http_status=404)

    # 409 防重：已有 pending/running 同类任务
    existing = (
        db.query(Task)
        .filter(
            Task.type == "subtitle_fetch",
            Task.ref_type == "video",
            Task.ref_id == video_id,
            Task.status.in_(["pending", "running"]),
        )
        .first()
    )
    if existing is not None:
        raise BizError("TASK_CONFLICT", "已有进行中的字幕获取任务", http_status=409)

    task = Task(
        task_id=uuid.uuid4().hex[:12],
        type="subtitle_fetch",
        status="pending",
        progress=0,
        ref_type="video",
        ref_id=video_id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    runner = getattr(request.app.state, "runner", None)
    if runner is not None:
        runner.notify()

    return SubtitleFetchOut(task_id=task.task_id, type=task.type)


# ---------- 3.3.3 导出字幕 ----------

def _fmt_srt_time(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int(round((sec - int(sec)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


@router.get("/videos/{video_id}/subtitle/export")
def export_subtitle(
    video_id: str,
    format: str = Query("srt", pattern="^(srt|txt|json)$"),
    db: Session = Depends(get_db),
) -> Response:
    v = db.get(Video, video_id)
    if v is None:
        raise BizError("VIDEO_NOT_FOUND", "视频不存在", http_status=404)
    sub = db.get(Subtitle, video_id)
    if sub is None:
        raise BizError("SUBTITLE_NOT_FOUND", "字幕尚未获取", http_status=404)

    lines = sub.lines or []

    if format == "json":
        content = json.dumps({
            "video_id": video_id,
            "language": sub.language,
            "source": sub.source,
            "lines": lines,
        }, ensure_ascii=False, indent=2)
        media = "application/json; charset=utf-8"
        ext = "json"
    elif format == "txt":
        content = "\n".join((line.get("text") or "") for line in lines)
        media = "text/plain; charset=utf-8"
        ext = "txt"
    else:  # srt
        parts = []
        for i, line in enumerate(lines, 1):
            start = _fmt_srt_time(float(line.get("start_sec", 0)))
            end = _fmt_srt_time(float(line.get("end_sec", 0)))
            text = (line.get("text") or "").strip()
            parts.append(f"{i}\n{start} --> {end}\n{text}\n")
        content = "\n".join(parts)
        media = "application/x-subrip; charset=utf-8"
        ext = "srt"

    filename = f"{v.bvid}.{ext}"
    return Response(
        content=content.encode("utf-8"),
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )