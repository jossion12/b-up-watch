import { useMemo, useRef, useState, useEffect, useLayoutEffect } from 'react'
import {
  Play, Eye, MessageSquare, ThumbsUp, Clock, List, Sparkles, Download, CircleDot,
  CalendarClock, ZoomIn, ZoomOut, MousePointer2,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { HoverCard, HoverCardContent, HoverCardTrigger } from '@/components/ui/hover-card'
import { cn } from '@/lib/utils'
import { videoTime } from '@/lib/format'
import type { Video, Uploader } from '@/types'

interface Props {
  videos: Video[]
  uploaders: Uploader[]
  selectedVideoId: string | null
  onSelectVideo: (v: Video) => void
  onOpenVideo: (v: Video) => void
  filterUpIds: Set<string>
  filterCategories?: Set<string>
  mode: 'swimlane' | 'list'
  onModeChange: (m: 'swimlane' | 'list') => void
  now: Date
  onLoadOlder?: (days: number) => void | Promise<void>
}

const MS_PER_DAY = 86400000
const LABEL_W = 176
const ROW_H = 84
// 默认显示 21 天，确保在常见分辨率下时间线宽于视口，从而可以拖动
const INITIAL_DAYS = 21
const EXTEND_DAYS = 7
// 最大回溯 365 天，拖动到边缘时动态加载更早数据
const MAX_BACK_DAYS = 365
const EDGE_THRESHOLD = 260

const ZOOM_LEVELS = [110, 150, 210]
const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

const STATUS_DOT: Record<Video['status'], { cls: string; label: string }> = {
  new: { cls: 'bg-primary', label: '新发布' },
  downloaded: { cls: 'bg-sky-500', label: '已下载' },
  summarized: { cls: 'bg-emerald-500', label: '已总结' },
}

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

export default function SwimlaneTimeline({
  videos,
  uploaders,
  selectedVideoId,
  onSelectVideo,
  onOpenVideo,
  filterUpIds,
  filterCategories = new Set(),
  mode,
  onModeChange,
  now,
  onLoadOlder,
}: Props) {
  const [zoomIdx, setZoomIdx] = useState(1)
  const dayWidth = ZOOM_LEVELS[zoomIdx]
  const [extraBackDays, setExtraBackDays] = useState(0)
  const [loadingOlder, setLoadingOlder] = useState(false)

  const scrollRef = useRef<HTMLDivElement>(null)
  const drag = useRef({ isDown: false, startX: 0, startY: 0, startSL: 0, startST: 0, moved: false })
  const suppressClick = useRef(false)
  const pendingExtend = useRef(0)

  /** 日期范围：从今天起向前 INITIAL_DAYS + 已扩展天数；向后预留 1 天 */
  const { days, start } = useMemo(() => {
    const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate())
    const totalBack = INITIAL_DAYS - 1 + extraBackDays
    const start = new Date(startOfToday.getTime() - totalBack * MS_PER_DAY)
    const total = totalBack + 1 + 1 // 过去 + 今天 + 未来1天
    const days = Array.from({ length: total }, (_, i) => new Date(start.getTime() + i * MS_PER_DAY))
    return { days, start }
  }, [extraBackDays, now])

  const xOf = (d: Date) => ((d.getTime() - start.getTime()) / MS_PER_DAY) * dayWidth

  const rows = useMemo(() => {
    let ups = uploaders
    if (filterUpIds.size > 0) {
      ups = ups.filter((u) => filterUpIds.has(u.id))
    }
    if (filterCategories.size > 0) {
      ups = ups.filter((u) => filterCategories.has(u.category))
    }
    return ups
      .map((up) => {
        const vids = videos
          .filter((v) => {
            if (v.upId !== up.id) return false
            const t = videoTime(v).getTime()
            return t >= start.getTime() && t <= now.getTime()
          })
          .sort((a, b) => videoTime(a).getTime() - videoTime(b).getTime())
        const latest = vids.length ? videoTime(vids[vids.length - 1]).getTime() : 0
        return { up, vids, latest }
      })
      .sort((a, b) => b.latest - a.latest)
  }, [uploaders, videos, filterUpIds, start, now])

  const totalCount = rows.reduce((s, r) => s + r.vids.length, 0)
  const nowX = xOf(now)
  const todayX = xOf(new Date(now.getFullYear(), now.getMonth(), now.getDate()))
  const trackW = days.length * dayWidth

  const ticks = useMemo(() => {
    const arr: { x: number; major: boolean }[] = []
    for (let i = 0; i <= days.length * 4; i++) {
      arr.push({ x: (i * dayWidth) / 4, major: i % 4 === 0 })
    }
    return arr
  }, [days.length, dayWidth])

  /** 初始滚动到最右（今天） */
  useLayoutEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollLeft = el.scrollWidth
  }, [])

  /** 向左扩展日期后，保持视觉位置不跳 */
  useLayoutEffect(() => {
    const el = scrollRef.current
    if (el && pendingExtend.current > 0) {
      el.scrollLeft += pendingExtend.current * EXTEND_DAYS * dayWidth
      pendingExtend.current = 0
    }
  }, [extraBackDays, dayWidth])

  /** 滚动到左边缘时加载更早的日期与数据 */
  const handleScroll = () => {
    const el = scrollRef.current
    if (!el) return
    if (el.scrollLeft < EDGE_THRESHOLD && extraBackDays < MAX_BACK_DAYS && !loadingOlder) {
      setLoadingOlder(true)
      pendingExtend.current += 1
      const promise = onLoadOlder?.(EXTEND_DAYS)
      setExtraBackDays((d) => Math.min(d + EXTEND_DAYS, MAX_BACK_DAYS))
      if (promise) {
        promise.finally(() => setLoadingOlder(false))
      } else {
        setLoadingOlder(false)
      }
    }
  }

  /** 拖拽平移 */
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      const d = drag.current
      if (!d.isDown) return
      const dx = e.clientX - d.startX
      const dy = e.clientY - d.startY
      if (Math.abs(dx) > 4 || Math.abs(dy) > 4) d.moved = true
      const el = scrollRef.current
      if (el) {
        el.scrollLeft = d.startSL - dx
        el.scrollTop = d.startST - dy
      }
    }
    const onUp = () => {
      if (drag.current.isDown && drag.current.moved) {
        suppressClick.current = true
        setTimeout(() => (suppressClick.current = false), 50)
      }
      drag.current.isDown = false
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [])

  const onMouseDown = (e: React.MouseEvent) => {
    const el = scrollRef.current
    if (!el) return
    drag.current = {
      isDown: true, moved: false,
      startX: e.clientX, startY: e.clientY,
      startSL: el.scrollLeft, startST: el.scrollTop,
    }
    document.body.style.cursor = 'grabbing'
    document.body.style.userSelect = 'none'
  }

  const scrollToToday = () => {
    const el = scrollRef.current
    if (el) el.scrollTo({ left: el.scrollWidth, behavior: 'smooth' })
  }

  const isTodayIdx = (i: number) => i === days.length - 2

  return (
    <div className="flex-1 flex flex-col min-w-0 h-full relative">
      {/* 工具栏 */}
      <div className="px-5 pt-4 pb-3 flex items-center justify-between gap-3">
        <div>
          <h2 className="font-semibold">视频时间线</h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            {filterUpIds.size > 0 ? `已筛选 ${filterUpIds.size} 位UP主` : '全部UP主'} · 范围内 {totalCount} 条更新 · 向左拖动查看更早
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1 rounded-lg bg-muted p-1">
            <button
              onClick={() => setZoomIdx((i) => Math.max(0, i - 1))}
              disabled={zoomIdx === 0}
              className="h-6 w-6 rounded-md flex items-center justify-center text-muted-foreground hover:text-foreground disabled:opacity-40"
              title="缩小时间刻度"
            >
              <ZoomOut className="h-3.5 w-3.5" />
            </button>
            <span className="text-[10px] text-muted-foreground w-8 text-center">{dayWidth}px</span>
            <button
              onClick={() => setZoomIdx((i) => Math.min(ZOOM_LEVELS.length - 1, i + 1))}
              disabled={zoomIdx === ZOOM_LEVELS.length - 1}
              className="h-6 w-6 rounded-md flex items-center justify-center text-muted-foreground hover:text-foreground disabled:opacity-40"
              title="放大时间刻度"
            >
              <ZoomIn className="h-3.5 w-3.5" />
            </button>
          </div>
          <button
            onClick={scrollToToday}
            className="flex items-center gap-1.5 rounded-lg bg-muted px-3 py-1.5 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
          >
            <CalendarClock className="h-3.5 w-3.5" /> 回到今天
          </button>
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

      {/* 时间轴主体（可拖拽） */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        onMouseDown={onMouseDown}
        className="flex-1 overflow-auto border-t cursor-grab active:cursor-grabbing"
      >
        <div style={{ width: LABEL_W + trackW }} className="min-w-full">
          {/* 表头：日期刻度 */}
          <div className="sticky top-0 z-30 flex bg-card border-b">
            <div
              className="sticky left-0 z-40 shrink-0 border-r bg-card px-4 flex items-center justify-between text-xs text-muted-foreground"
              style={{ width: LABEL_W, height: 44 }}
            >
              <span>UP主</span>
              <span className="flex items-center gap-1">
                <MousePointer2 className="h-3 w-3" /> 拖动平移
              </span>
            </div>
            {days.map((d, i) => {
              const isToday = isTodayIdx(i)
              const isFuture = i === days.length - 1
              return (
                <div
                  key={i}
                  className={cn(
                    'shrink-0 border-l border-border/60 px-3 flex flex-col justify-center',
                    isToday && 'bg-primary/5'
                  )}
                  style={{ width: dayWidth, height: 44 }}
                >
                  <span className={cn('text-xs font-semibold leading-none', isToday && 'text-primary', isFuture && 'text-muted-foreground/60')}>
                    {isToday ? '今天' : `${d.getMonth() + 1}/${d.getDate()}`}
                  </span>
                  <span className="text-[10px] text-muted-foreground mt-1 leading-none">
                    {isFuture ? '明天' : WEEKDAYS[d.getDay()]}
                  </span>
                </div>
              )
            })}
          </div>

          {/* 泳道区 */}
          <div className="relative">
            {ticks.map((t, i) => (
              <div
                key={i}
                className={cn('absolute top-0 bottom-0 w-px pointer-events-none', t.major ? 'bg-border/60' : 'bg-border/30')}
                style={{ left: LABEL_W + t.x }}
              />
            ))}
            <div
              className="absolute top-0 bottom-0 bg-primary/[0.035] pointer-events-none"
              style={{ left: LABEL_W + todayX, width: dayWidth }}
            />
            <div className="absolute top-0 bottom-0 z-20 pointer-events-none" style={{ left: LABEL_W + nowX }}>
              <div className="w-px h-full bg-primary/70" />
              <div className="absolute -top-0 -translate-x-1/2 h-1.5 w-1.5 rounded-full bg-primary" />
            </div>

            {rows.length === 0 && (
              <div className="py-20 text-center text-sm text-muted-foreground">没有匹配的UP主，请调整筛选条件</div>
            )}

            {rows.map(({ up, vids }) => (
              <div key={up.id} className="flex border-b" style={{ height: ROW_H }}>
                <div
                  className="sticky left-0 z-10 shrink-0 border-r bg-card px-3 flex items-center gap-2.5"
                  style={{ width: LABEL_W }}
                >
                  <span
                    className="h-8 w-8 rounded-full flex items-center justify-center text-xs text-white font-semibold shrink-0"
                    style={{ backgroundColor: up.color }}
                  >
                    {up.name.charAt(0)}
                  </span>
                  <div className="min-w-0">
                    <div className="text-xs font-semibold truncate">{up.name}</div>
                    <div className="text-[10px] text-muted-foreground mt-0.5">
                      {vids.length > 0 ? `${vids.length} 条更新` : '暂无更新'}
                    </div>
                  </div>
                  {up.unread > 0 && (
                    <span className="ml-auto h-4 min-w-4 px-1 rounded-full bg-primary text-primary-foreground text-[9px] font-semibold flex items-center justify-center shrink-0">
                      {up.unread}
                    </span>
                  )}
                </div>

                <div className="relative flex-1">
                  {vids.length === 0 && (
                    <span className="absolute inset-0 flex items-center pl-4 text-[11px] text-muted-foreground/50">
                      — 该时间段内无更新 —
                    </span>
                  )}
                  {vids.map((v) => {
                    const x = xOf(videoTime(v))
                    const active = selectedVideoId === v.id
                    return (
                      <HoverCard key={v.id} openDelay={80} closeDelay={120}>
                        <HoverCardTrigger asChild>
                          <button
                            onClick={() => {
                              if (suppressClick.current) return
                              onSelectVideo(v)
                            }}
                            onDoubleClick={() => {
                              if (suppressClick.current) return
                              onOpenVideo(v)
                            }}
                            className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 group"
                            style={{ left: x }}
                          >
                            <div
                              className={cn(
                                'relative w-[74px] aspect-video rounded-md bg-gradient-to-br flex items-center justify-center border shadow-sm transition-all group-hover:scale-110 group-hover:shadow-md group-hover:z-10',
                                v.gradient,
                                active ? 'ring-2 ring-primary ring-offset-2 border-primary' : 'border-white/60'
                              )}
                            >
                              <Play className="h-4 w-4 text-white fill-white drop-shadow" />
                              <span
                                className={cn(
                                  'absolute -top-1 -right-1 h-2.5 w-2.5 rounded-full border-2 border-card',
                                  STATUS_DOT[v.status].cls
                                )}
                              />
                            </div>
                            <div className="absolute top-full left-1/2 -translate-x-1/2 mt-1 text-[9px] text-muted-foreground whitespace-nowrap">
                              {v.dateGroup === '今天' || v.dateGroup === '昨天' ? `${v.dateGroup} ${v.time}` : v.time}
                            </div>
                          </button>
                        </HoverCardTrigger>
                        <HoverCardContent side="top" align="center" className="w-[320px] p-0 overflow-hidden">
                          <div className={cn('relative aspect-video bg-gradient-to-br flex items-center justify-center overflow-hidden', v.gradient)}>
                            {v.cover && (
                              <img
                                src={v.cover}
                                alt={v.title}
                                className="absolute inset-0 h-full w-full object-cover"
                                loading="lazy"
                                referrerPolicy="no-referrer"
                                onError={(e) => { e.currentTarget.style.display = 'none' }}
                              />
                            )}
                            <Play className="relative h-10 w-10 text-white/85 fill-white/85 drop-shadow" />
                            <span className="absolute bottom-2 right-2 rounded bg-black/70 text-white text-[10px] px-1.5 py-0.5 font-medium">
                              {v.duration}
                            </span>
                            <div className="absolute top-2 right-2">
                              <StatusBadge status={v.status} />
                            </div>
                          </div>
                          <div className="p-3 space-y-2">
                            <h4 className="text-sm font-semibold leading-snug">{v.title}</h4>
                            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                              <span
                                className="inline-flex items-center justify-center h-4 w-4 rounded-full text-[9px] text-white font-semibold"
                                style={{ backgroundColor: up.color }}
                              >
                                {up.name.charAt(0)}
                              </span>
                              <span className="font-medium text-foreground/80">{up.name}</span>
                              <span>·</span>
                              <span>{v.dateGroup} {v.time} 发布</span>
                            </div>
                            <div className="flex items-center gap-3 text-xs text-muted-foreground">
                              <span className="inline-flex items-center gap-1"><Eye className="h-3 w-3" /> {v.views}</span>
                              <span className="inline-flex items-center gap-1"><MessageSquare className="h-3 w-3" /> {v.danmaku}</span>
                              <span className="inline-flex items-center gap-1"><ThumbsUp className="h-3 w-3" /> {v.likes}</span>
                            </div>
                            <div className="flex items-center gap-1.5 flex-wrap">
                              {v.tags.map((t) => (
                                <span key={t} className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">{t}</span>
                              ))}
                            </div>
                            <p className="text-[10px] text-primary/80 pt-1 border-t">双击节点打开详情页 · 下载字幕</p>
                          </div>
                        </HoverCardContent>
                      </HoverCard>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
