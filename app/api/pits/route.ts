import { NextResponse } from "next/server"
import { getSupabase } from "@/lib/supabase"

export const runtime = "nodejs"

// 简单限流：按 IP 记内存计数（单实例够用；生产可换 Redis/Upstash）
const rate = new Map<string, { count: number; ts: number }>()
const LIMIT = 20 // 每 10 分钟最多 20 次

function rateLimit(ip: string): boolean {
  const now = Date.now()
  const cur = rate.get(ip)
  if (!cur || now - cur.ts > 10 * 60 * 1000) {
    rate.set(ip, { count: 1, ts: now })
    return true
  }
  cur.count += 1
  return cur.count <= LIMIT
}

export async function POST(req: Request) {
  const ip =
    req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() || "unknown"
  if (!rateLimit(ip)) {
    return NextResponse.json({ error: "操作太频繁，请稍后再试" }, { status: 429 })
  }

  let body: { episode_id?: number; content?: string; ts_sec?: number | null }
  try {
    body = await req.json()
  } catch {
    return NextResponse.json({ error: "无效请求" }, { status: 400 })
  }

  if (!body.episode_id || !body.content?.trim()) {
    return NextResponse.json({ error: "缺少 episode_id 或 content" }, { status: 400 })
  }
  if (body.content.trim().length > 500) {
    return NextResponse.json({ error: "坑内容过长（≤500字）" }, { status: 400 })
  }

  const { data, error } = await getSupabase()
    .from("pits")
    .insert({
      episode_id: body.episode_id,
      content: body.content.trim(),
      ts_sec: body.ts_sec ?? null,
      source: "user",
    })
    .select()
    .single()

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 })
  }
  return NextResponse.json(data, { status: 201 })
}
