import { useEffect, useMemo, useState } from 'react'
import { Activity, Loader2, Clock, Film, Sparkles, Flame } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Switch } from '@/components/ui/switch'
import { Progress } from '@/components/ui/progress'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { jobsApi, tasksApi, type JobItem, type BackendTask, type TaskStatsOut } from '@/lib/api'
import type { Uploader, Video } from '@/types'

const JOB_ICONS: Record<string, string> = {
  subtitle: '📝',
  summary: '✨',
  backfill: '📚',
}

const TASK_STATUS_LABEL: Record<string, string> = {
  pending: '等待中',
  running: '执行中',
  success: '已完成',
  failed: '失败',
}

const TASK_TYPE_LABEL: Record<string, string> = {
  subtitle_fetch: '字幕抓取',
  whisper_transcribe: 'Whisper 转写',
  ai_summary: 'AI 总结',
  feed_refresh: '刷新订阅',
  video_stats_refresh: '数据更新',
}

interface JobsProps {
  videos: Video[]
  uploaders: Uploader[]
}

export default function Jobs({ videos, uploaders }: JobsProps) {
  const [jobs, setJobs] = useState<JobItem[]>([])
  const [loading, setLoading] = useState(true)
  const [updating, setUpdating] = useState<Record<string, boolean>>({})
  const [error, setError] = useState<string | null>(null)

  const [tasks, setTasks] = useState<BackendTask[]>([])
  const [tasksLoading, setTasksLoading] = useState(true)
  const [tasksError, setTasksError] = useState<string | null>(null)

  const [stats, setStats] = useState<TaskStatsOut | null>(null)
  const [statsLoading, setStatsLoading] = useState(true)

  const loadJobs = async () => {
    try {
      const res = await jobsApi.list()
      setJobs(res.items)
      setError(null)
    } catch (e: any) {
      setError(e?.error?.message || '加载任务调度状态失败')
    } finally {
      setLoading(false)
    }
  }

  const loadTasks = async () => {
    try {
      const res = await tasksApi.list(['pending', 'running'])
      setTasks(res.items)
      setTasksError(null)
    } catch (e: any) {
      setTasksError(e?.error?.message || '加载任务队列失败')
    } finally {
      setTasksLoading(false)
    }
  }

  const loadStats = async () => {
    try {
      const res = await tasksApi.stats()
      setStats(res)
    } catch {
      // 统计失败不阻塞主界面
    } finally {
      setStatsLoading(false)
    }
  }

  useEffect(() => {
    loadJobs()
    loadTasks()
    loadStats()
    const id = setInterval(() => {
      loadJobs()
      loadTasks()
      loadStats()
    }, 2000)
    return () => clearInterval(id)
  }, [])

  const toggleJob = async (job: JobItem) => {
    setUpdating((prev) => ({ ...prev, [job.name]: true }))
    try {
      const updated = await jobsApi.update(job.name, !job.enabled)
      setJobs((prev) => prev.map((j) => (j.name === updated.name ? updated : j)))
    } catch (e: any) {
      setError(e?.error?.message || '更新任务状态失败')
    } finally {
      setUpdating((prev) => ({ ...prev, [job.name]: false }))
    }
  }

  const subtitleTasks = useMemo(
    () => tasks.filter((t) => t.type === 'subtitle_fetch' || t.type === 'whisper_transcribe'),
    [tasks]
  )
  const summaryTasks = useMemo(() => tasks.filter((t) => t.type === 'ai_summary'), [tasks])

  const resolveRefTitle = (task: BackendTask): string | null => {
    if (!task.ref_id) return null
    if (task.ref_type === 'video') {
      const v = videos.find((x) => x.id === task.ref_id)
      return v?.title || null
    }
    if (task.ref_type === 'uploader') {
      const u = uploaders.find((x) => x.id === task.ref_id)
      return u?.name || null
    }
    return null
  }

  const QueueCard = ({
    icon: Icon,
    title,
    tasks,
    emptyText,
    accent,
  }: {
    icon: React.ElementType
    title: string
    tasks: BackendTask[]
    emptyText: string
    accent: string
  }) => (
    <Card className="flex flex-col h-full">
      <CardHeader className="pb-3">
        <div className="flex items-center gap-2">
          <Icon className={`h-4 w-4 ${accent}`} />
          <CardTitle className="text-base">{title}</CardTitle>
          <Badge variant="secondary" className="ml-auto text-xs">
            {tasks.length}
          </Badge>
        </div>
        <CardDescription className="text-xs">待执行 + 执行中</CardDescription>
      </CardHeader>
      <CardContent className="flex-1 min-h-0 p-0">
        {tasks.length === 0 ? (
          <div className="h-32 flex items-center justify-center text-sm text-muted-foreground">
            {tasksLoading ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
            {emptyText}
          </div>
        ) : (
          <ScrollArea className="h-[360px] px-6 pb-6">
            <div className="space-y-3 pt-1">
              {tasks.map((task) => {
                const title = resolveRefTitle(task)
                return (
                  <div
                    key={task.task_id}
                    className="rounded-lg border bg-card p-3 space-y-2"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2 min-w-0">
                        <Badge
                          variant={task.status === 'running' ? 'default' : 'outline'}
                          className="shrink-0 text-xs"
                        >
                          {TASK_STATUS_LABEL[task.status] || task.status}
                        </Badge>
                        <span className="text-sm truncate" title={TASK_TYPE_LABEL[task.type] || task.type}>
                          {TASK_TYPE_LABEL[task.type] || task.type}
                        </span>
                        {task.priority > 0 && (
                          <Badge className="gap-0.5 bg-amber-500/10 text-amber-600 border-amber-200 hover:bg-amber-500/10 text-[10px] px-1">
                            <Flame className="h-2.5 w-2.5" /> 优先
                          </Badge>
                        )}
                      </div>
                      <span className="text-xs text-muted-foreground shrink-0">
                        {task.progress}%
                      </span>
                    </div>
                    {title && (
                      <p className="text-xs text-muted-foreground line-clamp-2" title={title}>
                        {title}
                      </p>
                    )}
                    {task.status === 'running' && (
                      <Progress value={task.progress} className="h-1.5" />
                    )}
                    <div className="flex items-center gap-1 text-[10px] text-muted-foreground">
                      <Clock className="h-3 w-3" />
                      {new Date(task.created_at).toLocaleString('zh-CN')}
                    </div>
                  </div>
                )
              })}
            </div>
          </ScrollArea>
        )}
      </CardContent>
    </Card>
  )

  return (
    <div className="h-full flex flex-col bg-background">
      <header className="h-14 border-b bg-card flex items-center px-4 gap-3 shrink-0">
        <Activity className="h-4 w-4 text-muted-foreground" />
        <h1 className="font-semibold text-sm">任务调度</h1>
        {(error || tasksError) && (
          <span className="text-xs text-red-500 ml-auto">
            {error || tasksError}
          </span>
        )}
      </header>

      <main className="flex-1 overflow-auto p-4">
        <div className="max-w-6xl mx-auto space-y-6">
          {/* 调度任务开关 */}
          {loading && jobs.length === 0 ? (
            <div className="flex items-center justify-center h-40 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin mr-2" /> 加载中...
            </div>
          ) : (
            <div className="grid gap-4 md:grid-cols-3">
              {jobs.map((job) => (
                <Card key={job.name} className={job.enabled ? '' : 'opacity-80'}>
                  <CardHeader>
                    <div className="flex items-start justify-between">
                      <div>
                        <CardTitle className="text-base flex items-center gap-2">
                          <span>{JOB_ICONS[job.name] || '⚙️'}</span>
                          {job.label}
                        </CardTitle>
                        <CardDescription className="mt-1.5">
                          {job.enabled ? '启用中' : '已暂停'}
                        </CardDescription>
                      </div>
                      <Switch
                        checked={job.enabled}
                        disabled={updating[job.name]}
                        onCheckedChange={() => toggleJob(job)}
                      />
                    </div>
                  </CardHeader>
                  <CardContent>
                    {job.current ? (
                      <div className="space-y-3">
                        <div className="flex items-center justify-between">
                          <Badge variant="secondary" className="text-xs">
                            {job.current.operation_label}
                          </Badge>
                          <span className="text-xs text-muted-foreground">
                            {job.current.progress}%
                          </span>
                        </div>
                        {job.current.title && (
                          <p className="text-sm line-clamp-2" title={job.current.title}>
                            {job.current.ref_type === 'uploader' ? 'UP主：' : ''}
                            {job.current.title}
                          </p>
                        )}
                        <Progress value={job.current.progress} />
                      </div>
                    ) : (
                      <div className="h-[72px] flex items-center justify-center text-sm text-muted-foreground">
                        空闲
                      </div>
                    )}
                  </CardContent>
                </Card>
              ))}
            </div>
          )}

          {/* 任务统计 */}
          <div className="grid gap-4 md:grid-cols-2">
            <Card>
              <CardHeader className="pb-3">
                <div className="flex items-center gap-2">
                  <Film className="h-4 w-4 text-blue-500" />
                  <CardTitle className="text-base">字幕抓取</CardTitle>
                </div>
              </CardHeader>
              <CardContent>
                <div className="flex items-center gap-6">
                  <div>
                    <div className="text-2xl font-semibold">
                      {statsLoading || !stats ? (
                        <Loader2 className="h-5 w-5 animate-spin" />
                      ) : (
                        stats.subtitle_total
                      )}
                    </div>
                    <div className="text-xs text-muted-foreground">总数</div>
                  </div>
                  <div>
                    <div className="text-2xl font-semibold">
                      {statsLoading || !stats ? (
                        <Loader2 className="h-5 w-5 animate-spin" />
                      ) : (
                        stats.subtitle_pending
                      )}
                    </div>
                    <div className="text-xs text-muted-foreground">待执行</div>
                  </div>
                  <div>
                    <div className="text-2xl font-semibold">
                      {statsLoading || !stats ? (
                        <Loader2 className="h-5 w-5 animate-spin" />
                      ) : (
                        stats.subtitle_completed
                      )}
                    </div>
                    <div className="text-xs text-muted-foreground">已完成</div>
                  </div>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-3">
                <div className="flex items-center gap-2">
                  <Sparkles className="h-4 w-4 text-amber-500" />
                  <CardTitle className="text-base">AI 总结</CardTitle>
                </div>
              </CardHeader>
              <CardContent>
                <div className="flex items-center gap-6">
                  <div>
                    <div className="text-2xl font-semibold">
                      {statsLoading || !stats ? (
                        <Loader2 className="h-5 w-5 animate-spin" />
                      ) : (
                        stats.summary_total
                      )}
                    </div>
                    <div className="text-xs text-muted-foreground">总数</div>
                  </div>
                  <div>
                    <div className="text-2xl font-semibold">
                      {statsLoading || !stats ? (
                        <Loader2 className="h-5 w-5 animate-spin" />
                      ) : (
                        stats.summary_pending
                      )}
                    </div>
                    <div className="text-xs text-muted-foreground">待执行</div>
                  </div>
                  <div>
                    <div className="text-2xl font-semibold">
                      {statsLoading || !stats ? (
                        <Loader2 className="h-5 w-5 animate-spin" />
                      ) : (
                        stats.summary_completed
                      )}
                    </div>
                    <div className="text-xs text-muted-foreground">已完成</div>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* 待执行队列 */}
          <div className="grid gap-4 md:grid-cols-2">
            <QueueCard
              icon={Film}
              title="字幕抓取队列"
              tasks={subtitleTasks}
              emptyText="暂无字幕相关任务"
              accent="text-blue-500"
            />
            <QueueCard
              icon={Sparkles}
              title="AI 总结队列"
              tasks={summaryTasks}
              emptyText="暂无 AI 总结任务"
              accent="text-amber-500"
            />
          </div>
        </div>
      </main>
    </div>
  )
}
