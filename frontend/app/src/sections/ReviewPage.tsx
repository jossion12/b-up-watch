import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import { ArrowLeft, Database, ChevronDown, Settings, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { cn } from '@/lib/utils'
import {
  buildChatUrl,
  getEffectiveShareId,
  saveStoredShareId,
  removeStoredShareId,
} from '@/config/reviewChat'
import type { Uploader } from '@/types'

interface ReviewPageProps {
  uploaders: Uploader[]
}

export default function ReviewPage({ uploaders }: ReviewPageProps) {
  const navigate = useNavigate()
  const { uploaderId } = useParams<{ uploaderId: string }>()
  const [sharedId, setSharedId] = useState<string | undefined>(() =>
    getEffectiveShareId(uploaderId)
  )
  const [inputValue, setInputValue] = useState('')
  const [showConfig, setShowConfig] = useState(false)

  useEffect(() => {
    setSharedId(getEffectiveShareId(uploaderId))
    setInputValue('')
    setShowConfig(false)
  }, [uploaderId])

  const currentUploader = useMemo(
    () => uploaders.find((u) => u.id === uploaderId),
    [uploaders, uploaderId]
  )

  const upName = currentUploader?.name || '未知UP主'

  const handleSave = () => {
    const value = inputValue.trim()
    if (!uploaderId || !value) return
    saveStoredShareId(uploaderId, value)
    setSharedId(value)
    setShowConfig(false)
  }

  const handleRemove = () => {
    if (!uploaderId) return
    removeStoredShareId(uploaderId)
    setSharedId(undefined)
    setInputValue('')
  }

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
            <div className="text-[10px] text-muted-foreground mt-0.5">Dify 对话嵌入</div>
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

        <Button
          variant="ghost"
          size="sm"
          className="text-xs gap-1.5"
          onClick={() => {
            setInputValue(sharedId || '')
            setShowConfig((v) => !v)
          }}
        >
          <Settings className="h-3.5 w-3.5" />
          配置 shared_id
        </Button>
      </header>

      {/* 主体：对话 iframe */}
      <div className="flex-1 min-h-0 bg-background relative">
        {sharedId && !showConfig ? (
          <iframe
            src={buildChatUrl(sharedId)}
            title={`${upName} 复盘对话`}
            className="w-full h-full min-h-[600px] border-0"
            allow="clipboard-write"
          />
        ) : (
          <div className="h-full flex flex-col items-center justify-center p-8 text-center">
            <div className="text-sm font-medium">
              {showConfig ? '配置对话' : `尚未配置 ${upName} 的对话`}
            </div>
            <div className="text-xs text-muted-foreground mt-2 max-w-md leading-relaxed">
              在下方输入该 UP 主对应的 Dify shared_id，保存后即可嵌入对话。
            </div>

            <div className="w-full max-w-md mt-6 space-y-3">
              <Input
                placeholder="粘贴 shared_id"
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                className="text-sm"
              />
              <div className="flex items-center justify-center gap-2">
                <Button
                  onClick={handleSave}
                  disabled={!inputValue.trim()}
                  className="text-xs"
                >
                  保存
                </Button>
                {sharedId && (
                  <Button
                    variant="outline"
                    size="icon"
                    onClick={handleRemove}
                    title="清除配置"
                    className="text-xs"
                  >
                    <Trash2 className="h-4 w-4 text-destructive" />
                  </Button>
                )}
              </div>
            </div>

            <div className="text-xs text-muted-foreground mt-6">
              当前 uploaderId：<code className="bg-muted px-1 py-0.5 rounded">{uploaderId}</code>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
