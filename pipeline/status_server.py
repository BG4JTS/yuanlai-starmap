# -*- coding: utf-8 -*-
"""status_server — 《原来是这样》监控台（双线架构版）
面板: LLM 打标线(qwen3:8b CPU) | 喜马拉雅补转写线(FunASR GPU) | Ollama | 系统
端口 8080, 密码 yuanlai2026
"""
import json, os, re, time, uuid, subprocess, html, platform
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from pathlib import Path

try:
    import psutil
except ImportError:
    psutil = None

PASSWORD = "yuanlai2026"
SESSION_TTL = 86400 * 7
_SESSIONS = {}
START_TIME = time.time()
IS_WIN = platform.system() == "Windows"
BASE = Path(__file__).parent
OUTPUTS = BASE / "outputs"
TAGS_FILE = BASE / "analysis" / "tags.json"
XM_PROGRESS = BASE / "xm_progress.json"
TAGS_LOG = Path("/tmp/tags_v11.log")
XM_LOG = Path("/tmp/xm_batch.log")
FULL_LIST = BASE / "episodes_full_673.json"


def valid_keys():
    """673 期全集的有效目录 key 集合"""
    try:
        eps = json.loads(FULL_LIST.read_text(encoding="utf-8"))
        keys = set()
        for m in eps:
            n = m.get("num")
            if n:
                keys.add(f"{n:03d}")
            else:
                t = m.get("title", "")
                keys.add("X" + re.sub(r'[\\/:*?"<>|\r\n]+', "", t).strip()[:10])
        return keys
    except Exception:
        return None

_log_cache = {"path": None, "mtime": 0, "data": ""}


def read_log_tail(path, n=25):
    """读日志尾部（缓存 by mtime）"""
    try:
        p = Path(path)
        if not p.exists():
            return []
        mt = p.stat().st_mtime
        key = str(p)
        if _log_cache["path"] == key and _log_cache["mtime"] == mt:
            return _log_cache["data"]
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        out = [l for l in lines if "it/s]" not in l and l.strip()][-n:]
        _log_cache.update(path=key, mtime=mt, data=out)
        return out
    except Exception:
        return []


def get_tags_progress():
    """打标线: tags.json 期数（按 673 有效期过滤）+ 词表规模 + 日志尾部"""
    d = {"done": 0, "vocab": 0, "avg_tags": 0, "running": False, "last": "—", "extra": 0}
    keys = valid_keys()
    try:
        if TAGS_FILE.exists():
            data = json.loads(TAGS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                counts = []
                vocab = set()
                for x in data:
                    if not isinstance(x, dict):
                        continue
                    ep = x.get("ep")
                    tags_n = len(x.get("tags") or [])
                    if keys is None or ep in keys:
                        d["done"] += 1
                        counts.append(tags_n)
                    else:
                        d["extra"] += 1
                    vocab.update(x.get("tags") or [])
                if counts:
                    d["avg_tags"] = round(sum(counts) / len(counts), 1)
                d["vocab"] = len(vocab)
                last = data[-1] if data else {}
                d["last"] = f"{last.get('ep','')}: {len(last.get('tags') or [])} tags"
    except Exception:
        pass
    running = False
    try:
        out = subprocess.run(["pgrep", "-f", "tag_episodes"], capture_output=True, timeout=5)
        running = out.returncode == 0 and bool(out.stdout.strip())
    except Exception:
        pass
    d["running"] = bool(running)
    log = read_log_tail(TAGS_LOG, 8)
    for line in reversed(log):
        if "✓" in line or "✗" in line:
            d["last"] = line.strip()[:70]
            break
    d["log"] = log
    return d


def get_xm_progress():
    """补转写线: xm_progress.json (xm_batch.py 写)"""
    d = {"phase": "—", "total": 0, "done": 0, "failed": 0, "dl_queue": 0,
         "elapsed": 0, "rate": 0, "remain_h": -1, "running": False}
    try:
        raw = json.loads(XM_PROGRESS.read_text(encoding="utf-8"))
        d.update({k: raw.get(k, v) for k, v in d.items() if k != "running"})
        st = raw.get("started_at")
        if st:
            d["elapsed"] = (time.time() - st) / 60
    except Exception:
        pass
    try:
        out = subprocess.run(["pgrep", "-f", "xm_batch"], capture_output=True, timeout=5)
        d["running"] = out.returncode == 0 and bool(out.stdout.strip())
    except Exception:
        pass
    if d["done"] > 0 and d["elapsed"] > 0 and d["phase"] != "done":
        rate = d["done"] / d["elapsed"] * 60
        d["rate"] = round(rate, 1)
        remain = d["total"] - d["done"] - d["failed"]
        if rate > 0:
            d["remain_h"] = round(remain / rate, 1)
    return d


def get_ollama():
    d = {"model": "—", "proc": "—", "ctx": "—", "cpu": "—"}
    try:
        out = subprocess.run(["ollama", "ps"], capture_output=True, text=True, timeout=10)
        for line in out.stdout.splitlines()[1:]:
            parts = line.split()
            if parts:
                d["model"] = parts[0]
                for p in parts:
                    if "CPU" in p.upper() or "GPU" in p.upper():
                        d["proc"] = p
    except Exception:
        pass
    try:
        out = subprocess.run(["pgrep", "-af", "llama-server"], capture_output=True, text=True, timeout=5)
        m = re.search(r"-c (\d+)", out.stdout or "")
        if m:
            d["ctx"] = m.group(1)
    except Exception:
        pass
    if psutil:
        try:
            for p in psutil.process_iter(["pid", "name", "cpu_percent"]):
                if "llama-server" in (p.info.get("name") or ""):
                    d["cpu"] = f"{p.info.get('cpu_percent', 0):.0f}%"
        except Exception:
            pass
    return d


def get_gpu():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10)
        v = out.stdout.strip().split(", ")
        if len(v) >= 5:
            return {"util": f"{v[0]}%", "mem_used": f"{int(v[1])/1024:.1f}",
                    "mem_total": f"{int(v[2])/1024:.0f}", "temp": v[3], "power": v[4]}
    except Exception:
        pass
    return None


def get_sys():
    d = {"cpu_pct": "—", "mem": "—", "disk": "—", "ncpu": os.cpu_count() or "?", "conns": "—"}
    if psutil:
        try:
            d["cpu_pct"] = f"{psutil.cpu_percent(interval=0.4):.0f}"
            vm = psutil.virtual_memory()
            d["mem"] = f"{vm.used/1e9:.1f}/{vm.total/1e9:.0f}GB ({vm.percent}%)"
            du = psutil.disk_usage(str(BASE))
            d["disk"] = f"{du.used/1e9:.0f}/{du.total/1e9:.0f}GB ({du.percent}%)"
            d["conns"] = len(psutil.net_connections(kind="inet"))
        except Exception:
            pass
    return d


PAGE = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>原样监控台</title>
<meta http-equiv="refresh" content="10">
<style>
body{{font-family:"Microsoft YaHei",sans-serif;background:#0f172a;color:#e2e8f0;margin:20px;}}
h1{{font-size:20px;}} h2{{font-size:15px;margin:8px 0;}}
.sub{{color:#64748b;font-size:12px;margin-bottom:14px;}}
.badge{{padding:2px 8px;border-radius:10px;font-size:11px;}}
.badge-run{{background:#14532d;color:#4ade80;}} .badge-stop{{background:#7f1d1d;color:#fca5a5;}}
.bar-wrap{{background:#1e293b;border-radius:6px;height:14px;overflow:hidden;margin:8px 0 14px;}}
.bar{{background:linear-gradient(90deg,#38bdf8,#4ade80);height:100%;}}
.prog{{font-size:14px;margin-bottom:6px;}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin-bottom:12px;}}
.card{{background:#1e293b;border-radius:8px;padding:10px;}}
.card .k{{font-size:11px;color:#94a3b8;}} .card .v{{font-size:18px;font-weight:600;margin-top:3px;}}
.panel{{background:#1e293b;border-radius:10px;padding:14px;margin-bottom:12px;}}
table{{width:100%;font-size:12px;border-collapse:collapse;}} td{{padding:4px 8px;border-bottom:1px solid #334155;}}
td:first-child{{color:#94a3b8;width:110px;}}
pre.log{{background:#0b1220;padding:10px;border-radius:6px;font-size:11px;max-height:220px;overflow:auto;white-space:pre-wrap;}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:12px;}}
</style></head>
<body>
<h1>《原来是这样》监控台 <span class="badge badge-run">{platform}</span></h1>
<div class="sub">双线架构: CPU 打标线 + GPU 补转写线 | 10s 自动刷新</div>

<div class="panel">
  <h2>① LLM 打标线 <span class="badge {tags_badge}">{tags_status}</span> <span style="font-size:11px;color:#94a3b8">qwen3:8b CPU</span></h2>
  <div class="prog">已完成: <b>{tags_done}</b> / 673 期（{tags_pct:.1f}%）｜ 平均 <b>{tags_avg}</b> tags/期｜ 词表 <b>{tags_vocab}</b></div>
  <div class="bar-wrap"><div class="bar" style="width:{tags_pct:.1f}%"></div></div>
  <table>
    <tr><td>最近完成</td><td class="cur">{tags_last}</td></tr>
    <tr><td>Ollama</td><td>{ol_model} | {ol_proc} | ctx {ol_ctx} | runner CPU {ol_cpu}</td></tr>
  </table>
</div>

<div class="panel">
  <h2>② 喜马拉雅补转写线 <span class="badge {xm_badge}">{xm_status}</span> <span style="font-size:11px;color:#94a3b8">FunASR GPU</span></h2>
  <div class="prog">完成: <b>{xm_done}</b> / <b>{xm_total}</b> 期（{xm_pct:.1f}%）｜ 失败 {xm_failed}｜ 阶段 {xm_phase}</div>
  <div class="bar-wrap"><div class="bar" style="width:{xm_pct:.1f}%"></div></div>
  <table>
    <tr><td>速率/剩余</td><td>{xm_rate} 期/h ｜ {xm_remain}</td></tr>
    <tr><td>下载队列</td><td>{xm_dl_queue}</td></tr>
  </table>
</div>

<div class="cards">
  <div class="card"><div class="k">GPU 利用率</div><div class="v">{gpu_util}</div></div>
  <div class="card"><div class="k">显存</div><div class="v">{mem_used}/{mem_total} GB</div></div>
  <div class="card"><div class="k">GPU 温度/功耗</div><div class="v" style="font-size:13px">{temp}°C / {power}W</div></div>
  <div class="card"><div class="k">CPU</div><div class="v">{cpu_pct}%</div></div>
  <div class="card"><div class="k">内存</div><div class="v" style="font-size:14px">{mem}</div></div>
  <div class="card"><div class="k">项目磁盘</div><div class="v" style="font-size:14px">{disk}</div></div>
</div>

<div class="grid2">
  <div class="panel"><h2>打标日志（tags_v11 全量）</h2><pre class="log">{tags_log}</pre></div>
  <div class="panel"><h2>补转写日志（xm_batch）</h2><pre class="log">{xm_log}</pre></div>
</div>
</body></html>"""

LOGIN_PAGE = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>登录</title>
<style>body{{font-family:"Microsoft YaHei";background:#0f172a;color:#e2e8f0;display:flex;align-items:center;justify-content:center;height:100vh;}}
.box{{background:#1e293b;padding:30px;border-radius:12px;width:300px;}}
input{{width:100%;padding:10px;margin:10px 0;border-radius:6px;border:none;background:#0b1220;color:#fff;}}
button{{width:100%;padding:10px;background:#38bdf8;border:none;border-radius:6px;font-weight:600;cursor:pointer;}}</style></head>
<body><div class="box"><h2>监控台登录</h2>
<form method="POST" action="/login">
<input type="password" name="pwd" placeholder="请输入密码" required>
<button type="submit">进入</button>
</form></div></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    def _auth_ok(self, token=None):
        tok = token or ""
        if not tok:
            ck = self.headers.get("Cookie", "")
            m = re.search(r"auth=([a-f0-9]+)", ck)
            tok = m.group(1) if m else ""
        exp = _SESSIONS.get(tok)
        if exp and exp > time.time():
            return True
        _SESSIONS.pop(tok, None)
        return False

    def _send(self, body: bytes, code=200, ctype="text/html; charset=utf-8", cookie=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        if not self._auth_ok(parse_qs(parsed.query).get("token", [""])[0]):
            self._send(LOGIN_PAGE.encode("utf-8"))
            return
        try:
            tp = get_tags_progress()
            xm = get_xm_progress()
            ol = get_ollama()
            gpu = get_gpu() or {}
            sys_ = get_sys()
            platform_s = "Linux" if not IS_WIN else "Windows"
            tags_pct = tp["done"] * 100.0 / 673
            xm_pct = xm["done"] * 100.0 / max(xm["total"], 1)
            page = PAGE.format(
                platform=platform_s,
                tags_status="运行中" if tp["running"] else "停止",
                tags_badge="badge-run" if tp["running"] else "badge-stop",
                tags_done=tp["done"], tags_pct=min(tags_pct, 100),
                tags_avg=tp["avg_tags"], tags_vocab=tp["vocab"],
                tags_last=html.escape(tp["last"]),
                tags_log=html.escape("\n".join(tp["log"])) or "（暂无）",
                ol_model=html.escape(ol["model"]), ol_proc=ol["proc"],
                ol_ctx=ol["ctx"], ol_cpu=ol["cpu"],
                xm_status=xm["phase"] if xm["running"] else ("完成" if xm["phase"] == "done" else "停止"),
                xm_badge="badge-run" if xm["running"] else "badge-stop",
                xm_done=xm["done"], xm_total=max(xm["total"], 1), xm_pct=min(xm_pct, 100),
                xm_failed=xm["failed"], xm_phase=html.escape(str(xm["phase"])),
                xm_rate=xm["rate"],
                xm_remain=f"约 {xm['remain_h']}h" if xm["remain_h"] > 0 else "—",
                xm_dl_queue=xm["dl_queue"],
                xm_log=html.escape("\n".join(read_log_tail(XM_LOG, 12))) or "（暂无）",
                gpu_util=gpu.get("util", "—"), mem_used=gpu.get("mem_used", "—"),
                mem_total=gpu.get("mem_total", "—"), temp=gpu.get("temp", "—"),
                power=gpu.get("power", "—"),
                cpu_pct=sys_["cpu_pct"], mem=sys_["mem"], disk=sys_["disk"],
            )
            self._send(page.encode("utf-8"))
        except Exception as e:
            import traceback
            self._send((f"ERR {e}<pre>{html.escape(traceback.format_exc())}</pre>").encode(), 500)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/login":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8", "replace")
            pwd = parse_qs(body).get("pwd", [""])[0]
            if pwd == PASSWORD:
                tok = uuid.uuid4().hex
                _SESSIONS[tok] = time.time() + SESSION_TTL
                self.send_response(302)
                self.send_header("Location", "/")
                self.send_header("Set-Cookie", f"auth={tok}; Path=/; HttpOnly")
                self.end_headers()
            else:
                self._send("密码错误".encode(), 403)
            return
        self._send("not found".encode(), 404)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"监控台: http://0.0.0.0:{port}  密码: {PASSWORD}")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
