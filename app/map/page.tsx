import StarMap from "@/components/StarMap"
import { getGraph } from "@/lib/api"
import type { Graph } from "@/lib/types"

export const dynamic = "force-dynamic"

export default async function MapPage({
  searchParams,
}: {
  searchParams: Promise<{ focus?: string }>
}) {
  const params = await searchParams
  const focusNum = params.focus ? Number(params.focus) : undefined

  let graph: Graph = { nodes: [], edges: [] }
  let err: string | null = null
  try {
    graph = await getGraph(focusNum)
  } catch (e) {
    err = e instanceof Error ? e.message : String(e)
  }

  return (
    <main className="min-h-screen bg-surface text-fg">
      <div className="mx-auto max-w-7xl px-4 py-6">
        {err ? (
          <div className="rounded-none border border-amber-500/40 bg-brand/10 p-6 text-sm text-brand-light">
            星图数据未就绪（{err}）。请先执行 <code>supabase/schema.sql</code> 并导入数据。
          </div>
        ) : graph.nodes.length === 0 ? (
          <div className="rounded-none p-6 text-sm text-fg-secondary">
            暂无节目数据。
          </div>
        ) : (
          <StarMap graph={graph} />
        )}
      </div>
    </main>
  )
}
