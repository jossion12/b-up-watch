import { useMemo, useState } from 'react'
import { Filter, RotateCcw, Search } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { ScrollArea } from '@/components/ui/scroll-area'
import type { Uploader } from '@/types'

interface Props {
  uploaders: Uploader[]
  selected: Set<string>
  onChange: (s: Set<string>) => void
}

export default function CategoryFilter({ uploaders, selected, onChange }: Props) {
  const [query, setQuery] = useState('')

  const categories = useMemo(() => {
    const set = new Set<string>()
    for (const u of uploaders) {
      if (u.category && u.category !== '未分类') {
        set.add(u.category)
      }
    }
    return Array.from(set).sort()
  }, [uploaders])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return categories
    return categories.filter((c) => c.toLowerCase().includes(q))
  }, [categories, query])

  const toggle = (category: string) => {
    const next = new Set(selected)
    if (next.has(category)) next.delete(category)
    else next.add(category)
    onChange(next)
  }

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" className="gap-1.5 text-xs h-8">
          <Filter className="h-3.5 w-3.5" />
          类型筛选
          {selected.size > 0 && (
            <Badge className="h-4 min-w-4 px-1 text-[10px] rounded-full">{selected.size}</Badge>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-64 p-0">
        <div className="p-3 pb-2">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索类型..."
              className="h-8 pl-8 text-xs bg-muted/50 border-0 focus-visible:ring-1"
            />
          </div>
        </div>
        <div className="px-3 py-2 border-y flex items-center justify-between text-xs text-muted-foreground">
          <span>{selected.size > 0 ? `已选 ${selected.size} 类` : '显示全部类型'}</span>
          {selected.size > 0 && (
            <button
              onClick={() => onChange(new Set())}
              className="inline-flex items-center gap-1 text-primary hover:underline"
            >
              <RotateCcw className="h-3 w-3" /> 重置
            </button>
          )}
        </div>
        <ScrollArea className="h-[260px]">
          <div className="p-2 space-y-0.5">
            {filtered.map((c) => (
              <label
                key={c}
                className="flex items-center gap-2.5 rounded-lg px-2 py-2 hover:bg-accent cursor-pointer"
              >
                <Checkbox checked={selected.has(c)} onCheckedChange={() => toggle(c)} />
                <span className="text-xs font-medium">{c}</span>
                <span className="text-[10px] text-muted-foreground ml-auto">
                  {uploaders.filter((u) => u.category === c).length} 位
                </span>
              </label>
            ))}
            {filtered.length === 0 && (
              <div className="py-8 text-center text-xs text-muted-foreground">
                {categories.length === 0 ? '暂无类型，可在添加 UP主时设置' : '没有匹配的类型'}
              </div>
            )}
          </div>
        </ScrollArea>
      </PopoverContent>
    </Popover>
  )
}
