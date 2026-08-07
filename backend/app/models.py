"""SQLAlchemy 数据模型。

按接口文档第 2 节定义；所有业务表均预留 user_id（单用户版恒为 'default'）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db import Base

# 单用户占位 ID
DEFAULT_USER_ID = "default"


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ============== UP主 ==============

class Uploader(Base):
    __tablename__ = "uploaders"
    __table_args__ = (
        UniqueConstraint("user_id", "bilibili_uid", name="uq_uploader_user_uid"),
        Index("ix_uploader_user_group", "user_id", "group_id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # uuid 字符串
    user_id: Mapped[str] = mapped_column(String(32), default=DEFAULT_USER_ID, nullable=False)
    bilibili_uid: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(512))
    fans_count: Mapped[int] = mapped_column(Integer, default=0)
    category: Mapped[Optional[str]] = mapped_column(String(64))
    description: Mapped[Optional[str]] = mapped_column(Text)
    unread_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_video_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    group_id: Mapped[Optional[str]] = mapped_column(String(32))
    notify_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # RagFlow 侧资源 ID，由 rag_ingest 任务维护
    ragflow_dataset_id: Mapped[Optional[str]] = mapped_column(String(64))
    ragflow_chat_id: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    videos: Mapped[list["Video"]] = relationship(back_populates="uploader", cascade="all, delete-orphan")


# ============== 视频 ==============

VIDEO_STATUS = ("new", "subtitled", "summarizing", "summarized", "failed")


class Video(Base):
    __tablename__ = "videos"
    __table_args__ = (
        UniqueConstraint("user_id", "bvid", name="uq_video_user_bvid"),
        Index("ix_video_user_pub", "user_id", "published_at"),
        Index("ix_video_uploader_pub", "uploader_id", "published_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), default=DEFAULT_USER_ID, nullable=False)
    bvid: Mapped[str] = mapped_column(String(20), nullable=False)
    uploader_id: Mapped[str] = mapped_column(ForeignKey("uploaders.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    cover_url: Mapped[Optional[str]] = mapped_column(String(512))
    duration_sec: Mapped[int] = mapped_column(Integer, default=0)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    views: Mapped[int] = mapped_column(Integer, default=0)
    danmaku_count: Mapped[int] = mapped_column(Integer, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(Enum(*VIDEO_STATUS, name="video_status"), default="new", nullable=False)
    has_subtitle: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_summary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    uploader: Mapped[Uploader] = relationship(back_populates="videos")
    subtitle: Mapped[Optional["Subtitle"]] = relationship(back_populates="video", uselist=False, cascade="all, delete-orphan")
    summary: Mapped[Optional["Summary"]] = relationship(back_populates="video", uselist=False, cascade="all, delete-orphan")


# ============== 字幕 ==============

SUBTITLE_SOURCE = ("uploader", "bilibili_ai", "whisper")


class Subtitle(Base):
    __tablename__ = "subtitles"

    video_id: Mapped[str] = mapped_column(ForeignKey("videos.id"), primary_key=True)
    language: Mapped[str] = mapped_column(String(16), default="zh-CN", nullable=False)
    source: Mapped[str] = mapped_column(Enum(*SUBTITLE_SOURCE, name="subtitle_source"), nullable=False)
    lines: Mapped[list] = mapped_column(JSON, default=list)  # [{"start_sec":..., "end_sec":..., "text":...}]
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    video: Mapped[Video] = relationship(back_populates="subtitle")


# ============== 总结 ==============

class Summary(Base):
    __tablename__ = "summaries"

    video_id: Mapped[str] = mapped_column(ForeignKey("videos.id"), primary_key=True)
    template_id: Mapped[str] = mapped_column(String(32), nullable=False)
    brief: Mapped[str] = mapped_column(Text, default="")
    points: Mapped[list] = mapped_column(JSON, default=list)
    stance: Mapped[dict] = mapped_column(JSON, default=dict)
    topics: Mapped[list] = mapped_column(JSON, default=list)
    quote: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[Optional[str]] = mapped_column(String(64))
    token_usage: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    video: Mapped[Video] = relationship(back_populates="summary")


# ============== 总结模板 ==============

class SummaryTemplate(Base):
    __tablename__ = "summary_templates"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


# ============== 任务 ==============

TASK_TYPE = ("subtitle_fetch", "ai_summary", "feed_refresh", "whisper_transcribe", "video_stats_refresh", "rag_ingest")
TASK_STATUS = ("pending", "running", "success", "failed")


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_task_status_created", "status", "created_at"),
        Index("ix_task_ref", "ref_type", "ref_id"),
    )

    task_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    type: Mapped[str] = mapped_column(Enum(*TASK_TYPE, name="task_type"), nullable=False)
    status: Mapped[str] = mapped_column(Enum(*TASK_STATUS, name="task_status"), default="pending", nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    ref_type: Mapped[Optional[str]] = mapped_column(String(16))  # 'video' / 'uploader'
    ref_id: Mapped[Optional[str]] = mapped_column(String(32))
    meta: Mapped[Optional[dict]] = mapped_column(JSON)  # 任务级参数，如 template_id/model
    error: Mapped[Optional[dict]] = mapped_column(JSON)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


# ============== 系统配置（单行） ==============

class SystemConfig(Base):
    __tablename__ = "system_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    refresh_interval_sec: Mapped[int] = mapped_column(Integer, default=600, nullable=False)
    summary_model: Mapped[str] = mapped_column(String(64), default="qwen3-235b-a22b-instruct", nullable=False)
    summary_template_id: Mapped[str] = mapped_column(String(32), default="tpl_default", nullable=False)
    auto_summarize: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    bilibili_sessdata: Mapped[Optional[str]] = mapped_column(String(512), default=None)
    bilibili_cookie: Mapped[Optional[str]] = mapped_column(Text, default=None)
    last_refresh_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


# ============== 洞察聚合表 ==============

class TopicDailyStat(Base):
    __tablename__ = "topic_daily_stats"
    __table_args__ = (
        UniqueConstraint("video_id", "topic", name="uq_topic_daily_stat_video_topic"),
        Index("ix_topic_daily_stat_date", "date"),
        Index("ix_topic_daily_stat_topic", "topic"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_id: Mapped[str] = mapped_column(String(32), nullable=False)
    date: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD
    topic: Mapped[str] = mapped_column(String(64), nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class TopicOpinion(Base):
    __tablename__ = "topic_opinions"
    __table_args__ = (
        UniqueConstraint("video_id", "topic", name="uq_topic_opinion_video_topic"),
        Index("ix_topic_opinion_topic", "topic"),
        Index("ix_topic_opinion_date", "date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_id: Mapped[str] = mapped_column(String(32), nullable=False)
    topic: Mapped[str] = mapped_column(String(64), nullable=False)
    uploader_id: Mapped[str] = mapped_column(String(32), nullable=False)
    uploader_name: Mapped[str] = mapped_column(String(128), nullable=False)
    sentiment: Mapped[str] = mapped_column(String(16), nullable=False)
    stance: Mapped[str] = mapped_column(Text, default="")
    opinion: Mapped[str] = mapped_column(Text, default="")
    video_title: Mapped[str] = mapped_column(String(512), nullable=False)
    date: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class VideoStatsSnapshot(Base):
    __tablename__ = "video_stats_snapshot"
    __table_args__ = (
        Index("ix_video_stats_snapshot_date", "date"),
        Index("ix_video_stats_snapshot_uploader", "uploader_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    bvid: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    uploader_id: Mapped[str] = mapped_column(String(32), nullable=False)
    uploader_name: Mapped[str] = mapped_column(String(128), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    views: Mapped[int] = mapped_column(Integer, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    danmaku_count: Mapped[int] = mapped_column(Integer, default=0)
    date: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
