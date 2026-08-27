"use client"

import { useEffect, useRef } from "react"
import { Network } from "@vis-network/standalone"
import type { Graph } from "@/lib/types"

const EDGE_COLORS: Record<string, string> = {
  series: "#e15759",
  ref: "#edc948",
  tag: "#59a14f",
  semantic: "#4e79a7",
  concept: "#b07aa1",
}
const EDGE_CN: Record<string, string> = {
  series: "同系列",
  ref: "互相引用",
  tag: "共享标签",
  semantic: "语义相似",
  concept: "共享概念",
}

export default function StarMap({ graph }: { graph: Graph }) {
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const nodes = graph.nodes.map((n) => ({
      id: n.id,
      label: `${n.num ?? "?"} ${n.title.slice(0, 12)}`,
      value: n.size,
      size: n.size,
      title:
        `<b>${n.num ?? "?"} ${n.title}</b><br>` +
        (n.duration_sec ? `${(n.duration_sec / 60).toFixed(0)} 分钟<br>` : "") +
        (n.tags?.length ? `标签: ${n.tags.slice(0, 4).join("、")}<br>` : "") +
        (n.summary ? `<i>${n.summary.slice(0, 150)}</i>` : ""),
    }))
    const edges = graph.edges.map((e) => ({
      from: e.from,
      to: e.to,
      color: EDGE_COLORS[e.kind] ?? "#888",
      width: 1 + (e.weight ?? 0.5) * 4,
      label: EDGE_CN[e.kind] ?? e.kind,
      title: `${EDGE_CN[e.kind] ?? e.kind}${e.evidence ? `: ${e.evidence}` : ""}${
        e.weight ? ` (${e.weight.toFixed(2)})` : ""
      }`,
    }))

    const network = new Network(
      container,
      { nodes, edges },
      {
        physics: {
          barnesHut: { gravitationalConstant: -28000, centralGravity: 0.25 },
          minVelocity: 0.7,
        },
        interaction: { hover: true, tooltipDelay: 120, navigationButtons: true },
        nodes: { font: { size: 13, face: "Microsoft YaHei" }, borderWidth: 1, shadow: true },
        edges: {
          font: { size: 9, face: "Microsoft YaHei", align: "middle" },
          smooth: { type: "continuous" },
        },
      }
    )

    network.on("click", (params) => {
      if (params.nodes.length) {
        const id = params.nodes[0]
        const node = graph.nodes.find((n) => n.id === id)
        if (node?.num) window.location.href = `/episodes/${node.num}`
      }
    })

    return () => network.destroy()
  }, [graph])

  return (
    <div className="flex h-[calc(100vh-100px)] flex-col">
      <div className="flex items-center justify-between px-6 py-3">
        <h1 className="text-lg font-semibold">节目星图</h1>
        <div className="flex gap-4 text-xs text-slate-400">
          {Object.entries(EDGE_CN).map(([k, cn]) => (
            <span key={k} className="flex items-center gap-1">
              <span
                className="inline-block h-1 w-4 rounded"
                style={{ background: EDGE_COLORS[k] }}
              />
              {cn}
            </span>
          ))}
        </div>
      </div>
      <div ref={containerRef} className="flex-1 rounded-xl bg-white/5" />
    </div>
  )
}
