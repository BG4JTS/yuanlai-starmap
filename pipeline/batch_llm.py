# -*- coding: utf-8 -*-
"""
批量 LLM 增强：为已转写的文稿生成"终版"（支持多线程并发调用 LLM）。

每期流程：
    1. semantic_split  : raw.json → final.json / final.txt （LLM 分配说话人 + 拆分）
    2. correct_text    : 对 final.txt 做 LLM 错别字纠错，纠错稿覆盖为终版
    3. tag_episodes    : 打标/摘要/概念/引用 → analysis/tags_<ep>.json（最终合并为 tags.json）

用法:
    python batch_llm.py --all --workers 4          # 并发处理全部
    python batch_llm.py --range 540,569 --workers 3
    python batch_llm.py --ep 568
    python batch_llm.py --all --force              # 强制重跑语义
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import config


def run(cmd, timeout=900):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        print(f"    ⚠ 子命令失败: {r.stderr[-200:]}")
        return False
    return True


PY = sys.executable
BASE = config.BASE_DIR


def process_ep(ep, force):
    ep_dir = config.OUTPUT_DIR / ep
    if not ep_dir.is_dir():
        print(f"  ✗ {ep}: 目录不存在")
        return False
    raw = ep_dir / f"{ep}_raw.json"
    final = ep_dir / f"{ep}_final.json"
    final_txt = ep_dir / f"{ep}_final.txt"
    if not raw.exists() and not final.exists():
        print(f"  ✗ {ep}: 无 raw/final 文稿")
        return False

    # 1) 说话人分配 + 终版
    if not final.exists() or force:
        print(f"  → {ep}: 说话人分配 + 生成终版 ...")
        inp = raw if raw.exists() else final
        if not run([PY, str(BASE / "semantic_split.py"), "--input", str(inp),
                    "--output_json", str(final), "--output_txt", str(final_txt)]):
            return False
    else:
        print(f"  · {ep}: 已有终版，跳过语义（--force 可重跑）")

    # 2) LLM 纠错（纠错稿覆盖终版）
    print(f"  → {ep}: LLM 纠错 ...")
    run([PY, str(BASE / "correct_text.py"), "--ep", ep])
    corr = ep_dir / f"{ep}_corrected.txt"
    if corr.exists():
        corr.replace(final_txt)
        print(f"  ✓ {ep}: 纠错稿已覆盖终版 {final_txt.name}")

    # 3) 打标（写独立文件，避免并发冲突；主进程最后合并）
    print(f"  → {ep}: 打标 ...")
    run([PY, str(BASE / "tag_episodes.py"), "--ep", ep,
         "--out", str(BASE / "analysis" / f"tags_{ep}.json")])
    return True


def collect_eps(args):
    if args.ep:
        return [e.strip() for e in args.ep.split(",") if e.strip()]
    if args.range:
        a, b = [int(x) for x in args.range.split(",")]
        return [str(i) for i in range(a, b + 1)]
    if args.all:
        return sorted(d.name for d in config.OUTPUT_DIR.iterdir() if d.is_dir())
    return []


def merge_tags():
    """合并所有 tags_*.json 到 analysis/tags.json。"""
    merged = {}
    for f in glob.glob(str(BASE / "analysis" / "tags_*.json")):
        try:
            data = json.load(open(f, encoding="utf-8"))
            if isinstance(data, list):
                for d in data:
                    if isinstance(d, dict) and d.get("ep"):
                        merged[d["ep"]] = d
        except Exception:
            pass
        try:
            os.remove(f)
        except Exception:
            pass
    if merged:
        out = BASE / "analysis" / "tags.json"
        out.write_text(json.dumps(list(merged.values()), ensure_ascii=False, indent=2),
                       encoding="utf-8")
        print(f"[batch_llm] 已合并 {len(merged)} 期打标 → {out}")
    return len(merged)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--range", default=None, help="如 540,569")
    ap.add_argument("--ep", default=None, help="逗号分隔期号")
    ap.add_argument("--force", action="store_true", help="强制重跑语义步骤")
    ap.add_argument("--workers", type=int, default=8,
                    help="并发调 LLM 的期数（默认 8；智谱并发按 key 限制调整）")
    args = ap.parse_args()

    if not config.DEEPSEEK_API_KEY:
        raise SystemExit("缺少 DEEPSEEK_API_KEY（batch_llm 需要 LLM 完成语义/纠错/打标）")

    eps = collect_eps(args)
    if not eps:
        raise SystemExit("未指定范围：--all / --range a,b / --ep a,b,c")

    # ---- 调度优化 ----
    # 1) 正片（有期号）优先于番外 —— 核心内容先完成
    # 2) 正片中已有 final 的期（跳过慢的语义步骤）优先 —— 快速累积进度
    # 3) 同组内按文稿字数升序 —— 短期先完成，尽早产出打标结果
    def size_key(ep):
        is_main = ep.isdigit()
        p = config.OUTPUT_DIR / ep / f"{ep}_final.txt"
        if p.exists():
            return (0 if is_main else 1, 0, os.path.getsize(p))
        p2 = config.OUTPUT_DIR / ep / f"{ep}_raw.json"
        return (0 if is_main else 1, 1, os.path.getsize(p2) if p2.exists() else 0)

    eps.sort(key=size_key)

    config.ensure_dirs()
    (BASE / "analysis").mkdir(parents=True, exist_ok=True)
    print(f"[batch_llm] 处理 {len(eps)} 期（并发 {args.workers}）...")
    ok = fail = 0
    t0 = time.time()
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(process_ep, ep, args.force): ep for ep in eps}
        for fut in as_completed(futures):
            ep = futures[fut]
            try:
                if fut.result():
                    ok += 1
                else:
                    fail += 1
            except Exception as e:
                print(f"  ✗ {ep} 异常: {str(e)[:120]}")
                fail += 1
            done += 1
            if done % 10 == 0:
                print(f"  ... 进度 {done}/{len(eps)}，已用 {time.time()-t0:.0f}s")
            # 每完成 20 期合并一次（监控台能看到累积）
            if done % 20 == 0:
                merge_tags()
    n_tags = merge_tags()
    print(f"\n[batch_llm] 完成: 成功 {ok}, 失败 {fail}, 已打标 {n_tags} 期, "
          f"总耗时 {(time.time()-t0)/60:.1f} 分钟")
    print("提示: 之后运行 build_starmap.py 即可用 tags.json 刷新星图（共享标签/概念边）")


if __name__ == "__main__":
    main()
