import { useEffect, useRef, useCallback } from 'react'

export type WSEvent =
  | { event: 'video.new'; payload: any }
  | { event: 'task.updated'; payload: any }
  | { event: 'summary.completed'; payload: { video_id: string; summary: any } }
  | { event: 'uploader.unread'; payload: { uploader_id: string; unread_count: number } }
  | { event: 'pong' }

export function useWebSocket(onMessage: (msg: WSEvent) => void) {
  const wsRef = useRef<WebSocket | null>(null)
  const onMessageRef = useRef(onMessage)
  onMessageRef.current = onMessage

  const connect = useCallback(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    const url = `${protocol}//${host}/ws`
    const ws = new WebSocket(url)

    ws.onopen = () => {
      // optional heartbeat
    }
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data)
        onMessageRef.current(msg as WSEvent)
      } catch {
        // ignore malformed
      }
    }
    ws.onclose = () => {
      wsRef.current = null
      // auto reconnect after 3s
      setTimeout(connect, 3000)
    }
    ws.onerror = () => {
      ws.close()
    }
    wsRef.current = ws
  }, [])

  useEffect(() => {
    connect()
    return () => {
      wsRef.current?.close()
    }
  }, [connect])
}
