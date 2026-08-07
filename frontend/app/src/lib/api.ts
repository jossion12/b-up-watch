/** Backend API client. Base URL: /api/v1 (proxied by Vite in dev). */

const API_BASE = '/api/v1'

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const url = `${API_BASE}${path}`
  const res = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
    ...options,
  })
  if (!res.ok) {
    let err: any = { status: res.status, message: res.statusText }
    try {
      err = await res.json()
    } catch {
      // ignore
    }
    throw err
  }
  if (res.status === 204) {
    return undefined as T
  }
  return res.json() as Promise<T>
}

// ---------- UP主 ----------

export interface BackendUploader {
  id: string
  bilibili_uid: string
  name: string
  avatar_url?: string
  fans_count: number
  category?: string
  description?: string
  unread_count: number
  last_video_at?: string
  group_id?: string
  notify_enabled: boolean
  created_at: string
}

export interface UploaderCreateIn {
  bilibili_uid: string
  name?: string
  group_id?: string
  category?: string
  notify_enabled?: boolean
}

export interface UploaderUpdateIn {
  group_id?: string
  category?: string
  notify_enabled?: boolean
}

export interface UploaderPrioritizeLatestOut {
  enqueued_subtitle: number
  enqueued_summary: number
  task_ids: string[]
}

export interface UploaderBackfillYearOut {
  task_id: string
  type: string
  days_back: number
}

export const uploadersApi = {
  list: () => request<{ items: BackendUploader[]; total: number }>('/uploaders'),
  search: (q: string, page = 1) =>
    request<{ items: BackendUploader[]; page: number; has_more: boolean }>(
      `/uploaders/search?q=${encodeURIComponent(q)}&page=${page}`
    ),
  create: (payload: UploaderCreateIn) =>
    request<{ uploader: BackendUploader; task_id: string }>('/uploaders', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  delete: (id: string, keepHistory = true) =>
    request<void>(`/uploaders/${id}?keep_history=${keepHistory}`, { method: 'DELETE' }),
  update: (id: string, payload: UploaderUpdateIn) =>
    request<BackendUploader>(`/uploaders/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  prioritizeLatest: (id: string, count = 10) =>
    request<UploaderPrioritizeLatestOut>(`/uploaders/${id}/prioritize-latest?count=${count}`, {
      method: 'POST',
    }),
  backfillYear: (id: string) =>
    request<UploaderBackfillYearOut>(`/uploaders/${id}/backfill-year`, {
      method: 'POST',
    }),
}

// ---------- 视频 ----------

export interface BackendVideo {
  id: string
  bvid: string
  uploader_id: string
  title: string
  cover_url?: string
  duration_sec: number
  published_at: string
  views: number
  danmaku_count: number
  likes: number
  tags: string[]
  status: 'new' | 'subtitled' | 'summarizing' | 'summarized' | 'failed'
  has_subtitle: boolean
  has_summary: boolean
  is_read: boolean
  created_at?: string
}

export interface BackendVideoDetail extends BackendVideo {
  uploader: BackendUploader
  created_at: string
}

export interface VideoListOut {
  items: BackendVideo[]
  range: { start_date: string; end_date: string }
  total: number
}

export interface BackendVideoSearchItem {
  bvid: string
  title: string
  cover_url?: string
  duration_sec: number
  published_at?: string
  views: number
  danmaku_count: number
  likes: number
  uploader_mid?: string
  uploader_name: string
  uploader_avatar_url?: string
}

export interface VideoSearchOut {
  items: BackendVideoSearchItem[]
  page: number
  has_more: boolean
}

export interface VideoSearchFetchItem {
  bvid: string
  title?: string
}

export interface VideoSearchFetchResult {
  bvid: string
  video_id?: string
  task_id?: string
  error?: { code: string; message: string }
}

export interface VideoSearchFetchOut {
  task_ids: string[]
  video_ids: string[]
  results: VideoSearchFetchResult[]
}

export const videosApi = {
  list: (params: {
    start_date: string
    end_date: string
    up_ids?: string[]
    category?: string[]
    status?: string[]
    limit?: number
  }) => {
    const sp = new URLSearchParams()
    sp.set('start_date', params.start_date)
    sp.set('end_date', params.end_date)
    if (params.up_ids?.length) sp.set('up_ids', params.up_ids.join(','))
    if (params.category?.length) sp.set('category', params.category.join(','))
    if (params.status?.length) sp.set('status', params.status.join(','))
    if (params.limit) sp.set('limit', String(params.limit))
    return request<VideoListOut>(`/videos?${sp.toString()}`)
  },
  get: (id: string) => request<BackendVideoDetail>(`/videos/${id}`),
  refresh: () => request<{ task_id: string; type: string }>('/videos/refresh', { method: 'POST' }),
  markRead: (videoIds: string[]) =>
    request<void>('/videos/read', {
      method: 'PATCH',
      body: JSON.stringify({ video_ids: videoIds }),
    }),
  backfillLikes: (payload: { video_id?: string; up_id?: string }) =>
    request<{ task_id: string; type: string }>('/videos/backfill-likes', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  search: (q: string, page = 1, order = '') =>
    request<VideoSearchOut>(
      `/videos/search?q=${encodeURIComponent(q)}&page=${page}&order=${encodeURIComponent(order)}`
    ),
  fetchSubtitles: (items: VideoSearchFetchItem[]) =>
    request<VideoSearchFetchOut>('/videos/search/fetch-subtitles', {
      method: 'POST',
      body: JSON.stringify({ items }),
    }),
}

// ---------- 字幕 ----------

export interface SubtitleLine {
  start_sec: number
  end_sec: number
  text: string
}

export interface BackendSubtitle {
  video_id: string
  language: string
  source: 'uploader' | 'bilibili_ai' | 'whisper'
  lines: SubtitleLine[]
  fetched_at: string
}

export const subtitlesApi = {
  get: (videoId: string) => request<BackendSubtitle>(`/videos/${videoId}/subtitle`),
  fetch: (videoId: string) =>
    request<{ task_id: string; type: string }>(`/videos/${videoId}/subtitle/fetch`, { method: 'POST' }),
  export: (videoId: string, format: 'srt' | 'txt' | 'json') =>
    window.open(`${API_BASE}/videos/${videoId}/subtitle/export?format=${format}`, '_blank'),
}

// ---------- 总结 ----------

export interface BackendSummary {
  video_id: string
  template_id: string
  brief: string
  points: string[]
  stance: {
    label: string
    sentiment: 'positive' | 'neutral' | 'negative' | 'mixed'
    detail: string
  }
  topics: string[]
  quote: string
  model?: string
  token_usage: { prompt?: number; completion?: number }
  created_at: string
}

export const summariesApi = {
  get: (videoId: string) => request<BackendSummary>(`/videos/${videoId}/summary`),
  create: (videoId: string, templateId?: string, model?: string, force = false) =>
    request<{ task_id: string; type: string; chain?: { task_id: string; type: string }[] }>(
      `/videos/${videoId}/summary`,
      {
        method: 'POST',
        body: JSON.stringify({ template_id: templateId, model, force }),
      }
    ),
  regenerate: (videoId: string, templateId?: string, model?: string) =>
    request<{ task_id: string; type: string }>(`/videos/${videoId}/summary/regenerate`, {
      method: 'POST',
      body: JSON.stringify({ template_id: templateId, model }),
    }),
}

// ---------- 任务 ----------

export interface BackendTask {
  task_id: string
  type: string
  status: 'pending' | 'running' | 'success' | 'failed'
  progress: number
  ref_type?: string
  ref_id?: string
  ref_title?: string
  operation_label: string
  error?: { code: string; message: string; details?: any }
  priority: number
  meta?: Record<string, any>
  created_at: string
  finished_at?: string
}

export interface TaskStatsOut {
  subtitle_total: number
  subtitle_pending: number
  subtitle_completed: number
  subtitle_failed: number
  summary_total: number
  summary_pending: number
  summary_completed: number
  summary_failed: number
}

export interface TaskCancelOut {
  cancelled_task_ids: string[]
  deleted_task_ids: string[]
}

export const tasksApi = {
  get: (taskId: string) => request<BackendTask>(`/tasks/${taskId}`),
  list: (status?: string[], limit?: number, type?: string) => {
    const sp = new URLSearchParams()
    if (status?.length) sp.set('status', status.join(','))
    if (limit) sp.set('limit', String(limit))
    if (type) sp.set('task_type', type)
    return request<{ items: BackendTask[]; total: number }>(`/tasks?${sp.toString()}`)
  },
  stats: () => request<TaskStatsOut>('/tasks/stats'),
  retry: (taskId: string) =>
    request<BackendTask>(`/tasks/${taskId}/retry`, { method: 'POST' }),
  cancelByType: (taskType: string | string[]) =>
    request<TaskCancelOut>('/tasks/cancel', {
      method: 'POST',
      body: JSON.stringify({ task_type: taskType }),
    }),
}

// ---------- 模板 ----------

export interface SummaryTemplate {
  id: string
  name: string
  is_default: boolean
  prompt: string
  created_at: string
  updated_at: string
}

export const templatesApi = {
  list: () => request<{ items: SummaryTemplate[] }>('/summary/templates'),
  create: (payload: { name: string; prompt: string; is_default?: boolean }) =>
    request<SummaryTemplate>('/summary/templates', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  update: (id: string, payload: { name: string; prompt: string; is_default?: boolean }) =>
    request<SummaryTemplate>(`/summary/templates/${id}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  delete: (id: string) => request<void>(`/summary/templates/${id}`, { method: 'DELETE' }),
}

// ---------- 洞察 ----------

export interface OverviewOut {
  monitored_uploaders: number
  week_new_videos: number
  week_new_videos_delta: number
  summarized_count: number
  summary_coverage: number
  hot_topic_count: number
  rising_topic_count: number
}

export interface TopicTrendOut {
  series: Record<string, any>[]
  topics: string[]
}

export interface HotWordItem {
  word: string
  heat: number
  mention_count: number
  trend: 'up' | 'down' | 'flat'
}

export interface TopicOpinionItem {
  uploader_id: string
  uploader_name: string
  sentiment: string
  stance: string
  opinion: string
  video_id: string
  video_title: string
}

export interface TopicClusterItem {
  topic: string
  heat: number
  video_count: number
  opinions: TopicOpinionItem[]
}

export interface TopVideosOut {
  items: BackendVideoDetail[]
}

export const insightsApi = {
  overview: (days = 7) => request<OverviewOut>(`/insights/overview?days=${days}`),
  topicTrend: (days = 7) => request<TopicTrendOut>(`/insights/topic-trend?days=${days}`),
  hotWords: (days = 7, limit = 20) =>
    request<{ items: HotWordItem[] }>(`/insights/hot-words?days=${days}&limit=${limit}`),
  topicClusters: (days = 7) =>
    request<{ items: TopicClusterItem[] }>(`/insights/topic-clusters?days=${days}`),
  topVideos: (days = 7, by: 'views' | 'likes' | 'danmaku' = 'views', limit = 5) =>
    request<TopVideosOut>(`/insights/top-videos?days=${days}&by=${by}&limit=${limit}`),
}

// ---------- 系统 ----------

export interface SystemStatus {
  last_refresh_at?: string
  refresh_interval_sec: number
  running_tasks: number
  queued_tasks: number
  llm: { provider: string; model: string; available: boolean }
  storage: { db_mb: number; subtitles_count: number }
  bilibili_login?: boolean | null
}

export interface SystemConfig {
  refresh_interval_sec: number
  summary_model: string
  summary_template_id: string
  auto_summarize: boolean
  bilibili_sessdata?: string | null
  bilibili_cookie?: string | null
}

export const systemApi = {
  status: () => request<SystemStatus>('/system/status'),
  config: () => request<SystemConfig>('/system/config'),
  updateConfig: (payload: Partial<SystemConfig>) =>
    request<SystemConfig>('/system/config', {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
}

// ---------- Job 调度 ----------

export interface JobCurrentTask {
  task_id: string
  type: string
  status: string
  progress: number
  ref_type?: string
  ref_id?: string
  title?: string
  operation_label: string
}

export interface JobItem {
  name: string
  label: string
  enabled: boolean
  current?: JobCurrentTask | null
}

export interface JobListOut {
  items: JobItem[]
}

export const jobsApi = {
  list: () => request<JobListOut>('/system/jobs'),
  update: (name: string, enabled: boolean) =>
    request<JobItem>(`/system/jobs/${name}`, {
      method: 'PATCH',
      body: JSON.stringify({ enabled }),
    }),
}

// ---------- UP 复盘 RAG ----------

export interface RagChunkMetadata {
  video_title: string
  up_name: string
  date?: string
  time_position?: string
  content_type?: string
  argument_role?: string
  core_topic?: string
  stance_type?: string
  confidence?: string
  verifiability?: string
  source_type?: string
  sub_topics?: string[]
  original_arguments?: string[]
}

export interface RagSearchItem {
  chunk_id: string
  content: string
  distance: number
  metadata: RagChunkMetadata
}

export interface RagChatChunk extends RagSearchItem {}

export interface RagIngestOut {
  task_id: string
  type: string
}

export interface RagSearchOut {
  items: RagSearchItem[]
}

export interface RagChatOut {
  answer: string
  chunks: RagChatChunk[]
  token_usage?: Record<string, any>
}

export interface RagStatsOut {
  total_chunks: number
}

export const ragApi = {
  ingest: (uploaderId: string) =>
    request<RagIngestOut>(`/rag/up/${uploaderId}/ingest`, { method: 'POST' }),
  search: (uploaderId: string, q: string, n = 5) =>
    request<RagSearchOut>(
      `/rag/up/${uploaderId}/search?q=${encodeURIComponent(q)}&n=${n}`
    ),
  chat: (uploaderId: string, question: string, n_results = 5) =>
    request<RagChatOut>(`/rag/up/${uploaderId}/chat`, {
      method: 'POST',
      body: JSON.stringify({ question, n_results }),
    }),
  stats: (uploaderId: string) =>
    request<RagStatsOut>(`/rag/up/${uploaderId}/stats`),
}
