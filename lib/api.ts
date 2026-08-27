// 数据访问层：所有 Supabase 查询封装（服务端组件/API 使用）
import { supabase } from "./supabase"
import type {
  Episode,
  Edge,
  Pit,
  Fill,
  Graph,
  GraphNode,
  GraphEdge,
  PitStatus,
  SiteStats,
} from "./types"

// ---------- 节目 ----------
export async function getEpisodes(opts?: {
  limit?: number
  offset?: number
  tag?: string
  seriesId?: number
  search?: string
}): Promise<{ data: Episode[]; total: number }> {
  let q = supabase
    .from("episodes")
    .select("*, series:series_id(name, description)", { count: "exact" })
    .order("num", { ascending: true })

  if (opts?.tag) q = q.contains("tags", [opts.tag])
  if (opts?.seriesId) q = q.eq("series_id", opts.seriesId)
  if (opts?.search) q = q.ilike("title", `%${opts.search}%`)
  if (opts?.limit) q = q.range(opts.offset ?? 0, (opts.offset ?? 0) + opts.limit - 1)

  const { data, error, count } = await q
  if (error) throw error
  return { data: (data as Episode[]) ?? [], total: count ?? 0 }
}

export async function getEpisodeByNum(num: number): Promise<Episode | null> {
  const { data, error } = await supabase
    .from("episodes")
    .select("*, series:series_id(name, description)")
    .eq("num", num)
    .maybeSingle()
  if (error) throw error
  return (data as Episode) ?? null
}

export async function getEpisodeById(id: number): Promise<Episode | null> {
  const { data, error } = await supabase
    .from("episodes")
    .select("*, series:series_id(name, description)")
    .eq("id", id)
    .maybeSingle()
  if (error) throw error
  return (data as Episode) ?? null
}

// ---------- 星图 ----------
/** 拉取星图数据：默认全部节点+边；传 focusNum 时只取该节点 2 跳邻域（防毛线球） */
export async function getGraph(focusNum?: number, hopLimit = 2): Promise<Graph> {
  if (!focusNum) {
    const [nodes, edges] = await Promise.all([
      supabase.from("episodes").select("id, num, title, duration_sec, tags, series_id, summary").order("num"),
      supabase.from("edges").select("*").limit(20000),
    ])
    if (nodes.error) throw nodes.error
    if (edges.error) throw edges.error
    return { nodes: mapNodes(nodes.data ?? []), edges: mapEdges(edges.data ?? []) }
  }

  // 局部图：从焦点期出发取 2 跳邻域
  const focus = await getEpisodeByNum(focusNum)
  if (!focus) return { nodes: [], edges: [] }

  const ids = new Set<number>([focus.id])
  let frontier = [focus.id]
  for (let h = 0; h < hopLimit; h++) {
    const { data: edges, error } = await supabase
      .from("edges")
      .select("*")
      .or(`ep_a.in.(${[...frontier].join(",")}),ep_b.in.(${[...frontier].join(",")})`)
      .limit(2000)
    if (error) throw error
    const next = new Set<number>(frontier)
    for (const e of (edges ?? []) as Edge[]) {
      next.add(e.ep_a)
      next.add(e.ep_b)
    }
    next.forEach((id) => ids.add(id))
    frontier = [...next]
  }

  const { data: nodes, error: nodeErr } = await supabase
    .from("episodes")
    .select("id, num, title, duration_sec, tags, series_id, summary")
    .in("id", [...ids])
  if (nodeErr) throw nodeErr

  const { data: allEdges, error: edgeErr } = await supabase
    .from("edges")
    .select("*")
    .limit(20000)
  if (edgeErr) throw edgeErr

  const keep = (allEdges ?? []).filter(
    (e: Edge) => ids.has(e.ep_a) && ids.has(e.ep_b)
  )
  return { nodes: mapNodes(nodes ?? []), edges: mapEdges(keep) }
}

function mapNodes(rows: unknown[]): GraphNode[] {
  return (rows as Episode[]).map((e) => ({
    id: String(e.id),
    label: e.num ? `${e.num} ${e.title?.slice(0, 12)}` : e.title,
    num: e.num,
    title: e.title,
    duration_sec: e.duration_sec,
    tags: e.tags,
    series_id: e.series_id,
    summary: e.summary,
    size: 14 + Math.min(46, (e.duration_sec ?? 0) / 55),
  }))
}

function mapEdges(rows: unknown[]): GraphEdge[] {
  return (rows as Edge[]).map((e) => ({
    from: String(e.ep_a),
    to: String(e.ep_b),
    kind: e.kind,
    weight: e.weight,
    evidence: e.evidence,
  }))
}

// ---------- 相关节目（复用 edges 表） ----------
export async function getRelated(episodeId: number, limit = 12) {
  const { data, error } = await supabase
    .from("edges")
    .select("*, a:ep_a(id, num, title, tags, duration_sec), b:ep_b(id, num, title, tags, duration_sec)")
    .or(`ep_a.eq.${episodeId},ep_b.eq.${episodeId}`)
    .order("weight", { ascending: false })
    .limit(limit)
  if (error) throw error
  // 归一化：把对端提取出来
  return (data ?? []).map((row: Record<string, unknown>) => {
    const a = row.a as Episode
    const b = row.b as Episode
    const other = a.id === episodeId ? b : a
    return {
      episode: other,
      kind: row.kind,
      weight: row.weight,
      evidence: row.evidence,
    }
  })
}

// ---------- 坑 ----------
export async function getPits(opts?: { status?: PitStatus; episodeId?: number; limit?: number }) {
  let q = supabase
    .from("pits")
    .select("*, episode:episode_id(num, title), fills:fills(*)")
    .order("echo_count", { ascending: false })
  if (opts?.status) q = q.eq("status", opts.status)
  if (opts?.episodeId) q = q.eq("episode_id", opts.episodeId)
  if (opts?.limit) q = q.limit(opts.limit)
  const { data, error } = await q
  if (error) throw error
  return (data ?? []) as Pit[]
}

export async function createPit(input: {
  episode_id: number
  content: string
  ts_sec?: number | null
}): Promise<Pit> {
  const { data, error } = await supabase.from("pits").insert(input).select().single()
  if (error) throw error
  return data as Pit
}

export async function echoPit(pitId: number): Promise<void> {
  // 幂等由应用层（本地标记）控制；简单实现为 +1
  try {
    const { error } = await supabase.rpc("echo_pit", { pid: pitId })
    if (error) {
      // 兜底：直接 update echo_count = echo_count + 1
      const { data: pit } = await supabase
        .from("pits")
        .select("echo_count")
        .eq("id", pitId)
        .single()
      if (pit) {
        await supabase
          .from("pits")
          .update({ echo_count: (pit.echo_count ?? 0) + 1 })
          .eq("id", pitId)
      }
    }
  } catch {
    // 静默失败（匿名场景下可接受）
  }
}

export async function createFill(input: {
  pit_id: number
  content: string
  episode_id?: number | null
}): Promise<Fill> {
  const { data, error } = await supabase.from("fills").insert(input).select().single()
  if (error) throw error
  // 坑状态 → filled
  await supabase
    .from("pits")
    .update({ status: "filled", filled_by: input.episode_id ?? null })
    .eq("id", input.pit_id)
  return data as Fill
}

// ---------- 全站统计 ----------
export async function getStats(): Promise<SiteStats> {
  const [ep, edges, pits, series] = await Promise.all([
    supabase.from("episodes").select("id, duration_sec, word_count"),
    supabase.from("edges").select("id", { count: "exact", head: true }),
    supabase.from("pits").select("id", { count: "exact", head: true }),
    supabase.from("series").select("id", { count: "exact", head: true }),
  ])
  const eps = (ep.data ?? []) as Pick<Episode, "duration_sec" | "word_count">[]
  const totalDur = eps.reduce((s, e) => s + (e.duration_sec ?? 0), 0)
  const totalWords = eps.reduce((s, e) => s + (e.word_count ?? 0), 0)
  return {
    total_episodes: eps.length,
    total_duration_sec: totalDur,
    total_words: totalWords,
    avg_duration_sec: eps.length ? Math.round(totalDur / eps.length) : 0,
    series_count: series.count ?? 0,
    pit_count: pits.count ?? 0,
  }
}
