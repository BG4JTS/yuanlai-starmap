// 数据类型定义（对应 supabase/schema.sql）

export type Series = {
  id: number
  name: string
  description: string | null
  source: "llm" | "user"
  created_at: string
}

export type Episode = {
  id: number
  num: number | null
  title: string
  title_raw: string | null
  publish_date: string | null
  audio_url: string | null
  platforms: { ximalaya?: string; xiaoyuzhou?: string; apple?: string } | null
  duration_sec: number | null
  word_count: number | null
  transcript_ref: string | null
  summary: string | null
  tags: string[] | null
  concepts: string[] | null
  referenced: number[] | null
  series_id: number | null
  created_at: string
  // 关联（联表查询注入）
  series?: Series | null
}

export type EdgeKind = "series" | "ref" | "tag" | "semantic" | "concept"

export type Edge = {
  ep_a: number
  ep_b: number
  kind: EdgeKind
  weight: number | null
  evidence: string | null
}

export type PitStatus = "open" | "claimed" | "filled" | "verified" | "sleeping"

export type Pit = {
  id: number
  episode_id: number
  ts_sec: number | null
  content: string
  status: PitStatus
  source: "user" | "llm" | "host"
  echo_count: number
  claimant: string | null
  filled_by: number | null
  created_at: string
  updated_at: string
  // 关联
  episode?: Pick<Episode, "id" | "num" | "title"> | null
  fills?: Fill[] | null
}

export type Fill = {
  id: number
  pit_id: number
  content: string | null
  episode_id: number | null
  source: "user" | "host"
  verified: boolean
  created_at: string
}

// 星图节点/边（前端渲染）
export type GraphNode = {
  id: string
  label: string
  num: number | null
  title: string
  duration_sec: number | null
  tags: string[] | null
  series_id: number | null
  size: number
  color?: string
  summary?: string | null
}

export type GraphEdge = {
  from: string
  to: string
  kind: EdgeKind
  weight: number | null
  evidence: string | null
}

export type Graph = {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

// 全站统计
export type SiteStats = {
  total_episodes: number
  total_duration_sec: number
  total_words: number
  avg_duration_sec: number
  series_count: number
  pit_count: number
}
