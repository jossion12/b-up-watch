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
from app.models import DEFAULT_USER_ID, Task, Uploader
from app.schemas import (
    UploaderCreateIn,
    UploaderCreateOut,
    UploaderListOut,
    UploaderOut,
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
    keyword: Optional[str] = None,
    db: Session = Depends(get_db),
) -> UploaderListOut:
    stmt = select(Uploader).where(Uploader.user_id == DEFAULT_USER_ID)
    if group_id:
        stmt = stmt.where(Uploader.group_id == group_id)
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
        notify_enabled=payload.notify_enabled,
        unread_count=0,
        created_at=datetime.now(timezone.utc),
    )
    db.add(up)

    # 创建首次回溯任务（占位，真实采集属第二期）
    task = Task(
        task_id=_new_id(),
        type="feed_refresh",
        status="pending",
        ref_type="uploader",
        ref_id=up.id,
        progress=0,
        created_at=datetime.now(timezone.utc),
    )
    db.add(task)

    db.commit()
    db.refresh(up)

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
    if payload.notify_enabled is not None:
        up.notify_enabled = payload.notify_enabled

    db.commit()
    db.refresh(up)
    return UploaderOut.model_validate(up)