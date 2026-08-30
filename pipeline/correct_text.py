# -*- coding: utf-8 -*-
"""
文稿 LLM 纠错：用 DeepSeek 修正每期转写稿的错别字/同音字/识别错误，
保持口语风格与原意，保留时间戳与说话人标签。

用法:
    python correct_text.py --ep 541[,545,...]   # 指定期号
    python correct_text.py --all                 # 全部期
输出: outputs/<ep>/<ep>_corrected.txt （同时更新 *_final.txt 或生成副本）
"""
import argparse
import json
import re
import time
from pathlib import Path

import config


# ---------- 解析/写出文稿 ----------
LINE_PAT = re.compile(r"^\[(\d+\.\d+)s\s*->\s*(\d+\.\d+)s\]\s*([^:]+):\s*(.*)$")


def load_lines(txt_path):
    """返回 [{idx, start, end, speaker, text}]"""
    out = []
    for line in txt_path.read_text(encoding="utf-8").splitlines():
        m = LINE_PAT.match(line.strip())
        if m:
            out.append({"start": float(m.group(1)), "end": float(m.group(2)),
                        "speaker": m.group(3).strip(), "text": m.group(4)})
    return out


def pick_txt(ep_dir):
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
    return min(cands, key=score)


# ---------- DeepSeek ----------
def call_deepseek(prompt, temperature=0.1):
    from llm_client import call_llm
    return call_llm([{"role": "user", "content": prompt}],
                    temperature=temperature, max_tokens=20000,
                    json_mode=True, tag="correct", timeout=900)


def parse_json(output):
    if "```json" in output:
        output = output.split("```json")[1].split("```")[0]
    elif "```" in output:
        output = output.split("```")[1].split("```")[0]
    return json.loads(output.strip())


PROMPT = """你是中文播客文稿校对专家。下面是《原来是这样》节目（主持人旭岽、子零）的语音识别转写，含错别字/同音字/识别错误。

修正规则：
1. 修正错别字与同音字（例：车离子→车厘子、徐东→旭岽、子琳→子零、沟→J/钩、Gingyo→银杏/Ginkgo、里子→李子、打道→大道）。
2. 保持口语风格与原文意思，不增删内容、不重写句子、不润色文采。
3. 说话人姓名一律规范为 旭岽 / 子零。
4. 无法判断的保持原样。

输出 JSON 数组，每元素 {{"index": 行号, "corrected": "修正后文本", "changes": ["原词→新词", ...]}}（changes 可为空数组）。只输出 JSON。

转写文本：
{numbered}
"""


def correct_batch(items, start_idx):
    numbered = "\n".join(f"[{start_idx + i}] {it['text']}" for i, it in enumerate(items))
    out = call_deepseek(PROMPT.format(numbered=numbered))
    data = parse_json(out)
    if isinstance(data, dict):
        for key in ("data", "result", "segments"):
            if key in data and isinstance(data[key], list):
                data = data[key]
                break
    mapping = {}
    for item in (data or []):
        idx = item.get("index", item.get("id"))
        if isinstance(idx, int):
            mapping[idx] = (item.get("corrected", ""), item.get("changes", []))
    return mapping


def correct_episode(ep, batch_size=200):
    ep_dir = config.OUTPUT_DIR / ep
    txt = pick_txt(ep_dir)
    if not txt:
        print(f"  ✗ {ep}: 无文稿")
        return
    items = load_lines(txt)
    print(f"  {ep}: {len(items)} 行, 源 {txt.name}")

    total_changes = 0
    for start in range(0, len(items), batch_size):
        batch = items[start:start + batch_size]
        try:
            mapping = correct_batch(batch, start)
            for i, it in enumerate(batch):
                idx = start + i
                if idx in mapping:
                    new_text, changes = mapping[idx]
                    if new_text and new_text != it["text"]:
                        it["text"] = new_text
                        total_changes += len(changes or [])
            print(f"    批 {start//batch_size+1}: 修正 {len(mapping)} 行")
        except Exception as e:
            print(f"    批 {start//batch_size+1} 失败: {str(e)[:100]}")
        time.sleep(0.2)

    out = ep_dir / f"{ep}_corrected.txt"
    with open(out, "w", encoding="utf-8") as f:
        for it in items:
            f.write(f"[{it['start']:.2f}s -> {it['end']:.2f}s] {it['speaker']}: {it['text']}\n")
    print(f"  ✓ {ep}: 共修正 {total_changes} 处 → {out.name}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ep", default=None, help="逗号分隔期号")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    eps = []
    if args.all:
        eps = sorted(d.name for d in config.OUTPUT_DIR.iterdir() if d.is_dir())
    elif args.ep:
        eps = [e.strip() for e in args.ep.split(",") if e.strip()]
    if not eps:
        ap.error("需 --ep 或 --all")
    for ep in eps:
        correct_episode(ep)


if __name__ == "__main__":
    main()
