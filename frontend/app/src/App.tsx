import { useEffect, useMemo, useState } from 'react'
import { Routes, Route, useNavigate } from 'react-router'
import { Tv, LayoutList, LineChart, Activity, RefreshCw, Bell, Settings, Loader2 } from 'lucide-react'
import AddUploaderDialog from '@/sections/AddUploaderDialog'
import { cn } from '@/lib/utils'
import SwimlaneTimeline from '@/sections/SwimlaneTimeline'
import Timeline from '@/sections/Timeline'
import Insights from '@/sections/Insights'
import Jobs from '@/sections/Jobs'
import VideoPage from '@/sections/VideoPage'
import UpFilter from '@/sections/UpFilter'
import CategoryFilter from '@/sections/CategoryFilter'
import { uploadersApi, videosApi, systemApi } from '@/lib/api'
import { mapUploader, mapVideo } from '@/lib/format'
import { useWebSocket } from '@/hooks/useWebSocket'
import type { Uploader, Video } from '@/types'
import type { BackendVideo } from '@/lib/api'

type View = 'timeline' | 'insights'

const NOW = new Date()

function formatDate(d: Date) {
  return d.toISOString().split('T')[0]
}

export default function App() {
  const navigate = useNavigate()
  const [view, setView] = useState<View>('timeline')
  const [centerMode, setCenterMode] = useState<'swimlane' | 'list'>('swimlane')
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
    } else if (msg.event === 'summary.completed') {
      setVideos((prev) =>
        prev.map((v) => (v.id === msg.payload.video_id ? { ...v, status: 'summarized' } : v))
      )
      loadStatus()
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

  const handleSummarized = (id: string) => {
    setVideos((prev) => prev.map((v) => (v.id === id ? { ...v, status: 'summarized' } : v)))
  }

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

              {/* 视图切换 */}
              <div className="flex items-center gap-1 rounded-lg bg-muted p-1 ml-6">
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
                <button
                  onClick={() => navigate('/jobs')}
                  className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-md text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
                >
                  <Activity className="h-3.5 w-3.5" /> 任务
                </button>
              </div>

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
                <button className="h-8 w-8 rounded-lg flex items-center justify-center hover:bg-accent hover:text-foreground transition-colors" title="设置">
                  <Settings className="h-4 w-4" />
                </button>
              </div>
            </header>

            {/* 主体 */}
            <div className="flex-1 flex min-h-0">
              {view === 'timeline' ? (
                centerMode === 'swimlane' ? (
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
                )
              ) : (
                <Insights uploaders={uploaders} videos={filteredVideos} onOpenVideo={handleOpenVideo} />
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
            onSummarized={handleSummarized}
          />
        }
      />
      <Route path="/jobs" element={<Jobs videos={videos} uploaders={uploaders} />} />
    </Routes>
  )
}
