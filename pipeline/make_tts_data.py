# -*- coding: utf-8 -*-
"""
TTS 训练数据准备：从 final.txt 解析带说话人的片段，用 ffmpeg 按时间切割音频，
并可选做"单说话人纯净度"校验（wespeaker 聚类；未装则跳过，直接切）。

产物结构：tts_data/<期号>/<说话人>/<起秒>s_<说话人>_<文本前20字>.wav
可疑混合片段放入 <说话人>/pending/ 子目录。

用法:
    python make_tts_data.py --ep 548 [--audio-dir audio_new] [--no-purity]
"""
import argparse
import os
import re
import subprocess
import sys

import config


def parse_txt(txt_path):
    pat = re.compile(r"\[(\d+\.\d+)\s*s?\s*->\s*(\d+\.\d+)\s*s?\]\s*([^:]+):\s*(.*)")
    segs = []
    with open(txt_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            m = pat.match(line)
            if m:
                segs.append({"start": float(m.group(1)), "end": float(m.group(2)),
                             "speaker": m.group(3).strip(), "text": m.group(4).strip()})
    return segs


def cut(audio_in, start, end, out_path):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    subprocess.run(["ffmpeg", "-i", audio_in, "-ss", str(start), "-to", str(end),
                    "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", "-y", out_path],
                   check=True, capture_output=True)


def purity_check(audio, start, end, threshold=0.2):
    """wespeaker ECAPA-TDNN 聚类，判断片段是否单一说话人。返回 (is_pure, reason)。"""
    try:
        import torch
        import numpy as np
        from sklearn.cluster import KMeans
        from collections import Counter
        import librosa
        import wespeaker
    except ImportError:
        return True, "wespeaker/sklearn/librosa 未安装，跳过校验"
    model = wespeaker.load_model("ECAPA-TDNN")
    model.eval()
    y, sr = librosa.load(audio, offset=start, duration=end - start, sr=16000)
    if len(y) / sr < 0.5:
        return True, "太短"
    chunk = int(sr * 1.0)
    embs = []
    with torch.no_grad():
        for i in range(0, len(y), chunk):
            c = y[i:i + chunk]
            if len(c) < sr * 0.5:
                continue
            e = model.compute_embedding(torch.from_numpy(c).float().unsqueeze(0)).numpy().flatten()
            embs.append(e)
    if len(embs) < 2:
        return True, "块太少"
    labels = KMeans(n_clusters=2, random_state=0, n_init=10).fit(embs).labels_
    cnt = Counter(labels)
    small = min(cnt.values()) / sum(cnt.values())
    return (small < threshold, f"小簇占比{small:.2f}")


def process_episode(ep, audio_dir, do_purity=True):
    # 定位 final.txt
    final_txt = config.OUTPUT_DIR / ep / f"{ep}_final.txt"
    if not final_txt.exists():
        matches = list(config.OUTPUT_DIR.glob(f"{ep}*_final.txt"))
        if not matches:
            raise FileNotFoundError(f"找不到 {ep} 的 final.txt")
        final_txt = matches[0]
    # 定位音频（优先期号对应的 16k wav）
    audio = None
    for d in (config.AUDIO_DIR, config.AUDIO_NEW_DIR, Path(audio_dir or "")):
        for pat in (f"{ep}*.wav",):
            cands = sorted(d.glob(pat)) if d.exists() else []
            if cands:
                audio = str(cands[0])
                break
        if audio:
            break
    if not audio:
        raise FileNotFoundError(f"找不到 {ep} 的音频")

    segs = parse_txt(final_txt)
    if not segs:
        raise RuntimeError(f"{ep} 文稿解析为空")
    total = segs[-1]["end"]
    print(f"[tts_data] {ep}: {len(segs)} 段, 音频 {audio}")

    out_root = config.TTS_DIR / ep
    n_ok = n_pending = n_skip = 0
    for i, seg in enumerate(segs):
        start, end, text = seg["start"], seg["end"], seg["text"]
        if start < config.TTS_SKIP_START or end > total - config.TTS_SKIP_END:
            n_skip += 1
            continue
        if end - start < config.TTS_MIN_DURATION:
            n_skip += 1
            continue
        if any(kw in text for kw in config.TTS_FILTER_KEYWORDS):
            n_skip += 1
            continue
        spk = config.normalize_speaker(seg["speaker"])
        if spk not in (config.SPEAKER_MAIN, config.SPEAKER_SUB):
            n_skip += 1
            continue
        safe = re.sub(r'[\\/*?:"<>|]', "", text[:20]).strip() or f"seg{i}"
        fname = f"{start:.2f}s_{'xudong' if spk == config.SPEAKER_MAIN else 'ziling'}_{safe}.wav"
        sub = ""
        if do_purity:
            pure, reason = purity_check(audio, start, end)
            if not pure:
                sub = "pending"
        subdir = "xudong" if spk == config.SPEAKER_MAIN else "ziling"
        out = out_root / subdir / sub / fname
        try:
            cut(audio, start, end, out)
            if sub:
                n_pending += 1
                print(f"  ⚠ {fname} (混合:{reason})")
            else:
                n_ok += 1
        except Exception as e:
            print(f"  ✗ 切割失败 {fname}: {e}")
    print(f"[tts_data] 完成: 正常 {n_ok}, 待审 {n_pending}, 跳过 {n_skip} → {out_root}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ep", required=True, help="期号，如 548")
    ap.add_argument("--audio-dir", default=None, help="音频所在目录（默认 audio/ 与 audio_new/）")
    ap.add_argument("--no-purity", action="store_true", help="跳过说话人纯度校验")
    args = ap.parse_args()
    process_episode(args.ep, args.audio_dir, do_purity=not args.no_purity)


if __name__ == "__main__":
    main()
