import { useEffect, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router'
import {
  Play, Eye, MessageSquare, ThumbsUp, FileText,
  Loader2, Check, ExternalLink,
  ArrowLeft, Tv, Download, Zap,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { videosApi, subtitlesApi, tasksApi, uploadersApi } from '@/lib/api'
import { mapVideo, mapSubtitles, pickColor } from '@/lib/format'
import type { Video, Uploader, SubtitleLine } from '@/types'
import type { BackendVideoDetail, BackendTask } from '@/lib/api'

interface Props {
  videos: Video[]
  uploaders: Uploader[]
  // AI 总结功能已暂停
  onSummarized?: (id: string) => void
}

// AI 总结功能已暂停：情感样式暂时不用
// const SENTIMENT_STYLE: Record<string, { cls: string; label: string }> = {
//   positive: { cls: 'bg-emerald-500/10 text-emerald-600 border-emerald-200', label: '积极' },
//   negative: { cls: 'bg-red-500/10 text-red-600 border-red-200', label: '消极' },
//   neutral: { cls: 'bg-slate-500/10 text-slate-600 border-slate-200', label: '中立' },
//   mixed: { cls: 'bg-amber-500/10 text-amber-600 border-amber-200', label: '复杂' },
// }

function useTaskPoller(taskId: string | null, onSuccess: () => void, onFailed?: (t: BackendTask) => void) {
  const callbacks = useRef({ onSuccess, onFailed })
  callbacks.current = { onSuccess, onFailed }
  useEffect(() => {
    if (!taskId) return
    let cancelled = false
    const poll = async () => {
      while (!cancelled) {
        await new Promise((r) => setTimeout(r, 1500))
        try {
          const t: BackendTask = await tasksApi.get(taskId)
          if (t.status === 'success') {
            callbacks.current.onSuccess()
            return
          }
          if (t.status === 'failed') {
            callbacks.current.onFailed?.(t)
            return
          }
        } catch {
          // ignore
        }
      }
    }
    poll()
    return () => {
      cancelled = true
    }
  }, [taskId])
}

export default function VideoPage({ videos: _videos, uploaders, onSummarized: _onSummarized }: Props) {
  const { id } = useParams()
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [video, setVideo] = useState<Video | null>(null)
  const [up, setUp] = useState<Uploader | null>(null)

  const [subtitleTaskId, setSubtitleTaskId] = useState<string | null>(null)
  // AI 总结功能已暂停
  // const [summaryTaskId, setSummaryTaskId] = useState<string | null>(null)
  const [subtitleLoading, setSubtitleLoading] = useState(false)
  // const [summaryLoading, setSummaryLoading] = useState(false)
  const [subtitleError, setSubtitleError] = useState<string | null>(null)
  // const [summaryError, setSummaryError] = useState<string | null>(null)
  const [prioritizeLoading, setPrioritizeLoading] = useState(false)
  const [downloadLoading, setDownloadLoading] = useState(false)

  // const [summary, setSummary] = useState<VideoSummary | null>(null)
  const [subtitles, setSubtitles] = useState<SubtitleLine[]>([])

  const fetchVideo = async () => {
    if (!id) return
    setLoading(true)
    try {
      const detail: BackendVideoDetail = await videosApi.get(id)
      const mapped = mapVideo(detail, new Date())
      mapped.summary = undefined
      setVideo(mapped)
      const mappedUp = uploaders.find((u) => u.id === detail.uploader_id) || {
        id: detail.uploader_id,
        name: detail.uploader?.name || '未知UP主',
        fans: String(detail.uploader?.fans_count || 0),
        category: detail.uploader?.category || '未分类',
        color: pickColor(detail.uploader_id),
        description: detail.uploader?.description || '',
        unread: detail.uploader?.unread_count || 0,
        lastActive: '未知',
      }
      setUp(mappedUp)

      // try load existing subtitle / summary
      if (detail.has_subtitle) {
        try {
          const sub = await subtitlesApi.get(id)
          setSubtitles(mapSubtitles(sub.lines))
        } catch {
          // ignore
        }
      }
      // AI 总结功能已暂停：不再加载总结数据
      // if (detail.has_summary) {
      //   try {
      //     const s = await summariesApi.get(id)
      //     setSummary(mapSummary(s))
      //   } catch {
      //     // ignore
      //   }
      // }
    } catch (e: any) {
      setError(e?.error?.message || '加载视频失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchVideo()
  }, [id])

  useTaskPoller(subtitleTaskId, () => {
    setSubtitleLoading(false)
    setSubtitleTaskId(null)
    fetchVideo()
  }, (t) => {
    setSubtitleLoading(false)
    setSubtitleTaskId(null)
    setSubtitleError(t.error?.message || '获取字幕失败')
  })

  // AI 总结功能已暂停：不再轮询总结任务
  // useTaskPoller(summaryTaskId, () => {
  //   setSummaryLoading(false)
  //   setSummaryTaskId(null)
  //   fetchVideo()
  //   if (id) onSummarized(id)
  // }, (t) => {
  //   setSummaryLoading(false)
  //   setSummaryTaskId(null)
  //   setSummaryError(t.error?.message || '生成总结失败')
  // })

  const handleFetchSubtitle = async () => {
    if (!id) return
    setSubtitleLoading(true)
    setSubtitleError(null)
    try {
      const res = await subtitlesApi.fetch(id)
      setSubtitleTaskId(res.task_id)
    } catch (e: any) {
      setSubtitleError(e?.error?.message || '获取字幕失败')
      setSubtitleLoading(false)
    }
  }

  const handleExportSubtitle = (format: 'srt' | 'txt' | 'json') => {
    if (!id) return
    subtitlesApi.export(id, format)
  }

  // AI 总结功能已暂停：不再提供生成总结入口
  // const handleSummarize = async () => {
  //   if (!id) return
  //   setSummaryLoading(true)
  //   setSummaryError(null)
  //   try {
  //     const res = await summariesApi.create(id, undefined, undefined, true)
  //     setSummaryTaskId(res.task_id)
  //   } catch (e: any) {
  //     setSummaryError(e?.error?.message || '生成总结失败')
  //     setSummaryLoading(false)
  //   }
  // }

  const handlePrioritizeUploader = async () => {
    if (!up) return
    setPrioritizeLoading(true)
    try {
      const res = await uploadersApi.prioritizeLatest(up.id, 10)
      const total = res.enqueued_subtitle + res.enqueued_summary
      if (total === 0) {
        toast.info(`「${up.name}」的最近 10 个视频已全部处理完毕`)
      } else {
        toast.success(
          `已为「${up.name}」优先排队 ${total} 个任务（字幕 ${res.enqueued_subtitle} / 总结 ${res.enqueued_summary}）`
        )
      }
    } catch (e: any) {
      toast.error(e?.error?.message || '优先排队失败')
    } finally {
      setPrioritizeLoading(false)
    }
  }

  const handleDownloadWebm = async () => {
    if (!id) return
    setDownloadLoading(true)
    try {
      await videosApi.downloadWebm(id)
    } catch (e: any) {
      const code = e?.error?.code
      const msg = e?.displayMessage || e?.error?.message || '下载失败'
      if (code === 'SESSDATA_REQUIRED') {
        toast.error(msg, { duration: 8000 })
      } else {
        toast.error(msg)
      }
    } finally {
      setDownloadLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-primary" />
      </div>
    )
  }

  if (error || !video) {
    return (
      <div className="min-h-screen bg-background flex flex-col items-center justify-center gap-3">
        <p className="text-muted-foreground">{error || '视频不存在或已被删除'}</p>
        <Button variant="outline" size="sm" onClick={() => navigate('/')}>
          <ArrowLeft className="h-4 w-4" /> 返回时间线
        </Button>
      </div>
    )
  }

  // AI 总结功能已暂停
  // const sentiment = summary ? SENTIMENT_STYLE[summary.stance.sentiment] : null
  const hasSubtitle = subtitles.length > 0
  // const hasSummary = !!summary

  return (
    <div className="min-h-screen bg-background">
      {/* 顶栏 */}
      <header className="h-14 border-b bg-card flex items-center px-4 gap-3 sticky top-0 z-10">
        <button
          onClick={() => navigate('/')}
          className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeft className="h-4 w-4" /> 返回时间线
        </button>
        <div className="h-4 w-px bg-border" />
        <div className="flex items-center gap-2">
          <div className="h-6 w-6 rounded-md bg-primary flex items-center justify-center">
            <Tv className="h-3 w-3 text-primary-foreground" />
          </div>
          <span className="text-sm font-semibold">视频详情</span>
        </div>
        <div className="flex-1" />
        <span className="text-xs text-muted-foreground font-mono">{video.bvid}</span>
        <Button
          variant="outline"
          size="sm"
          className="text-xs gap-1"
          onClick={handlePrioritizeUploader}
          disabled={prioritizeLoading || !up}
        >
          {prioritizeLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Zap className="h-3.5 w-3.5" />}
          为该 UP 优先排队最近 10 个
        </Button>
        <Button variant="outline" size="sm" className="text-xs gap-1" asChild>
          <a href={`https://www.bilibili.com/video/${video.bvid}`} target="_blank" rel="noreferrer">
            <ExternalLink className="h-3.5 w-3.5" /> 在B站打开
          </a>
        </Button>
      </header>

      {/* 主体 */}
      <main className="max-w-[880px] mx-auto px-6 py-6 space-y-5">
        {/* 封面 */}
        <div className={cn('relative aspect-video rounded-2xl bg-gradient-to-br flex items-center justify-center overflow-hidden shadow-lg', video.gradient)}>
          {video.cover && (
            <img
              src={video.cover}
              alt={video.title}
              className="absolute inset-0 h-full w-full object-cover"
              loading="lazy"
              referrerPolicy="no-referrer"
              onError={(e) => { e.currentTarget.style.display = 'none' }}
            />
          )}
          <Play className="relative h-20 w-20 text-white/80 fill-white/80 drop-shadow" />
          <span className="absolute bottom-3 right-3 rounded bg-black/70 text-white text-sm px-2.5 py-1 font-medium">
            {video.duration}
          </span>
        </div>

        {/* 标题与数据 */}
        <div>
          <h1 className="text-xl font-bold leading-snug">{video.title}</h1>
          <div className="mt-3 flex items-center gap-2.5 text-sm">
            <span
              className="inline-flex items-center justify-center h-8 w-8 rounded-full text-xs text-white font-semibold"
              style={{ backgroundColor: up?.color }}
            >
              {up?.name.charAt(0)}
            </span>
            <div>
              <div className="font-medium leading-none">{up?.name}</div>
              <div className="text-xs text-muted-foreground mt-1">{up?.fans}粉丝 · {up?.category}</div>
            </div>
            <span className="text-muted-foreground mx-1">·</span>
            <span className="text-sm text-muted-foreground">{video.dateGroup} {video.time} 发布</span>
          </div>
          <div className="mt-3 flex items-center gap-5 text-sm text-muted-foreground">
            <span className="inline-flex items-center gap-1.5"><Eye className="h-4 w-4" /> {video.views} 播放</span>
            <span className="inline-flex items-center gap-1.5"><MessageSquare className="h-4 w-4" /> {video.danmaku} 弹幕</span>
            <span className="inline-flex items-center gap-1.5"><ThumbsUp className="h-4 w-4" /> {video.likes} 点赞</span>
          </div>
          <div className="mt-3 flex items-center gap-1.5">
            {video.tags.map((t) => (
              <Badge key={t} variant="secondary" className="text-xs">{t}</Badge>
            ))}
          </div>
        </div>

        {/* 操作按钮 */}
        <div className="flex items-center gap-2.5 flex-wrap">
          <Button
            variant={hasSubtitle ? 'secondary' : 'outline'}
            onClick={handleFetchSubtitle}
            disabled={subtitleLoading || hasSubtitle}
            className="gap-1.5"
          >
            {subtitleLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : hasSubtitle ? <Check className="h-4 w-4 text-emerald-500" /> : <FileText className="h-4 w-4" />}
            {subtitleLoading ? '获取中...' : hasSubtitle ? '字幕已获取' : '获取字幕'}
          </Button>
          {hasSubtitle && (
            <>
              <Button variant="outline" size="sm" className="gap-1" onClick={() => handleExportSubtitle('srt')}>
                <Download className="h-3.5 w-3.5" /> SRT
              </Button>
              <Button variant="outline" size="sm" className="gap-1" onClick={() => handleExportSubtitle('txt')}>
                <Download className="h-3.5 w-3.5" /> TXT
              </Button>
            </>
          )}
          <Button
            variant="outline"
            size="sm"
            className="gap-1"
            onClick={handleDownloadWebm}
            disabled={downloadLoading}
          >
            {downloadLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
            {downloadLoading ? '下载中...' : 'WebM'}
          </Button>
          {/* AI 总结功能已暂停：隐藏生成按钮 */}
          {/* <Button onClick={handleSummarize} disabled={summaryLoading} className="gap-1.5">
            {summaryLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            {summaryLoading ? 'AI总结中...' : hasSummary ? '重新生成总结' : '生成AI总结'}
          </Button> */}
        </div>

        {(subtitleError /* || summaryError */) && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-600 space-y-1">
            {subtitleError && <p>字幕获取失败：{subtitleError}</p>}
            {/* {summaryError && <p>总结生成失败：{summaryError}</p>} */}
          </div>
        )}

        {/* AI 总结功能已暂停：隐藏加载与结果展示 */}
        {/* {summaryLoading && (
          <div className="rounded-xl border bg-muted/40 p-5 space-y-3 animate-pulse">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin text-primary" />
              正在读取字幕并调用大模型总结，预计需要几秒钟...
            </div>
            <div className="h-3.5 rounded bg-muted" />
            <div className="h-3.5 rounded bg-muted w-4/5" />
            <div className="h-3.5 rounded bg-muted w-3/5" />
          </div>
        )} */}

        {/* 字幕原文（AI 总结功能已暂停） */}
        {hasSubtitle && (
          <div className="rounded-xl border divide-y">
            {subtitles.map((s, i) => (
              <div key={i} className="flex gap-4 px-4 py-3">
                <span className="shrink-0 font-mono text-sm text-primary/80 pt-0.5">{s.time}</span>
                <span className="leading-relaxed text-foreground/90">{s.text}</span>
              </div>
            ))}
          </div>
        )}
        {hasSubtitle && (
          <p className="mt-3 text-xs text-muted-foreground text-center">
            共 {subtitles.length} 条字幕 · 可导出 SRT / TXT 格式
          </p>
        )}
      </main>
    </div>
  )
}
