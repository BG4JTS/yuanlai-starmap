"use client"

import { useState } from "react"

export default function PitForm({ episodeId }: { episodeId: number }) {
  const [content, setContent] = useState("")
  const [ts, setTs] = useState("")
  const [status, setStatus] = useState<"idle" | "submitting" | "ok" | "err">("idle")
  const [msg, setMsg] = useState("")

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!content.trim()) return
    setStatus("submitting")
    try {
      const body: Record<string, unknown> = { episode_id: episodeId, content: content.trim() }
      if (ts) {
        const sec = Number(ts)
        if (!Number.isNaN(sec)) body.ts_sec = sec
      }
      const r = await fetch("/api/pits", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
      if (!r.ok) throw new Error((await r.text()) || "提交失败")
      setStatus("ok")
      setMsg("已挖坑 ✅ 等 3 个「我也想知道」后上公开看板")
      setContent("")
      setTs("")
    } catch (e2) {
      setStatus("err")
      setMsg(e2 instanceof Error ? e2.message : "提交失败")
    }
  }

  return (
    <form onSubmit={submit} className="space-y-2">
      <div>
        <label className="text-xs text-slate-400">挖一个坑（这期提到但没展开的话题）</label>
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          rows={2}
          placeholder="例如：12:30 提到反物质但没解释，这是个坑"
          className="mt-1 w-full rounded-lg bg-slate-900 p-2 text-sm outline-none focus:ring-2 focus:ring-sky-500"
        />
      </div>
      <div className="flex items-center gap-2">
        <input
          value={ts}
          onChange={(e) => setTs(e.target.value)}
          placeholder="时间戳(秒，可选)"
          className="w-36 rounded-lg bg-slate-900 p-2 text-xs outline-none focus:ring-2 focus:ring-sky-500"
        />
        <button
          type="submit"
          disabled={status === "submitting"}
          className="rounded-lg bg-sky-500 px-4 py-2 text-xs font-medium hover:bg-sky-400 disabled:opacity-50"
        >
          {status === "submitting" ? "提交中…" : "挖坑"}
        </button>
      </div>
      {status === "ok" && <p className="text-xs text-emerald-400">{msg}</p>}
      {status === "err" && <p className="text-xs text-rose-400">{msg}</p>}
    </form>
  )
}
