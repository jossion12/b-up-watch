import { useState } from 'react'
import { Search, ListFilter, RotateCcw, Trash2 } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
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
import type { Uploader } from '@/types'

interface Props {
  uploaders: Uploader[]
  selected: Set<string>
  onChange: (s: Set<string>) => void
  onDelete?: (id: string) => void | Promise<void>
}

export default function UpFilter({ uploaders, selected, onChange, onDelete }: Props) {
  const [query, setQuery] = useState('')
  const [confirmId, setConfirmId] = useState<string | null>(null)
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

  const confirmingUploader = confirmId ? uploaders.find((u) => u.id === confirmId) : undefined

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
                {onDelete && (
                  <button
                    type="button"
                    onClick={(e) => {
                      e.preventDefault()
                      e.stopPropagation()
                      setConfirmId(u.id)
                    }}
                    className="h-6 w-6 rounded-md flex items-center justify-center text-muted-foreground hover:text-red-500 hover:bg-red-500/10 opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity"
                    title="删除UP主"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                )}
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
    </>
  )
}
