# -*- coding: utf-8 -*-
"""
全量批量处理管线：从 episodes_list.json（RSS 全量清单）批量
    下载音频 → 16k → 转写 → (说话人分离) → (语义/纠错/打标) → outputs/<期号>/
幂等（已存在产物自动跳过），支持断点续跑与分批。

用法:
    python batch_ingest.py --limit 3              # 只处理前 3 期（测试）
    python batch_ingest.py --range 540,570        # 处理 540-570 期
    python batch_ingest.py --all                  # 全部
    python batch_ingest.py --only-numbered        # 只处理有正式期号的
    python batch_ingest.py --steps 1,2            # 只跑 下载+16k+转写（默认 1,2,3）
    python batch_ingest.py --list                 # 只打印清单统计

说明:
    - 下载音频来自 RSS 提供的音频直链（荔枝 FM CDN）。
    - 步骤1=下载+16k, 步骤2=转写, 步骤3=说话人分离(需 HF token), 步骤4=语义(需 DeepSeek key)
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

import config

DEFAULT_LIST = Path(__file__).parent / "episodes_list.json"


def load_list(path):
    if not Path(path).exists():
        raise FileNotFoundError(f"找不到期数清单 {path}（先运行 fetch_episodes.py 生成）")
    return json.load(open(path, encoding="utf-8"))


def safe_name(s):
    return re.sub(r'[\\/:*?"<>|\r\n]+', "", s).strip()[:40] or "ep"


_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
_HEADERS = {"User-Agent": _UA, "Referer": "https://www.lizhi.fm/", "Accept": "*/*"}


def download_audio(url, dest: Path) -> bool:
    """下载音频。URL 可能不带扩展名，依次尝试：原样 / +.mp3 / +.m4a。"""
    if dest.exists() and dest.stat().st_size > 100_000:
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    candidates = [url, url + ".mp3", url + ".m4a", url + ".aac"]
    for u in candidates:
        try:
            r = requests.get(u, stream=True, timeout=120, headers=_HEADERS, allow_redirects=True)
            if r.status_code != 200:
                print(f"    · {r.status_code} {u[-40:]}")
                continue
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
            if tmp.stat().st_size < 100_000:
                print(f"    · 太小，跳过 {tmp.stat().st_size}B")
                continue
            tmp.rename(dest)
            return True
        except Exception as e:
            print(f"    · 尝试失败 {u[-40:]}: {str(e)[:60]}")
    if tmp.exists():
        tmp.unlink()
    print(f"    ✗ 全部候选下载失败")
    return False


def to_16k(src: Path, dst: Path) -> bool:
    if dst.exists():
        return True
    try:
        subprocess.run(["ffmpeg", "-i", str(src), "-acodec", "pcm_s16le", "-ar", "16000",
                        "-ac", "1", "-y", str(dst)], check=True, capture_output=True)
        return True
    except Exception as e:
        print(f"    ✗ 转 16k 失败: {str(e)[:80]}")
        return False


def process_one(ep, steps, audio_root, out_root, only_transcribe=True):
    num = ep.get("num")
    key = f"{num:03d}" if num else "X" + safe_name(ep["title"])[:10]
    title = ep["title"]
    url = ep.get("audio", "")
    if not url:
        print(f"  ✗ {key}: 无音频URL")
        return None

    ep_dir = out_root / key
    ep_dir.mkdir(parents=True, exist_ok=True)
    raw = ep_dir / f"{key}_raw.json"
    if 1 in steps and raw.exists():
        print(f"  · {key}: 已转写，跳过 ({title[:24]})")
        return key

    # 下载
    audio_path = audio_root / f"{key}.mp3"
    print(f"  → {key}: 下载 {title[:24]} ...")
    if not download_audio(url, audio_path):
        return None
    wav16 = audio_root / f"{key}_16k.wav"
    if 1 in steps:
        if not to_16k(audio_path, wav16):
            return None
        print(f"  ✓ {key}: 16k 完成 {wav16.stat().st_size/1e6:.1f}MB")
    if 2 in steps:
        t0 = time.time()
        try:
            r = subprocess.run([sys.executable, os.path.join(config.BASE_DIR, "transcribe.py"),
                                "--audio", str(wav16), "--out", str(raw)],
                               capture_output=True, text=True, timeout=1800)
            if r.returncode != 0:
                print(f"    ✗ 转写失败: {r.stderr[-200:]}")
                return None
        except subprocess.TimeoutExpired:
            print(f"    ✗ 转写超时(>30min)，跳过 {key}")
            return None
        print(f"  ✓ {key}: 转写完成 ({time.time()-t0:.0f}s)")
    # 步骤 3/4 走 pipeline 的 diarize/semantic（需要 token/key，失败不阻塞）
    if 3 in steps:
        sw = ep_dir / f"{key}_with_switches.json"
        try:
            subprocess.run([sys.executable, os.path.join(config.BASE_DIR, "diarize.py"),
                            "--audio", str(wav16), "--segments", str(raw), "--out", str(sw)],
                           capture_output=True, text=True, timeout=1200)
        except subprocess.TimeoutExpired:
            print(f"    ⚠ {key}: 说话人分离超时")
    if 4 in steps:
        try:
            subprocess.run([sys.executable, os.path.join(config.BASE_DIR, "semantic_split.py"),
                            "--input", str(ep_dir / f"{key}_with_switches.json"),
                            "--output_json", str(ep_dir / f"{key}_final.json"),
                            "--output_txt", str(ep_dir / f"{key}_final.txt")],
                           capture_output=True, text=True, timeout=1200)
        except subprocess.TimeoutExpired:
            print(f"    ⚠ {key}: 语义处理超时")
    return key


def cleanup_batch(audio_root, out_root, keys):
    """每批完成后的磁盘释放：音频总删；中间 json 仅当该期已有 *_final 终版时才删。
    这样只跑转写（无 LLM key）时，_raw.json 会作为当前文稿保留下来。"""
    n_audio = n_mid = 0
    for k in keys:
        for suf in (".mp3", ".m4a", ".aac", ".wav", "_16k.wav", ".part"):
            p = audio_root / f"{k}{suf}"
            if p.exists():
                p.unlink()
                n_audio += 1
        ep_dir = out_root / k
        if not ep_dir.is_dir():
            continue
        has_final = (ep_dir / f"{k}_final.txt").exists() or (ep_dir / f"{k}_final.json").exists()
        if has_final:
            for f in ep_dir.glob("*"):
                if "_raw" in f.name or "_with_switches" in f.name:
                    f.unlink()
                    n_mid += 1
    print(f"  [清理] 删音频 {n_audio}, 删中间产物 {n_mid}（音频已释放；中间 json 仅在存在终版时删除）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="只打印清单统计")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--range", default=None, help="如 540,570")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--only-numbered", action="store_true")
    ap.add_argument("--steps", default="1,2", help="1=下载+16k, 2=转写, 3=分离, 4=语义")
    ap.add_argument("--batch-size", type=int, default=5,
                    help="每批处理的期数，批完成即删音频释放磁盘")
    ap.add_argument("--workers", type=int, default=1,
                    help="并行转写进程数（GPU 有余量时开 2，如 --workers 2）")
    ap.add_argument("--keep-audio", action="store_true", help="调试用：不删除音频")
    ap.add_argument("--list-file", default=str(DEFAULT_LIST))
    args = ap.parse_args()

    eps = load_list(args.list_file)
    numbered = [e for e in eps if e.get("num")]
    if args.list:
        print(f"总期数: {len(eps)}")
        print(f"有期号: {len(numbered)}  (范围 {numbered[0]['num']}~{numbered[-1]['num']})")
        print(f"番外/特刊: {len(eps) - len(numbered)}")
        return

    # 过滤
    selected = eps
    if args.only_numbered:
        selected = numbered
    if args.range:
        parts = [int(x) for x in args.range.split(",")]
        a, b = (parts[0], parts[0]) if len(parts) == 1 else (parts[0], parts[1])
        selected = [e for e in selected if e.get("num") and a <= e["num"] <= b]
    if args.limit:
        selected = selected[: args.limit]
    if not args.all and not args.limit and not args.range:
        print("未指定范围。用 --all / --limit N / --range a,b 明确范围。")
        return

    steps = [int(x) for x in args.steps.split(",") if x.strip()]
    config.ensure_dirs()
    audio_root = config.BASE_DIR / "audio_ingest"
    out_root = config.OUTPUT_DIR

    import shutil
    ok = fail = 0
    failed_keys = []
    t_all = time.time()
    batch_size = args.batch_size
    for start in range(0, len(selected), batch_size):
        # 磁盘空间防护：<3G 则等待（音频批次清理前可能被占满）
        while shutil.disk_usage(str(config.BASE_DIR)).free < 3e9:
            print(f"  ⚠ 磁盘剩余不足 3G，等待 120s 后重试 ...")
            time.sleep(120)
        batch = selected[start:start + batch_size]
        keys = []
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futures = {ex.submit(process_one, ep, steps, audio_root, out_root): ep
                       for ep in batch}
            for fut in as_completed(futures):
                try:
                    k = fut.result()
                except Exception as e:
                    print(f"  ✗ 处理异常: {str(e)[:100]}")
                    k = None
                if k:
                    keys.append(k)
                    ok += 1
                else:
                    failed_keys.append(getattr(fut, '_ep', '?'))
                    fail += 1
        # 批完成 → 释放磁盘：删本批音频与中间产物，仅保留最终文稿
        if not args.keep_audio and keys:
            cleanup_batch(audio_root, out_root, keys)
        print(f"  [批次 {start//batch_size+1}] {len(keys)} 期完成，"
              f"累计 {ok} 成功 / {fail} 失败，总耗时 {(time.time()-t_all)/60:.1f} 分钟")
    print(f"\n[batch] 全部完成: 成功 {ok}, 失败 {fail}, "
          f"总耗时 {(time.time()-t_all)/60:.1f} 分钟")
    if failed_keys:
        print(f"[batch] 失败期: {failed_keys}")
        print(f"[batch] 补跑命令: python3 batch_ingest.py --range {','.join(str(k) for k in failed_keys[:2])} --steps {args.steps} --workers {args.workers}")


if __name__ == "__main__":
    main()
