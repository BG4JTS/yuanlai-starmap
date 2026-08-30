# -*- coding: utf-8 -*-
"""
DeepSeek 语义后处理：
1) 按节目规则给每一段分配说话人（旭岽=知识输出/长句，子零=捧哏/短回应）
2) 对含说话人切换点(has_switch)的长段，语义拆分成独立发言
3) 短回应归属修正（"对/是/嗯"开头的短句归给另一方）
4) 输出 *_final.json + *_final.txt

用法:
    python semantic_split.py --input <with_switches.json> --output_json <final.json> --output_txt <final.txt>
"""
import argparse
import json
import time

import requests

import config


# ---------- DeepSeek 调用 ----------
def _call_deepseek(messages: list, temperature: float = None, max_tokens: int = 8000,
                   json_mode: bool = True):
    from llm_client import call_llm
    return call_llm(messages, temperature=temperature, max_tokens=max_tokens,
                    json_mode=json_mode, tag="semantic")


def _strip_markdown(text: str) -> str:
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]
    return text.strip()


def _parse_json_any(output: str):
    """宽容解析 DeepSeek 返回的 JSON（数组 / {idx:speaker} / {data:[...]} 等）。"""
    output = _strip_markdown(output)
    data = json.loads(output)
    # dict -> 提取列表
    if isinstance(data, dict):
        for key in ("data", "result", "segments", "mapping", "transcript", "speakers"):
            if key in data and isinstance(data[key], list):
                return data[key]
        if all(str(k).isdigit() for k in data.keys()):
            return [{"index": int(k), "speaker": v if isinstance(v, str) else v.get("speaker", "UNKNOWN")}
                    for k, v in data.items()]
    return data


# ---------- 说话人分配 ----------
SPEAKER_RULES = """你是一位播客对话分析专家。请为以下《原来是这样》节目转录逐段分配说话人。

### 固定规则
1. **旭岽**：主持人、知识输出者。发言通常较长，负责讲解、科普、总结、推进话题。常用"你记不记得/我觉得/所以/其实/也就是说/这里先解释一下/给大家科普一下"。
2. **子零**：捧哏、接梗、提问者。发言通常较短，常以"对/是/确实/真的吗/是吗/没错/那……呢/被你这么一说"回应，承接话题引导展开。
3. 开头自我介绍"我是xx"按姓名分配；结尾旭岽说"原来是这样"，子零回"就是这样！"。
4. 大部分情况是一人一句轮流。若一句话混有"回应词+长篇讲解"，把回应词归子零、讲解归旭岽（视为打断）。

### 重要：均衡性自查（必须遵守）
- 两人发言应**大体交替出现**：连续 3 段以上分配给同一个人，几乎必然有误，请重新审视这些段落的归属。
- 长篇讲解归旭岽、短回应归子零，但**两人总段数占比不应悬殊**（如 80% : 20% 以上即为异常）。
- 如果你给某个人分配了超过 70% 的段落，说明你的判断有系统性偏差，必须重新分配。

### 输出
JSON 对象，键为片段编号（字符串），值为说话人（"旭岽" 或 "子零"）。只输出 JSON。

### 转录
{numbered}
"""


def assign_speakers(segments: list) -> None:
    """分批用 DeepSeek 给每个 segment 分配说话人，就地写入 seg["speaker"]。"""
    total = len(segments)
    for start in range(0, total, config.DEEPSEEK_BATCH):
        end = min(start + config.DEEPSEEK_BATCH, total)
        batch = segments[start:end]
        numbered = "\n".join(f"[{start + i}] {s['text'].strip()}" for i, s in enumerate(batch))
        prompt = SPEAKER_RULES.format(numbered=numbered)
        try:
            out = _call_deepseek([{"role": "user", "content": prompt}])
            mapping = _parse_json_any(out)
            n = 0
            for item in mapping:
                idx = item.get("index", item.get("id"))
                if not isinstance(idx, int):
                    continue
                spk = config.normalize_speaker(item.get("speaker", "UNKNOWN"))
                if spk in (config.SPEAKER_MAIN, config.SPEAKER_SUB) and 0 <= idx < total:
                    segments[idx]["speaker"] = spk
                    n += 1
            print(f"  [语义分配] 批 {start//config.DEEPSEEK_BATCH+1}: 分配 {n}/{len(batch)} 段")
        except Exception as e:
            print(f"  [语义分配] 批 {start//config.DEEPSEEK_BATCH+1} 失败: {e}")
        time.sleep(0.2)


# ---------- 混合段语义拆分 ----------
SPLIT_PROMPT = """你是播客对话分析专家。下面是一段《原来是这样》节目文本，可能包含旭岽、子零两人的交替发言。

请按说话人切换拆分成多个片段，每片段是某一人的完整单次发言。特别注意：
- 以短回应词（对/是/嗯/欸/是的/没错/真的吗 等）开头且明显是回应前一句的，单独拆出归回应者。
- 如果短回应是自我确认（如旭岽说"是的"确认自己的观点），保留在同一片段。

输出 JSON 数组，每个元素：{{"speaker": "旭岽"|"子零", "text": "发言内容（保持原文不改词）"}}。只输出 JSON。

待拆分文本：
{text}
"""


def split_by_switch(seg: dict) -> list:
    """含切换点或有长文本/回应标记的段，交给 DeepSeek 拆分为多段。
    时间按文本长度比例切分。"""
    text = seg["text"].strip()
    duration = seg["end"] - seg["start"]
    need_split = seg.get("has_switch", False)
    if not need_split:
        # 阈值启发：超长 或 明显含交替
        if len(text) <= 120 and duration <= 15:
            return [seg]
        if not any(m in text for m in ["对", "是", "确实", "真的吗", "那", "这倒是", "被你这么一说", "我觉得"]):
            return [seg]
    try:
        out = _call_deepseek([{"role": "user", "content": SPLIT_PROMPT.format(text=text)}])
        parts = _parse_json_any(out)
        if not isinstance(parts, list) or not parts:
            return [seg]
        total_chars = sum(len(p.get("text", "")) for p in parts)
        if total_chars == 0:
            return [seg]
        new_segs = []
        cur = seg["start"]
        for p in parts:
            spk = config.normalize_speaker(p.get("speaker", seg.get("speaker", "UNKNOWN")))
            ratio = len(p.get("text", "")) / total_chars
            nxt = cur + duration * ratio
            new_segs.append({
                "start": round(cur, 3), "end": round(nxt, 3),
                "text": p.get("text", "").strip(), "speaker": spk,
            })
            cur = nxt
        if new_segs:
            new_segs[-1]["end"] = seg["end"]
        return new_segs
    except Exception as e:
        print(f"  [拆分] 失败保留原文: {e}")
        return [seg]


# ---------- 短回应修正 ----------
def is_short_response(text: str) -> bool:
    t = text.strip()
    if len(t) > 6:
        return False
    return any(t.startswith(w) for w in config.SHORT_RESPONSES)


def fix_short_responses(segments: list) -> list:
    """短回应若与前一发言人相同，多半是误归属，改为对方。"""
    if len(segments) < 2:
        return segments
    fixed = 0
    for i in range(1, len(segments)):
        cur, prev = segments[i], segments[i - 1]
        t = cur["text"].strip()
        if is_short_response(t) and len(t) <= 5 and len(prev["text"]) > 10:
            cur_spk = cur.get("speaker")
            prev_spk = prev.get("speaker")
            if cur_spk is not None and cur_spk == prev_spk:
                cur["speaker"] = config.SPEAKER_SUB if prev_spk == config.SPEAKER_MAIN else config.SPEAKER_MAIN
                fixed += 1
    print(f"  [短回应修正] 调整 {fixed} 段")
    return segments


# ---------- 主流程 ----------
def main():
    ap = argparse.ArgumentParser(description="DeepSeek 语义分配 + 拆分 + 短回应修正")
    ap.add_argument("--input", required=True, help="diarize 输出的带切换点 JSON")
    ap.add_argument("--output_json", required=True)
    ap.add_argument("--output_txt", required=True)
    args = ap.parse_args()

    with open(args.input, encoding="utf-8") as f:
        data = json.load(f)
    segments = data["segments"]
    print(f"[semantic] 原始片段数: {len(segments)}")

    print("[semantic] 1/3 说话人语义分配 ...")
    assign_speakers(segments)

    print("[semantic] 2/3 混合段拆分 ...")
    new_segs = []
    for seg in segments:
        new_segs.extend(split_by_switch(seg))
    print(f"[semantic] 拆分后: {len(new_segs)} 段")

    print("[semantic] 3/3 短回应修正 ...")
    new_segs = fix_short_responses(new_segs)

    print("[semantic] 4/4 MISSING 兜底 ...")
    # 无 speaker 的段继承前一段（防 MISSING 扩散到文稿）
    prev_spk = None
    filled = 0
    for seg in new_segs:
        if not seg.get("speaker") or seg.get("speaker") == "UNKNOWN":
            seg["speaker"] = prev_spk or config.SPEAKER_MAIN
            filled += 1
        else:
            prev_spk = seg["speaker"]
    if filled:
        print(f"  [兜底] {filled} 段无 speaker，已继承前段")

    # 均衡性检查：单人占比 > 85% 时警告（供人工复核）
    spk_count = {}
    for seg in new_segs:
        spk = seg.get("speaker", "UNKNOWN")
        spk_count[spk] = spk_count.get(spk, 0) + 1
    total_n = len(new_segs)
    for spk, n in spk_count.items():
        if total_n and n / total_n > 0.85:
            print(f"  ⚠ 均衡警告: {spk} 占 {n}/{total_n} 段（{n*100//total_n}%），分配可能失衡，建议 --force 重跑")

    data["segments"] = new_segs
    with open(args.output_json, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    with open(args.output_txt, "w", encoding="utf-8") as f:
        for seg in new_segs:
            spk = seg.get("speaker", "UNKNOWN")
            f.write(f"[{seg['start']:.2f}s -> {seg['end']:.2f}s] {spk}: {seg['text'].strip()}\n")

    # 统计
    dur = {}
    for seg in new_segs:
        spk = seg.get("speaker", "UNKNOWN")
        dur[spk] = dur.get(spk, 0.0) + (seg["end"] - seg["start"])
    print("[semantic] 说话人时长(分钟): " + ", ".join(f"{k}:{v/60:.2f}" for k, v in dur.items()))
    print(f"[semantic] 完成: {args.output_json} / {args.output_txt}")


if __name__ == "__main__":
    main()
