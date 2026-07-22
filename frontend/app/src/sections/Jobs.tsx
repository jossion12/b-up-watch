import { useEffect, useState } from 'react'
import { Activity, Loader2 } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Switch } from '@/components/ui/switch'
import { Progress } from '@/components/ui/progress'
import { Badge } from '@/components/ui/badge'
import { jobsApi, type JobItem } from '@/lib/api'

const JOB_ICONS: Record<string, string> = {
  subtitle: '📝',
  summary: '✨',
  backfill: '📚',
}

export default function Jobs() {
  const [jobs, setJobs] = useState<JobItem[]>([])
  const [loading, setLoading] = useState(true)
  const [updating, setUpdating] = useState<Record<string, boolean>>({})
  const [error, setError] = useState<string | null>(null)

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

  useEffect(() => {
    loadJobs()
    const id = setInterval(loadJobs, 2000)
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

  return (
    <div className="h-full flex flex-col bg-background">
      <header className="h-14 border-b bg-card flex items-center px-4 gap-3 shrink-0">
        <Activity className="h-4 w-4 text-muted-foreground" />
        <h1 className="font-semibold text-sm">任务调度</h1>
        {error && <span className="text-xs text-red-500 ml-auto">{error}</span>}
      </header>

      <main className="flex-1 overflow-auto p-4">
        {loading && jobs.length === 0 ? (
          <div className="flex items-center justify-center h-40 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin mr-2" /> 加载中...
          </div>
        ) : (
          <div className="grid gap-4 md:grid-cols-3 max-w-5xl mx-auto">
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
      </main>
    </div>
  )
}
