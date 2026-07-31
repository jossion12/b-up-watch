import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import {
  ArrowLeft, Bot, Database, Loader2, MessageSquare,
  RefreshCw, Search, Send, User, ChevronDown,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Progress } from '@/components/ui/progress'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Badge } from '@/components/ui/badge'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { cn } from '@/lib/utils'
import { ragApi, tasksApi, type RagSearchItem, type RagChatChunk, type BackendTask } from '@/lib/api'
import { useWebSocket } from '@/hooks/useWebSocket'
import type { Uploader } from '@/types'

interface ReviewPageProps {
  uploaders: Uploader[]
}

export default function ReviewPage({ uploaders }: ReviewPageProps) {
  const navigate = useNavigate()
  const { uploaderId } = useParams<{ uploaderId: string }>()
  const [mode, setMode] = useState<'search' | 'chat'>('search')
  const [query, setQuery] = useState('')
  const [chatInput, setChatInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [ingesting, setIngesting] = useState(false)
  const [stats, setStats] = useState({ total_chunks: 0 })
  const [ingestTask, setIngestTask] = useState<BackendTask | null>(null)
  const [results, setResults] = useState<RagSearchItem[]>([])
  const [searched, setSearched] = useState(false)
  const [chatHistory, setChatHistory] = useState<{ role: 'user' | 'assistant'; content: string; chunks?: RagChatChunk[] }[]>([])
  const bottomRef = useRef<HTMLDivElement>(null)

  const currentUploader = useMemo(
    () => uploaders.find((u) => u.id === uploaderId),
    [uploaders, uploaderId]
  )

  const upName = currentUploader?.name || '未知UP主'

  const isIngestActive = useMemo(
    () =>
      !!ingestTask &&
      (ingestTask.status === 'pending' || ingestTask.status === 'running') &&
      ingestTask.ref_id === uploaderId,
    [ingestTask, uploaderId]
  )

  const loadStats = async () => {
    if (!uploaderId) return
    try {
      const s = await ragApi.stats(uploaderId)
      setStats(s)
    } catch {
      // ignore
    }
  }

  useEffect(() => {
    loadStats()
    // 切换 UP 主时清空搜索/对话状态与导入任务跟踪
    setQuery('')
    setChatInput('')
    setResults([])
    setSearched(false)
    setChatHistory([])
    setIngestTask(null)
  }, [uploaderId])

  useEffect(() => {
    if (bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [chatHistory])

  // 轮询 rag_ingest 任务状态
  useEffect(() => {
    if (!isIngestActive || !ingestTask) return
    const poll = async () => {
      try {
        const task = await tasksApi.get(ingestTask.task_id)
        setIngestTask(task)
        if (task.status === 'success') {
          await loadStats()
          const meta = task.meta || {}
          alert(
            `导入完成：${meta.files ?? 0} 个文件，${meta.segments ?? 0} 个话题段，${meta.chunks ?? 0} 个观点卡片`
          )
        } else if (task.status === 'failed') {
          alert(task.error?.message || '导入失败')
        }
      } catch {
        // 轮询失败不中断，等待下次重试
      }
    }
    poll()
    const id = setInterval(poll, 2000)
    return () => clearInterval(id)
  }, [isIngestActive, ingestTask?.task_id])

  useWebSocket((msg) => {
    if (msg.event === 'task.updated') {
      const task = msg.payload as BackendTask
      if (task.type === 'rag_ingest' && task.ref_id === uploaderId) {
        setIngestTask(task)
        if (task.status === 'success') {
          loadStats()
          const meta = task.meta || {}
          alert(
            `导入完成：${meta.files ?? 0} 个文件，${meta.segments ?? 0} 个话题段，${meta.chunks ?? 0} 个观点卡片`
          )
        } else if (task.status === 'failed') {
          alert(task.error?.message || '导入失败')
        }
      }
    }
  })

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!uploaderId || !query.trim()) return
    setLoading(true)
    setSearched(true)
    try {
      const res = await ragApi.search(uploaderId, query.trim())
      setResults(res.items)
    } catch (e: any) {
      setResults([])
    } finally {
      setLoading(false)
    }
  }

  const handleChat = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!uploaderId || !chatInput.trim()) return
    const question = chatInput.trim()
    setChatInput('')
    setChatHistory((prev) => [...prev, { role: 'user', content: question }])
    setLoading(true)
    try {
      const res = await ragApi.chat(uploaderId, question)
      setChatHistory((prev) => [...prev, { role: 'assistant', content: res.answer, chunks: res.chunks }])
    } catch (e: any) {
      setChatHistory((prev) => [...prev, { role: 'assistant', content: '对话失败，请稍后重试。' }])
    } finally {
      setLoading(false)
    }
  }

  const handleIngest = async () => {
    if (!uploaderId || isIngestActive) return
    setIngesting(true)
    try {
      const res = await ragApi.ingest(uploaderId)
      const task = await tasksApi.get(res.task_id)
      setIngestTask(task)
    } catch (e: any) {
      alert(e?.error?.message || '导入失败')
    } finally {
      setIngesting(false)
    }
  }

  const resultList = useMemo(() => {
    if (!searched) return null
    if (loading && results.length === 0) {
      return (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-32 w-full rounded-xl" />
          ))}
        </div>
      )
    }
    if (results.length === 0) {
      return <div className="text-sm text-muted-foreground text-center py-12">未找到相关观点卡片</div>
    }
    return (
      <div className="space-y-3">
        {results.map((item, idx) => (
          <ResultCard key={item.chunk_id || idx} item={item} index={idx} />
        ))}
      </div>
    )
  }, [results, loading, searched])

  if (!currentUploader) {
    return (
      <div className="h-screen flex flex-col items-center justify-center bg-background">
        <div className="text-sm text-muted-foreground">未找到该 UP 主，或暂无复盘数据</div>
        <Button variant="outline" className="mt-4" onClick={() => navigate('/')}>
          <ArrowLeft className="h-4 w-4 mr-2" /> 返回首页
        </Button>
      </div>
    )
  }

  return (
    <div className="h-screen flex flex-col bg-background overflow-hidden">
      {/* 顶栏 */}
      <header className="h-14 border-b bg-card flex items-center px-4 gap-3 shrink-0">
        <Button variant="ghost" size="icon" onClick={() => navigate('/')} className="shrink-0">
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="flex items-center gap-2">
          <div className="h-8 w-8 rounded-lg bg-primary flex items-center justify-center">
            <Database className="h-4 w-4 text-primary-foreground" />
          </div>
          <div>
            <div className="font-bold text-sm leading-none">{upName}复盘</div>
            <div className="text-[10px] text-muted-foreground mt-0.5">Milvus 向量检索与对话</div>
          </div>
        </div>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="sm" className="text-xs gap-1">
              切换 UP <ChevronDown className="h-3 w-3" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="max-h-80 overflow-y-auto">
            {uploaders.map((u) => (
              <DropdownMenuItem
                key={u.id}
                onClick={() => navigate(`/review/${u.id}`)}
                className={cn(u.id === uploaderId && 'bg-muted')}
              >
                {u.name}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>

        <div className="flex-1" />

        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Database className="h-3.5 w-3.5" />
          <span>已导入 {stats.total_chunks} 条观点卡片</span>
        </div>
        {isIngestActive && ingestTask && (
          <div className="flex items-center gap-2 w-48">
            <Progress value={ingestTask.progress} className="h-1.5 flex-1" />
            <span className="text-xs text-muted-foreground shrink-0">{ingestTask.progress}%</span>
          </div>
        )}
        <Button
          variant="outline"
          size="sm"
          onClick={handleIngest}
          disabled={ingesting || isIngestActive}
          className="text-xs gap-1.5"
        >
          {ingesting || isIngestActive ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <RefreshCw className="h-3.5 w-3.5" />
          )}
          {isIngestActive ? '导入中' : '重新导入'}
        </Button>
      </header>

      {/* 主体 */}
      <div className="flex-1 flex min-h-0">
        {/* 左侧输入区 */}
        <div className="w-[380px] border-r bg-card flex flex-col shrink-0">
          <div className="p-4 border-b">
            <Tabs value={mode} onValueChange={(v) => setMode(v as 'search' | 'chat')} className="w-full">
              <TabsList className="grid w-full grid-cols-2">
                <TabsTrigger value="search" className="text-xs gap-1">
                  <Search className="h-3.5 w-3.5" /> 检索
                </TabsTrigger>
                <TabsTrigger value="chat" className="text-xs gap-1">
                  <Bot className="h-3.5 w-3.5" /> 对话
                </TabsTrigger>
              </TabsList>
            </Tabs>
          </div>

          <div className="p-4 flex-1 flex flex-col min-h-0">
            {mode === 'search' ? (
              <form onSubmit={handleSearch} className="space-y-3">
                <div className="text-sm font-medium">语义检索</div>
                <Input
                  placeholder={`例如：${upName}最新观点是什么？`}
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  className="text-sm"
                />
                <Button type="submit" className="w-full gap-1.5" disabled={loading || !query.trim()}>
                  {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                  搜索
                </Button>
                <p className="text-[11px] text-muted-foreground leading-relaxed">
                  基于 BAAI/bge-large-zh-v1.5 向量模型，检索{upName}复盘观点卡片。
                </p>
              </form>
            ) : (
              <form onSubmit={handleChat} className="space-y-3">
                <div className="text-sm font-medium">RAG 对话</div>
                <Input
                  placeholder={`例如：${upName}对当前市场怎么看？`}
                  value={chatInput}
                  onChange={(e) => setChatInput(e.target.value)}
                  className="text-sm"
                />
                <Button type="submit" className="w-full gap-1.5" disabled={loading || !chatInput.trim()}>
                  {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                  提问
                </Button>
                <p className="text-[11px] text-muted-foreground leading-relaxed">
                  先检索相关观点片段，再由大模型基于片段生成带来源引用的回答。
                </p>
              </form>
            )}

            {chatHistory.length > 0 && mode === 'chat' && (
              <div className="mt-4 flex-1 min-h-0">
                <div className="text-xs font-medium text-muted-foreground mb-2">对话历史</div>
                <ScrollArea className="h-full pr-2">
                  <div className="space-y-3">
                    {chatHistory.map((msg, idx) => (
                      <div
                        key={idx}
                        className={cn(
                          'flex gap-2',
                          msg.role === 'user' ? 'flex-row-reverse' : 'flex-row'
                        )}
                      >
                        <div
                          className={cn(
                            'h-7 w-7 rounded-full flex items-center justify-center shrink-0',
                            msg.role === 'user' ? 'bg-primary text-primary-foreground' : 'bg-muted'
                          )}
                        >
                          {msg.role === 'user' ? <User className="h-3.5 w-3.5" /> : <Bot className="h-3.5 w-3.5" />}
                        </div>
                        <div
                          className={cn(
                            'rounded-lg px-3 py-2 text-xs leading-relaxed max-w-[85%]',
                            msg.role === 'user'
                              ? 'bg-primary text-primary-foreground'
                              : 'bg-muted border'
                          )}
                        >
                          {msg.content}
                        </div>
                      </div>
                    ))}
                    <div ref={bottomRef} />
                  </div>
                </ScrollArea>
              </div>
            )}
          </div>
        </div>

        {/* 右侧结果区 */}
        <div className="flex-1 bg-background min-h-0">
          <ScrollArea className="h-full">
            <div className="p-5 max-w-[900px] mx-auto">
              {mode === 'search' ? (
                <div>
                  <div className="flex items-center gap-2 mb-4">
                    <Search className="h-4 w-4 text-primary" />
                    <h2 className="font-semibold text-sm">检索结果</h2>
                  </div>
                  {resultList}
                </div>
              ) : (
                <div>
                  <div className="flex items-center gap-2 mb-4">
                    <MessageSquare className="h-4 w-4 text-primary" />
                    <h2 className="font-semibold text-sm">回答与引用</h2>
                  </div>
                  {chatHistory.length === 0 ? (
                    <div className="text-sm text-muted-foreground text-center py-20">
                      在左侧输入问题，开始基于{upName}复盘的 RAG 对话
                    </div>
                  ) : (
                    <div className="space-y-4">
                      {chatHistory
                        .filter((m) => m.role === 'assistant' && m.chunks)
                        .map((msg, idx) => (
                          <div key={idx}>
                            <div className="bg-card border rounded-xl p-4 text-sm leading-relaxed mb-3">
                              {msg.content}
                            </div>
                            {msg.chunks && msg.chunks.length > 0 && (
                              <div className="space-y-2">
                                <div className="text-xs font-medium text-muted-foreground">引用来源</div>
                                {msg.chunks.map((chunk, cidx) => (
                                  <ResultCard key={cidx} item={chunk} index={cidx} compact />
                                ))}
                              </div>
                            )}
                          </div>
                        ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          </ScrollArea>
        </div>
      </div>
    </div>
  )
}

function ResultCard({ item, index, compact = false }: { item: RagSearchItem; index: number; compact?: boolean }) {
  const meta = item.metadata || {}
  return (
    <Card className={cn('overflow-hidden', compact && 'border-dashed')}>
      <CardHeader className={cn('pb-2', compact ? 'p-3' : 'p-4')}>
        <div className="flex items-center justify-between gap-2">
          <div className="text-xs font-semibold truncate">{meta.video_title || '未知标题'}</div>
          {!compact && (
            <Badge variant="outline" className="text-[10px] shrink-0">
              #{index + 1}
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-2 text-[10px] text-muted-foreground mt-1 flex-wrap">
          {meta.date && <span>{meta.date}</span>}
          <span>{meta.time_position || ''}</span>
          {meta.content_type && (
            <Badge className="text-[10px] px-1 py-0" variant="secondary">
              {meta.content_type}
            </Badge>
          )}
          {meta.stance_type && meta.stance_type !== '无' && (
            <Badge className="text-[10px] px-1 py-0" variant="secondary">
              {meta.stance_type}
            </Badge>
          )}
          {meta.confidence && (
            <Badge className="text-[10px] px-1 py-0" variant="outline">
              置信度 {meta.confidence}
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent className={cn('pt-0', compact ? 'px-3 pb-3' : 'px-4 pb-4')}>
        <p className={cn('text-foreground/90 leading-relaxed', compact ? 'text-xs' : 'text-sm')}>
          {item.content}
        </p>
        {meta.core_topic && (
          <div className="mt-2 text-[10px] text-muted-foreground">
            主题：{meta.core_topic}
          </div>
        )}
        {meta.sub_topics && meta.sub_topics.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-2">
            {meta.sub_topics.map((t, i) => (
              <Badge key={i} variant="outline" className="text-[10px] px-1 py-0">
                {t}
              </Badge>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
