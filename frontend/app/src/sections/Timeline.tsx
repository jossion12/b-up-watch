import { useMemo, useState } from 'react'
import { Play, Eye, MessageSquare, ThumbsUp, Sparkles, Download, CircleDot, Clock, List } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { videoTime } from '@/lib/format'
import type { Video, Uploader } from '@/types'

function getDateLabels(now: Date) {
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const labels: string[] = ['今天', '昨天']
  for (let i = 2; i <= 30; i++) {
    const d = new Date(today.getTime() - i * 86400000)
    labels.push(`${d.getMonth() + 1}月${d.getDate()}日`)
  }
  return labels
}

interface Props {
  videos: Video[]
  uploaders: Uploader[]
  onOpenVideo: (v: Video) => void
  filterUpIds: Set<string>
  mode: 'swimlane' | 'list'
  onModeChange: (m: 'swimlane' | 'list') => void
  now: Date
}

const RANGE_OPTIONS = [
  { key: 'all', label: '全部' },
  { key: 'today', label: '今天' },
  { key: '3d', label: '近3天' },
  { key: 'week', label: '本周' },
] as const

function StatusBadge({ status }: { status: Video['status'] }) {
  if (status === 'summarized')
    return (
      <Badge className="gap-1 bg-emerald-500/10 text-emerald-600 border-emerald-200 hover:bg-emerald-500/10 text-[10px] px-1.5 py-0">
        <Sparkles className="h-2.5 w-2.5" /> 已总结
      </Badge>
    )
  if (status === 'downloaded')
    return (
      <Badge className="gap-1 bg-sky-500/10 text-sky-600 border-sky-200 hover:bg-sky-500/10 text-[10px] px-1.5 py-0">
        <Download className="h-2.5 w-2.5" /> 已下载
      </Badge>
    )
  return (
    <Badge className="gap-1 bg-primary/10 text-primary border-pink-200 hover:bg-primary/10 text-[10px] px-1.5 py-0">
      <CircleDot className="h-2.5 w-2.5" /> 新发布
    </Badge>
  )
}

export default function Timeline({ videos, uploaders, onOpenVideo, filterUpIds, mode, onModeChange, now }: Props) {
  const [range, setRange] = useState<string>('all')

  const upMap = useMemo(() => new Map(uploaders.map((u) => [u.id, u])), [uploaders])

  const labels = useMemo(() => getDateLabels(now), [now])

  const filtered = useMemo(() => {
    let list = videos
    if (filterUpIds.size > 0) list = list.filter((v) => filterUpIds.has(v.upId))
    if (range === 'today') list = list.filter((v) => v.dateGroup === labels[0])
    else if (range === '3d') list = list.filter((v) => labels.slice(0, 3).includes(v.dateGroup))
    return list
  }, [videos, filterUpIds, range, labels])

  const groups = useMemo(() => {
    const map = new Map<string, Video[]>()
    for (const v of filtered) {
      const arr = map.get(v.dateGroup) ?? []
      arr.push(v)
      map.set(v.dateGroup, arr)
    }
    return Array.from(map.entries())
      .map(([label, items]) => ({
        label,
        items,
        t: Math.max(...items.map((v) => videoTime(v).getTime())),
      }))
      .sort((a, b) => b.t - a.t)
  }, [filtered])

  return (
    <div className="flex-1 flex flex-col min-w-0 h-full">
      {/* 工具栏 */}
      <div className="px-5 pt-4 pb-3 flex items-center justify-between gap-3">
        <div>
          <h2 className="font-semibold">视频时间线</h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            {filterUpIds.size > 0 ? `已筛选 ${filterUpIds.size} 位UP主` : '全部UP主'} · 共 {filtered.length} 条更新 · 点击卡片查看详情
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1 rounded-lg bg-muted p-1">
            {RANGE_OPTIONS.map((o) => (
              <button
                key={o.key}
                onClick={() => setRange(o.key)}
                className={cn(
                  'px-3 py-1 rounded-md text-xs font-medium transition-colors',
                  range === o.key ? 'bg-card shadow-sm text-foreground' : 'text-muted-foreground hover:text-foreground'
                )}
              >
                {o.label}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-1 rounded-lg bg-muted p-1">
            <button
              onClick={() => onModeChange('swimlane')}
              className={cn(
                'flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium transition-colors',
                mode === 'swimlane' ? 'bg-card shadow-sm' : 'text-muted-foreground hover:text-foreground'
              )}
            >
              <Clock className="h-3 w-3" /> 时间轴
            </button>
            <button
              onClick={() => onModeChange('list')}
              className={cn(
                'flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium transition-colors',
                mode === 'list' ? 'bg-card shadow-sm' : 'text-muted-foreground hover:text-foreground'
              )}
            >
              <List className="h-3 w-3" /> 列表
            </button>
          </div>
        </div>
      </div>

      {/* 列表 */}
      <div className="flex-1 overflow-auto">
        <div className="px-5 pb-8 max-w-[980px] mx-auto">
          {groups.map((group) => (
            <div key={group.label} className="relative">
              <div className="sticky top-0 z-10 bg-background/95 backdrop-blur py-2 flex items-center gap-2">
                <div className="h-2.5 w-2.5 rounded-full bg-primary shrink-0" />
                <span className="text-sm font-semibold">{group.label}</span>
                <span className="text-xs text-muted-foreground">{group.items.length} 条</span>
                <div className="flex-1 h-px bg-border ml-2" />
              </div>

              <div className="ml-[5px] border-l-2 border-border/70 pl-5 space-y-3 pb-5">
                {group.items.map((v) => {
                  const up = upMap.get(v.upId)
                  return (
                    <button
                      key={v.id}
                      onClick={() => onOpenVideo(v)}
                      className="w-full text-left rounded-xl border bg-card p-3 flex gap-3 transition-all hover:shadow-md hover:border-primary/40"
                    >
                      <div
                        className={cn(
                          'relative w-40 aspect-video rounded-lg bg-gradient-to-br shrink-0 flex items-center justify-center overflow-hidden',
                          v.gradient
                        )}
                      >
                        <Play className="h-8 w-8 text-white/80 fill-white/80" />
                        <span className="absolute bottom-1.5 right-1.5 rounded bg-black/70 text-white text-[10px] px-1.5 py-0.5 font-medium">
                          {v.duration}
                        </span>
                      </div>

                      <div className="flex-1 min-w-0 flex flex-col">
                        <div className="flex items-start gap-2">
                          <h3 className="text-sm font-medium leading-snug line-clamp-2 flex-1">{v.title}</h3>
                          <StatusBadge status={v.status} />
                        </div>
                        <div className="mt-1.5 flex items-center gap-1.5 text-xs text-muted-foreground">
                          <span
                            className="inline-flex items-center justify-center h-4.5 w-4.5 rounded-full text-[9px] text-white font-semibold"
                            style={{ backgroundColor: up?.color }}
                          >
                            {up?.name.charAt(0)}
                          </span>
                          <span className="font-medium text-foreground/80">{up?.name}</span>
                          <span>·</span>
                          <span>{v.time}</span>
                        </div>
                        <div className="mt-auto pt-2 flex items-center gap-3 text-xs text-muted-foreground">
                          <span className="inline-flex items-center gap-1">
                            <Eye className="h-3 w-3" /> {v.views}
                          </span>
                          <span className="inline-flex items-center gap-1">
                            <MessageSquare className="h-3 w-3" /> {v.danmaku}
                          </span>
                          <span className="inline-flex items-center gap-1">
                            <ThumbsUp className="h-3 w-3" /> {v.likes}
                          </span>
                          <span className="flex-1" />
                          {v.tags.slice(0, 3).map((t) => (
                            <span key={t} className="rounded bg-muted px-1.5 py-0.5 text-[10px]">
                              {t}
                            </span>
                          ))}
                        </div>
                      </div>
                    </button>
                  )
                })}
              </div>
            </div>
          ))}

          {groups.length === 0 && (
            <div className="py-20 text-center text-sm text-muted-foreground">该时间范围内没有更新</div>
          )}
        </div>
      </div>
    </div>
  )
}
