import type { BackendUploader, BackendVideo, BackendSummary, BackendSubtitle } from './api'
import type { Uploader, Video, VideoSummary, SubtitleLine } from '@/types'

const COLORS = [
  '#FB7299', '#7C5CFF', '#00A1D6', '#FF8A3D', '#23C39E',
  '#F5A623', '#4A90D9', '#8B5CF6', '#FF5C7A', '#54B435',
  '#00B8A9', '#D96C4A', '#3B82F6', '#EC4899', '#10B981',
]

export function stringHash(str: string): number {
  let h = 0
  for (let i = 0; i < str.length; i++) {
    h = (h << 5) - h + str.charCodeAt(i)
    h |= 0
  }
  return Math.abs(h)
}

export function pickColor(seed: string): string {
  return COLORS[stringHash(seed) % COLORS.length]
}

export function formatFans(n: number): string {
  if (n >= 10000) return (n / 10000).toFixed(1).replace(/\.0$/, '') + '万'
  return String(n)
}

export function formatNumber(n: number): string {
  if (n >= 10000) return (n / 10000).toFixed(1).replace(/\.0$/, '') + '万'
  return String(n)
}

export function formatDuration(sec: number): string {
  sec = Math.max(0, sec | 0)
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  const s = sec % 60
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
  return `${m}:${String(s).padStart(2, '0')}`
}

export function formatRelativeTime(iso?: string): string {
  if (!iso) return '暂无更新'
  const then = new Date(iso)
  const now = new Date()
  const diff = now.getTime() - then.getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days} 天前`
  return then.toLocaleDateString('zh-CN')
}

export function formatDateGroup(iso: string, now: Date): { label: string; time: string } {
  const d = new Date(iso)
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const target = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  const diffDays = Math.round((today.getTime() - target.getTime()) / 86400000)

  let label: string
  if (diffDays === 0) label = '今天'
  else if (diffDays === 1) label = '昨天'
  else label = `${d.getMonth() + 1}月${d.getDate()}日`

  const time = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  return { label, time }
}

export function mapBackendStatus(status: BackendVideo['status']): Video['status'] {
  if (status === 'summarized') return 'summarized'
  if (status === 'new' || status === 'failed') return 'new'
  return 'downloaded'
}

export function mapUploader(u: BackendUploader): Uploader {
  return {
    id: u.id,
    name: u.name,
    fans: formatFans(u.fans_count),
    category: u.category || '未分类',
    color: pickColor(u.id),
    description: u.description || '',
    unread: u.unread_count,
    lastActive: formatRelativeTime(u.last_video_at),
  }
}

export function mapVideo(v: BackendVideo, now: Date): Video {
  const { label, time } = formatDateGroup(v.published_at, now)
  return {
    id: v.id,
    bvid: v.bvid,
    upId: v.uploader_id,
    title: v.title,
    duration: formatDuration(v.duration_sec),
    dateGroup: label,
    time,
    publishedAt: v.published_at,
    views: formatNumber(v.views),
    danmaku: formatNumber(v.danmaku_count),
    likes: formatNumber(v.likes),
    tags: v.tags || [],
    status: mapBackendStatus(v.status),
    gradient: `from-${toneFromColor(pickColor(v.id))}-400 to-${toneFromColor(pickColor(v.uploader_id))}-600`,
    cover: v.cover_url || undefined,
    summary: undefined,
    subtitles: [],
  }
}

export function mapSummary(s: BackendSummary): VideoSummary {
  return {
    brief: s.brief,
    points: s.points,
    stance: {
      label: s.stance.label,
      sentiment: s.stance.sentiment,
      detail: s.stance.detail,
    },
    topics: s.topics,
    quote: s.quote,
  }
}

export function mapSubtitles(lines: BackendSubtitle['lines']): SubtitleLine[] {
  return (lines || []).map((ln) => {
    const fmt = (sec: number) => {
      const h = Math.floor(sec / 3600)
      const m = Math.floor((sec % 3600) / 60)
      const s = Math.floor(sec % 60)
      if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
      return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
    }
    return { time: fmt(ln.start_sec), text: ln.text }
  })
}

/** 从 Video 中提取精确的发布时间，用于时间轴定位与排序。
 * 优先使用后端返回的 ISO 时间，避免依赖 mock 数据里的硬编码日期映射。
 */
export function videoTime(v: Video): Date {
  if (v.publishedAt) return new Date(v.publishedAt)

  // 兜底：根据 dateGroup + time 反向推导（主要用于未更新 publishedAt 的历史 mock 数据）
  const match = v.dateGroup.match(/^(\d{1,2})月(\d{1,2})日$/)
  const now = new Date()
  if (v.dateGroup === '今天') {
    return new Date(`${now.toISOString().split('T')[0]}T${v.time}:00`)
  }
  if (v.dateGroup === '昨天') {
    const y = new Date(now)
    y.setDate(y.getDate() - 1)
    return new Date(`${y.toISOString().split('T')[0]}T${v.time}:00`)
  }
  if (match) {
    const d = new Date(now.getFullYear(), parseInt(match[1], 10) - 1, parseInt(match[2], 10))
    const [hh, mm] = v.time.split(':').map(Number)
    d.setHours(hh, mm, 0, 0)
    return d
  }
  return new Date()
}

function toneFromColor(hex: string): string {
  // Map hex to a tailwind-ish color name. Used for gradient classes.
  const mapping: Record<string, string> = {
    '#FB7299': 'pink', '#7C5CFF': 'violet', '#00A1D6': 'cyan', '#FF8A3D': 'orange',
    '#23C39E': 'teal', '#F5A623': 'amber', '#4A90D9': 'blue', '#8B5CF6': 'violet',
    '#FF5C7A': 'rose', '#54B435': 'green', '#00B8A9': 'teal', '#D96C4A': 'orange',
    '#3B82F6': 'blue', '#EC4899': 'pink', '#10B981': 'emerald',
  }
  return mapping[hex] || 'slate'
}
