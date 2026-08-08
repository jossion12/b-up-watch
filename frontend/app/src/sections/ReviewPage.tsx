import { useMemo } from 'react'
import { useNavigate, useParams } from 'react-router'
import { ArrowLeft, Database, ChevronDown } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { cn } from '@/lib/utils'
import type { Uploader } from '@/types'

interface ReviewPageProps {
  uploaders: Uploader[]
}

export default function ReviewPage({ uploaders }: ReviewPageProps) {
  const navigate = useNavigate()
  const { uploaderId } = useParams<{ uploaderId: string }>()

  const currentUploader = useMemo(
    () => uploaders.find((u) => u.id === uploaderId),
    [uploaders, uploaderId]
  )

  const upName = currentUploader?.name || '未知UP主'
  const chatUrl = currentUploader?.ragflowChatUrl

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
            <div className="text-[10px] text-muted-foreground mt-0.5">RagFlow 对话嵌入</div>
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
      </header>

      {/* 主体：对话 iframe */}
      <div className="flex-1 min-h-0 bg-background relative">
        {chatUrl ? (
          <iframe
            src={chatUrl}
            title={`${upName} 复盘对话`}
            className="w-full h-full min-h-[600px] border-0"
            allow="clipboard-write"
          />
        ) : (
          <div className="h-full flex flex-col items-center justify-center p-8 text-center">
            <div className="text-sm font-medium">尚未生成 {upName} 的 RagFlow 对话</div>
            <div className="text-xs text-muted-foreground mt-2 max-w-md leading-relaxed">
              请在任务页面触发该 UP 主的 RAG 同步任务，待 RagFlow 聊天助手创建完成后即可自动嵌入。
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
