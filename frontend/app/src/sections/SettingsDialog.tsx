import { useEffect, useState } from 'react'
import { Loader2, Save, Settings } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { systemApi, type SystemConfig, type SystemStatus } from '@/lib/api'

interface SettingsDialogProps {
  open?: boolean
  onOpenChange?: (open: boolean) => void
}

export default function SettingsDialog({ open: controlledOpen, onOpenChange }: SettingsDialogProps) {
  const [internalOpen, setInternalOpen] = useState(false)
  const open = controlledOpen ?? internalOpen
  const setOpen = (value: boolean) => {
    setInternalOpen(value)
    onOpenChange?.(value)
  }
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [config, setConfig] = useState<SystemConfig | null>(null)
  const [status, setStatus] = useState<SystemStatus | null>(null)
  const [cookie, setCookie] = useState('')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    setLoading(true)
    setError(null)
    Promise.all([systemApi.config(), systemApi.status()])
      .then(([cfg, s]) => {
        setConfig(cfg)
        setStatus(s)
        setCookie(cfg.bilibili_cookie || '')
      })
      .catch((e: any) => {
        setError(e?.error?.message || '加载配置失败')
      })
      .finally(() => setLoading(false))
  }, [open])

  const handleSave = async () => {
    setSaving(true)
    setError(null)
    try {
      const updated = await systemApi.updateConfig({
        bilibili_cookie: cookie,
      })
      setConfig(updated)
      setCookie(updated.bilibili_cookie || '')
      const sessLen = (updated.bilibili_sessdata || '').length
      const cookieLen = (updated.bilibili_cookie || '').length
      if (cookieLen === 0) {
        toast.success('已保存（已清除 Cookie / SESSDATA）')
      } else if (sessLen === 0) {
        toast.error(
          `Cookie 中未找到 SESSDATA！请确认你已登录 B 站，并复制登录态 cookie（包含 SESSDATA / bili_jct / DedeUserID），而不是浏览器的匿名追踪 cookie（buvid3/buvid4/_uuid）。`,
          { duration: 12000 },
        )
      } else {
        toast.success(
          `已保存：SESSDATA 已从 Cookie 自动提取（${sessLen} 字符）`
        )
      }
      setOpen(false)
    } catch (e: any) {
      setError(e?.error?.message || '保存失败')
      toast.error(e?.error?.message || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <button
          className="h-8 w-8 rounded-lg flex items-center justify-center hover:bg-accent hover:text-foreground transition-colors"
          title="设置"
        >
          <Settings className="h-4 w-4" />
        </button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>系统设置</DialogTitle>
          <DialogDescription>管理 B站 Cookie 等运行时配置。</DialogDescription>
        </DialogHeader>

        {loading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label htmlFor="bilibili-cookie">B站 Cookie</Label>
              <Textarea
                id="bilibili-cookie"
                value={cookie}
                onChange={(e) => setCookie(e.target.value)}
                placeholder="SESSDATA=xxx; bili_jct=xxx; DedeUserID=xxx; buvid3=xxx; buvid4=xxx; ..."
                rows={6}
              />
              <p className="text-xs text-muted-foreground">
                <strong>必须包含 SESSDATA</strong>（登录态凭证）。获取方式：
                <br />
                1. 浏览器登录 <a href="https://www.bilibili.com" target="_blank" rel="noreferrer" className="underline">bilibili.com</a>
                <br />
                2. F12 → Application → Cookies → 选 https://www.bilibili.com
                <br />
                3. 找到 SESSDATA / bili_jct / DedeUserID 这一组（注意 ⚠️ 不要只复制 buvid3/buvid4 等匿名追踪字段）
                <br />
                4. 在 Console 跑 <code className="px-1 bg-muted rounded">document.cookie</code> 一键复制所有 cookie
              </p>
            </div>

            {status && (
              <div className="grid gap-2">
                <Label>当前 LLM 模型</Label>
                <div className="text-sm text-muted-foreground">{status.llm.model}</div>
              </div>
            )}

            {config && (
              <div className="grid gap-2">
                <Label>总结模型（AI 总结已暂停）</Label>
                <div className="text-sm text-muted-foreground">{config.summary_model}</div>
              </div>
            )}
          </div>
        )}

        {error && <p className="text-xs text-red-500">{error}</p>}

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} disabled={saving}>
            取消
          </Button>
          <Button onClick={handleSave} disabled={loading || saving}>
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            保存
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
