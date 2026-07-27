import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router'
import { AlertCircle, ArrowLeft, Clock, Film, Loader2, RefreshCw, Sparkles } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { tasksApi, type BackendTask } from '@/lib/api'
import type { Uploader, Video } from '@/types'

const TASK_TYPE_LABEL: Record<string, string> = {
  subtitle_fetch: '字幕抓取',
  whisper_transcribe: 'Whisper 转写',
  ai_summary: 'AI 总结',
  feed_refresh: '刷新订阅',
  video_stats_refresh: '数据更新',
}

const TASK_TYPE_ICON: Record<string, React.ElementType> = {
  subtitle_fetch: Film,
  whisper_transcribe: Film,
  ai_summary: Sparkles,
  feed_refresh: RefreshCw,
  video_stats_refresh: RefreshCw,
}

interface FailedTasksProps {
  videos: Video[]
  uploaders: Uploader[]
}

export default function FailedTasks({ videos, uploaders }: FailedTasksProps) {
  const navigate = useNavigate()
  const [tasks, setTasks] = useState<BackendTask[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [retrying, setRetrying] = useState<Record<string, boolean>>({})
  const [lastAction, setLastAction] = useState<string | null>(null)

  const loadFailedTasks = async () => {
    try {
      const res = await tasksApi.list(['failed'], 100)
      setTasks(res.items)
      setError(null)
    } catch (e: any) {
      setError(e?.error?.message || '加载失败任务失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadFailedTasks()
    const id = setInterval(loadFailedTasks, 3000)
    return () => clearInterval(id)
  }, [])

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

  const handleRetry = async (task: BackendTask) => {
    setRetrying((prev) => ({ ...prev, [task.task_id]: true }))
    try {
      await tasksApi.retry(task.task_id)
      setTasks((prev) => prev.filter((t) => t.task_id !== task.task_id))
      setLastAction(`已重新执行：${TASK_TYPE_LABEL[task.type] || task.type}`)
      setTimeout(() => setLastAction((cur) => (cur ? null : cur)), 3000)
    } catch (e: any) {
      setError(e?.error?.message || '重试失败')
    } finally {
      setRetrying((prev) => ({ ...prev, [task.task_id]: false }))
    }
  }

  const sortedTasks = useMemo(
    () => [...tasks].sort((a, b) => +new Date(b.created_at) - +new Date(a.created_at)),
    [tasks]
  )

  return (
    <div className="h-full flex flex-col bg-background">
      <header className="h-14 border-b bg-card flex items-center px-4 gap-3 shrink-0">
        <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => navigate('/')} title="返回首页">
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <AlertCircle className="h-4 w-4 text-red-500" />
        <h1 className="font-semibold text-sm">失败任务</h1>
        {lastAction && <span className="text-xs text-green-600 ml-2">{lastAction}</span>}
        {error && <span className="text-xs text-red-500 ml-auto">{error}</span>}
      </header>

      <main className="flex-1 overflow-auto p-4">
        <div className="max-w-4xl mx-auto">
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center gap-2">
                <AlertCircle className="h-4 w-4 text-red-500" />
                <CardTitle className="text-base">失败任务列表</CardTitle>
                <Badge variant="secondary" className="ml-auto text-xs">
                  {tasks.length}
                </Badge>
              </div>
              <CardDescription className="text-xs">显示执行失败的任务，可查看错误原因并手动重新执行</CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              {loading && tasks.length === 0 ? (
                <div className="h-40 flex items-center justify-center text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin mr-2" /> 加载中...
                </div>
              ) : sortedTasks.length === 0 ? (
                <div className="h-40 flex flex-col items-center justify-center text-sm text-muted-foreground">
                  <AlertCircle className="h-8 w-8 mb-2 opacity-20" />
                  暂无失败任务
                </div>
              ) : (
                <ScrollArea className="h-[calc(100vh-180px)]">
                  <div className="divide-y">
                    {sortedTasks.map((task) => {
                      const Icon = TASK_TYPE_ICON[task.type] || RefreshCw
                      const title = resolveRefTitle(task)
                      return (
                        <div key={task.task_id} className="p-4 space-y-3 hover:bg-muted/40 transition-colors">
                          <div className="flex items-start justify-between gap-3">
                            <div className="flex items-center gap-2 min-w-0">
                              <Icon className="h-4 w-4 text-muted-foreground shrink-0" />
                              <span className="text-sm font-medium truncate">
                                {TASK_TYPE_LABEL[task.type] || task.type}
                              </span>
                              <Badge variant="destructive" className="shrink-0 text-[10px]">
                                失败
                              </Badge>
                            </div>
                            <Button
                              size="sm"
                              variant="outline"
                              className="shrink-0 h-7 text-xs"
                              disabled={retrying[task.task_id]}
                              onClick={() => handleRetry(task)}
                            >
                              {retrying[task.task_id] ? (
                                <Loader2 className="h-3 w-3 animate-spin mr-1" />
                              ) : (
                                <RefreshCw className="h-3 w-3 mr-1" />
                              )}
                              重新执行
                            </Button>
                          </div>

                          {title && (
                            <p className="text-xs text-muted-foreground line-clamp-2" title={title}>
                              {task.ref_type === 'uploader' ? 'UP主：' : '视频：'}
                              {title}
                            </p>
                          )}

                          {task.error && (
                            <div className="rounded-md bg-red-50 border border-red-100 p-3 text-xs space-y-1">
                              <div className="flex items-center gap-1.5 text-red-700 font-medium">
                                <AlertCircle className="h-3 w-3" />
                                {task.error.code || 'ERROR'}
                              </div>
                              <p className="text-red-600 whitespace-pre-wrap">{task.error.message}</p>
                            </div>
                          )}

                          <div className="flex items-center gap-4 text-[10px] text-muted-foreground">
                            <span className="flex items-center gap-1">
                              <Clock className="h-3 w-3" />
                              创建：{new Date(task.created_at).toLocaleString('zh-CN')}
                            </span>
                            {task.finished_at && (
                              <span className="flex items-center gap-1">
                                <Clock className="h-3 w-3" />
                                失败时间：{new Date(task.finished_at).toLocaleString('zh-CN')}
                              </span>
                            )}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </ScrollArea>
              )}
            </CardContent>
          </Card>
        </div>
      </main>
    </div>
  )
}
