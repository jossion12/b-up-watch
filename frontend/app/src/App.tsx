import { useEffect, useMemo, useState } from 'react'
import { Routes, Route, useNavigate } from 'react-router'
import { Tv, Activity, AlertCircle, RefreshCw, Bell, Loader2, Database, Search } from 'lucide-react'
import AddUploaderDialog from '@/sections/AddUploaderDialog'
import SettingsDialog from '@/sections/SettingsDialog'
// import { cn } from '@/lib/utils'
import SwimlaneTimeline from '@/sections/SwimlaneTimeline'
import Timeline from '@/sections/Timeline'
import MonthlyTimeline from '@/sections/MonthlyTimeline'
// AI 总结功能已暂停：隐藏洞察页
// import Insights from '@/sections/Insights'
import Jobs from '@/sections/Jobs'
import FailedTasks from '@/sections/FailedTasks'
import VideoPage from '@/sections/VideoPage'
import ReviewPage from '@/sections/ReviewPage'
import VideoSearchPage from '@/sections/VideoSearchPage'
import UpFilter from '@/sections/UpFilter'
import CategoryFilter from '@/sections/CategoryFilter'
import { uploadersApi, videosApi, systemApi } from '@/lib/api'
import { mapUploader, mapVideo } from '@/lib/format'
import { useWebSocket } from '@/hooks/useWebSocket'
import type { Uploader, Video } from '@/types'
import type { BackendVideo } from '@/lib/api'

const NOW = new Date()

function formatDate(d: Date) {
  return d.toISOString().split('T')[0]
}

export default function App() {
  const navigate = useNavigate()
  const [centerMode, setCenterMode] = useState<'swimlane' | 'list' | 'month'>('swimlane')
  const [currentMonth, setCurrentMonth] = useState<Date>(() => {
    const d = new Date(NOW)
    d.setDate(1)
    d.setHours(0, 0, 0, 0)
    return d
  })
  const [filterUpIds, setFilterUpIds] = useState<Set<string>>(new Set())
  const [filterCategories, setFilterCategories] = useState<Set<string>>(new Set())
  const [selectedVideoId, setSelectedVideoId] = useState<string | null>(null)

  const [uploaders, setUploaders] = useState<Uploader[]>([])
  const [videos, setVideos] = useState<Video[]>([])
  const [loading, setLoading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [lastRefreshAt, setLastRefreshAt] = useState<string | null>(null)
  const [runningTasks, setRunningTasks] = useState(0)
  const [queuedTasks, setQueuedTasks] = useState(0)
  const [error, setError] = useState<string | null>(null)

  // 时间线日期范围：默认最近 60 天，向左拖动时动态扩展
  const [startDate, setStartDate] = useState<Date>(() => {
    const d = new Date(NOW)
    d.setDate(d.getDate() - 60)
    return d
  })
  const endDate = NOW

  const mergeVideos = (older: Video[]) => {
    setVideos((prev) => {
      const map = new Map(prev.map((v) => [v.id, v]))
      for (const v of older) map.set(v.id, v)
      return Array.from(map.values())
    })
  }

  const loadUploaders = async () => {
    try {
      const res = await uploadersApi.list()
      setUploaders(res.items.map(mapUploader))
    } catch (e: any) {
      setError(e?.error?.message || '加载UP主失败')
    }
  }

  const loadVideos = async () => {
    try {
      const res = await videosApi.list({
        start_date: formatDate(startDate),
        end_date: formatDate(endDate),
        limit: 500,
      })
      setVideos(res.items.map((v: BackendVideo) => mapVideo(v, NOW)))
    } catch (e: any) {
      setError(e?.error?.message || '加载视频失败')
    }
  }

  const loadOlderVideos = async (days: number) => {
    const newStart = new Date(startDate)
    newStart.setDate(newStart.getDate() - days)
    try {
      const res = await videosApi.list({
        start_date: formatDate(newStart),
        end_date: formatDate(startDate),
        limit: 500,
      })
      mergeVideos(res.items.map((v: BackendVideo) => mapVideo(v, NOW)))
      setStartDate(newStart)
    } catch (e: any) {
      setError(e?.error?.message || '加载更早视频失败')
    }
  }

  const loadMonthVideos = async (month: Date) => {
    const start = new Date(month.getFullYear(), month.getMonth(), 1)
    const end = new Date(month.getFullYear(), month.getMonth() + 1, 0)
    try {
      const res = await videosApi.list({
        start_date: formatDate(start),
        end_date: formatDate(end),
        limit: 1000,
      })
      mergeVideos(res.items.map((v: BackendVideo) => mapVideo(v, NOW)))
    } catch (e: any) {
      setError(e?.error?.message || '加载月份视频失败')
    }
  }

  const loadStatus = async () => {
    try {
      const s = await systemApi.status()
      setLastRefreshAt(s.last_refresh_at || null)
      setRunningTasks(s.running_tasks)
      setQueuedTasks(s.queued_tasks)
    } catch {
      // ignore
    }
  }

  const refresh = async () => {
    setRefreshing(true)
    try {
      await videosApi.refresh()
      await loadStatus()
    } catch (e: any) {
      setError(e?.error?.message || '刷新失败')
    } finally {
      setRefreshing(false)
    }
  }

  useEffect(() => {
    setLoading(true)
    Promise.all([loadUploaders(), loadVideos(), loadStatus()]).finally(() => setLoading(false))
  }, [])

  // Poll status & running tasks every 3s
  useEffect(() => {
    const id = setInterval(() => {
      loadStatus()
      if (runningTasks > 0 || queuedTasks > 0) {
        loadVideos()
      }
    }, 3000)
    return () => clearInterval(id)
  }, [runningTasks, queuedTasks])

  useWebSocket((msg) => {
    if (msg.event === 'video.new') {
      setVideos((prev) => {
        const exists = prev.some((v) => v.id === msg.payload.id)
        if (exists) return prev
        return [mapVideo(msg.payload as BackendVideo, NOW), ...prev]
      })
      loadStatus()
    } else if (msg.event === 'uploader.unread') {
      setUploaders((prev) =>
        prev.map((u) => (u.id === msg.payload.uploader_id ? { ...u, unread: msg.payload.unread_count } : u))
      )
    // AI 总结功能已暂停
    // } else if (msg.event === 'summary.completed') {
    //   setVideos((prev) =>
    //     prev.map((v) => (v.id === msg.payload.video_id ? { ...v, status: 'summarized' } : v))
    //   )
    //   loadStatus()
    } else if (msg.event === 'task.updated') {
      loadStatus()
      if (msg.payload.status === 'success') {
        loadVideos()
      }
    }
  })

  const handleSelectVideo = (v: Video) => {
    setSelectedVideoId(v.id === selectedVideoId ? null : v.id)
  }

  const handleOpenVideo = (v: Video) => {
    navigate(`/video/${v.id}`)
  }

  const handleDownloadVideo = (id: string) => {
    setVideos((prev) => prev.map((v) => (v.id === id && v.status === 'new' ? { ...v, status: 'downloaded' } : v)))
  }

  // AI 总结功能已暂停
  // const handleSummarized = (id: string) => {
  //   setVideos((prev) => prev.map((v) => (v.id === id ? { ...v, status: 'summarized' } : v)))
  // }

  const filteredVideos = useMemo(() => {
    let list = videos
    if (filterUpIds.size > 0) {
      list = list.filter((v) => filterUpIds.has(v.upId))
    }
    if (filterCategories.size > 0) {
      list = list.filter((v) => {
        const up = uploaders.find((u) => u.id === v.upId)
        return up && filterCategories.has(up.category)
      })
    }
    return list
  }, [videos, filterUpIds, filterCategories, uploaders])

  return (
    <Routes>
      <Route
        path="/"
        element={
          <div className="h-screen flex flex-col bg-background overflow-hidden">
            {/* 顶栏 */}
            <header className="h-14 border-b bg-card flex items-center px-4 gap-4 shrink-0">
              <div className="flex items-center gap-2.5">
                <div className="h-8 w-8 rounded-lg bg-primary flex items-center justify-center">
                  <Tv className="h-4.5 w-4.5 text-primary-foreground" />
                </div>
                <div>
                  <div className="font-bold text-sm leading-none">UP雷达</div>
                  <div className="text-[10px] text-muted-foreground mt-0.5">Bilibili UP主监控台</div>
                </div>
              </div>

              {/* AI 总结功能已暂停：隐藏视图切换，仅保留时间线 */}
              {/* <div className="flex items-center gap-1 rounded-lg bg-muted p-1 ml-6">
                <button
                  onClick={() => setView('timeline')}
                  className={cn(
                    'flex items-center gap-1.5 px-3.5 py-1.5 rounded-md text-xs font-medium transition-colors',
                    view === 'timeline' ? 'bg-card shadow-sm' : 'text-muted-foreground hover:text-foreground'
                  )}
                >
                  <LayoutList className="h-3.5 w-3.5" /> 时间线
                </button>
                <button
                  onClick={() => setView('insights')}
                  className={cn(
                    'flex items-center gap-1.5 px-3.5 py-1.5 rounded-md text-xs font-medium transition-colors',
                    view === 'insights' ? 'bg-card shadow-sm' : 'text-muted-foreground hover:text-foreground'
                  )}
                >
                  <LineChart className="h-3.5 w-3.5" /> 洞察
                </button>
              </div> */}
              <button
                onClick={() => navigate('/jobs')}
                className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-md text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
              >
                <Activity className="h-3.5 w-3.5" /> 任务
              </button>
              <button
                onClick={() => navigate('/failed-tasks')}
                className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-md text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
              >
                <AlertCircle className="h-3.5 w-3.5" /> 失败任务
              </button>
              <button
                onClick={() => navigate('/video-search')}
                className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-md text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
              >
                <Search className="h-3.5 w-3.5" /> 视频搜索
              </button>
              <button
                onClick={() => {
                  const target = uploaders[0]?.id
                  navigate(target ? `/review/${target}` : '/')
                }}
                className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-md text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
              >
                <Database className="h-3.5 w-3.5" /> UP复盘
              </button>

              <div className="flex-1" />

              {error && <span className="text-xs text-red-500">{error}</span>}

              <CategoryFilter
                uploaders={uploaders}
                selected={filterCategories}
                onChange={setFilterCategories}
              />

              <UpFilter
                uploaders={uploaders}
                selected={filterUpIds}
                onChange={setFilterUpIds}
                onDelete={async (id) => {
                  await uploadersApi.delete(id)
                  setFilterUpIds((prev) => {
                    const next = new Set(prev)
                    next.delete(id)
                    return next
                  })
                  await loadUploaders()
                }}
                onUpdate={async (id, payload) => {
                  await uploadersApi.update(id, payload)
                  await loadUploaders()
                }}
              />

              <AddUploaderDialog
                onAdded={() => {
                  loadUploaders()
                  loadStatus()
                }}
              />

              <div className="flex items-center gap-1 text-muted-foreground">
                <span className="text-xs mr-2">
                  {loading ? '加载中...' : lastRefreshAt ? `上次更新：${new Date(lastRefreshAt).toLocaleString('zh-CN')}` : '未刷新'}
                </span>
                <button
                  onClick={refresh}
                  disabled={refreshing}
                  className="h-8 w-8 rounded-lg flex items-center justify-center hover:bg-accent hover:text-foreground transition-colors disabled:opacity-50"
                  title="立即刷新"
                >
                  {refreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                </button>
                <button className="h-8 w-8 rounded-lg flex items-center justify-center hover:bg-accent hover:text-foreground transition-colors relative" title="通知">
                  <Bell className="h-4 w-4" />
                  {(runningTasks > 0 || queuedTasks > 0) && (
                    <span className="absolute top-1.5 right-1.5 h-2 w-2 rounded-full bg-primary" />
                  )}
                </button>
                <SettingsDialog />
              </div>
            </header>

            {/* 主体 */}
            <div className="flex-1 flex min-h-0">
              {centerMode === 'month' ? (
                <MonthlyTimeline
                  videos={filteredVideos}
                  uploaders={uploaders}
                  currentMonth={currentMonth}
                  onMonthChange={(m) => {
                    setCurrentMonth(m)
                    loadMonthVideos(m)
                  }}
                  onOpenVideo={handleOpenVideo}
                  filterUpIds={filterUpIds}
                  filterCategories={filterCategories}
                  mode={centerMode}
                  onModeChange={setCenterMode}
                />
              ) : centerMode === 'swimlane' ? (
                <SwimlaneTimeline
                  videos={filteredVideos}
                  uploaders={uploaders}
                  selectedVideoId={selectedVideoId}
                  onSelectVideo={handleSelectVideo}
                  onOpenVideo={handleOpenVideo}
                  filterUpIds={filterUpIds}
                  filterCategories={filterCategories}
                  mode={centerMode}
                  onModeChange={setCenterMode}
                  now={NOW}
                  onLoadOlder={loadOlderVideos}
                />
              ) : (
                <Timeline
                  videos={filteredVideos}
                  uploaders={uploaders}
                  onOpenVideo={handleOpenVideo}
                  filterUpIds={filterUpIds}
                  filterCategories={filterCategories}
                  mode={centerMode}
                  onModeChange={setCenterMode}
                  now={NOW}
                />
              )}
            </div>
          </div>
        }
      />
      <Route
        path="/video/:id"
        element={
          <VideoPage
            videos={videos}
            uploaders={uploaders}
            onDownloadVideo={handleDownloadVideo}
          />
        }
      />
      <Route path="/jobs" element={<Jobs />} />
      <Route path="/failed-tasks" element={<FailedTasks />} />
      <Route path="/video-search" element={<VideoSearchPage />} />
      <Route
        path="/review/:uploaderId"
        element={<ReviewPage uploaders={uploaders} />}
      />
    </Routes>
  )
}
