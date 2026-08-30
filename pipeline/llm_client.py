# -*- coding: utf-8 -*-
"""
llm_client.py：统一 LLM 调用客户端（所有分析脚本共用）。
- OpenAI 兼容格式（智谱 GLM / DeepSeek 均可）
- 详细 API 日志：每次调用打印 [API] 行（状态/耗时/token），并追加 analysis/api_stats.jsonl
- 失败自动重试（3 次，指数退避）
"""
import json
import os
import time
from pathlib import Path

import requests

BASE = Path(os.environ.get("PROJECT_ROOT", "/hy-tmp/whisperx_project"))
API_LOG = BASE / "analysis" / "api_stats.jsonl"

_config = None


def _get_config():
    global _config
    if _config is None:
        import config
        _config = config
    return _config


def _log_api(entry: dict):
    """每次 API 调用：控制台一行 + 追加 api_stats.jsonl"""
    ts = time.strftime("%H:%M:%S")
    cached = entry.get("cached_tokens")
    cache_str = f" cache={cached}" if cached else ""
    line = (f"[API] {ts} {entry.get('tag','')} status={entry.get('status')} "
            f"time={entry.get('time', 0):.1f}s in={entry.get('prompt_tokens', '-')} "
            f"out={entry.get('completion_tokens', '-')}{cache_str} "
            f"retry={entry.get('retry', 0)}")
    if entry.get("error"):
        line += f" error={str(entry['error'])[:120]}"
    print(line, flush=True)
    try:
        API_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(API_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({**entry, "ts": time.strftime("%Y-%m-%d %H:%M:%S")},
                               ensure_ascii=False) + "\n")
    except Exception:
        pass


def call_llm(messages, temperature=0.1, max_tokens=8000, json_mode=True,
             timeout=240, tag="llm", retries=3):
    """
    统一 LLM 调用。返回 content 字符串。
    失败重试 retries 次（指数退避）。最终失败抛 RuntimeError。
    """
    cfg = _get_config()
    if not cfg.DEEPSEEK_API_KEY:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY")
    url = f"{cfg.DEEPSEEK_BASE_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {cfg.DEEPSEEK_API_KEY}"}
    payload = {
        "model": cfg.DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    last_err = ""
    for attempt in range(retries):
        t0 = time.time()
        entry = {"tag": tag, "retry": attempt}
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=timeout)
            entry["time"] = time.time() - t0
            if r.status_code != 200:
                entry.update({"status": r.status_code, "error": r.text[:200]})
                _log_api(entry)
                last_err = f"HTTP {r.status_code}: {r.text[:150]}"
                time.sleep(min(60, 5 * (attempt + 1)))
                continue
            d = r.json()
            usage = d.get("usage", {}) or {}
            m = d["choices"][0]["message"]
            content = m.get("content", "") or ""
            cached = 0
            pt_details = usage.get("prompt_tokens_details") or {}
            cached = pt_details.get("cached_tokens") or 0
            entry.update({
                "status": 200,
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
                "cached_tokens": cached,
                "finish": d["choices"][0].get("finish_reason"),
            })
            _log_api(entry)
            if not content.strip():
                # GLM 思考模式：max_tokens 不足时 content 为空（思考占满）
                entry["error"] = "content 为空（思考 token 占满，需调大 max_tokens）"
                _log_api(entry)
                last_err = "content 为空"
                time.sleep(3)
                continue
            return content
        except Exception as e:
            entry["time"] = time.time() - t0
            entry["status"] = "EXC"
            entry["error"] = str(e)[:200]
            _log_api(entry)
            last_err = str(e)[:150]
            time.sleep(min(60, 5 * (attempt + 1)))
    raise RuntimeError(f"LLM 调用失败（重试 {retries} 次）[{tag}]: {last_err}")


def strip_markdown(text: str) -> str:
    """去掉 ```json / ``` 包裹"""
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]
    return text.strip()


def parse_json(text: str):
    """宽容解析 JSON（含 markdown 包裹/字典包列表等常见形态）"""
    text = strip_markdown(text)
    data = json.loads(text)
    if isinstance(data, dict):
        for key in ("data", "result", "segments", "mapping", "transcript", "speakers"):
            if key in data and isinstance(data[key], list):
                return data[key]
    return data


def api_stats_summary():
    """汇总 api_stats.jsonl：总调用/成功/失败/token/平均耗时"""
    if not API_LOG.exists():
        return {"calls": 0}
    total = ok = fail = 0
    tin = tout = 0
    times = []
    for line in API_LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            d = json.loads(line)
            total += 1
            if d.get("status") == 200:
                ok += 1
                tin += d.get("prompt_tokens") or 0
                tout += d.get("completion_tokens") or 0
                times.append(d.get("time") or 0)
            else:
                fail += 1
        except Exception:
            continue
    return {"calls": total, "ok": ok, "fail": fail,
            "prompt_tokens": tin, "completion_tokens": tout,
            "avg_time": round(sum(times) / len(times), 1) if times else 0}
