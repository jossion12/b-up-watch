import { useState } from 'react'
import { useNavigate } from 'react-router'
import { ArrowLeft, Search, Film, Loader2, Captions } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/checkbox'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { Spinner } from '@/components/ui/spinner'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { toast } from 'sonner'
import { videosApi, type BackendVideoSearchItem, type VideoSearchFetchResult } from '@/lib/api'
import { formatDuration, formatNumber, formatRelativeTime } from '@/lib/format'

export default function VideoSearchPage() {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [order, setOrder] = useState('default')
  const [searching, setSearching] = useState(false)
  const [items, setItems] = useState<BackendVideoSearchItem[]>([])
  const [hasMore, setHasMore] = useState(false)
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [fetching, setFetching] = useState(false)
  const [brokenCovers, setBrokenCovers] = useState<Set<string>>(new Set())

  const doSearch = async (p = 1, currentOrder = order) => {
    const q = query.trim()
    if (!q) return
    setSearching(true)
    try {
      const apiOrder = currentOrder === 'default' ? '' : currentOrder
      const res = await videosApi.search(q, p, apiOrder)
      if (p === 1) {
        setItems(res.items)
      } else {
        setItems((prev) => [...prev, ...res.items])
      }
      setHasMore(res.has_more)
      setPage(res.page)
      setSelected(new Set())
    } catch (e: any) {
      toast.error(e?.error?.message || '搜索失败，请检查网络或 B站接口状态')
    } finally {
      setSearching(false)
    }
  }

  const toggleSelect = (bvid: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(bvid)) next.delete(bvid)
      else next.add(bvid)
      return next
    })
  }

  const toggleAll = () => {
    if (selected.size === items.length && items.length > 0) {
      setSelected(new Set())
    } else {
      setSelected(new Set(items.map((it) => it.bvid)))
    }
  }

  const fetchSubtitles = async () => {
    if (selected.size === 0) return
    const selectedItems = items
      .filter((it) => selected.has(it.bvid))
      .map((it) => ({ bvid: it.bvid, title: it.title }))
    setFetching(true)
    try {
      const res = await videosApi.fetchSubtitles(selectedItems)
      const succeeded = res.results.filter((r: VideoSearchFetchResult) => !r.error)
      const failed = res.results.filter((r: VideoSearchFetchResult) => r.error)
      if (succeeded.length > 0) {
        toast.success(`已为 ${succeeded.length} 个视频排队获取字幕`)
      }
      if (failed.length > 0) {
        toast.error(`${failed.length} 个视频失败：${failed[0].error?.message}`)
      }
      navigate('/jobs')
    } catch (e: any) {
      toast.error(e?.error?.message || '提交失败')
    } finally {
      setFetching(false)
    }
  }

  return (
    <div className="h-screen flex flex-col bg-background">
      <header className="h-14 border-b bg-card flex items-center px-4 gap-3 shrink-0">
        <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => navigate('/')}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <Film className="h-4 w-4 text-muted-foreground" />
        <h1 className="font-semibold text-sm">视频搜索</h1>
      </header>

      <main className="flex-1 flex flex-col min-h-0 max-w-4xl mx-auto w-full p-4">
        <div className="flex items-center gap-2 shrink-0">
          <div className="relative flex-1">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && doSearch()}
              placeholder="输入关键词搜索 B站视频..."
              className="h-10 pl-8 text-sm"
            />
          </div>
          <Select value={order} onValueChange={(v) => { setOrder(v); doSearch(1, v) }}>
            <SelectTrigger className="h-10 w-[140px] text-xs">
              <SelectValue placeholder="综合排序" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="default">综合排序</SelectItem>
              <SelectItem value="pubdate">最新发布</SelectItem>
              <SelectItem value="click">最多播放</SelectItem>
            </SelectContent>
          </Select>
          <Button onClick={() => doSearch()} disabled={searching || !query.trim()} className="h-10">
            {searching ? <Spinner className="h-4 w-4" /> : <Search className="h-4 w-4" />}
            <span className="ml-1.5">搜索</span>
          </Button>
        </div>

        {items.length > 0 && (
          <div className="flex items-center justify-between mt-4 mb-2 shrink-0">
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Checkbox
                checked={selected.size === items.length && items.length > 0}
                onCheckedChange={toggleAll}
                id="select-all"
              />
              <label htmlFor="select-all" className="cursor-pointer">
                全选
              </label>
              <span className="ml-2">
                已选 {selected.size} / {items.length}
              </span>
            </div>
            {hasMore && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => doSearch(page + 1)}
                disabled={searching}
              >
                {searching ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : '加载更多'}
              </Button>
            )}
          </div>
        )}

        <ScrollArea className="flex-1 -mx-4 px-4">
          <div className="space-y-2 pb-20">
            {items.map((item) => (
              <div
                key={item.bvid}
                className="flex items-start gap-3 p-3 rounded-lg border bg-card hover:bg-accent/40 transition-colors"
              >
                <Checkbox
                  checked={selected.has(item.bvid)}
                  onCheckedChange={() => toggleSelect(item.bvid)}
                  className="mt-1"
                />
                <div className="shrink-0 w-32 aspect-video rounded-md overflow-hidden bg-muted">
                  {item.cover_url && !brokenCovers.has(item.bvid) ? (
                    <img
                      src={item.cover_url}
                      alt={item.title}
                      className="w-full h-full object-cover"
                      loading="lazy"
                      referrerPolicy="no-referrer"
                      onError={() => setBrokenCovers((prev) => new Set(prev).add(item.bvid))}
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center text-muted-foreground">
                      <Film className="h-6 w-6" />
                    </div>
                  )}
                </div>
                <div className="flex-1 min-w-0 space-y-1">
                  <div className="text-sm font-medium line-clamp-2" title={item.title}>
                    {item.title}
                  </div>
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <Avatar className="h-4 w-4">
                      <AvatarImage src={item.uploader_avatar_url} referrerPolicy="no-referrer" />
                      <AvatarFallback className="text-[8px]">
                        {item.uploader_name.charAt(0)}
                      </AvatarFallback>
                    </Avatar>
                    <span className="truncate max-w-[120px]">{item.uploader_name}</span>
                    <span>·</span>
                    <span>{formatDuration(item.duration_sec)}</span>
                    <span>·</span>
                    <span>{formatNumber(item.views)} 播放</span>
                    {item.published_at && (
                      <>
                        <span>·</span>
                        <span>{formatRelativeTime(item.published_at)}</span>
                      </>
                    )}
                  </div>
                </div>
              </div>
            ))}
            {items.length === 0 && !searching && (
              <div className="h-64 flex flex-col items-center justify-center text-sm text-muted-foreground">
                <Search className="h-8 w-8 mb-2 opacity-40" />
                输入关键词搜索视频
              </div>
            )}
            {searching && items.length === 0 && (
              <div className="h-64 flex items-center justify-center text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin mr-2" /> 搜索中...
              </div>
            )}
          </div>
        </ScrollArea>

        {selected.size > 0 && (
          <div className="shrink-0 border-t bg-card p-3 -mx-4 px-4 flex items-center justify-between">
            <span className="text-sm text-muted-foreground">已选择 {selected.size} 个视频</span>
            <Button onClick={fetchSubtitles} disabled={fetching} className="gap-1.5">
              {fetching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Captions className="h-4 w-4" />}
              获取字幕
            </Button>
          </div>
        )}
      </main>
    </div>
  )
}
