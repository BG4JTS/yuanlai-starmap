# -*- coding: utf-8 -*-
"""
语言风格分析：对 outputs/ 下多期 final.json 做定量统计（jieba 词频/句长/语速/互动节奏）
+ 用 DeepSeek 生成综合风格报告。

用法:
    python analyze.py --episodes 554,555,556        # 指定期号
    python analyze.py --all                          # 全部期号
"""
import argparse
import json
import re
import time
from collections import Counter, defaultdict

import jieba

import config


STOPWORDS = set("""的 了 在 是 我 有 和 就 不 人 都 一 一个 上 也 很 到 说 要 去 你 会 着 没有 看 好
自己 这 那 它 他 她 我们 你们 他们 啊 呢 吧 哦 嗯 呃 这个 那个 就是 其实 然后 所以 因为""".split())


def load_episode(ep: str):
    p = config.OUTPUT_DIR / ep / f"{ep}_final.json"
    if not p.exists():
        # 允许 *_final.json 通配
        matches = list(config.OUTPUT_DIR.glob(f"{ep}*_final.json"))
        if not matches:
            return []
        p = matches[0]
    with open(p, encoding="utf-8") as f:
        return json.load(f).get("segments", [])


def speaker_stats(segments, spk):
    texts = [s["text"].strip() for s in segments if s.get("speaker") == spk]
    if not texts:
        return None
    total_chars = sum(len(t) for t in texts)
    total_dur = sum(s["end"] - s["start"] for s in segments if s.get("speaker") == spk)
    sents = [x for t in texts for x in re.split(r"[。？！；]", t) if x.strip()]
    avg_sent = sum(len(x) for x in sents) / len(sents) if sents else 0
    punct = {p: sum(t.count(p) for t in texts) for p in "。？！，、"}
    words = [w for t in texts for w in jieba.cut(t)
             if len(w) >= 2 and w not in STOPWORDS and not w.isdigit()]
    freq = Counter(words).most_common(30)
    return {
        "发言总数": len(texts),
        "总时长(分钟)": round(total_dur / 60, 2),
        "总字数": total_chars,
        "平均句长(字)": round(avg_sent, 1),
        "语速(字/秒)": round(total_chars / total_dur, 1) if total_dur else 0,
        "标点统计": punct,
        "高频词(前30)": [{"词": w, "次数": c} for w, c in freq],
    }


def timing_stats(segments):
    switches = []
    for i in range(1, len(segments)):
        if segments[i].get("speaker") != segments[i - 1].get("speaker"):
            switches.append({
                "from": segments[i - 1].get("speaker"), "to": segments[i].get("speaker"),
                "gap": round(segments[i]["start"] - segments[i - 1]["end"], 2)})
    from_spk, to_spk = defaultdict(int), defaultdict(int)
    for s in switches:
        from_spk[s["from"]] += 1
        to_spk[s["to"]] += 1
    return {
        "切换次数": len(switches),
        "平均回应间隔(秒)": round(sum(s["gap"] for s in switches) / len(switches), 2) if switches else 0,
        "从谁切换": dict(from_spk),
        "切换到谁": dict(to_spk),
    }


def deepseek_report(stats, timing, samples, episodes):
    if not config.DEEPSEEK_API_KEY:
        print("缺少 DEEPSEEK_API_KEY，跳过报告生成")
        return ""
    prompt = f"""你是语言学和传播学专家。以下是对播客《原来是这样》{len(episodes)} 期文稿（主持人旭岽、子零）的汇总统计与样例。
请撰写约 2000 字 Markdown 风格报告，结构：引言 / 语言风格总评 / 句式词汇对比 / 互动模式 / 风格稳定性 / 总结建议。多用数据说话。

### 汇总统计
{json.dumps(stats, ensure_ascii=False, indent=2)}

### 互动时序
{json.dumps(timing, ensure_ascii=False, indent=2)}

### 文稿样例
{samples}
"""
    import requests
    headers = {"Authorization": f"Bearer {config.DEEPSEEK_API_KEY}"}
    payload = {"model": config.DEEPSEEK_MODEL, "messages": [{"role": "user", "content": prompt}],
               "temperature": 0.3, "max_tokens": 4000}
    resp = requests.post(f"{config.DEEPSEEK_BASE_URL}/chat/completions", headers=headers, json=payload, timeout=180)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", help="逗号分隔期号，如 554,555,556")
    ap.add_argument("--all", action="store_true", help="分析全部期号")
    args = ap.parse_args()

    if args.all:
        eps = sorted(d.name for d in config.OUTPUT_DIR.iterdir() if d.is_dir())
    elif args.episodes:
        eps = [e.strip() for e in args.episodes.split(",") if e.strip()]
    else:
        eps = sorted(d.name for d in config.OUTPUT_DIR.iterdir() if d.is_dir())

    all_segments = []
    loaded = []
    for ep in eps:
        segs = load_episode(ep)
        if segs:
            all_segments.extend(segs)
            loaded.append(ep)
            print(f"[analyze] {ep}: {len(segs)} 段")
    if not all_segments:
        print("没有可分析的文稿")
        return

    config.ensure_dirs()
    speakers = {s.get("speaker") for s in all_segments if s.get("speaker") not in (None, "UNKNOWN")}
    stats = {spk: speaker_stats(all_segments, spk) for spk in speakers}
    timing = timing_stats(all_segments)
    overall = {
        "总片段数": len(all_segments),
        "总时长(分钟)": round(sum(s["end"] - s["start"] for s in all_segments) / 60, 2),
        "说话人统计": stats,
    }
    with open(config.ANALYSIS_DIR / "stats.json", "w", encoding="utf-8") as f:
        json.dump({"overall": overall, "timing": timing}, f, ensure_ascii=False, indent=2)

    samples = ""
    for ep in loaded[:3]:
        txt = config.OUTPUT_DIR / ep / f"{ep}_final.txt"
        if txt.exists():
            samples += f"\n--- {ep} ---\n" + txt.read_text(encoding="utf-8")[:1500] + "\n"

    print("[analyze] 生成风格报告 ...")
    report = deepseek_report(overall, timing, samples, loaded)
    if report:
        (config.ANALYSIS_DIR / "style_report.md").write_text(report, encoding="utf-8")
    print(f"[analyze] 完成 → {config.ANALYSIS_DIR}")


if __name__ == "__main__":
    main()
