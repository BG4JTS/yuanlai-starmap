import Link from "next/link"
import fs from "fs"
import path from "path"

type Meta = { ep: string; num: number | null; title: string; duration_min: number }
type PitLink = {
  dig_ep: string
  dig_title: string
  dig_num: number | null
  fill_ep: string
  fill_title: string
  fill_num: number | null
  phrase: string
  gap: number | null
}

const D = path.join(process.cwd(), "src", "data")
function load<T>(name: string): T {
  return JSON.parse(fs.readFileSync(path.join(D, name), "utf-8"))
}

const tree = load<Record<string, Record<string, string[]>>>("subject_tree.json")
const pits = load<PitLink[]>("pits.json")
const eras = load<Record<string, string[]>>("era_groups.json")
const guests = load<Record<string, string[]>>("guest_groups.json")
const meta = load<Record<string, Meta>>("episodes_meta.json")

function EpChip({ ep }: { ep: string }) {
  const m = meta[ep]
  const label = m ? `${m.num ?? ep} ${m.title.slice(0, 18)}` : ep
  const inner = (
    <span className="inline-block rounded-none bg-surface-2/80 px-2 py-0.5 text-[11px] text-fg hover:bg-brand-hover/40 hover:text-brand-light">
      {label}
    </span>
  )
  return m?.num ? (
    <Link href={`/episodes/${m.num}`}>{inner}</Link>
  ) : (
    <span title="番外">{inner}</span>
  )
}

const TABS = [
  { id: "subject", label: "📚 学科分类" },
  { id: "pits", label: "🕳️ 挖坑填坑链" },
  { id: "era", label: "⏳ 年代长廊" },
  { id: "guest", label: "🎤 嘉宾图谱" },
] as const

export default async function BrowsePage({
  searchParams,
}: {
  searchParams: Promise<{ tab?: string }>
}) {
  const params = await searchParams
  const tab = (params.tab ?? "subject") as (typeof TABS)[number]["id"]

  return (
    <main className="min-h-screen bg-surface text-fg">
      <div className="mx-auto max-w-5xl px-6 py-8">
        <nav className="mb-6 text-xs text-fg-secondary">
          <Link href="/" className="hover:text-brand">← 主页</Link>
          <span className="mx-2">·</span>
          <Link href="/map" className="hover:text-brand">星图</Link>
          <span className="mx-2">·</span>
          <Link href="/pits" className="hover:text-brand">坑</Link>
        </nav>

        <header className="mb-6">
          <h1 className="text-2xl font-bold">🔍 细化分类</h1>
          <p className="mt-1 text-xs text-fg-secondary">
            基于 673 期全量打标（词表 {6958} 标签跨期对齐）· 静态数据快照
          </p>
        </header>

        <div className="mb-6 flex flex-wrap gap-2">
          {TABS.map((t) => (
            <Link
              key={t.id}
              href={`/browse?tab=${t.id}`}
              className={`rounded-none px-4 py-1.5 text-sm ${
                tab === t.id
                  ? "bg-brand text-fg font-semibold"
                  : "bg-surface-2 text-fg hover:bg-surface-2"
              }`}
            >
              {t.label}
            </Link>
          ))}
        </div>

        {tab === "subject" && (
          <div className="space-y-3">
            {Object.entries(tree).map(([major, minors]) => {
              const total = Object.values(minors).reduce((s, v) => s + v.length, 0)
              return (
                <details key={major} className="rounded-none bg-surface-2/70 p-4">
                  <summary className="cursor-pointer text-sm font-semibold text-fg">
                    {major} <span className="ml-1 text-xs text-fg-secondary">{total} 期 · {Object.keys(minors).length} 子类</span>
                  </summary>
                  <div className="mt-3 space-y-3">
                    {Object.entries(minors).slice(0, 40).map(([minor, eps]) => (
                      <div key={minor}>
                        <div className="mb-1 text-xs text-brand">{minor} <span className="text-fg-secondary">({eps.length})</span></div>
                        <div className="flex flex-wrap gap-1">
                          {eps.slice(0, 24).map((ep) => <EpChip key={ep} ep={ep} />)}
                          {eps.length > 24 && <span className="text-[11px] text-fg-secondary">+{eps.length - 24}</span>}
                        </div>
                      </div>
                    ))}
                    {Object.keys(minors).length > 40 && (
                      <div className="text-[11px] text-fg-secondary">…另有 {Object.keys(minors).length - 40} 个子类</div>
                    )}
                  </div>
                </details>
              )
            })}
          </div>
        )}

        {tab === "pits" && (
          <div className="space-y-3">
            {pits.map((p, i) => (
              <div key={i} className="rounded-none bg-surface-2/70 p-4">
                <div className="mb-2 inline-block rounded-none bg-brand/15 px-2 py-0.5 text-xs text-brand-light">
                  🕳️ {p.phrase}
                </div>
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="text-fg-secondary">第 {p.dig_num ?? "番外"} 期挖</span>
                  <span className="text-fg-secondary">→</span>
                  <span className="text-emerald-400">第 {p.fill_num ?? "番外"} 期填 ✅</span>
                  {p.gap !== null && p.gap > 0 && (
                    <span className="text-xs text-fg-secondary">（间隔 {p.gap} 期）</span>
                  )}
                </div>
                <div className="mt-2 flex flex-wrap gap-1">
                  <EpChip ep={p.dig_ep} />
                  <span className="text-fg-secondary">→</span>
                  <EpChip ep={p.fill_ep} />
                </div>
              </div>
            ))}
          </div>
        )}

        {tab === "era" && (
          <div className="grid gap-3 sm:grid-cols-2">
            {Object.entries(eras).map(([era, eps]) => (
              <details key={era} className="rounded-none bg-surface-2/70 p-4">
                <summary className="cursor-pointer text-sm font-semibold text-fg">
                  {era} <span className="ml-1 text-xs text-fg-secondary">{eps.length} 期</span>
                </summary>
                <div className="mt-2 flex flex-wrap gap-1">
                  {eps.slice(0, 30).map((ep) => <EpChip key={ep} ep={ep} />)}
                </div>
              </details>
            ))}
          </div>
        )}

        {tab === "guest" && (
          <div className="grid gap-3 sm:grid-cols-2">
            {Object.entries(guests).map(([g, eps]) => (
              <div key={g} className="rounded-none bg-surface-2/70 p-4">
                <div className="mb-2 text-sm font-semibold text-fg">
                  🎤 {g} <span className="ml-1 text-xs text-fg-secondary">{eps.length} 期</span>
                </div>
                <div className="flex flex-wrap gap-1">
                  {eps.map((ep) => <EpChip key={ep} ep={ep} />)}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </main>
  )
}
