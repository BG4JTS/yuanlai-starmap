import Link from "next/link"
import { notFound } from "next/navigation"
import PitForm from "@/components/PitForm"
import { getEpisodeByNum, getRelated, getPits } from "@/lib/api"
import type { EdgeKind } from "@/lib/types"

export const dynamic = "force-dynamic"
export const dynamicParams = true

const KIND_CN: Record<EdgeKind, string> = {
  series: "同系列",
  ref: "互相引用",
  tag: "共享标签",
  semantic: "语义相似",
  concept: "共享概念",
}

export default async function EpisodePage({
  params,
}: {
  params: Promise<{ num: string }>
}) {
  const { num: numStr } = await params
  const num = Number(numStr)
  if (Number.isNaN(num)) notFound()

  const ep = await getEpisodeByNum(num).catch(() => null)
  if (!ep) notFound()

  const [related, pits] = await Promise.all([
    getRelated(ep.id, 12).catch(() => []),
    getPits({ episodeId: ep.id }).catch(() => []),
  ])

  const fmtMin = (s: number | null) => (s ? (s / 60).toFixed(0) : "—")
  const fmtWords = (n: number | null) => (n ? (n / 10000).toFixed(1) : "—")

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100">
      <div className="mx-auto max-w-4xl px-6 py-8">
        <nav className="mb-6 text-xs text-slate-500">
          <Link href="/" className="hover:text-sky-400">
            ← 首页
          </Link>
          <span className="mx-2">/</span>
          <Link href="/map" className="hover:text-sky-400">
            星图
          </Link>
        </nav>

        <header className="mb-6">
          <div className="flex items-baseline gap-3">
            {ep.num && <span className="text-2xl font-bold text-slate-500">{ep.num}</span>}
            <h1 className="text-2xl font-bold">{ep.title}</h1>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-4 text-sm text-slate-400">
            {ep.duration_sec && <span>{fmtMin(ep.duration_sec)} 分钟</span>}
            {ep.word_count && <span>{fmtWords(ep.word_count)} 万字</span>}
            {ep.publish_date && <span>{ep.publish_date}</span>}
            {ep.series && (
              <Link href={`/map?focus=${ep.num ?? ""}`} className="text-sky-400 hover:underline">
                系列：{ep.series.name}
              </Link>
            )}
          </div>
          {ep.tags && ep.tags.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {ep.tags.map((t) => (
                <Link
                  key={t}
                  href={`/map?focus=${ep.num ?? ""}`}
                  className="rounded bg-slate-800 px-2 py-0.5 text-xs text-sky-300 hover:bg-slate-700"
                >
                  {t}
                </Link>
              ))}
            </div>
          )}
          {ep.concepts && ep.concepts.length > 0 && (
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <span className="text-xs text-slate-500">概念：</span>
              {ep.concepts.map((c) => (
                <span key={c} className="rounded bg-slate-800/60 px-2 py-0.5 text-xs text-slate-300">
                  {c}
                </span>
              ))}
            </div>
          )}
          {ep.guests && ep.guests.length > 0 && (
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <span className="text-xs text-slate-500">嘉宾：</span>
              {ep.guests.map((g) => (
                <Link
                  key={g}
                  href={`/browse?tab=guest`}
                  className="rounded bg-teal-500/15 px-2 py-0.5 text-xs text-teal-300 hover:bg-teal-500/30"
                >
                  🎤 {g}
                </Link>
              ))}
            </div>
          )}
          {ep.era && ep.era.length > 0 && (
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <span className="text-xs text-slate-500">年代：</span>
              {ep.era.map((e) => (
                <Link
                  key={e}
                  href={`/browse?tab=era`}
                  className="rounded bg-amber-500/15 px-2 py-0.5 text-xs text-amber-300 hover:bg-amber-500/30"
                >
                  ⏳ {e}
                </Link>
              ))}
            </div>
          )}
          {ep.summary && (
            <p className="mt-3 text-sm leading-relaxed text-slate-300">{ep.summary}</p>
          )}
          {ep.promised && ep.promised.length > 0 && (
            <div className="mt-3 rounded-lg border border-orange-500/30 bg-orange-500/5 p-3">
              <div className="text-xs text-orange-300">🕳️ 本期挖坑（主播预告后续细说）</div>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {ep.promised.map((p) => (
                  <span key={p} className="rounded bg-orange-500/10 px-2 py-0.5 text-xs text-orange-200">
                    {p}
                  </span>
                ))}
              </div>
            </div>
          )}
        </header>

        {ep.audio_url && (
          <div className="mb-6">
            <audio controls src={ep.audio_url} className="w-full" preload="none" />
          </div>
        )}

        {ep.platforms && Object.keys(ep.platforms).length > 0 && (
          <div className="mb-6 flex gap-3 text-sm">
            {Object.entries(ep.platforms).map(([k, v]) =>
              v ? (
                <a
                  key={k}
                  href={v}
                  target="_blank"
                  rel="noreferrer"
                  className="text-sky-400 hover:underline"
                >
                  {k === "ximalaya" ? "喜马拉雅" : k === "xiaoyuzhou" ? "小宇宙" : "Apple"} ↗
                </a>
              ) : null
            )}
          </div>
        )}

        <section className="mb-8">
          <h2 className="mb-3 text-lg font-semibold">相关节目</h2>
          {related.length === 0 ? (
            <p className="text-sm text-slate-500">暂无关联（数据导入后自动出现）。</p>
          ) : (
<div className="grid gap-2 sm:grid-cols-2">
              {related.map((r: any, i: number) => {
                const ep = r.episode as { num?: number | null; id: number; title: string }
                const k = r.kind as EdgeKind
                const ev = r.evidence as string | null
                return (
                <Link
                  key={i}
                  href={`/episodes/${ep.num ?? ep.id}`}
                  className="rounded-lg bg-slate-900 p-3 transition hover:bg-slate-800"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-medium">
                      {ep.num ? `${ep.num} · ` : ""}
                      {ep.title}
                    </span>
                    <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[11px] text-slate-300">
                      {KIND_CN[k]}
                    </span>
                  </div>
                  {ev && (
                    <div className="mt-1 text-xs text-slate-500">因 {ev}</div>
                  )}
                </Link>
                )
              })}
            </div>
          )}
        </section>

        <section>
          <h2 className="mb-3 text-lg font-semibold">
            坑（{pits.length}）
          </h2>
          <PitForm episodeId={ep.id} />
          {pits.length > 0 && (
            <ul className="mt-4 space-y-2">
              {pits.map((p) => (
                <li key={p.id} className="rounded-lg bg-slate-900 p-3 text-sm">
                  <div className="flex items-start justify-between gap-2">
                    <span>{p.content}</span>
                    <span className="shrink-0 rounded bg-slate-800 px-1.5 py-0.5 text-[11px] text-slate-400">
                      {p.status} · {p.echo_count} 共鸣
                    </span>
                  </div>
                  {p.ts_sec != null && (
                    <div className="mt-1 text-xs text-slate-500">
                      时间戳 {Math.floor(p.ts_sec / 60)}:{String(p.ts_sec % 60).padStart(2, "0")}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </main>
  )
}
