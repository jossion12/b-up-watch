"""视频相关：3.2.1 时间线、3.2.3 手动刷新、视频搜索。"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session
import httpx

from app.bilibili import search as bili_search
from app.bilibili import subtitle as bili_sub
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
    VideoSearchFetchIn,
    VideoSearchFetchOut,
    VideoSearchFetchResult,
    VideoSearchItem,
    VideoSearchOut,
)

log = logging.getLogger(__name__)

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

# ---------- 视频搜索（新增） ----------


def _parse_timestamp(ts: int | None) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None


@router.get("/videos/search", response_model=VideoSearchOut)
async def search_videos(
    q: str = Query(..., min_length=1, max_length=64),
    page: int = Query(1, ge=1, le=50),
    order: str = Query("", description="排序：空=综合，pubdate=最新发布，click=最多播放"),
) -> VideoSearchOut:
    """代理 B站视频搜索，返回候选视频列表。"""
    try:
        raw, has_more = await bili_search.search_bili_video(q, page, order)
    except BizError as exc:
        if exc.code == "BILIBILI_RATE_LIMITED":
            raise
        log.warning(
            "search_videos upstream degraded q=%s page=%s code=%s message=%s",
            q,
            page,
            exc.code,
            exc.message,
        )
        raw, has_more = [], False
    except httpx.HTTPError as exc:
        log.warning("search_videos network error q=%s page=%s err=%s", q, page, exc)
        raw, has_more = [], False

    parsed = bili_search.parse_video_items(raw)
    items = [
        VideoSearchItem(
            bvid=it["bvid"],
            title=it["title"],
            cover_url=it.get("cover_url"),
            duration_sec=it.get("duration_sec") or 0,
            published_at=_parse_timestamp(it.get("published_at")),
            views=it.get("views") or 0,
            danmaku_count=it.get("danmaku_count") or 0,
            likes=it.get("likes") or 0,
            uploader_mid=it.get("uploader_mid"),
            uploader_name=it.get("uploader_name") or "",
            uploader_avatar_url=it.get("uploader_avatar_url"),
        )
        for it in parsed
    ]
    return VideoSearchOut(items=items, page=page, has_more=has_more)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _ensure_search_uploader(
    db: Session,
    mid: str,
    name: str,
    avatar_url: Optional[str],
) -> Uploader:
    """按 B站 mid 查询或创建一个占位 UP主（用于归属搜索到的视频）。"""
    up = db.execute(
        select(Uploader).where(
            Uploader.user_id == DEFAULT_USER_ID,
            Uploader.bilibili_uid == mid,
        )
    ).scalar_one_or_none()
    if up is not None:
        return up
    up = Uploader(
        id=_new_id(),
        user_id=DEFAULT_USER_ID,
        bilibili_uid=mid,
        name=name or f"UID:{mid}",
        avatar_url=avatar_url,
        fans_count=0,
        unread_count=0,
        created_at=datetime.now(timezone.utc),
    )
    db.add(up)
    db.commit()
    db.refresh(up)
    log.info("search_videos created placeholder uploader mid=%s id=%s", mid, up.id)
    return up


def _active_subtitle_task_exists(db: Session, video_id: str) -> Optional[Task]:
    return (
        db.execute(
            select(Task).where(
                Task.type == "subtitle_fetch",
                Task.ref_type == "video",
                Task.ref_id == video_id,
                Task.status.in_(["pending", "running"]),
            )
        )
        .scalar_one_or_none()
    )


def _ensure_search_video(
    db: Session,
    bvid: str,
    info: dict,
    uploader_id: str,
) -> Video:
    """按 bvid 查询或创建视频，并用 B站 view 接口元数据回填。"""
    v = db.execute(
        select(Video).where(
            Video.user_id == DEFAULT_USER_ID,
            Video.bvid == bvid,
        )
    ).scalar_one_or_none()

    stat = info.get("stat") or {}
    owner = info.get("owner") or {}
    title = info.get("title") or ""
    cover_url = info.get("pic") or None
    duration = info.get("duration") or 0
    pub = _parse_timestamp(info.get("pubdate"))
    tags = info.get("tag") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]

    if v is not None:
        v.title = title or v.title
        v.cover_url = cover_url or v.cover_url
        if duration:
            v.duration_sec = int(duration)
        if pub:
            v.published_at = pub
        v.views = int(stat.get("view") or v.views)
        v.danmaku_count = int(stat.get("danmaku") or v.danmaku_count)
        v.likes = int(stat.get("like") or v.likes)
        if tags:
            v.tags = tags
        db.commit()
        db.refresh(v)
        return v

    v = Video(
        id=_new_id(),
        user_id=DEFAULT_USER_ID,
        bvid=bvid,
        uploader_id=uploader_id,
        title=title,
        cover_url=cover_url,
        duration_sec=int(duration) if duration else 0,
        published_at=pub or datetime.now(timezone.utc),
        views=int(stat.get("view") or 0),
        danmaku_count=int(stat.get("danmaku") or 0),
        likes=int(stat.get("like") or 0),
        tags=tags,
        status="new",
        has_subtitle=False,
        has_summary=False,
        is_read=False,
    )
    db.add(v)
    db.commit()
    db.refresh(v)
    return v


@router.post("/videos/search/fetch-subtitles", response_model=VideoSearchFetchOut, status_code=202)
async def fetch_subtitles_from_search(
    payload: VideoSearchFetchIn,
    request: Request,
    db: Session = Depends(get_db),
) -> VideoSearchFetchOut:
    """将搜索到的视频入库，并为每个视频创建字幕获取任务。"""
    task_ids: list[str] = []
    video_ids: list[str] = []
    results: list[VideoSearchFetchResult] = []

    for item in payload.items:
        bvid = item.bvid
        try:
            info = await bili_sub.get_video_info(bvid)
            owner = info.get("owner") or {}
            mid = owner.get("mid")
            if not mid:
                raise BizError("VIDEO_OWNER_MISSING", "视频缺少 UP主信息", http_status=422)

            up = _ensure_search_uploader(
                db,
                str(mid),
                owner.get("name") or "",
                owner.get("face"),
            )
            v = _ensure_search_video(db, bvid, info, up.id)

            existing = _active_subtitle_task_exists(db, v.id)
            if existing is not None:
                task = existing
            else:
                task = create_task(db, "subtitle_fetch", "video", v.id)
                db.commit()
                db.refresh(task)

            task_ids.append(task.task_id)
            video_ids.append(v.id)
            results.append(
                VideoSearchFetchResult(
                    bvid=bvid,
                    video_id=v.id,
                    task_id=task.task_id,
                )
            )
        except BizError as exc:
            results.append(
                VideoSearchFetchResult(
                    bvid=bvid,
                    error={"code": exc.code, "message": exc.message},
                )
            )
        except Exception as exc:
            log.exception("fetch_subtitles_from_search failed bvid=%s", bvid)
            results.append(
                VideoSearchFetchResult(
                    bvid=bvid,
                    error={"code": "INTERNAL_ERROR", "message": str(exc)},
                )
            )

    runner = getattr(request.app.state, "runner", None)
    if runner is not None:
        runner.notify()

    return VideoSearchFetchOut(
        task_ids=task_ids,
        video_ids=video_ids,
        results=results,
    )


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
