import Link from "next/link"
import { getPits } from "@/lib/api"
import type { PitStatus } from "@/lib/types"

export const dynamic = "force-dynamic"

const STATUS_CN: Record<PitStatus, string> = {
  open: "待填",
  claimed: "已认领",
  filled: "已填",
  verified: "已验证",
  sleeping: "沉睡",
}
const STATUS_COLOR: Record<PitStatus, string> = {
  open: "bg-sky-500/15 text-sky-300",
  claimed: "bg-amber-500/15 text-amber-300",
  filled: "bg-emerald-500/15 text-emerald-300",
  verified: "bg-purple-500/15 text-purple-300",
  sleeping: "bg-slate-600/30 text-slate-400",
}

export default async function PitsPage({
  searchParams,
}: {
  searchParams: Promise<{ status?: string }>
}) {
  const params = await searchParams
  const status = (params.status as PitStatus | undefined) ?? "open"
  const pits = await getPits({ status, limit: 100 }).catch(() => [])

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100">
      <div className="mx-auto max-w-3xl px-6 py-8">
        <nav className="mb-6 text-xs text-slate-500">
          <Link href="/" className="hover:text-sky-400">
            ← 首页
          </Link>
        </nav>

        <header className="mb-6">
          <h1 className="text-2xl font-bold">坑看板</h1>
          <p className="mt-1 text-sm text-slate-400">
            节目中提到但没展开的话题 —— 你来填，或等主播做"填坑特辑"。
          </p>
          <div className="mt-3 flex gap-2 text-xs">
            {(["open", "claimed", "filled", "verified"] as PitStatus[]).map((s) => (
              <Link
                key={s}
                href={`/pits?status=${s}`}
                className={`rounded-full px-3 py-1 ${
                  status === s
                    ? "bg-sky-500 text-white"
                    : "bg-slate-800 text-slate-300 hover:bg-slate-700"
                }`}
              >
                {STATUS_CN[s]}
              </Link>
            ))}
          </div>
        </header>

        {pits.length === 0 ? (
          <p className="text-sm text-slate-500">
            暂无{" "}{STATUS_CN[status]} 的坑。数据导入后这里会显示听众挖的坑。
          </p>
        ) : (
          <ul className="space-y-2">
            {pits.map((p) => (
              <li
                key={p.id}
                className="rounded-xl bg-slate-900 p-4 transition hover:bg-slate-800"
              >
                <div className="flex items-start justify-between gap-3">
                  <Link
                    href={`/episodes/${p.episode?.num ?? p.episode_id}`}
                    className="font-medium hover:text-sky-400"
                  >
                    {p.content}
                  </Link>
                  <span
                    className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] ${STATUS_COLOR[p.status]}`}
                  >
                    {STATUS_CN[p.status]}
                  </span>
                </div>
                <div className="mt-2 flex items-center gap-3 text-xs text-slate-500">
                  {p.episode && (
                    <span>
                      出自 {p.episode.num ? `第${p.episode.num}期` : ""}《
                      {p.episode.title}
                      》
                    </span>
                  )}
                  <span>{p.echo_count} 人共鸣</span>
                  {p.ts_sec != null && (
                    <span>
                      @{Math.floor(p.ts_sec / 60)}:{String(p.ts_sec % 60).padStart(2, "0")}
                    </span>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </main>
  )
}
