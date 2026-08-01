"""Pydantic 请求/响应模型，对齐接口文档字段（snake_case）。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Base(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ---------- UP主 ----------

class UploaderOut(_Base):
    id: str
    bilibili_uid: str
    name: str
    avatar_url: Optional[str] = None
    fans_count: int = 0
    category: Optional[str] = None
    description: Optional[str] = None
    unread_count: int = 0
    last_video_at: Optional[datetime] = None
    group_id: Optional[str] = None
    notify_enabled: bool = True
    created_at: datetime


class UploaderListOut(_Base):
    items: list[UploaderOut]
    total: int


class UploaderCreateIn(_Base):
    bilibili_uid: str = Field(min_length=1, max_length=32)
    group_id: Optional[str] = None
    category: Optional[str] = Field(None, max_length=64)
    notify_enabled: bool = True


class UploaderUpdateIn(_Base):
    group_id: Optional[str] = None
    category: Optional[str] = Field(None, max_length=64)
    notify_enabled: Optional[bool] = None


class UploaderCreateOut(_Base):
    uploader: UploaderOut
    task_id: str


class UploaderPrioritizeLatestOut(_Base):
    enqueued_subtitle: int
    enqueued_summary: int
    task_ids: list[str]


class UploaderBackfillYearOut(_Base):
    task_id: str
    type: str
    days_back: int


# ---------- 搜索代理（3.1.2） ----------

class UploaderSearchItem(_Base):
    bilibili_uid: str
    name: str
    avatar_url: Optional[str] = None
    fans_count: int = 0
    description: Optional[str] = None
    already_followed: bool = False


class UploaderSearchOut(_Base):
    items: list[UploaderSearchItem]
    page: int
    has_more: bool


# ---------- 视频 ----------

class VideoOut(_Base):
    id: str
    bvid: str
    uploader_id: str
    title: str
    cover_url: Optional[str] = None
    duration_sec: int = 0
    published_at: datetime
    views: int = 0
    danmaku_count: int = 0
    likes: int = 0
    tags: list = []
    status: str
    has_subtitle: bool = False
    has_summary: bool = False


class VideoDetailOut(VideoOut):
    uploader: UploaderOut
    created_at: datetime


class VideoListOut(_Base):
    items: list[VideoOut]
    range: dict
    total: int


class RefreshOut(_Base):
    task_id: str
    type: str


class VideoSearchItem(_Base):
    bvid: str
    title: str
    cover_url: Optional[str] = None
    duration_sec: int = 0
    published_at: Optional[datetime] = None
    views: int = 0
    danmaku_count: int = 0
    likes: int = 0
    uploader_mid: Optional[str] = None
    uploader_name: str = ""
    uploader_avatar_url: Optional[str] = None


class VideoSearchOut(_Base):
    items: list[VideoSearchItem]
    page: int
    has_more: bool


class VideoSearchFetchItem(_Base):
    bvid: str = Field(min_length=1, max_length=20)
    title: Optional[str] = None


class VideoSearchFetchIn(_Base):
    items: list[VideoSearchFetchItem] = Field(min_length=1, max_length=50)


class VideoSearchFetchResult(_Base):
    bvid: str
    video_id: Optional[str] = None
    task_id: Optional[str] = None
    error: Optional[dict] = None


class VideoSearchFetchOut(_Base):
    task_ids: list[str]
    video_ids: list[str]
    results: list[VideoSearchFetchResult]


class VideoReadIn(_Base):
    video_ids: list[str] = Field(min_length=1, max_length=200)


class BackfillLikesIn(_Base):
    video_id: Optional[str] = None
    up_id: Optional[str] = None


# ---------- 任务 ----------

class TaskOut(_Base):
    task_id: str
    type: str
    status: str
    progress: int = 0
    ref_type: Optional[str] = None
    ref_id: Optional[str] = None
    ref_title: Optional[str] = None
    operation_label: str
    error: Optional[dict] = None
    priority: int = 0
    created_at: datetime
    finished_at: Optional[datetime] = None


class TaskListOut(_Base):
    items: list[TaskOut]
    total: int


class TaskStatsOut(_Base):
    subtitle_total: int
    subtitle_pending: int
    subtitle_completed: int
    subtitle_failed: int
    summary_total: int
    summary_pending: int
    summary_completed: int
    summary_failed: int


class RagIngestTaskOut(_Base):
    task_id: str
    type: str


class TaskCancelIn(_Base):
    task_type: str | list[str]

    @field_validator('task_type', mode='before')
    @classmethod
    def _ensure_list(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [v]
        return v


class TaskCancelOut(_Base):
    cancelled_task_ids: list[str]
    deleted_task_ids: list[str]


# ---------- 字幕 ----------

class SubtitleLine(_Base):
    start_sec: float
    end_sec: float
    text: str


class SubtitleOut(_Base):
    video_id: str
    language: str
    source: str
    lines: list
    fetched_at: datetime


class SubtitleFetchOut(_Base):
    task_id: str
    type: str


# ---------- 系统状态 ----------

class SystemStatusLLM(_Base):
    provider: str
    model: str
    available: bool


class SystemStatusStorage(_Base):
    db_mb: float
    subtitles_count: int


class SystemStatusOut(_Base):
    last_refresh_at: Optional[datetime] = None
    refresh_interval_sec: int
    running_tasks: int
    queued_tasks: int
    llm: SystemStatusLLM
    storage: SystemStatusStorage


class SystemConfigIn(_Base):
    refresh_interval_sec: Optional[int] = Field(None, ge=60, le=86400)
    summary_model: Optional[str] = Field(None, min_length=1, max_length=128)
    summary_template_id: Optional[str] = Field(None, min_length=1, max_length=32)
    auto_summarize: Optional[bool] = None
    bilibili_sessdata: Optional[str] = Field(None, max_length=512)


class SystemConfigOut(_Base):
    refresh_interval_sec: int
    summary_model: str
    summary_template_id: str
    auto_summarize: bool
    bilibili_sessdata: Optional[str] = None


# ---------- 调度 Job ----------

class JobCurrentTaskOut(_Base):
    task_id: str
    type: str
    status: str
    progress: int = 0
    ref_type: Optional[str] = None
    ref_id: Optional[str] = None
    title: Optional[str] = None
    operation_label: str


class JobOut(_Base):
    name: str
    label: str
    enabled: bool
    current: Optional[JobCurrentTaskOut] = None


class JobListOut(_Base):
    items: list[JobOut]


class JobUpdateIn(_Base):
    enabled: bool


# ---------- AI 总结（3.4） ----------

class StanceOut(_Base):
    label: str
    sentiment: str
    detail: str


class SummaryOut(_Base):
    video_id: str
    template_id: str
    brief: str
    points: list = []
    stance: StanceOut
    topics: list = []
    quote: str
    model: Optional[str] = None
    token_usage: dict = {}
    created_at: datetime


class SummaryTaskRef(_Base):
    task_id: str
    type: str


class SummaryCreateIn(_Base):
    template_id: Optional[str] = None
    model: Optional[str] = None
    force: bool = False


class SummaryCreateOut(_Base):
    task_id: str
    type: str
    chain: list[SummaryTaskRef] = []  # 自动级联的字幕获取任务（如有）


class SummaryRegenerateIn(_Base):
    template_id: Optional[str] = None
    model: Optional[str] = None


class SummaryRegenerateOut(_Base):
    task_id: str
    type: str


class BatchSummaryIn(_Base):
    video_ids: list[str] = Field(min_length=1, max_length=100)
    template_id: Optional[str] = None
    model: Optional[str] = None


class BatchSummaryOut(_Base):
    batch_id: str
    task_ids: list[str] = []


# ---------- 总结模板 ----------

class SummaryTemplateOut(_Base):
    id: str
    name: str
    is_default: bool = False
    prompt: str
    created_at: datetime
    updated_at: datetime


class SummaryTemplateIn(_Base):
    name: str = Field(min_length=1, max_length=128)
    prompt: str = Field(min_length=1)
    is_default: bool = False

# ---------- 洞察（3.6） ----------

class OverviewOut(_Base):
    monitored_uploaders: int
    week_new_videos: int
    week_new_videos_delta: int
    summarized_count: int
    summary_coverage: float
    hot_topic_count: int
    rising_topic_count: int


class TopicTrendOut(_Base):
    series: list[dict]
    topics: list[str]


class HotWordItem(_Base):
    word: str
    heat: int
    mention_count: int
    trend: str


class HotWordsOut(_Base):
    items: list[HotWordItem]


class TopicOpinionItem(_Base):
    uploader_id: str
    uploader_name: str
    sentiment: str
    stance: str
    opinion: str
    video_id: str
    video_title: str


class TopicClusterItem(_Base):
    topic: str
    heat: int
    video_count: int
    opinions: list[TopicOpinionItem]


class TopicClustersOut(_Base):
    items: list[TopicClusterItem]


class TopVideosOut(_Base):
    items: list[VideoDetailOut]
