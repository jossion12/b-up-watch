import { useEffect, useMemo, useState } from 'react'
import {
  Users, Video as VideoIcon, Sparkles, Flame, TrendingUp,
  ThumbsUp, Eye, BarChart3, MessagesSquare,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts'
import { insightsApi } from '@/lib/api'
import { pickColor } from '@/lib/format'
import type { Uploader, Video } from '@/types'
import type { OverviewOut, HotWordItem, TopicClusterItem } from '@/lib/api'

interface Props {
  uploaders: Uploader[]
  videos: Video[]
  onOpenVideo: (v: Video) => void
}

const SENTIMENT_STYLE: Record<string, string> = {
  positive: 'bg-emerald-500/10 text-emerald-600 border-emerald-200',
  negative: 'bg-red-500/10 text-red-600 border-red-200',
  neutral: 'bg-slate-500/10 text-slate-600 border-slate-200',
  mixed: 'bg-amber-500/10 text-amber-600 border-amber-200',
}

function WORD_SIZE(heat: number, max: number): string {
  const ratio = max > 0 ? heat / max : 0
  if (ratio > 0.85) return 'text-2xl px-4 py-2 font-bold'
  if (ratio > 0.65) return 'text-lg px-3.5 py-1.5 font-semibold'
  if (ratio > 0.45) return 'text-base px-3 py-1.5 font-medium'
  if (ratio > 0.25) return 'text-sm px-2.5 py-1'
  return 'text-xs px-2 py-1'
}

const CHART_COLORS = ['#FB7299', '#7C5CFF', '#23C39E', '#F5A623', '#00A1D6', '#FF8A3D']

export default function Insights({ uploaders, videos, onOpenVideo }: Props) {
  const upMap = useMemo(() => new Map(uploaders.map((u) => [u.id, u])), [uploaders])
  const [loading, setLoading] = useState(true)
  const [overview, setOverview] = useState<OverviewOut | null>(null)
  const [trend, setTrend] = useState<Record<string, any>[]>([])
  const [trendTopics, setTrendTopics] = useState<string[]>([])
  const [hotWords, setHotWords] = useState<HotWordItem[]>([])
  const [topicClusters, setTopicClusters] = useState<TopicClusterItem[]>([])
  const [topVideos, setTopVideos] = useState<Video[]>([])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    Promise.all([
      insightsApi.overview(7),
      insightsApi.topicTrend(7),
      insightsApi.hotWords(7, 20),
      insightsApi.topicClusters(7),
      insightsApi.topVideos(7, 'views', 5),
    ])
      .then(([ov, tr, hw, tc, tv]) => {
        if (cancelled) return
        setOverview(ov)
        setTrend(tr.series)
        setTrendTopics(tr.topics)
        setHotWords(hw.items)
        setTopicClusters(tc.items)
        setTopVideos(tv.items.map((v) => ({
          id: v.id,
          bvid: v.bvid,
          upId: v.uploader_id,
          title: v.title,
          duration: `${Math.floor((v.duration_sec || 0) / 60)}:${String((v.duration_sec || 0) % 60).padStart(2, '0')}`,
          dateGroup: new Date(v.published_at).toLocaleDateString('zh-CN', { month: 'long', day: 'numeric' }),
          time: new Date(v.published_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
          publishedAt: v.published_at,
          views: String(v.views),
          danmaku: String(v.danmaku_count),
          likes: String(v.likes),
          tags: [],
          status: 'summarized' as const,
          gradient: `from-${pickColor(v.uploader_id).replace('#', '')}-400 to-${pickColor(v.id).replace('#', '')}-600`,
          summary: undefined,
          subtitles: [],
        })))
      })
      .finally(() => setLoading(false))
    return () => {
      cancelled = true
    }
  }, [])

  const maxHeat = useMemo(() => Math.max(...hotWords.map((w) => w.heat), 1), [hotWords])

  const stats = overview
    ? [
        { icon: Users, label: '监控UP主', value: overview.monitored_uploaders, sub: `${uploaders.filter((u) => u.unread > 0).length} 位有更新`, color: 'text-sky-500 bg-sky-500/10' },
        { icon: VideoIcon, label: '本周新视频', value: overview.week_new_videos, sub: `较上周 ${overview.week_new_videos_delta >= 0 ? '+' : ''}${overview.week_new_videos_delta}`, color: 'text-violet-500 bg-violet-500/10' },
        { icon: Sparkles, label: '已生成总结', value: overview.summarized_count, sub: `覆盖率 ${Math.round(overview.summary_coverage * 100)}%`, color: 'text-primary bg-primary/10' },
        { icon: Flame, label: '热点话题', value: overview.hot_topic_count, sub: `${overview.rising_topic_count} 个持续升温`, color: 'text-amber-500 bg-amber-500/10' },
      ]
    : []

  return (
    <ScrollArea className="flex-1 h-full">
      <div className="p-5 space-y-5 max-w-[1200px] mx-auto">
        {/* 统计卡片 */}
        <div className="grid grid-cols-4 gap-3">
          {loading
            ? Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="rounded-xl border bg-card p-4 flex items-center gap-3">
                  <Skeleton className="h-10 w-10 rounded-lg" />
                  <div className="space-y-2">
                    <Skeleton className="h-6 w-16" />
                    <Skeleton className="h-3 w-24" />
                  </div>
                </div>
              ))
            : stats.map((s) => (
                <div key={s.label} className="rounded-xl border bg-card p-4 flex items-center gap-3">
                  <div className={cn('h-10 w-10 rounded-lg flex items-center justify-center shrink-0', s.color)}>
                    <s.icon className="h-5 w-5" />
                  </div>
                  <div className="min-w-0">
                    <div className="text-2xl font-bold leading-none">{s.value}</div>
                    <div className="text-xs text-muted-foreground mt-1">{s.label} · {s.sub}</div>
                  </div>
                </div>
              ))}
        </div>

        <div className="grid grid-cols-5 gap-5">
          {/* 趋势图 */}
          <div className="col-span-3 rounded-xl border bg-card p-4">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <TrendingUp className="h-4 w-4 text-primary" />
                <h3 className="font-semibold text-sm">话题热度趋势（近7天）</h3>
              </div>
              <span className="text-xs text-muted-foreground">基于已总结视频的话题标签统计</span>
            </div>
            <div className="h-[260px]">
              {loading ? (
                <Skeleton className="h-full w-full" />
              ) : (
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={trend} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                    <XAxis dataKey="date" tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" />
                    <YAxis tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" allowDecimals={false} />
                    <Tooltip
                      contentStyle={{
                        fontSize: 12,
                        borderRadius: 8,
                        border: '1px solid hsl(var(--border))',
                        background: 'hsl(var(--card))',
                      }}
                    />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    {trendTopics.map((k, i) => (
                      <Area
                        key={k}
                        type="monotone"
                        dataKey={k}
                        stackId="1"
                        stroke={CHART_COLORS[i % CHART_COLORS.length]}
                        fill={CHART_COLORS[i % CHART_COLORS.length]}
                        fillOpacity={0.35}
                      />
                    ))}
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>

          {/* 热词 */}
          <div className="col-span-2 rounded-xl border bg-card p-4 flex flex-col">
            <div className="flex items-center gap-2 mb-3">
              <Flame className="h-4 w-4 text-primary" />
              <h3 className="font-semibold text-sm">本周热词</h3>
            </div>
            <div className="flex-1 flex flex-wrap items-center justify-center content-center gap-2 py-2">
              {loading ? (
                <Skeleton className="h-32 w-full" />
              ) : (
                hotWords.map((w) => (
                  <button
                    key={w.word}
                    className={cn(
                      'rounded-full border transition-all hover:scale-105 hover:border-primary hover:text-primary',
                      WORD_SIZE(w.heat, maxHeat),
                      w.heat >= maxHeat * 0.85 ? 'bg-primary/10 border-primary/30 text-primary' : 'bg-muted/50 border-border'
                    )}
                    title={`热度 ${w.heat} · 环比 ${w.trend === 'up' ? '↑' : w.trend === 'down' ? '↓' : '—'}`}
                  >
                    {w.word}
                  </button>
                ))
              )}
            </div>
            <p className="text-[11px] text-muted-foreground text-center mt-2">字号越大代表本周提及频次越高</p>
          </div>
        </div>

        {/* 观点聚类 */}
        <div className="rounded-xl border bg-card p-4">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <MessagesSquare className="h-4 w-4 text-primary" />
              <h3 className="font-semibold text-sm">热点话题 · UP主观点聚类</h3>
            </div>
            <span className="text-xs text-muted-foreground">从 {overview?.summarized_count || videos.filter((v) => v.status === 'summarized').length} 条视频总结中提炼</span>
          </div>

          {loading ? (
            <div className="grid grid-cols-2 gap-4">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-48 w-full" />
              ))}
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-4">
              {topicClusters.map((t) => (
                <div key={t.topic} className="rounded-xl border bg-muted/30 p-4">
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-sm">{t.topic}</span>
                      <Badge className="bg-primary/10 text-primary border-pink-200 text-[10px] px-1.5 py-0 hover:bg-primary/10">
                        热度 {t.heat}
                      </Badge>
                    </div>
                    <span className="text-xs text-muted-foreground">{t.video_count} 个视频讨论</span>
                  </div>
                  <div className="space-y-2.5">
                    {t.opinions.slice(0, 4).map((o, i) => {
                      const up = upMap.get(o.uploader_id)
                      return (
                        <div key={i} className="flex gap-2.5 rounded-lg bg-card border p-3">
                          <span
                            className="shrink-0 h-7 w-7 rounded-full flex items-center justify-center text-[11px] text-white font-semibold"
                            style={{ backgroundColor: up?.color || pickColor(o.uploader_id) }}
                          >
                            {(up?.name || o.uploader_name).charAt(0)}
                          </span>
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-1.5 flex-wrap">
                              <span className="text-xs font-semibold">{up?.name || o.uploader_name}</span>
                              <Badge className={cn('text-[10px] px-1.5 py-0 border', SENTIMENT_STYLE[o.sentiment] || SENTIMENT_STYLE.neutral)}>
                                {o.stance}
                              </Badge>
                            </div>
                            <p className="text-xs leading-relaxed text-foreground/85 mt-1">{o.opinion}</p>
                            <p className="text-[11px] text-muted-foreground mt-1 truncate">来源：{o.video_title}</p>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 热门视频 */}
        <div className="rounded-xl border bg-card p-4">
          <div className="flex items-center gap-2 mb-3">
            <BarChart3 className="h-4 w-4 text-primary" />
            <h3 className="font-semibold text-sm">本周播放量 Top 5</h3>
          </div>
          <div className="divide-y">
            {loading
              ? Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-14 w-full my-2" />)
              : topVideos.map((v, i) => {
                  const up = upMap.get(v.upId)
                  return (
                    <button
                      key={v.id}
                      onClick={() => onOpenVideo(v)}
                      className="w-full flex items-center gap-3 py-2.5 text-left hover:bg-accent/50 rounded-lg px-2 transition-colors"
                    >
                      <span
                        className={cn(
                          'w-5 text-center text-sm font-bold',
                          i < 3 ? 'text-primary' : 'text-muted-foreground'
                        )}
                      >
                        {i + 1}
                      </span>
                      <div className={cn('h-10 w-16 rounded-md bg-gradient-to-br shrink-0 flex items-center justify-center', v.gradient)}>
                        <Eye className="h-3.5 w-3.5 text-white/80" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="text-sm truncate">{v.title}</div>
                        <div className="text-xs text-muted-foreground mt-0.5">{up?.name} · {v.dateGroup}</div>
                      </div>
                      <div className="flex items-center gap-3 text-xs text-muted-foreground shrink-0">
                        <span className="inline-flex items-center gap-1"><Eye className="h-3 w-3" /> {v.views}</span>
                        <span className="inline-flex items-center gap-1"><ThumbsUp className="h-3 w-3" /> {v.likes}</span>
                      </div>
                    </button>
                  )
                })}
          </div>
        </div>
      </div>
    </ScrollArea>
  )
}
