"""洞察聚合写入侧。

在每次总结完成后增量更新三张聚合表：
- topic_daily_stats：每日话题命中次数
- topic_opinions：按话题聚合的观点
- video_stats_snapshot：Top 视频榜快照

使用 video_id 级粒度，支持重新生成总结时覆盖旧聚合。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import Summary, TopicDailyStat, TopicOpinion, Video, VideoStatsSnapshot

log = logging.getLogger(__name__)


def _date_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def update_insights_for_summary(db: Session, video: Video, summary: Summary) -> None:
    """总结完成时调用：覆盖该视频旧的聚合数据并写入最新数据。"""
    if not summary.topics:
        log.debug("no topics for video %s, skip insights", video.id)
        # 仍然更新 video_stats_snapshot，因为榜单不依赖 topics

    date = _date_str(video.published_at)
    stance = summary.stance or {}
    opinion_text = stance.get("detail") or ""
    sentiment = stance.get("sentiment") or "neutral"
    stance_label = stance.get("label") or ""

    # 1. 清理旧聚合（覆盖模式，避免重新生成时重复计数）
    db.query(TopicDailyStat).filter(TopicDailyStat.video_id == video.id).delete()
    db.query(TopicOpinion).filter(TopicOpinion.video_id == video.id).delete()
    db.commit()

    # 2. 写入 topic_daily_stats / topic_opinions
    now = datetime.now(timezone.utc)
    uploader_name = video.uploader.name if video.uploader else ""
    for topic in summary.topics or []:
        topic = str(topic).strip()
        if not topic:
            continue
        db.add(TopicDailyStat(
            video_id=video.id,
            date=date,
            topic=topic,
            count=1,
            updated_at=now,
        ))
        db.add(TopicOpinion(
            video_id=video.id,
            topic=topic,
            uploader_id=video.uploader_id,
            uploader_name=uploader_name,
            sentiment=sentiment,
            stance=stance_label,
            opinion=opinion_text,
            video_title=video.title,
            date=date,
            updated_at=now,
        ))

    # 3. 写入/覆盖 video_stats_snapshot
    snapshot = db.query(VideoStatsSnapshot).filter_by(video_id=video.id).first()
    if snapshot is None:
        snapshot = VideoStatsSnapshot(video_id=video.id)
        db.add(snapshot)
    snapshot.bvid = video.bvid
    snapshot.title = video.title
    snapshot.uploader_id = video.uploader_id
    snapshot.uploader_name = uploader_name
    snapshot.published_at = video.published_at
    snapshot.views = video.views or 0
    snapshot.likes = video.likes or 0
    snapshot.danmaku_count = video.danmaku_count or 0
    snapshot.date = date
    snapshot.updated_at = now

    db.commit()
    log.info("insights updated for video %s: %d topics", video.id, len(summary.topics or []))
