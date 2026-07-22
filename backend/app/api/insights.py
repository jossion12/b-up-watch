"""洞察分析接口：3.6.1–3.6.5。

数据来自预聚合表：
- topic_daily_stats：每日话题命中次数
- topic_opinions：按话题聚合的观点
- video_stats_snapshot：Top 视频榜快照
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import (
    DEFAULT_USER_ID,
    TopicDailyStat,
    TopicOpinion,
    Uploader,
    Video,
    VideoStatsSnapshot,
)
from app.schemas import (
    HotWordsOut,
    OverviewOut,
    TopicClustersOut,
    TopicClusterItem,
    TopicOpinionItem,
    TopicTrendOut,
    TopVideosOut,
    VideoDetailOut,
    UploaderOut,
)

router = APIRouter()

TOP_N = 6  # 话题趋势默认 Top N


def _date_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _parse_days(days: int) -> tuple[str, str]:
    """返回 (start_date, end_date) 字符串，end_date 为今天。"""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days - 1)
    return _date_str(start), _date_str(end)


# ---------- 3.6.1 总览统计 ----------

@router.get("/insights/overview", response_model=OverviewOut)
def overview(
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
) -> OverviewOut:
    start, end = _parse_days(days)
    prev_start, prev_end = _parse_days(days * 2)

    monitored_uploaders = db.execute(
        select(func.count()).select_from(Uploader).where(Uploader.user_id == DEFAULT_USER_ID)
    ).scalar() or 0

    week_new_videos = db.execute(
        select(func.count()).select_from(Video).where(
            Video.user_id == DEFAULT_USER_ID,
            Video.published_at >= datetime.fromisoformat(start).replace(tzinfo=timezone.utc),
            Video.published_at <= datetime.fromisoformat(end).replace(tzinfo=timezone.utc) + timedelta(days=1),
        )
    ).scalar() or 0

    prev_new_videos = db.execute(
        select(func.count()).select_from(Video).where(
            Video.user_id == DEFAULT_USER_ID,
            Video.published_at >= datetime.fromisoformat(prev_start).replace(tzinfo=timezone.utc),
            Video.published_at < datetime.fromisoformat(start).replace(tzinfo=timezone.utc),
        )
    ).scalar() or 0

    total_videos_period = db.execute(
        select(func.count()).select_from(Video).where(
            Video.user_id == DEFAULT_USER_ID,
            Video.published_at >= datetime.fromisoformat(start).replace(tzinfo=timezone.utc),
        )
    ).scalar() or 0

    summarized_count = db.execute(
        select(func.count()).select_from(Video).where(
            Video.user_id == DEFAULT_USER_ID,
            Video.has_summary.is_(True),
            Video.published_at >= datetime.fromisoformat(start).replace(tzinfo=timezone.utc),
        )
    ).scalar() or 0

    coverage = round(summarized_count / total_videos_period, 2) if total_videos_period else 0.0

    # 热词：取当前周期 Top N 话题
    hot_topics = db.execute(
        select(TopicDailyStat.topic, func.sum(TopicDailyStat.count).label("heat"))
        .where(TopicDailyStat.date >= start, TopicDailyStat.date <= end)
        .group_by(TopicDailyStat.topic)
        .order_by(func.sum(TopicDailyStat.count).desc())
        .limit(TOP_N)
    ).all()

    # 上升话题：与上一周期环比增长的话题数
    prev_topics = {
        row.topic: int(row.heat or 0)
        for row in db.execute(
            select(TopicDailyStat.topic, func.sum(TopicDailyStat.count).label("heat"))
            .where(TopicDailyStat.date >= prev_start, TopicDailyStat.date < start)
            .group_by(TopicDailyStat.topic)
        ).all()
    }
    rising = 0
    for topic, heat in hot_topics:
        prev = prev_topics.get(topic, 0)
        if int(heat or 0) > prev:
            rising += 1

    return OverviewOut(
        monitored_uploaders=int(monitored_uploaders),
        week_new_videos=int(week_new_videos),
        week_new_videos_delta=int(week_new_videos) - int(prev_new_videos),
        summarized_count=int(summarized_count),
        summary_coverage=coverage,
        hot_topic_count=len(hot_topics),
        rising_topic_count=rising,
    )


# ---------- 3.6.2 话题热度趋势 ----------

@router.get("/insights/topic-trend", response_model=TopicTrendOut)
def topic_trend(
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
) -> TopicTrendOut:
    start, end = _parse_days(days)

    # 取当前周期 Top N 话题
    top_topics = [
        row.topic
        for row in db.execute(
            select(TopicDailyStat.topic, func.sum(TopicDailyStat.count).label("heat"))
            .where(TopicDailyStat.date >= start, TopicDailyStat.date <= end)
            .group_by(TopicDailyStat.topic)
            .order_by(func.sum(TopicDailyStat.count).desc())
            .limit(TOP_N)
        ).all()
    ]

    # 每日各话题计数
    rows = db.execute(
        select(TopicDailyStat.date, TopicDailyStat.topic, func.sum(TopicDailyStat.count).label("cnt"))
        .where(
            TopicDailyStat.date >= start,
            TopicDailyStat.date <= end,
            TopicDailyStat.topic.in_(top_topics),
        )
        .group_by(TopicDailyStat.date, TopicDailyStat.topic)
        .order_by(TopicDailyStat.date)
    ).all()

    data_by_date: dict[str, dict[str, int]] = {}
    for date, topic, cnt in rows:
        data_by_date.setdefault(date, {})[topic] = int(cnt or 0)

    # 补齐日期（无数据则为 0）
    series = []
    cur = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(end).replace(tzinfo=timezone.utc)
    while cur <= end_dt:
        d = _date_str(cur)
        point = {"date": d}
        for topic in top_topics:
            point[topic] = data_by_date.get(d, {}).get(topic, 0)
        series.append(point)
        cur += timedelta(days=1)

    return TopicTrendOut(series=series, topics=top_topics)


# ---------- 3.6.3 热词榜 ----------

@router.get("/insights/hot-words", response_model=HotWordsOut)
def hot_words(
    days: int = Query(7, ge=1, le=90),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> HotWordsOut:
    start, end = _parse_days(days)
    prev_start, _ = _parse_days(days * 2)

    current = db.execute(
        select(TopicDailyStat.topic, func.sum(TopicDailyStat.count).label("heat"))
        .where(TopicDailyStat.date >= start, TopicDailyStat.date <= end)
        .group_by(TopicDailyStat.topic)
        .order_by(func.sum(TopicDailyStat.count).desc())
        .limit(limit)
    ).all()

    prev = {
        row.topic: int(row.heat or 0)
        for row in db.execute(
            select(TopicDailyStat.topic, func.sum(TopicDailyStat.count).label("heat"))
            .where(TopicDailyStat.date >= prev_start, TopicDailyStat.date < start)
            .group_by(TopicDailyStat.topic)
        ).all()
    }

    items = []
    for topic, heat in current:
        heat_int = int(heat or 0)
        prev_heat = prev.get(topic, 0)
        if heat_int > prev_heat:
            trend = "up"
        elif heat_int < prev_heat:
            trend = "down"
        else:
            trend = "flat"
        items.append({
            "word": topic,
            "heat": heat_int,
            "mention_count": heat_int,
            "trend": trend,
        })

    return HotWordsOut(items=items)


# ---------- 3.6.4 观点聚类 ----------

@router.get("/insights/topic-clusters", response_model=TopicClustersOut)
def topic_clusters(
    days: int = Query(7, ge=1, le=90),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> TopicClustersOut:
    start, end = _parse_days(days)

    rows = db.execute(
        select(TopicOpinion)
        .where(TopicOpinion.date >= start, TopicOpinion.date <= end)
        .order_by(TopicOpinion.updated_at.desc())
    ).scalars().all()

    clusters: dict[str, dict] = {}
    for op in rows:
        if op.topic not in clusters:
            clusters[op.topic] = {
                "topic": op.topic,
                "heat": 0,
                "video_ids": set(),
                "opinions": [],
            }
        c = clusters[op.topic]
        c["heat"] += op.count if hasattr(op, "count") else 1
        c["video_ids"].add(op.video_id)
        c["opinions"].append(TopicOpinionItem(
            uploader_id=op.uploader_id,
            uploader_name=op.uploader_name,
            sentiment=op.sentiment,
            stance=op.stance,
            opinion=op.opinion,
            video_id=op.video_id,
            video_title=op.video_title,
        ))

    # 按热度排序，取 Top
    sorted_clusters = sorted(clusters.values(), key=lambda x: x["heat"], reverse=True)[:limit]
    items = [
        TopicClusterItem(
            topic=c["topic"],
            heat=c["heat"],
            video_count=len(c["video_ids"]),
            opinions=c["opinions"][:20],  # 单话题最多展示 20 条观点
        )
        for c in sorted_clusters
    ]
    return TopicClustersOut(items=items)


# ---------- 3.6.5 播放 Top 视频 ----------

@router.get("/insights/top-videos", response_model=TopVideosOut)
def top_videos(
    days: int = Query(7, ge=1, le=90),
    by: str = Query("views", pattern="^(views|likes|danmaku)$"),
    limit: int = Query(5, ge=1, le=50),
    db: Session = Depends(get_db),
) -> TopVideosOut:
    start, end = _parse_days(days)

    sort_col = {
        "views": VideoStatsSnapshot.views,
        "likes": VideoStatsSnapshot.likes,
        "danmaku": VideoStatsSnapshot.danmaku_count,
    }[by]

    rows = db.execute(
        select(VideoStatsSnapshot, Uploader)
        .join(Uploader, VideoStatsSnapshot.uploader_id == Uploader.id)
        .where(VideoStatsSnapshot.date >= start, VideoStatsSnapshot.date <= end)
        .order_by(sort_col.desc())
        .limit(limit)
    ).all()

    items = []
    for snapshot, uploader in rows:
        items.append(VideoDetailOut(
            id=snapshot.video_id,
            bvid=snapshot.bvid,
            uploader_id=snapshot.uploader_id,
            title=snapshot.title,
            cover_url=None,
            duration_sec=0,
            published_at=snapshot.published_at,
            views=snapshot.views,
            danmaku_count=snapshot.danmaku_count,
            likes=snapshot.likes,
            tags=[],
            status="summarized",
            has_subtitle=True,
            has_summary=True,
            uploader=UploaderOut.model_validate(uploader),
            created_at=snapshot.published_at,
        ))

    return TopVideosOut(items=items)
