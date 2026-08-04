import { useMemo } from 'react'
import {
  Clock, List, CalendarDays,
  ChevronLeft, ChevronRight, CalendarClock,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { videoTime } from '@/lib/format'
import type { Video, Uploader } from '@/types'

interface Props {
  videos: Video[]
  uploaders: Uploader[]
  currentMonth: Date
  onMonthChange: (d: Date) => void
  onOpenVideo: (v: Video) => void
  filterUpIds: Set<string>
  filterCategories?: Set<string>
  mode: 'swimlane' | 'list' | 'month'
  onModeChange: (m: 'swimlane' | 'list' | 'month') => void
}

const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六']
const MS_PER_DAY = 86400000

function StatusDot({ status }: { status: Video['status'] }) {
  const cls =
    status === 'summarized'
      ? 'bg-emerald-500'
      : status === 'downloaded'
        ? 'bg-sky-500'
        : 'bg-primary'
  return <span className={cn('h-1.5 w-1.5 rounded-full', cls)} />
}

function getCalendarDays(month: Date) {
  const year = month.getFullYear()
  const monthIdx = month.getMonth()
  const firstDay = new Date(year, monthIdx, 1)
  const startOffset = firstDay.getDay()

  const start = new Date(firstDay.getTime() - startOffset * MS_PER_DAY)
  const cells: Date[] = []
  // 6 行 * 7 列足够覆盖所有月份布局
  for (let i = 0; i < 42; i++) {
    cells.push(new Date(start.getTime() + i * MS_PER_DAY))
  }
  return { cells, year, monthIdx }
}

function isSameDay(a: Date, b: Date) {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  )
}

export default function MonthlyTimeline({
  videos,
  uploaders,
  currentMonth,
  onMonthChange,
  onOpenVideo,
  filterUpIds,
  filterCategories = new Set(),
  mode,
  onModeChange,
}: Props) {
  const upMap = useMemo(() => new Map(uploaders.map((u) => [u.id, u])), [uploaders])

  const { cells, year, monthIdx } = useMemo(() => getCalendarDays(currentMonth), [currentMonth])

  const videosByDay = useMemo(() => {
    let list = videos
    if (filterUpIds.size > 0) {
      list = list.filter((v) => filterUpIds.has(v.upId))
    }
    if (filterCategories.size > 0) {
      list = list.filter((v) => {
        const up = upMap.get(v.upId)
        return up && filterCategories.has(up.category)
      })
    }

    const map = new Map<number, Video[]>()
    for (const v of list) {
      const t = videoTime(v)
      const key = new Date(t.getFullYear(), t.getMonth(), t.getDate()).getTime()
      const arr = map.get(key) ?? []
      arr.push(v)
      map.set(key, arr)
    }
    return map
  }, [videos, filterUpIds, filterCategories, upMap])

  const today = new Date()
  today.setHours(0, 0, 0, 0)

  const changeMonth = (delta: number) => {
    const d = new Date(currentMonth)
    d.setMonth(d.getMonth() + delta)
    onMonthChange(d)
  }

  const goToToday = () => {
    onMonthChange(new Date())
  }

  const monthLabel = `${year}年${monthIdx + 1}月`
  const totalCount = Array.from(videosByDay.values()).reduce((s, arr) => s + arr.length, 0)

  return (
    <div className="flex-1 flex flex-col min-w-0 h-full">
      {/* 工具栏 */}
      <div className="px-5 pt-4 pb-3 flex items-center justify-between gap-3">
        <div>
          <h2 className="font-semibold">视频时间线</h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            {filterUpIds.size > 0
              ? `已筛选 ${filterUpIds.size} 位UP主`
              : filterCategories.size > 0
                ? `已筛选 ${filterCategories.size} 种类型`
                : '全部UP主'}
            {' · '}
            {monthLabel} 共 {totalCount} 条更新
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1 rounded-lg bg-muted p-1">
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={() => changeMonth(-1)}
              title="上一月"
              className="h-7 w-7"
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <span className="text-xs font-medium min-w-[80px] text-center">{monthLabel}</span>
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={() => changeMonth(1)}
              title="下一月"
              className="h-7 w-7"
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={goToToday}
            className="flex items-center gap-1.5 rounded-lg bg-muted px-3 py-1.5 text-xs font-medium text-muted-foreground hover:text-foreground"
          >
            <CalendarClock className="h-3.5 w-3.5" /> 回到今天
          </Button>
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
            <button
              onClick={() => onModeChange('month')}
              className={cn(
                'flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium transition-colors',
                mode === 'month' ? 'bg-card shadow-sm' : 'text-muted-foreground hover:text-foreground'
              )}
            >
              <CalendarDays className="h-3 w-3" /> 月视图
            </button>
          </div>
        </div>
      </div>

      {/* 月历 */}
      <div className="flex-1 overflow-auto px-5 pb-5">
        <div className="grid grid-cols-7 border rounded-lg overflow-hidden min-h-full">
          {WEEKDAYS.map((w, i) => (
            <div
              key={w}
              className={cn(
                'text-center text-xs font-medium text-muted-foreground py-2 bg-muted/50 border-r border-b last:border-r-0',
                i === 0 && 'text-rose-500',
                i === 6 && 'text-sky-500'
              )}
            >
              {w}
            </div>
          ))}
          {cells.map((day, i) => {
            const inMonth = day.getMonth() === monthIdx && day.getFullYear() === year
            const isToday = isSameDay(day, today)
            const dayOfWeek = day.getDay()
            const isSunday = dayOfWeek === 0
            const isSaturday = dayOfWeek === 6
            const dayVideos = videosByDay.get(day.getTime()) ?? []

            return (
              <div
                key={i}
                className={cn(
                  'min-h-[120px] border-r border-b p-2 flex flex-col gap-1.5 transition-colors',
                  (i + 1) % 7 === 0 && 'border-r-0',
                  i >= 35 && 'border-b-0',
                  isSunday && 'bg-rose-50/50 dark:bg-muted/40',
                  isSaturday && 'bg-sky-50/50 dark:bg-muted/20',
                  !inMonth && 'bg-muted/60',
                  isToday && 'bg-primary/[0.04]'
                )}
              >
                <div className="flex items-center justify-between">
                  <span
                    className={cn(
                      'text-xs font-medium h-5 w-5 flex items-center justify-center rounded-full',
                      isToday
                        ? 'bg-primary text-primary-foreground'
                        : inMonth
                          ? 'text-foreground'
                          : 'text-muted-foreground/60'
                    )}
                  >
                    {day.getDate()}
                  </span>
                  {dayVideos.length > 0 && (
                    <Badge variant="secondary" className="text-[9px] h-4 px-1">
                      {dayVideos.length}
                    </Badge>
                  )}
                </div>

                <div className="flex-1 flex flex-col gap-1 overflow-y-auto">
                  {dayVideos.slice(0, 3).map((v) => {
                    const up = upMap.get(v.upId)
                    return (
                      <div
                        key={v.id}
                        onClick={() => onOpenVideo(v)}
                        className="flex items-center gap-1.5 px-1.5 py-1 rounded bg-card border hover:border-primary/40 hover:shadow-sm cursor-pointer transition-all group"
                      >
                        <StatusDot status={v.status} />
                        <span
                          className="h-4 w-4 rounded-full flex items-center justify-center text-[8px] text-white font-semibold shrink-0"
                          style={{ backgroundColor: up?.color }}
                        >
                          {up?.name.charAt(0)}
                        </span>
                        <span className="text-[10px] line-clamp-1 flex-1">{v.title}</span>
                      </div>
                    )
                  })}
                  {dayVideos.length > 3 && (
                    <div className="text-[9px] text-muted-foreground px-1">+{dayVideos.length - 3} 条</div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
