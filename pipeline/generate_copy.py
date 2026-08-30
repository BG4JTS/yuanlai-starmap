# -*- coding: utf-8 -*-
"""
风格匹配文案生成器：参考风格报告 + 官方示例文案，用 DeepSeek 生成符合节目调性的完整文案。

用法:
    python generate_copy.py "车厘子" --out analysis/original_copy_车厘子.txt
"""
import argparse
import json
import time
from datetime import datetime
from pathlib import Path

import requests

import config

STYLE_FALLBACK = """（未找到风格报告，将按通用科普播客风格生成）"""


def load_style():
    p1 = config.ANALYSIS_DIR / "style_report.md"
    p2 = config.ANALYSIS_DIR / "style_report.json"
    for p in (p1, p2):
        if p.exists():
            return p.read_text(encoding="utf-8")
    return STYLE_FALLBACK


def build_prompt(topic, style, sample=""):
    return f"""你是一位经验丰富的科普播客文案策划师。请为《原来是这样？！》节目撰写一段符合其风格的文案。

### 节目风格报告
{style}

### 官方文案示例（参考结构/语气/双人对话节奏）
{sample[:3000]}

### 文案规范
1. 四种写法任选：设定情景串联知识 / 科普杂谈 / 基于一个问题展开 / "如果是这样"假设。
2. 节目框架：前言(约300字) + 正文(5000-5500字，多个问答段，每段200-300字) + 结尾"原来是这样，就是这样！" + 彩蛋(1-3个冷知识/宣传/NG)。
3. 双人对话：旭岽（正常字体）=知识输出，语气理性清晰；子零（加粗）=捧哏接梗提问，语气轻快幽默。每段至少一个知识回答+一个回应提问。
4. 口语化，避免书面语；有自然转折（"你记不记得/对/原来是这样"）；适当生活化类比和冷知识。

### 任务
- 选题：{topic}
- 请直接输出完整文案，不要附加说明。
"""


def generate(topic: str, out_path: str = None):
    if not config.DEEPSEEK_API_KEY:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY")
    style = load_style()
    sample_path = Path(config.BASE_DIR) / "关于《原样》的文案.doc"
    sample = sample_path.read_text(encoding="utf-8", errors="ignore") if sample_path.exists() else ""
    if not sample:
        # 允许 .txt 版本的官方样例
        alt = list(Path(config.BASE_DIR).glob("关于*文案*"))
        if alt:
            sample = alt[0].read_text(encoding="utf-8", errors="ignore")

    prompt = build_prompt(topic, style, sample)
    headers = {"Authorization": f"Bearer {config.DEEPSEEK_API_KEY}"}
    payload = {"model": config.DEEPSEEK_MODEL, "messages": [{"role": "user", "content": prompt}],
               "temperature": 0.7, "max_tokens": 6000}
    print("[generate_copy] 生成中 ...")
    resp = requests.post(f"{config.DEEPSEEK_BASE_URL}/chat/completions", headers=headers,
                         json=payload, timeout=300)
    resp.raise_for_status()
    result = resp.json()["choices"][0]["message"]["content"]

    if out_path is None:
        config.ensure_dirs()
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        out_path = config.ANALYSIS_DIR / f"original_copy_{topic}_{ts}.txt"
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(result, encoding="utf-8")
    print(f"[generate_copy] 已保存 {out_path}（{len(result)} 字）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("topic", help="选题方向，如：车厘子、马年、彩虹")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    generate(args.topic, args.out)


if __name__ == "__main__":
    main()
