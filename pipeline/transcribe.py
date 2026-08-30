# -*- coding: utf-8 -*-
"""
转写：faster-whisper（CTranslate2，GPU）ASR + 词级时间戳。
输出结构兼容原 whisperx 的 segments：[{start, end, text, words:[{word,start,end,score}]}]

用法:
    python transcribe.py --audio <音频路径> [--out <json路径>]
"""
import argparse
import json
import os
import time

import config


def transcribe(audio_path: str, model_name: str = None, language: str = None,
               device: str = None, compute_type: str = None, batch_size: int = None) -> list:
    """返回 segments 列表。优先用 BatchedInferencePipeline（支持 batch_size，充分利用显存）。"""
    from faster_whisper import WhisperModel

    model_name = model_name or config.WHISPER_MODEL
    language = language or config.TRANSCRIBE_LANG
    device = device or config.detect_device()
    compute_type = compute_type or config.COMPUTE_TYPE
    batch_size = batch_size or config.TRANSCRIBE_BATCH_SIZE

    print(f"[transcribe] 模型={model_name} device={device} compute={compute_type}")
    model = WhisperModel(
        model_name, device=device, compute_type=compute_type,
        download_root=str(config.HF_CACHE),
    )

    t0 = time.time()
    try:
        # BatchedInferencePipeline：真正的批处理推理（batch_size 可调大）
        from faster_whisper import BatchedInferencePipeline
        batched = BatchedInferencePipeline(model=model)
        segments_iter, info = batched.transcribe(
            audio_path,
            language=language,
            batch_size=batch_size,
            chunk_length=30,
            vad_filter=True,
            word_timestamps=True,
        )
        print(f"[transcribe] 批处理 batch_size={batch_size}")
    except (ImportError, TypeError, ValueError):
        # 回退：普通 transcribe（不支持 batch_size）
        segments_iter, info = model.transcribe(
            audio_path,
            language=language,
            word_timestamps=True,
            vad_filter=config.VAD_FILTER,
        )
        print("[transcribe] 回退普通转写（无批处理）")
    segments = []
    for s in segments_iter:
        words = []
        for w in (s.words or []):
            words.append({
                "word": w.word,
                "start": round(w.start, 3),
                "end": round(w.end, 3),
                "score": round(float(w.probability), 4),
            })
        segments.append({
            "start": round(s.start, 3),
            "end": round(s.end, 3),
            "text": s.text.strip(),
            "words": words,
        })
    print(f"[transcribe] {len(segments)} 段, 耗时 {time.time()-t0:.1f}s, "
          f"语言={info.language} 置信度={info.language_probability:.2f}")
    return segments


def save(segments: list, out_path: str):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"segments": segments}, f, ensure_ascii=False, indent=2)
    print(f"[transcribe] 已保存 {out_path}")


def main():
    ap = argparse.ArgumentParser(description="faster-whisper 转写")
    ap.add_argument("--audio", required=True, help="输入音频")
    ap.add_argument("--out", required=True, help="输出 JSON 路径")
    args = ap.parse_args()
    segments = transcribe(args.audio)
    save(segments, args.out)


if __name__ == "__main__":
    main()
