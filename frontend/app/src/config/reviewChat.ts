/**
 * Up 复盘页面默认配置
 *
 * 如需在代码里预置某些 UP 的 shared_id，可在此添加。
 * 页面上的配置会保存在浏览器 localStorage，优先级高于此处。
 */
export const CHAT_SHARE_IDS: Record<string, string> = {
  // 示例：'uploaderId': 'shared_id'
}

/** Dify 分享对话基础地址（无需修改） */
export const CHAT_BASE_URL = 'http://localhost:8899/chats/share'

/** Dify 分享对话固定参数（无需修改） */
export const CHAT_FIXED_PARAMS =
  'from=chat&auth=x6trEIhnczD9vljT4q_HHvvovNPxpWwL&locale=zh-Hans&theme=light'

export function buildChatUrl(sharedId: string): string {
  return `${CHAT_BASE_URL}?shared_id=${encodeURIComponent(sharedId)}&${CHAT_FIXED_PARAMS}`
}

const LOCAL_STORAGE_KEY = 'upwatch_chat_share_ids'

export function getStoredShareIds(): Record<string, string> {
  try {
    const raw = localStorage.getItem(LOCAL_STORAGE_KEY)
    return raw ? (JSON.parse(raw) as Record<string, string>) : {}
  } catch {
    return {}
  }
}

export function saveStoredShareId(uploaderId: string, sharedId: string): void {
  const current = getStoredShareIds()
  current[uploaderId] = sharedId
  localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(current))
}

export function removeStoredShareId(uploaderId: string): void {
  const current = getStoredShareIds()
  delete current[uploaderId]
  localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(current))
}

export function getEffectiveShareId(uploaderId: string | undefined): string | undefined {
  if (!uploaderId) return undefined
  return getStoredShareIds()[uploaderId] || CHAT_SHARE_IDS[uploaderId]
}
