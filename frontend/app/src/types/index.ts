export type Sentiment = 'positive' | 'neutral' | 'negative' | 'mixed'

export interface Uploader {
  id: string
  name: string
  fans: string
  category: string
  color: string
  description: string
  unread: number
  lastActive: string
}

export interface VideoSummary {
  brief: string
  points: string[]
  stance: {
    label: string
    sentiment: Sentiment
    detail: string
  }
  topics: string[]
  quote: string
}

export type VideoStatus = 'new' | 'downloaded' | 'summarized'

export interface SubtitleLine {
  time: string
  text: string
}

export interface Video {
  id: string
  bvid: string
  upId: string
  title: string
  duration: string
  /** 发布日期分组文案，如「今天」「7月21日」 */
  dateGroup: string
  /** 发布时分，如「10:32」 */
  time: string
  /** ISO 8601 完整发布时间，用于精确排序/定位 */
  publishedAt: string
  views: string
  danmaku: string
  likes: string
  tags: string[]
  status: VideoStatus
  gradient: string
  summary?: VideoSummary
  subtitles: SubtitleLine[]
}

export interface TopicOpinion {
  upId: string
  sentiment: Sentiment
  stance: string
  opinion: string
  videoTitle: string
}

export interface TopicCluster {
  id: string
  topic: string
  heat: number
  videoCount: number
  opinions: TopicOpinion[]
}
