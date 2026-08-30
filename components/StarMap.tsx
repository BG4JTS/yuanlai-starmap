"use client"

import { useEffect, useRef, useState } from "react"
import type { Graph } from "@/lib/types"

const EDGE_COLORS: Record<string, string> = {
  series: "#e15759",
  pit: "#ff7f0e",
  ref: "#edc948",
  tag: "#59a14f",
  semantic: "#4e79a7",
  concept: "#b07aa1",
  guest: "#17becf",
  era: "#8c564b",
}
const EDGE_CN: Record<string, string> = {
  series: "同系列",
  pit: "挖坑-填坑",
  ref: "互相引用",
  tag: "共享标签",
  semantic: "语义相似",
  concept: "共享概念",
  guest: "同嘉宾",
  era: "同年代",
}
/** lite 档只渲染高价值边 */
const LITE_KINDS = new Set(["series", "pit", "ref", "guest"])

export type Quality = "high" | "medium" | "lite"
const QUALITY_KEY = "starmap_quality"

function loadQuality(): Quality {
  if (typeof window === "undefined") return "medium"
  const v = window.localStorage.getItem(QUALITY_KEY)
  return v === "high" || v === "medium" || v === "lite" ? v : "medium"
}

export default function StarMap({ graph }: { graph: Graph }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [quality, setQuality] = useState<Quality>("medium")
  const [ready, setReady] = useState(false)

  useEffect(() => setQuality(loadQuality()), [])

  useEffect(() => {
    const container = containerRef.current
    if (!container || !graph.nodes.length) return
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let network: any = null
    let cancelled = false

    import("vis-network/standalone")
      .then(({ Network, DataSet }) => {
        if (cancelled) return

        const lite = quality === "lite"
        const edgesFiltered = lite
          ? graph.edges.filter((e) => LITE_KINDS.has(e.kind))
          : graph.edges

        const nodes = new DataSet(
          graph.nodes.map((n) => ({
            id: n.id,
            label: `${n.num ?? ""} ${n.title.slice(0, 10)}`,
            value: n.size,
            size: Math.max(4, Math.min(18, n.size)),
            shape: "dot" as const, // 恒为正圆，不随 label 变形
            title:
              `<b>${n.num ?? "番外"} ${n.title}</b><br>` +
              (n.duration_sec ? `${(n.duration_sec / 60).toFixed(0)} 分钟<br>` : "") +
              (n.tags?.length ? `标签: ${n.tags.slice(0, 4).join("、")}<br>` : "") +
              (n.summary ? `<i>${n.summary.slice(0, 120)}</i>` : ""),
            font: { size: quality === "high" ? 12 : 10, face: "Microsoft YaHei", color: "#cbd5e1" },
          }))
        ) as any

        const edges = new (DataSet as any)(
          edgesFiltered.map((e: any) => ({
            from: e.from,
            to: e.to,
            color: { color: EDGE_COLORS[e.kind] ?? "#888", opacity: quality === "high" ? 0.85 : 0.5 },
            width: Math.max(0.5, (e.weight ?? 0.5) * (quality === "high" ? 4 : 2)),
            label: quality === "high" ? (EDGE_CN[e.kind] ?? e.kind) : undefined,
            title: `${EDGE_CN[e.kind] ?? e.kind}${e.evidence ? `: ${e.evidence}` : ""}${
              e.weight ? ` (${Number(e.weight).toFixed(2)})` : ""
            }`,
            physics: false, // 边不参与物理计算
          }))
        ) as any

        network = new Network(
          container,
          { nodes, edges },
          {
            autoResize: true,
            physics: {
              enabled: true,
              solver: "barnesHut",
              barnesHut: {
                gravitationalConstant: -32000,
                centralGravity: 0.3,
                springLength: 90,
                springConstant: 0.02,
                damping: 0.4,
                avoidOverlap: 0.4,
              },
              stabilization: {
                enabled: true,
                iterations: quality === "lite" ? 150 : 300,
                fit: true,
              },
              minVelocity: 1,
            },
            interaction: {
              hover: true,
              tooltipDelay: 140,
              navigationButtons: true,
              keyboard: false,
              hideEdgesOnDrag: true, // 拖拽时隐藏边（核心性能项）
              hideEdgesOnZoom: quality !== "high",
              hideNodesOnDrag: false,
            },
            nodes: {
              borderWidth: quality === "high" ? 1 : 0,
              shadow: quality === "high",
              scaling: { min: 4, max: 18 },
            },
            edges: {
              smooth: quality === "high" ? { enabled: true, type: "continuous", roundness: 0.4 } : false,
              selectionWidth: 1,
            },
          }
        )

        network.once("stabilizationIterationsDone", () => setReady(true))
        network.on("click", (params: { nodes: string[] }) => {
          if (params.nodes.length) {
            const id = params.nodes[0]
            const node = graph.nodes.find((n) => n.id === id)
            if (node?.num) window.location.href = `/episodes/${node.num}`
          }
        })
      })
      .catch((err) => console.error("vis-network 加载失败:", err))

    return () => {
      cancelled = true
      try {
        network?.destroy()
      } catch {
        // noop
      }
    }
  }, [graph, quality])

  function setQ(q: Quality) {
    window.localStorage.setItem(QUALITY_KEY, q)
    setQuality(q)
  }

  const BTN = (q: Quality, label: string, hint: string) => (
    <button
      key={q}
      onClick={() => setQ(q)}
      title={hint}
      className={`rounded px-2.5 py-1 text-xs transition ${
        quality === q ? "bg-sky-500 text-slate-950 font-semibold" : "bg-slate-800 text-slate-300 hover:bg-slate-700"
      }`}
    >
      {label}
    </button>
  )

  return (
    <div className="flex h-[calc(100vh-100px)] flex-col">
      <div className="flex flex-wrap items-center justify-between gap-3 px-6 py-3">
        <h1 className="text-lg font-semibold">原样星图</h1>
        <div className="flex flex-wrap items-center gap-4 text-xs text-slate-400">
          <span className="text-slate-500">
            {graph.nodes.length} 节点 ·{" "}
            {quality === "lite" ? graph.edges.filter((e) => LITE_KINDS.has(e.kind)).length : graph.edges.length} 边
            {!ready && <span className="ml-2 text-sky-400">布局计算中…</span>}
          </span>
          <div className="flex items-center gap-1">
            <span className="text-slate-500">渲染：</span>
            {BTN("lite", "流畅", "只显示系列/挖坑/引用/嘉宾边，无阴影平滑")}
            {BTN("medium", "均衡", "全部边但隐藏边标签，关平滑与阴影")}
            {BTN("high", "精细", "全部边 + 边标签 + 平滑 + 阴影")}
          </div>
        </div>
      </div>
      <div className="flex flex-wrap gap-3 px-6 pb-2 text-[11px] text-slate-400">
        {Object.entries(EDGE_CN).map(([k, cn]) => (
          <span
            key={k}
            className={`flex items-center gap-1 ${quality === "lite" && !LITE_KINDS.has(k) ? "opacity-30" : ""}`}
          >
            <span className="inline-block h-1 w-4 rounded" style={{ background: EDGE_COLORS[k] }} />
            {cn}
          </span>
        ))}
      </div>
      <div ref={containerRef} className="flex-1 rounded-xl bg-white/5" />
    </div>
  )
}
