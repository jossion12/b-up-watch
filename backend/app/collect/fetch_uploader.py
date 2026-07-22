"""采集 UP 主最新投稿：拉取空间列表 → 按 bvid 去重入库 → 更新 UP主 未读/最新时间。

被后台 TaskRunner 调用（每条 feed_refresh 任务处理一次）。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bilibili import space as bili_space
from app.bilibili.client import get_client
from app.models import Uploader, Video
from app.websocket import push_uploader_unread_sync, push_video_new_sync

log = logging.getLogger(__name__)

# 默认最多扫 5 页（150 条），命中 cutoff 即提前停止
_MAX_PAGES = 5


async def fetch_uploader_videos(
    db: Session,
    uploader: Uploader,
    days_back: int = 30,
    max_pages: int = _MAX_PAGES,
) -> int:
    """拉取并入库。返回新增视频数。

    Args:
        days_back: 只保留多久以内发布的视频（超出该时间窗的视频被跳过）。
        max_pages: 最多翻页数，回溯任务可适当调大。
    """
    if uploader.user_id is None:
        # 防御：老数据兜底
        pass

    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    client = get_client()

    # 回填 UP 主真实昵称/头像/粉丝数/简介（首次或占位时更新）
    await _refresh_uploader_profile(db, uploader, client)

    new_count = 0
    latest_pub: datetime | None = None
    new_videos: list[Video] = []

    log.info(
        "fetch_uploader_videos start uid=%s days_back=%s max_pages=%s cutoff=%s",
        uploader.bilibili_uid,
        days_back,
        max_pages,
        cutoff.isoformat(),
    )
    for pn in range(1, max_pages + 1):
        data = await bili_space.fetch_space_archive(uploader.bilibili_uid, pn=pn, client=client)
        list_node = (data or {}).get("list") or {}
        vlist = list_node.get("vlist") or []

        # 兜底：名片接口失败时，从投稿列表的作者字段回填昵称/头像
        if vlist and uploader.name and uploader.name.startswith("UID:"):
            for item in vlist:
                author = item.get("author")
                if author and isinstance(author, str) and author.strip():
                    uploader.name = author.strip()
                    face = item.get("face")
                    if face and isinstance(face, str) and face.strip():
                        uploader.avatar_url = face.strip()
                    db.commit()
                    log.info(
                        "fallback uploader profile from archive uid=%s name=%s",
                        uploader.bilibili_uid, uploader.name,
                    )
                    break
        log.info(
            "fetch_space_archive uid=%s pn=%s data_keys=%s list_keys=%s vlist_len=%s",
            uploader.bilibili_uid,
            pn,
            list(data.keys()) if isinstance(data, dict) else type(data).__name__,
            list(list_node.keys()) if isinstance(list_node, dict) else type(list_node).__name__,
            len(vlist),
        )
        if not vlist:
            log.info("fetch_uploader_videos uid=%s pn=%s empty vlist, stop", uploader.bilibili_uid, pn)
            break

        reached_cutoff = False
        for idx, item in enumerate(vlist):
            # B站 /x/space/wbi/arc/search 实际返回 created（10 位时间戳）
            raw_pub = item.get("created") or item.get("pubdate")
            pub = bili_space.parse_pubdate(raw_pub)
            bvid = item.get("bvid")
            title = item.get("title", "") or ""
            log.debug(
                "fetch_uploader_videos item uid=%s idx=%s bvid=%s title=%s raw_pub=%s parsed_pub=%s",
                uploader.bilibili_uid,
                idx,
                bvid,
                title[:40],
                raw_pub,
                pub.isoformat() if pub else None,
            )
            if pub is None or pub < cutoff:
                log.info(
                    "fetch_uploader_videos skip uid=%s bvid=%s reason=cutoff raw_pub=%s parsed_pub=%s cutoff=%s",
                    uploader.bilibili_uid,
                    bvid,
                    raw_pub,
                    pub.isoformat() if pub else None,
                    cutoff.isoformat(),
                )
                reached_cutoff = True
                continue  # 当前页剩余可能都更老，跳过但继续看下一页（应对乱序）

            if not bvid:
                log.info("fetch_uploader_videos skip uid=%s idx=%s reason=no_bvid", uploader.bilibili_uid, idx)
                continue

            existing = db.execute(
                select(Video).where(
                    Video.user_id == uploader.user_id,
                    Video.bvid == bvid,
                )
            ).scalar_one_or_none()
            if existing is not None:
                # 已知视频，更新一下热度/计数（轻量）
                existing.views = int(item.get("play") or existing.views)
                existing.danmaku_count = int(item.get("video_review") or existing.danmaku_count)
                existing.likes = int(item.get("like") or existing.likes)
                log.info(
                    "fetch_uploader_videos skip uid=%s bvid=%s reason=existing views=%s likes=%s",
                    uploader.bilibili_uid,
                    bvid,
                    existing.views,
                    existing.likes,
                )
                continue

            video = Video(
                id=uuid.uuid4().hex[:12],
                user_id=uploader.user_id,
                bvid=bvid,
                uploader_id=uploader.id,
                title=title,
                cover_url=item.get("pic") or None,
                duration_sec=_parse_duration(item.get("length")),
                published_at=pub,
                views=int(item.get("play") or 0),
                danmaku_count=int(item.get("video_review") or 0),
                likes=int(item.get("like") or 0),
                tags=item.get("tag") or [],
                status="new",
                has_subtitle=False,
                has_summary=False,
                is_read=False,
            )
            db.add(video)
            new_videos.append(video)
            uploader.unread_count = (uploader.unread_count or 0) + 1
            new_count += 1
            if latest_pub is None or pub > latest_pub:
                latest_pub = pub
            log.info(
                "fetch_uploader_videos insert uid=%s bvid=%s title=%s published_at=%s",
                uploader.bilibili_uid,
                bvid,
                title[:40],
                pub.isoformat(),
            )

        db.commit()

        if reached_cutoff:
            log.info("fetch_uploader_videos uid=%s reached cutoff, stop", uploader.bilibili_uid)
            break

    if latest_pub is not None:
        current = uploader.last_video_at
        if current is None or latest_pub > current:
            uploader.last_video_at = latest_pub

    db.commit()

    # WebSocket 推送：新视频 + 未读数变化
    for video in new_videos:
        push_video_new_sync({
            "id": video.id,
            "bvid": video.bvid,
            "uploader_id": video.uploader_id,
            "title": video.title,
            "cover_url": video.cover_url,
            "duration_sec": video.duration_sec,
            "published_at": video.published_at,
            "views": video.views,
            "danmaku_count": video.danmaku_count,
            "likes": video.likes,
            "tags": video.tags or [],
            "status": video.status,
            "has_subtitle": video.has_subtitle,
            "has_summary": video.has_summary,
        })
    if new_count:
        push_uploader_unread_sync(uploader.id, uploader.unread_count or 0)

    log.info(
        "fetched uploader %s: %d new videos (latest_pub=%s)",
        uploader.bilibili_uid, new_count, latest_pub,
    )
    return new_count


async def _refresh_uploader_profile(
    db: Session,
    uploader: Uploader,
    client,
) -> None:
    """调用用户名片接口回填真实昵称、头像、粉丝数、简介。失败则保持原值。"""
    try:
        card = await bili_space.fetch_user_card(uploader.bilibili_uid, client=client)
    except Exception:
        log.warning("refresh uploader profile failed uid=%s", uploader.bilibili_uid, exc_info=True)
        return

    if not card:
        return

    name = card.get("name")
    if name and isinstance(name, str) and name.strip():
        uploader.name = name.strip()

    face = card.get("face")
    if face and isinstance(face, str):
        uploader.avatar_url = face

    fans = card.get("fans")
    if fans is not None:
        try:
            uploader.fans_count = int(fans)
        except (TypeError, ValueError):
            pass

    sign = card.get("sign")
    if sign and isinstance(sign, str):
        uploader.description = sign

    db.commit()


def _parse_duration(raw: Any) -> int:
    """B站 length 字段格式为 'MM:SS' 或 'HH:MM:SS'。"""
    if not raw:
        return 0
    if isinstance(raw, int):
        return raw
    parts = str(raw).split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return 0
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    if len(nums) == 3:
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    return 0