import { useEffect, useState } from 'react'
import { Loader2, Save, Settings } from 'lucide-react'

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
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { systemApi, type SystemConfig, type SystemStatus } from '@/lib/api'

export default function SettingsDialog() {
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [config, setConfig] = useState<SystemConfig | null>(null)
  const [status, setStatus] = useState<SystemStatus | null>(null)
  const [sessdata, setSessdata] = useState('')
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
        setSessdata(cfg.bilibili_sessdata || '')
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
        bilibili_sessdata: sessdata,
        bilibili_cookie: cookie,
      })
      setConfig(updated)
      setSessdata(updated.bilibili_sessdata || '')
      setCookie(updated.bilibili_cookie || '')
      setOpen(false)
    } catch (e: any) {
      setError(e?.error?.message || '保存失败')
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
              <Label htmlFor="bilibili-sessdata">B站 SESSDATA</Label>
              <Input
                id="bilibili-sessdata"
                value={sessdata}
                onChange={(e) => setSessdata(e.target.value)}
                placeholder="从浏览器 Cookie 中复制 SESSDATA 值"
              />
              <p className="text-xs text-muted-foreground">
                留空表示不使用登录态。若已填写完整 Cookie，此项可留空。
              </p>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="bilibili-cookie">B站完整 Cookie（可选）</Label>
              <Textarea
                id="bilibili-cookie"
                value={cookie}
                onChange={(e) => setCookie(e.target.value)}
                placeholder="从浏览器开发者工具复制 bilibili.com 下的完整 Cookie 字符串"
                rows={4}
              />
              <p className="text-xs text-muted-foreground">
                包含 SESSDATA、buvid3、buvid4 等指纹 Cookie，可显著降低 412 风控概率。修改后即时生效。
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
