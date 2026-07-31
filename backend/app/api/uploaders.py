"""UP主管理：接口文档 3.1.1–3.1.5。"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.bilibili import search as bili_search
from app.db import get_db
from app.errors import BizError
from app.models import DEFAULT_USER_ID, Task, Uploader, Video
from app.tasks.service import create_task
from app.schemas import (
    UploaderBackfillYearOut,
    UploaderCreateIn,
    UploaderCreateOut,
    UploaderListOut,
    UploaderOut,
    UploaderPrioritizeLatestOut,
    UploaderSearchItem,
    UploaderSearchOut,
    UploaderUpdateIn,
)

log = logging.getLogger(__name__)
router = APIRouter()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


# ---------- 3.1.2 搜索（必须在 /uploaders/{id} 之前注册） ----------

@router.get("/uploaders/search", response_model=UploaderSearchOut)
async def search_uploaders(
    q: str = Query(..., min_length=1, max_length=64),
    page: int = Query(1, ge=1, le=50),
    db: Session = Depends(get_db),
) -> UploaderSearchOut:
    log.info("search_uploaders request q=%s page=%s", q, page)
    try:
        raw, has_more = await bili_search.search_bili_user(q, page)
    except BizError as exc:
        # 上游非 JSON/WAF/不可达等临时异常降级为空结果，避免整接口 502
        if exc.code == "BILIBILI_RATE_LIMITED":
            raise
        log.warning(
            "search_uploaders upstream degraded q=%s page=%s code=%s message=%s",
            q,
            page,
            exc.code,
            exc.message,
        )
        raw, has_more = [], False
    items = bili_search.parse_search_items(raw)

    # 标注 already_followed
    followed_count = 0
    if items:
        uids = {it["bilibili_uid"] for it in items}
        rows = db.execute(
            select(Uploader.bilibili_uid).where(
                Uploader.user_id == DEFAULT_USER_ID,
                Uploader.bilibili_uid.in_(uids),
            )
        ).all()
        followed = {r[0] for r in rows}
        followed_count = len(followed)
        for it in items:
            it["already_followed"] = it["bilibili_uid"] in followed

    log.info(
        "search_uploaders response q=%s page=%s items=%s has_more=%s followed=%s",
        q,
        page,
        len(items),
        has_more,
        followed_count,
    )
    return UploaderSearchOut(
        items=[UploaderSearchItem(**it) for it in items],
        page=page,
        has_more=has_more,
    )


# ---------- 3.1.1 列表 ----------

@router.get("/uploaders", response_model=UploaderListOut)
def list_uploaders(
    group_id: Optional[str] = None,
    category: Optional[str] = None,
    keyword: Optional[str] = None,
    db: Session = Depends(get_db),
) -> UploaderListOut:
    stmt = select(Uploader).where(Uploader.user_id == DEFAULT_USER_ID)
    if group_id:
        stmt = stmt.where(Uploader.group_id == group_id)
    if category:
        categories = [s.strip() for s in category.split(",") if s.strip()]
        if categories:
            stmt = stmt.where(Uploader.category.in_(categories))
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(Uploader.name.like(like), Uploader.bilibili_uid.like(like)))

    rows = db.execute(stmt.order_by(Uploader.created_at.desc())).scalars().all()
    return UploaderListOut(items=[UploaderOut.model_validate(r) for r in rows], total=len(rows))


# ---------- 3.1.3 添加 ----------

@router.post("/uploaders", response_model=UploaderCreateOut, status_code=status.HTTP_201_CREATED)
def create_uploader(
    payload: UploaderCreateIn,
    request: Request,
    db: Session = Depends(get_db),
) -> UploaderCreateOut:
    existing = db.execute(
        select(Uploader).where(
            Uploader.user_id == DEFAULT_USER_ID,
            Uploader.bilibili_uid == payload.bilibili_uid,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise BizError("UPLOADER_ALREADY_EXISTS", "该 UP 主已在关注列表中", http_status=409)

    up = Uploader(
        id=_new_id(),
        user_id=DEFAULT_USER_ID,
        bilibili_uid=payload.bilibili_uid,
        name=f"UID:{payload.bilibili_uid}",  # 真实名称由采集层回填
        group_id=payload.group_id,
        category=payload.category,
        notify_enabled=payload.notify_enabled,
        unread_count=0,
        created_at=datetime.now(timezone.utc),
    )
    db.add(up)

    # 创建首次回溯任务（占位，真实采集属第二期）
    task = create_task(db, "feed_refresh", "uploader", up.id)

    db.commit()
    db.refresh(up)
    db.refresh(task)

    runner = getattr(request.app.state, "runner", None)
    if runner is not None:
        runner.notify()

    return UploaderCreateOut(uploader=UploaderOut.model_validate(up), task_id=task.task_id)


# ---------- 3.1.4 取消关注 ----------

@router.delete("/uploaders/{uploader_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_uploader(
    uploader_id: str,
    keep_history: bool = Query(True),
    db: Session = Depends(get_db),
) -> Response:
    up = db.get(Uploader, uploader_id)
    if up is None or up.user_id != DEFAULT_USER_ID:
        raise BizError("UPLOADER_NOT_FOUND", "UP主不存在", http_status=404)

    if not keep_history:
        # 级联删除视频及附属字幕/总结（model 关系 cascade 已配置）
        videos = db.execute(select(Video).where(Video.uploader_id == up.id)).scalars().all()
        for v in videos:
            db.delete(v)

    db.delete(up)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- 3.1.5 更新 ----------

@router.patch("/uploaders/{uploader_id}", response_model=UploaderOut)
def update_uploader(
    uploader_id: str,
    payload: UploaderUpdateIn,
    db: Session = Depends(get_db),
) -> UploaderOut:
    up = db.get(Uploader, uploader_id)
    if up is None or up.user_id != DEFAULT_USER_ID:
        raise BizError("UPLOADER_NOT_FOUND", "UP主不存在", http_status=404)

    if payload.group_id is not None:
        up.group_id = payload.group_id
    if payload.category is not None:
        up.category = payload.category or None
    if payload.notify_enabled is not None:
        up.notify_enabled = payload.notify_enabled

    db.commit()
    db.refresh(up)
    return UploaderOut.model_validate(up)


# ---------- 优先处理最近 N 个视频 ----------

PRIORITY_LEVEL = 10


def _active_task_exists(db: Session, task_type: str, ref_id: str) -> bool:
    return (
        db.execute(
            select(Task.task_id).where(
                Task.type == task_type,
                Task.ref_type == "video",
                Task.ref_id == ref_id,
                Task.status.in_(["pending", "running"]),
            )
        ).scalar_one_or_none()
        is not None
    )


@router.post(
    "/uploaders/{uploader_id}/prioritize-latest",
    response_model=UploaderPrioritizeLatestOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def prioritize_uploader_latest(
    uploader_id: str,
    request: Request,
    count: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
) -> UploaderPrioritizeLatestOut:
    """为某 UP 主最近 count 个视频优先排队字幕/总结任务。"""
    up = db.get(Uploader, uploader_id)
    if up is None or up.user_id != DEFAULT_USER_ID:
        raise BizError("UPLOADER_NOT_FOUND", "UP主不存在", http_status=404)

    videos = db.execute(
        select(Video)
        .where(Video.user_id == DEFAULT_USER_ID, Video.uploader_id == up.id)
        .order_by(Video.published_at.desc())
        .limit(count)
    ).scalars().all()

    enqueued_subtitle = 0
    enqueued_summary = 0
    task_ids: list[str] = []

    for v in videos:
        if not v.has_subtitle and not _active_task_exists(db, "subtitle_fetch", v.id):
            task = create_task(
                db, "subtitle_fetch", "video", v.id, priority=PRIORITY_LEVEL
            )
            task_ids.append(task.task_id)
            enqueued_subtitle += 1

        # AI 总结功能已暂停：不再排队总结任务
        # if not v.has_summary and not _active_task_exists(db, "ai_summary", v.id):
        #     task = create_task(
        #         db, "ai_summary", "video", v.id, priority=PRIORITY_LEVEL
        #     )
        #     task_ids.append(task.task_id)
        #     enqueued_summary += 1

    db.commit()

    runner = getattr(request.app.state, "runner", None)
    if runner is not None:
        runner.notify()

    log.info(
        "prioritize_latest uploader=%s count=%d videos=%d subtitle=%d summary=%d",
        up.bilibili_uid,
        count,
        len(videos),
        enqueued_subtitle,
        enqueued_summary,
    )

    return UploaderPrioritizeLatestOut(
        enqueued_subtitle=enqueued_subtitle,
        enqueued_summary=enqueued_summary,
        task_ids=task_ids,
    )


# ---------- 回溯该 UP 主当年视频 ----------


def _current_year_days_back() -> int:
    """计算从今天到当年 1 月 1 日的天数差，用于回溯当年视频。"""
    now = datetime.now(timezone.utc)
    year_start = now.date().replace(month=1, day=1)
    return (now.date() - year_start).days


@router.post(
    "/uploaders/{uploader_id}/backfill-year",
    response_model=UploaderBackfillYearOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def backfill_uploader_year(
    uploader_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> UploaderBackfillYearOut:
    """为某 UP 主创建 feed_refresh 任务，拉取当年（1月1日至今）的视频。"""
    up = db.get(Uploader, uploader_id)
    if up is None or up.user_id != DEFAULT_USER_ID:
        raise BizError("UPLOADER_NOT_FOUND", "UP主不存在", http_status=404)

    days_back = _current_year_days_back()

    existing = db.execute(
        select(Task.task_id).where(
            Task.type == "feed_refresh",
            Task.ref_type == "uploader",
            Task.ref_id == up.id,
            Task.status.in_(["pending", "running"]),
        )
    ).scalar_one_or_none()
    if existing is not None:
        return UploaderBackfillYearOut(
            task_id=existing,
            type="feed_refresh",
            days_back=days_back,
        )

    task = create_task(
        db,
        "feed_refresh",
        "uploader",
        up.id,
        meta={
            "days_back": days_back,
            "mode": "backfill-year",
        },
    )
    db.commit()
    db.refresh(task)

    runner = getattr(request.app.state, "runner", None)
    if runner is not None:
        runner.notify()

    log.info(
        "backfill_year uploader=%s days_back=%d task_id=%s",
        up.bilibili_uid,
        days_back,
        task.task_id,
    )

    return UploaderBackfillYearOut(
        task_id=task.task_id,
        type=task.type,
        days_back=days_back,
    )