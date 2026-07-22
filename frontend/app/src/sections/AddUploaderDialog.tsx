import { useState } from 'react'
import { Plus, Search, UserPlus, User } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { Spinner } from '@/components/ui/spinner'
import { uploadersApi } from '@/lib/api'
import { formatFans } from '@/lib/format'

interface SearchItem {
  bilibili_uid: string
  name: string
  avatar_url?: string
  fans_count: number
  description?: string
  already_followed?: boolean
}

interface Props {
  onAdded?: () => void
}

export default function AddUploaderDialog({ onAdded }: Props) {
  const [open, setOpen] = useState(false)

  const [query, setQuery] = useState('')
  const [searching, setSearching] = useState(false)
  const [items, setItems] = useState<SearchItem[]>([])

  const [uid, setUid] = useState('')
  const [addingUid, setAddingUid] = useState<string | null>(null)

  const [message, setMessage] = useState<{ type: 'error' | 'success'; text: string } | null>(null)

  const reset = () => {
    setQuery('')
    setItems([])
    setUid('')
    setMessage(null)
  }

  const doSearch = async () => {
    const q = query.trim()
    if (!q) return
    setSearching(true)
    setMessage(null)
    try {
      const res = await uploadersApi.search(q)
      setItems(res.items as SearchItem[])
      if ((res.items as SearchItem[]).length === 0) {
        setMessage({ type: 'error', text: '未找到匹配的 UP主' })
      }
    } catch (e: any) {
      setMessage({
        type: 'error',
        text: e?.error?.message || '搜索失败，请检查网络或 B站接口状态（未登录时容易被风控）',
      })
    } finally {
      setSearching(false)
    }
  }

  const addByUid = async (bilibili_uid: string, name?: string) => {
    setAddingUid(bilibili_uid)
    setMessage(null)
    try {
      await uploadersApi.create({
        bilibili_uid,
        notify_enabled: true,
      })
      setMessage({
        type: 'success',
        text: name ? `已添加 ${name}，后台正在拉取投稿` : `已添加 UID:${bilibili_uid}，后台正在拉取投稿`,
      })
      onAdded?.()
      setTimeout(() => {
        setOpen(false)
        reset()
      }, 800)
    } catch (e: any) {
      setMessage({ type: 'error', text: e?.error?.message || '添加失败' })
    } finally {
      setAddingUid(null)
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="gap-1.5 text-xs h-8">
          <UserPlus className="h-3.5 w-3.5" />
          添加UP主
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>添加关注的 UP主</DialogTitle>
        </DialogHeader>

        {message && (
          <div
            className={`text-xs px-2 py-1.5 rounded ${
              message.type === 'success' ? 'bg-emerald-500/10 text-emerald-600' : 'bg-red-500/10 text-red-600'
            }`}
          >
            {message.text}
          </div>
        )}

        {/* 昵称搜索 */}
        <div className="flex items-center gap-2 mt-1">
          <div className="relative flex-1">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && doSearch()}
              placeholder="输入昵称搜索 B站 UP主..."
              className="h-9 pl-8 text-xs"
            />
          </div>
          <Button size="sm" className="h-9 text-xs" onClick={doSearch} disabled={searching || !query.trim()}>
            {searching ? <Spinner className="h-3.5 w-3.5" /> : <Plus className="h-3.5 w-3.5" />}
            搜索
          </Button>
        </div>

        <ScrollArea className="h-[220px] -mx-2 px-2">
          <div className="space-y-1.5">
            {items.map((item) => (
              <div
                key={item.bilibili_uid}
                className="flex items-center gap-3 p-2 rounded-lg border bg-card/50 hover:bg-accent/50 transition-colors"
              >
                <Avatar className="h-9 w-9">
                  <AvatarImage src={item.avatar_url} alt={item.name} />
                  <AvatarFallback className="text-xs">{item.name.charAt(0)}</AvatarFallback>
                </Avatar>
                <div className="min-w-0 flex-1">
                  <div className="text-xs font-medium truncate">{item.name}</div>
                  <div className="text-[10px] text-muted-foreground truncate">
                    {item.fans_count > 0 ? `${formatFans(item.fans_count)} 粉丝` : '粉丝数未知'}
                    {item.description ? ` · ${item.description}` : ''}
                  </div>
                </div>
                <Button
                  size="sm"
                  className="h-7 text-[11px] px-2"
                  disabled={item.already_followed || addingUid === item.bilibili_uid}
                  onClick={() => addByUid(item.bilibili_uid, item.name)}
                >
                  {addingUid === item.bilibili_uid ? (
                    <Spinner className="h-3 w-3" />
                  ) : item.already_followed ? (
                    '已关注'
                  ) : (
                    '添加'
                  )}
                </Button>
              </div>
            ))}
            {items.length === 0 && !searching && (
              <div className="py-8 text-center text-xs text-muted-foreground">
                输入昵称并搜索，选择要添加的 UP主
              </div>
            )}
          </div>
        </ScrollArea>

        <Separator />

        {/* UID 直接添加 */}
        <div className="space-y-1.5">
          <div className="text-xs text-muted-foreground">或者直接用 UID 添加（搜索被风控时可用）</div>
          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <User className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
              <Input
                value={uid}
                onChange={(e) => setUid(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && uid.trim() && addByUid(uid.trim())}
                placeholder="输入 B站 UID..."
                className="h-9 pl-8 text-xs"
              />
            </div>
            <Button
              size="sm"
              className="h-9 text-xs"
              onClick={() => addByUid(uid.trim())}
              disabled={!uid.trim() || addingUid === uid.trim()}
            >
              {addingUid === uid.trim() ? <Spinner className="h-3.5 w-3.5" /> : '添加'}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
