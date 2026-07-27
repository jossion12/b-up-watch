"""视频相关：3.2.1 时间线、3.2.3 手动刷新。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import BizError
from app.models import DEFAULT_USER_ID, Task, Uploader, Video
from app.tasks.service import create_task
from app.websocket import push_uploader_unread_sync
from app.schemas import (
    BackfillLikesIn,
    RefreshOut,
    UploaderOut,
    VideoDetailOut,
    VideoListOut,
    VideoOut,
    VideoReadIn,
)

router = APIRouter()


def _parse_date(s: str) -> datetime:
    try:
        return datetime.fromisoformat(s)
    except ValueError as e:
        raise BizError("INVALID_PARAM", f"日期格式应为 YYYY-MM-DD: {s}") from e


@router.get("/videos", response_model=VideoListOut)
def list_videos(
    start_date: str = Query(..., description="YYYY-MM-DD"),
    end_date: str = Query(..., description="YYYY-MM-DD"),
    up_ids: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
) -> VideoListOut:
    start = _parse_date(start_date).replace(tzinfo=timezone.utc)
    end_day = _parse_date(end_date).replace(tzinfo=timezone.utc)
    end_inclusive = end_day.replace(hour=23, minute=59, second=59, microsecond=999999)

    stmt = select(Video).where(
        Video.user_id == DEFAULT_USER_ID,
        Video.published_at >= start,
        Video.published_at <= end_inclusive,
    )
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if statuses:
            stmt = stmt.where(Video.status.in_(statuses))
    if up_ids:
        ids = [s.strip() for s in up_ids.split(",") if s.strip()]
        if ids:
            stmt = stmt.where(Video.uploader_id.in_(ids))
    if category:
        categories = [s.strip() for s in category.split(",") if s.strip()]
        if categories:
            stmt = stmt.join(Uploader, Video.uploader_id == Uploader.id).where(
                Uploader.category.in_(categories)
            )

    stmt = stmt.order_by(Video.published_at.asc()).limit(limit)
    rows = db.execute(stmt).scalars().all()
    return VideoListOut(
        items=[VideoOut.model_validate(r) for r in rows],
        range={"start_date": start_date, "end_date": end_date},
        total=len(rows),
    )


@router.post("/videos/refresh", response_model=RefreshOut, status_code=202)
def refresh_all(request: Request, db: Session = Depends(get_db)) -> RefreshOut:
    """全局刷新：创建一条 ref 为空的 feed_refresh 任务，runner 拉起所有 UP主。"""
    task = create_task(db, "feed_refresh")
    db.commit()
    db.refresh(task)

    runner = getattr(request.app.state, "runner", None)
    if runner is not None:
        runner.notify()

    return RefreshOut(task_id=task.task_id, type=task.type)


@router.post("/videos/backfill-likes", response_model=RefreshOut, status_code=202)
def backfill_likes(
    payload: BackfillLikesIn,
    request: Request,
    db: Session = Depends(get_db),
) -> RefreshOut:
    """触发点赞数回填任务：按 video_id 单个回填，或按 up_id 回填该 UP 主全部视频。"""
    if payload.video_id:
        v = db.get(Video, payload.video_id)
        if v is None or v.user_id != DEFAULT_USER_ID:
            raise BizError("VIDEO_NOT_FOUND", "视频不存在", http_status=404)
        ref_type, ref_id = "video", v.id
    elif payload.up_id:
        up = db.get(Uploader, payload.up_id)
        if up is None or up.user_id != DEFAULT_USER_ID:
            raise BizError("UPLOADER_NOT_FOUND", "UP主不存在", http_status=404)
        ref_type, ref_id = "uploader", up.id
    else:
        raise BizError("INVALID_PARAM", "需提供 video_id 或 up_id", http_status=422)

    task = create_task(db, "video_stats_refresh", ref_type, ref_id)
    db.commit()
    db.refresh(task)

    runner = getattr(request.app.state, "runner", None)
    if runner is not None:
        runner.notify()

    return RefreshOut(task_id=task.task_id, type=task.type)

# ---------- 3.2.2 视频详情 ----------

@router.get("/videos/{video_id}", response_model=VideoDetailOut)
def get_video(video_id: str, db: Session = Depends(get_db)) -> VideoDetailOut:
    stmt = (
        select(Video, Uploader)
        .join(Uploader, Video.uploader_id == Uploader.id)
        .where(Video.id == video_id, Video.user_id == DEFAULT_USER_ID)
    )
    row = db.execute(stmt).one_or_none()
    if row is None:
        raise BizError("VIDEO_NOT_FOUND", "视频不存在", http_status=404)
    video, uploader = row
    return VideoDetailOut(
        id=video.id,
        bvid=video.bvid,
        uploader_id=video.uploader_id,
        title=video.title,
        cover_url=video.cover_url,
        duration_sec=video.duration_sec,
        published_at=video.published_at,
        views=video.views,
        danmaku_count=video.danmaku_count,
        likes=video.likes,
        tags=video.tags or [],
        status=video.status,
        has_subtitle=video.has_subtitle,
        has_summary=video.has_summary,
        uploader=UploaderOut.model_validate(uploader),
        created_at=video.created_at,
    )


# ---------- 3.2.4 标记已读 ----------

@router.patch("/videos/read", status_code=status.HTTP_204_NO_CONTENT)
def mark_videos_read(
    payload: VideoReadIn,
    db: Session = Depends(get_db),
) -> Response:
    """批量标记视频已读，并扣减对应 UP 主的未读计数。"""
    if not payload.video_ids:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    stmt = (
        select(Video)
        .where(
            Video.user_id == DEFAULT_USER_ID,
            Video.id.in_(payload.video_ids),
            Video.is_read.is_(False),
        )
    )
    videos = db.execute(stmt).scalars().all()

    # 按 uploader 汇总本次需要扣减的未读数
    unread_delta: dict[str, int] = {}
    for v in videos:
        v.is_read = True
        unread_delta[v.uploader_id] = unread_delta.get(v.uploader_id, 0) + 1

    for uploader_id, delta in unread_delta.items():
        up = db.get(Uploader, uploader_id)
        if up is not None:
            up.unread_count = max((up.unread_count or 0) - delta, 0)
            push_uploader_unread_sync(uploader_id, up.unread_count)

    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
