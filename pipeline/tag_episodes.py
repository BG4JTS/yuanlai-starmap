# -*- coding: utf-8 -*-
"""
节目打标 + 元数据：用 DeepSeek 为每期生成
    - summary   2-3 句摘要
    - tags      5-10 个分层主题标签（如 植物/银杏、语言学/演化）
    - concepts  5-10 个核心概念/实体
    - referenced 文中明确提到的往期话题（跨期关联线索）

输出: analysis/tags.json （供 build_starmap.py 使用）

用法:
    python tag_episodes.py --ep 541,545,...     # 指定
    python tag_episodes.py --all                # 全部
"""
import argparse
import json
import time
from pathlib import Path

import config


_CLEAN = None


def _clean(text):
    """去掉 FunASR 富标签残留（🎼😊 等事件/情感 emoji 与 <|zh|> 类标记）"""
    global _CLEAN
    if _CLEAN is None:
        import re
        _CLEAN = re.compile(r'<\|[^|]*\|>|[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]')
    return _CLEAN.sub('', text or '').strip()


def load_episode_text(ep):
    ep_dir = config.OUTPUT_DIR / ep
    # 新流水线: FunASR raw.json（含 spk 说话人编号 + 时间戳）
    raw = ep_dir / f"{ep}_raw.json"
    if raw.exists():
        try:
            d = json.loads(raw.read_text(encoding="utf-8"))
            lines = []
            for s in d.get("segments", []):
                txt = _clean(s.get("text", ""))
                if not txt:
                    continue
                mm, sec = int(s["start"] // 60), s["start"] % 60
                spk = s.get("spk", -1)
                prefix = f"SPK{spk}: " if spk >= 0 else ""
                lines.append(f"[{mm:02d}:{sec:04.1f}] {prefix}{txt}")
            if lines:
                return raw.name, "\n".join(lines)
        except Exception:
            pass
    # 旧流水线: *_final.txt
    cands = sorted(ep_dir.glob("*.txt"))
    if not cands:
        return None
    def score(c):
        n = c.name
        if n.endswith("_final.txt") and "_split" not in n and "_refined" not in n:
            return 0
        if "_final" in n and "_split" not in n:
            return 1
        return 2
    txt = min(cands, key=score)
    import re
    body = []
    for line in txt.read_text(encoding="utf-8").splitlines():
        body.append(re.sub(r"^\[\d+\.\d+s\s*->\s*\d+\.\d+s\]\s*[^:]*:\s*", "", line))
    return txt.name, "\n".join(body)


LLAMA_URL = "http://localhost:8081/v1/chat/completions"
LLAMA_MODEL = "qwen3"


def call_deepseek(prompt, max_tokens=8000):
    """LLM 打标调用：自编译 llama-server（GPU, CUDA 11.8 kernel）+ qwen3:8b"""
    import requests
    r = requests.post(LLAMA_URL, timeout=600, json={
        "model": LLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 2000,
        "temperature": 0.2,
        "chat_template_kwargs": {"enable_thinking": False},  # 关闭 Qwen3 思考
    })
    r.raise_for_status()
    d = r.json()
    return d["choices"][0]["message"]["content"]


PROMPT = """你是科普播客《原来是这样》的编目专家。下面是一期节目的转写稿，格式为 [分钟:秒] SPK编号: 文本。
说话人说明：SPK0 通常为主讲人旭岽，SPK1 通常为搭档子凌（子零），偶尔有嘉宾。转写稿可能存在少量语音识别错别字，理解时请结合上下文自动纠正，忽略明显的识别噪音。

请为这期节目生成结构化元数据：
1. "summary": 2-3 句内容摘要（概括主题与亮点）。
2. "tags": 15-20 个主题标签，用"大类/小类"分层（例：植物/银杏、语言学/语言演化、历史/饮食、经济学/市场）。要求：
   - 下方"已有标签词表"是往期积累的标签库：**优先从词表中选取**适合本期的标签（保持跨期一致，这对星图关联至关重要）
   - 词表中确实没有合适项时才创造新标签（同样用"大类/小类"格式）
   - 覆盖本期全部主要话题维度：主题学科、延伸知识、历史背景、生活应用等
3. "concepts": 8-12 个核心概念/实体（人名、物种、学科术语、事件等）。
4. "referenced": 若文中明确提到往期内容（如"上期我们聊过…""之前讲过…"），列出提到的话题；没有则为 []。
5. "guests": 本期出现的嘉宾/科学顾问姓名列表（如 ["水兄","何鑫"]）；没有则为 []。注意从"文案/主播/嘉宾"署名和对话中识别，旭岽和子凌是固定主持不算嘉宾。
6. "era": 本期内容涉及的主要历史时期/地质年代（如 ["白垩纪","二战","唐朝","文艺复兴"]）；没有则为 []。
7. "promised": 本期主持人明确"挖坑"的话题——即说到"这个我们以后细说/改天再讲/下期聊"之类的话所指向的话题，提炼为短语列表（如 ["恐龙灭绝细节"]）；没有则为 []。

只输出 JSON 对象（keys: summary, tags, concepts, referenced, guests, era, promised）。不要其他内容。

已有标签词表（优先从中选取）：
{vocab}

节目转写：
{text}
"""


def tag_episode(ep, vocab=""):
    res = load_episode_text(ep)
    if not res:
        print(f"  ✗ {ep}: 无文稿")
        return None
    fname, text = res
    # CPU 推理 prompt 处理是瓶颈: 头 2500 字(开场+主题) + 尾 1500 字(结尾挖坑/预告), 合计 ~6K token
    if len(text) > 4000:
        text = text[:2500] + "\n……（中段略）……\n" + text[-1500:]
    else:
        text = text[:4000]
    out = call_deepseek(PROMPT.format(text=text, vocab=vocab or "（暂无，自由创造）"))
    if "```json" in out:
        out = out.split("```json")[1].split("```")[0]
    elif "```" in out:
        out = out.split("```")[1].split("```")[0]
    d = json.loads(out.strip())
    d["ep"] = ep
    d["source"] = fname
    print(f"  ✓ {ep}: tags={d.get('tags')}")
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ep", default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--workers", type=int, default=1, help="并发线程数（LLM API 并发）")
    ap.add_argument("--shard", default=None, help="分片 i/N（例 0/2）, 配合多 Ollama 实例")
    ap.add_argument("--port", type=int, default=11434, help="Ollama 端口")
    ap.add_argument("--out", default=None, help="输出文件（默认 analysis/tags.json；并发时传独立文件）")
    args = ap.parse_args()
    global OLLAMA_URL
    OLLAMA_URL = f"http://localhost:{args.port}/api/chat"

    if args.all:
        eps = sorted(d.name for d in config.OUTPUT_DIR.iterdir() if d.is_dir())
    elif args.ep:
        eps = [e.strip() for e in args.ep.split(",") if e.strip()]
    else:
        ap.error("需 --ep 或 --all")

    if args.shard:
        i, n = map(int, args.shard.split("/"))
        eps = sorted(eps)
        eps = [e for idx, e in enumerate(eps) if idx % n == i]
        print(f"[shard] {i}/{n}: {len(eps)} 期")

    config.ensure_dirs()
    # 跳过逻辑：已完成且 tags>=15 的跳过；不达标（<15）的重打
    out_path = Path(args.out) if args.out else config.ANALYSIS_DIR / "tags.json"
    done_eps = {}  # ep -> tags 数
    vocab_set = set()
    if out_path.exists():
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
            if isinstance(existing, list):
                for d in existing:
                    if isinstance(d, dict) and d.get("ep"):
                        n = len(d.get("tags") or [])
                        done_eps[d["ep"]] = n
                        vocab_set.update(d.get("tags") or [])
        except Exception:
            pass
    MIN_TAGS = 15
    to_redo = [e for e, n in done_eps.items() if n < MIN_TAGS]
    skip = {e for e, n in done_eps.items() if n >= MIN_TAGS}
    if done_eps:
        print(f"[skip] 已达标 {len(skip)} 期跳过 | 不达标重打 {len(to_redo)} 期 | 词表 {len(vocab_set)} 个标签")
    eps = [e for e in eps if e not in skip]
    print(f"[plan] 待打标 {len(eps)} 期, workers={args.workers}, MIN_TAGS={MIN_TAGS}")
    results = []
    lock = __import__("threading").RLock()  # 可重入: run_one 持锁调 _merge_save 内再拿锁
    out = Path(args.out) if args.out else config.ANALYSIS_DIR / "tags.json"

    def current_vocab():
        """当前词表快照（截断 300 个防 prompt 超 ctx; 换行分隔）"""
        with lock:
            if not vocab_set:
                return ""
            items = sorted(vocab_set)[:300]
            return "\n".join(items)

    def _merge_save(d):
        """增量合并写盘（每期完成即保存, 断点安全; 原子替换防写坏）+ 词表更新"""
        existing = []
        if out.exists():
            try:
                existing = json.loads(out.read_text(encoding="utf-8"))
                if not isinstance(existing, list):
                    existing = []
            except Exception:
                existing = []
        merged = {x.get("ep"): x for x in existing if isinstance(x, dict)}
        if isinstance(d, dict) and d.get("ep"):
            merged[d["ep"]] = d
        with lock:
            vocab_set.update(d.get("tags") or [])
        tmp = out.with_suffix(".tmp")
        tmp.write_text(json.dumps(list(merged.values()), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(out)

    def run_one(ep):
        try:
            r = tag_episode(ep, vocab=current_vocab())
            if r:
                with lock:
                    results.append(r)
                    _merge_save(r)
        except Exception as e:
            print(f"  ✗ {ep} 失败: {str(e)[:120]}")

    if args.workers > 1:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            list(as_completed([pool.submit(run_one, ep) for ep in eps]))
    else:
        for ep in eps:
            run_one(ep)
            time.sleep(0.3)
        eps_done = True

    out = Path(args.out) if args.out else config.ANALYSIS_DIR / "tags.json"
    # 追加合并：读取已有 tags.json，按 ep 去重后合并（batch_llm 逐期调用时累积）
    existing = []
    if out.exists():
        try:
            existing = json.loads(out.read_text(encoding="utf-8"))
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []
    merged = {d.get("ep"): d for d in existing if isinstance(d, dict)}
    for d in results:
        if isinstance(d, dict) and d.get("ep"):
            merged[d["ep"]] = d
    final = list(merged.values())
    out.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[tags] 本次 {len(results)} 期，累积 {len(final)} 期 → {out}")


if __name__ == "__main__":
    main()
