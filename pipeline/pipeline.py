# -*- coding: utf-8 -*-
"""
《原来是这样》流水线主入口。

处理一期节目：
    下载(可选) → 16kHz 单声道 → faster-whisper 转写 → pyannote 说话人分离
    → DeepSeek 语义分配/拆分/修正 → outputs/<期号>/<期号>_final.json + .txt

用法:
    # 从喜马拉雅 URL 批量处理
    python pipeline.py --urls urls.txt --steps 1,2,3,4

    # 处理已有音频目录（自动跳过已转 16k 的）
    python pipeline.py --audio-dir audio_new --steps 1,2,3,4

    # 只重跑某一步
    python pipeline.py --audio <xxx.wav> --ep 548 --steps 3,4
"""
import argparse
import glob
import os
import subprocess
import sys
import time

import config


def run(cmd: list, **kw) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, check=True, **kw)


def to_16k(src: str, dst: str):
    """ffmpeg 转 16kHz 单声道 WAV。"""
    run(["ffmpeg", "-i", src, "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
         "-y", dst], capture_output=True)


def download_audio(url: str, out_dir) -> str:
    """yt-dlp 下载喜马拉雅音频为 wav，返回文件名。"""
    config.ensure_dirs()
    run(["yt-dlp", "-f", "bestaudio", "--extract-audio", "--audio-format", "wav",
         "--audio-quality", "0", "-o", f"{out_dir}/%(title)s.%(ext)s", url],
        capture_output=True)
    wavs = glob.glob(os.path.join(out_dir, "*.wav"))
    return max(wavs, key=os.path.getmtime)


def episode_name(audio_path: str) -> str:
    """从文件名推导期号：优先取前导数字（如 548：银杏...  -> 548）。"""
    base = os.path.splitext(os.path.basename(audio_path))[0]
    digits = ""
    for ch in base:
        if ch.isdigit():
            digits += ch
        else:
            break
    return digits or base


def process_one(audio_path: str, steps: list, ep: str = None):
    config.ensure_dirs()
    ep = ep or episode_name(audio_path)
    out_dir = config.OUTPUT_DIR / ep
    out_dir.mkdir(parents=True, exist_ok=True)

    # 16k 转换（幂等：已有则跳过）
    wav16 = os.path.join(os.path.dirname(audio_path), f"{ep}_16k.wav")
    if os.path.exists(wav16) and os.path.getmtime(wav16) >= os.path.getmtime(audio_path):
        use = audio_path
    else:
        print(f"[pipeline] 转 16kHz: {audio_path}")
        to_16k(audio_path, wav16)
        use = wav16

    raw = out_dir / f"{ep}_raw.json"
    sw = out_dir / f"{ep}_with_switches.json"
    final = out_dir / f"{ep}_final.json"
    final_txt = out_dir / f"{ep}_final.txt"

    py = sys.executable
    if 1 in steps:
        print(f"\n=== 步骤1 转写 ===")
        run([py, os.path.join(config.BASE_DIR, "transcribe.py"), "--audio", use, "--out", str(raw)])
    if 2 in steps:
        print(f"\n=== 步骤2 说话人分离 ===")
        run([py, os.path.join(config.BASE_DIR, "diarize.py"), "--audio", use,
             "--segments", str(raw), "--out", str(sw)])
    if 3 in steps:
        print(f"\n=== 步骤3 语义处理 ===")
        run([py, os.path.join(config.BASE_DIR, "semantic_split.py"), "--input", str(sw),
             "--output_json", str(final), "--output_txt", str(final_txt)])
    print(f"\n[pipeline] {ep} 完成 → {out_dir}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--urls", help="URL 列表文件（喜马拉雅）")
    ap.add_argument("--audio-dir", help="本地音频目录（与 --urls 二选一）")
    ap.add_argument("--audio", help="单个音频文件")
    ap.add_argument("--ep", help="期号（覆盖从文件名推导）")
    ap.add_argument("--steps", default="1,2,3", help="逗号分隔步骤，如 1,2,3")
    ap.add_argument("--skip-download-install", action="store_true")
    args = ap.parse_args()

    steps = [int(s.strip()) for s in args.steps.split(",") if s.strip()]

    audio_files = []
    if args.audio:
        audio_files = [args.audio]
    elif args.urls:
        if not args.skip_download_install:
            run([sys.executable, "-m", "pip", "install", "-q", "yt-dlp"])
        with open(args.urls, encoding="utf-8") as f:
            for url in [l.strip() for l in f if l.strip()]:
                print(f"[pipeline] 下载: {url}")
                w = download_audio(url, config.AUDIO_NEW_DIR)
                audio_files.append(w)
    elif args.audio_dir:
        audio_files = sorted(glob.glob(os.path.join(args.audio_dir, "*.wav")))
    else:
        ap.error("需提供 --audio / --urls / --audio-dir 之一")

    if not audio_files:
        print("未找到音频")
        sys.exit(1)

    for a in audio_files:
        t0 = time.time()
        try:
            process_one(a, steps, ep=args.ep)
        except Exception as e:
            print(f"[pipeline] 处理失败 {a}: {e}")
        print(f"[pipeline] 单期耗时 {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
