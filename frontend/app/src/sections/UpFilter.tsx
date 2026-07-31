import { useState } from 'react'
import { Search, ListFilter, RotateCcw, Trash2, Pencil, Zap, History } from 'lucide-react'
import { toast } from 'sonner'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { uploadersApi } from '@/lib/api'
import type { Uploader } from '@/types'

const PRESET_CATEGORIES = [
  '财经',
  '时政',
  'AI',
  '美食',
  '科技',
  '数码',
  '影视',
  '知识',
  '生活',
  '游戏',
  '娱乐',
  '体育',
  '其他',
]
const NONE_KEY = '__none__'
const CUSTOM_KEY = '__custom__'

interface Props {
  uploaders: Uploader[]
  selected: Set<string>
  onChange: (s: Set<string>) => void
  onDelete?: (id: string) => void | Promise<void>
  onUpdate?: (id: string, payload: { category: string }) => void | Promise<void>
}

export default function UpFilter({ uploaders, selected, onChange, onDelete, onUpdate }: Props) {
  const [query, setQuery] = useState('')
  const [confirmId, setConfirmId] = useState<string | null>(null)
  const [editId, setEditId] = useState<string | null>(null)
  const [editCategory, setEditCategory] = useState(NONE_KEY)
  const [editCustom, setEditCustom] = useState('')
  const [updating, setUpdating] = useState(false)
  const [prioritizeId, setPrioritizeId] = useState<string | null>(null)
  const [prioritizing, setPrioritizing] = useState(false)
  const [backfillId, setBackfillId] = useState<string | null>(null)
  const [backfilling, setBackfilling] = useState(false)
  const filtered = uploaders.filter((u) => u.name.toLowerCase().includes(query.toLowerCase()))

  const toggle = (id: string) => {
    const next = new Set(selected)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    onChange(next)
  }

  const handleConfirmDelete = async () => {
    if (!confirmId) return
    try {
      await onDelete?.(confirmId)
    } finally {
      setConfirmId(null)
    }
  }

  const startEdit = (u: Uploader) => {
    const cat = u.category && u.category !== '未分类' ? u.category : ''
    const isPreset = PRESET_CATEGORIES.includes(cat)
    setEditId(u.id)
    setEditCategory(isPreset ? cat : cat ? CUSTOM_KEY : NONE_KEY)
    setEditCustom(isPreset ? '' : cat)
  }

  const handleSaveEdit = async () => {
    if (!editId) return
    const effective =
      editCategory === CUSTOM_KEY ? editCustom.trim() : editCategory === NONE_KEY ? '' : editCategory
    setUpdating(true)
    try {
      await onUpdate?.(editId, { category: effective })
    } finally {
      setUpdating(false)
      setEditId(null)
      setEditCategory(NONE_KEY)
      setEditCustom('')
    }
  }

  const handleCancelEdit = () => {
    setEditId(null)
    setEditCategory(NONE_KEY)
    setEditCustom('')
  }

  const confirmingUploader = confirmId ? uploaders.find((u) => u.id === confirmId) : undefined
  const editingUploader = editId ? uploaders.find((u) => u.id === editId) : undefined
  const prioritizingUploader = prioritizeId ? uploaders.find((u) => u.id === prioritizeId) : undefined
  const backfillingUploader = backfillId ? uploaders.find((u) => u.id === backfillId) : undefined

  const handleConfirmPrioritize = async () => {
    if (!prioritizeId) return
    setPrioritizing(true)
    try {
      const res = await uploadersApi.prioritizeLatest(prioritizeId, 10)
      const total = res.enqueued_subtitle + res.enqueued_summary
      if (total === 0) {
        toast.info(`「${prioritizingUploader?.name || ''}」的最近 10 个视频已全部处理完毕`)
      } else {
        toast.success(
          `已为「${prioritizingUploader?.name || ''}」优先排队 ${total} 个任务（字幕 ${res.enqueued_subtitle} / 总结 ${res.enqueued_summary}）`
        )
      }
    } catch (e: any) {
      toast.error(e?.error?.message || '优先排队失败')
    } finally {
      setPrioritizing(false)
      setPrioritizeId(null)
    }
  }

  const handleConfirmBackfill = async () => {
    if (!backfillId) return
    setBackfilling(true)
    try {
      const res = await uploadersApi.backfillYear(backfillId)
      toast.success(
        `已为「${backfillingUploader?.name || ''}」创建回溯任务（最近 ${res.days_back} 天）`
      )
    } catch (e: any) {
      toast.error(e?.error?.message || '创建回溯任务失败')
    } finally {
      setBackfilling(false)
      setBackfillId(null)
    }
  }

  return (
    <>
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" className="gap-1.5 text-xs h-8">
          <ListFilter className="h-3.5 w-3.5" />
          筛选UP主
          {selected.size > 0 && (
            <Badge className="h-4 min-w-4 px-1 text-[10px] rounded-full">{selected.size}</Badge>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-72 p-0">
        <div className="p-3 pb-2">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索UP主..."
              className="h-8 pl-8 text-xs bg-muted/50 border-0 focus-visible:ring-1"
            />
          </div>
        </div>
        <div className="px-3 py-2 border-y flex items-center justify-between text-xs text-muted-foreground">
          <span>{selected.size > 0 ? `已选 ${selected.size} 位` : '显示全部UP主'}</span>
          {selected.size > 0 && (
            <button
              onClick={() => onChange(new Set())}
              className="inline-flex items-center gap-1 text-primary hover:underline"
            >
              <RotateCcw className="h-3 w-3" /> 重置为全部
            </button>
          )}
        </div>
        <ScrollArea className="h-[300px]">
          <div className="p-2 space-y-0.5">
            {filtered.map((u) => (
              <label
                key={u.id}
                className="group flex items-center gap-2.5 rounded-lg px-2 py-2 hover:bg-accent cursor-pointer"
              >
                <Checkbox checked={selected.has(u.id)} onCheckedChange={() => toggle(u.id)} />
                <span
                  className="h-7 w-7 rounded-full flex items-center justify-center text-[11px] text-white font-semibold shrink-0"
                  style={{ backgroundColor: u.color }}
                >
                  {u.name.charAt(0)}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-xs font-medium truncate">{u.name}</div>
                  <div className="text-[10px] text-muted-foreground">{u.category}</div>
                </div>
                <div className="flex items-center opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
                  <button
                    type="button"
                    onClick={(e) => {
                      e.preventDefault()
                      e.stopPropagation()
                      setBackfillId(u.id)
                    }}
                    className="h-6 w-6 rounded-md flex items-center justify-center text-muted-foreground hover:text-blue-500 hover:bg-blue-500/10"
                    title="回溯该 UP 主当年视频"
                  >
                    <History className="h-3.5 w-3.5" />
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.preventDefault()
                      e.stopPropagation()
                      setPrioritizeId(u.id)
                    }}
                    className="h-6 w-6 rounded-md flex items-center justify-center text-muted-foreground hover:text-amber-500 hover:bg-amber-500/10"
                    title="优先处理最近 10 个视频"
                  >
                    <Zap className="h-3.5 w-3.5" />
                  </button>
                  {onUpdate && (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.preventDefault()
                        e.stopPropagation()
                        startEdit(u)
                      }}
                      className="h-6 w-6 rounded-md flex items-center justify-center text-muted-foreground hover:text-primary hover:bg-primary/10"
                      title="修改分类"
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                  )}
                  {onDelete && (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.preventDefault()
                        e.stopPropagation()
                        setConfirmId(u.id)
                      }}
                      className="h-6 w-6 rounded-md flex items-center justify-center text-muted-foreground hover:text-red-500 hover:bg-red-500/10"
                      title="删除UP主"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
              </label>
            ))}
            {filtered.length === 0 && (
              <div className="py-8 text-center text-xs text-muted-foreground">没有匹配的UP主</div>
            )}
          </div>
        </ScrollArea>
      </PopoverContent>
    </Popover>

    <AlertDialog open={!!confirmId} onOpenChange={(open) => !open && setConfirmId(null)}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>确认删除 UP 主？</AlertDialogTitle>
          <AlertDialogDescription>
            {confirmingUploader
              ? `将取消关注「${confirmingUploader.name}」，已采集的视频仍会保留。`
              : '将取消关注该 UP 主，已采集的视频仍会保留。'}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel onClick={() => setConfirmId(null)}>取消</AlertDialogCancel>
          <AlertDialogAction onClick={handleConfirmDelete} className="bg-red-600 hover:bg-red-700">
            删除
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>

    <AlertDialog open={!!prioritizeId} onOpenChange={(open) => !open && setPrioritizeId(null)}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>优先处理最近 10 个视频？</AlertDialogTitle>
          <AlertDialogDescription>
            {prioritizingUploader
              ? `将为「${prioritizingUploader.name}」的最近 10 个视频优先排队字幕和总结任务，已有进行中的任务会自动跳过。`
              : '将为该 UP 主的最近 10 个视频优先排队字幕和总结任务。'}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel onClick={() => setPrioritizeId(null)} disabled={prioritizing}>
            取消
          </AlertDialogCancel>
          <AlertDialogAction
            onClick={handleConfirmPrioritize}
            disabled={prioritizing}
            className="bg-amber-600 hover:bg-amber-700"
          >
            {prioritizing ? '排队中...' : '确认优先'}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>

    <AlertDialog open={!!backfillId} onOpenChange={(open) => !open && setBackfillId(null)}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>回溯该 UP 主当年视频？</AlertDialogTitle>
          <AlertDialogDescription>
            {backfillingUploader
              ? `将为「${backfillingUploader.name}」创建任务，拉取当年 1 月 1 日至今的视频。若已有进行中的回溯任务，会自动返回现有任务。`
              : '将为该 UP 主创建任务，拉取当年 1 月 1 日至今的视频。'}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel onClick={() => setBackfillId(null)} disabled={backfilling}>
            取消
          </AlertDialogCancel>
          <AlertDialogAction
            onClick={handleConfirmBackfill}
            disabled={backfilling}
            className="bg-blue-600 hover:bg-blue-700"
          >
            {backfilling ? '创建中...' : '确认回溯'}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>

    <Dialog open={!!editId} onOpenChange={(open) => !open && handleCancelEdit()}>
      <DialogContent className="sm:max-w-xs">
        <DialogHeader>
          <DialogTitle className="text-sm">修改「{editingUploader?.name}」的类型</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 py-1">
          <Select value={editCategory} onValueChange={setEditCategory}>
            <SelectTrigger className="h-9 text-xs w-full">
              <SelectValue placeholder="未分类" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE_KEY}>未分类</SelectItem>
              {PRESET_CATEGORIES.map((c) => (
                <SelectItem key={c} value={c}>
                  {c}
                </SelectItem>
              ))}
              <SelectItem value={CUSTOM_KEY}>自定义</SelectItem>
            </SelectContent>
          </Select>
          {editCategory === CUSTOM_KEY && (
            <Input
              value={editCustom}
              onChange={(e) => setEditCustom(e.target.value)}
              placeholder="输入类型..."
              className="h-9 text-xs"
            />
          )}
          <div className="flex justify-end gap-2">
            <Button variant="outline" size="sm" className="h-8 text-xs" onClick={handleCancelEdit}>
              取消
            </Button>
            <Button
              size="sm"
              className="h-8 text-xs"
              onClick={handleSaveEdit}
              disabled={updating || (editCategory === CUSTOM_KEY && !editCustom.trim())}
            >
              {updating ? '保存中...' : '保存'}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
    </>
  )
}
