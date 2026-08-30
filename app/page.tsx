import Link from "next/link"
import { getEpisodes, getStats } from "@/lib/api"
import type { Episode } from "@/lib/types"

export const dynamic = "force-dynamic"

export default async function Home() {
  let stats = null
  let episodes: Episode[] = []
  let err = null
  try {
    stats = await getStats()
    const res = await getEpisodes({ limit: 20 })
    episodes = res.data
  } catch (e) {
    err = e instanceof Error ? e.message : String(e)
  }

  const fmtMin = (s: number | null) => (s ? (s / 60).toFixed(0) : "—")
  const fmtHr = (s: number | null) =>
    s ? `${(s / 3600).toFixed(1)} 小时` : "—"
  const fmtWords = (n: number | null) =>
    n ? `${(n / 10000).toFixed(1)} 万` : "—"

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100">
      <div className="mx-auto max-w-5xl px-6 py-10">
        <header className="mb-8">
          <h1 className="text-3xl font-bold">《原来是这样》节目星图</h1>
          <p className="mt-2 text-slate-400">
            673 期科普节目的内容地图 —— 从任何一期出发，顺着关联听下去。
          </p>
          <div className="mt-4 flex gap-3">
            <Link
              href="/map"
              className="rounded-lg bg-sky-500 px-4 py-2 text-sm font-medium hover:bg-sky-400"
            >
              打开星图 →
            </Link>
            <Link
              href="/pits"
              className="rounded-lg bg-slate-800 px-4 py-2 text-sm font-medium hover:bg-slate-700"
            >
              坑看板
            </Link>
            <Link
              href="/browse?tab=subject"
              className="rounded-lg bg-slate-800 px-4 py-2 text-sm font-medium hover:bg-slate-700"
            >
              🔍 细化分类
            </Link>
          </div>
        </header>

        {err && (
          <div className="mb-6 rounded-lg border border-amber-500/40 bg-amber-500/10 p-4 text-sm text-amber-300">
            数据尚未就绪（{err}）。请先在 Supabase 执行 <code>supabase/schema.sql</code> 并导入数据。
          </div>
        )}

        {stats && (
          <section className="mb-8 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              { k: "总期数", v: String(stats.total_episodes) },
              { k: "总时长", v: fmtHr(stats.total_duration_sec) },
              { k: "总字数", v: fmtWords(stats.total_words) },
              { k: "平均时长", v: `${fmtMin(stats.avg_duration_sec)} 分钟` },
            ].map((c) => (
              <div key={c.k} className="rounded-xl bg-slate-900 p-4">
                <div className="text-xs text-slate-400">{c.k}</div>
                <div className="mt-1 text-xl font-semibold">{c.v}</div>
              </div>
            ))}
          </section>
        )}

        <section>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-lg font-semibold">最近节目</h2>
            <span className="text-xs text-slate-500">
              共 {stats?.total_episodes ?? "…"} 期
            </span>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            {episodes.map((e) => (
              <Link
                key={e.id}
                href={`/episodes/${e.num ?? e.id}`}
                className="rounded-lg bg-slate-900 p-4 transition hover:bg-slate-800"
              >
                <div className="flex items-baseline justify-between">
                  <span className="font-medium">
                    {e.num ? `${e.num} · ` : ""}
                    {e.title}
                  </span>
                  <span className="text-xs text-slate-500">
                    {fmtMin(e.duration_sec)} 分钟
                  </span>
                </div>
                {e.tags && e.tags.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {e.tags.slice(0, 4).map((t) => (
                      <span
                        key={t}
                        className="rounded bg-slate-800 px-1.5 py-0.5 text-[11px] text-sky-300"
                      >
                        {t}
                      </span>
                    ))}
                  </div>
                )}
              </Link>
            ))}
          </div>
        </section>
      </div>
    </main>
  )
}
