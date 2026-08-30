# -*- coding: utf-8 -*-
"""
说话人分离：pyannote.audio speaker-diarization-3.1。
只做声纹分离，输出说话人时间段 + 在 whisper segment 上标记"切换点"。
具体说话人是"旭岽/子零"由 DeepSeek 语义分配决定（见 semantic_split.py）。

用法:
    python diarize.py --audio <音频路径> [--segments <raw.json>] [--out <json路径>]
"""
import argparse
import json
import time

import config


def _install_hf_compat():
    """huggingface_hub>=1.0 移除了 use_auth_token 参数，而 pyannote.audio 3.4 仍在调用。
    此兼容层把 use_auth_token 转发为 token，使两者可共存。"""
    try:
        import huggingface_hub
        from huggingface_hub import hf_hub_download as _orig_dl
        from huggingface_hub import snapshot_download as _orig_snap

        def _dl(repo_id, filename=None, use_auth_token=None, **kw):
            if use_auth_token is not None and "token" not in kw:
                kw["token"] = use_auth_token
            return _orig_dl(repo_id, filename=filename, **kw)

        def _snap(repo_id, use_auth_token=None, **kw):
            if use_auth_token is not None and "token" not in kw:
                kw["token"] = use_auth_token
            return _orig_snap(repo_id, **kw)

        huggingface_hub.hf_hub_download = _dl
        huggingface_hub.snapshot_download = _snap
        try:
            import huggingface_hub.file_download as _fd
            _fd.hf_hub_download = _dl
        except Exception:
            pass
    except ImportError:
        pass


_install_hf_compat()


def diarize(audio_path: str, min_speakers: int = None, max_speakers: int = None,
            device: str = None) -> list:
    """返回说话人时间段 [{start, end, speaker}]。需要 HF token。"""
    if not config.HF_TOKEN:
        raise RuntimeError("缺少 HUGGINGFACE_HUB_TOKEN 环境变量（pyannote 模型需要授权）")

    import torch
    from pyannote.audio import Pipeline

    device = device or config.detect_device()
    print(f"[diarize] 加载 {config.DIARIZE_MODEL} ...")
    try:
        pipeline = Pipeline.from_pretrained(
            config.DIARIZE_MODEL,
            use_auth_token=config.HF_TOKEN,   # pyannote 3.x
            cache_dir=str(config.MODEL_CACHE),
        )
    except TypeError:
        pipeline = Pipeline.from_pretrained(
            config.DIARIZE_MODEL,
            token=config.HF_TOKEN,            # pyannote 4.x（移除了 use_auth_token）
            cache_dir=str(config.MODEL_CACHE),
        )
    pipeline.to(torch.device(device))

    t0 = time.time()
    kw = {}
    if min_speakers:
        kw["min_speakers"] = min_speakers
    if max_speakers:
        kw["max_speakers"] = max_speakers
    diarization = pipeline(audio_path, **kw)
    print(f"[diarize] 分离完成，耗时 {time.time()-t0:.1f}s")

    out = []
    for seg, _, speaker in diarization.itertracks(yield_label=True):
        out.append({"start": round(seg.start, 3), "end": round(seg.end, 3), "speaker": speaker})
    return out


def mark_switch_points(segments: list, diar_segs: list, min_gap: float = 1.0) -> list:
    """在每个 whisper segment 上标记是否有说话人切换点。
    返回 (segments, switch_points)。"""
    # 提取切换点（说话人变化的时间点），过滤过近的点
    switch_points = []
    last = None
    for ds in sorted(diar_segs, key=lambda x: x["start"]):
        if last is not None and ds["speaker"] != last:
            p = ds["start"]
            if not switch_points or p - switch_points[-1] > min_gap:
                switch_points.append(round(p, 3))
        last = ds["speaker"]

    for seg in segments:
        cuts = [p for p in switch_points if seg["start"] < p < seg["end"]]
        if cuts:
            seg["has_switch"] = True
            seg["switch_points"] = cuts
        else:
            seg["has_switch"] = False
    return segments, switch_points


def main():
    ap = argparse.ArgumentParser(description="pyannote 说话人分离 + 切换点标记")
    ap.add_argument("--audio", required=True, help="输入音频")
    ap.add_argument("--segments", required=True, help="transcribe 输出的 raw.json")
    ap.add_argument("--out", required=True, help="输出带切换点标记的 JSON")
    args = ap.parse_args()

    with open(args.segments, encoding="utf-8") as f:
        data = json.load(f)
    segments = data["segments"]

    diar_segs = diarize(args.audio)
    segments, switch_points = mark_switch_points(segments, diar_segs)

    data["segments"] = segments
    data["diarization"] = diar_segs
    data["switch_points"] = switch_points
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[diarize] {len(switch_points)} 个切换点，已保存 {args.out}")


if __name__ == "__main__":
    main()
