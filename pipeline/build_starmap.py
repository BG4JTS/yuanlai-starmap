# -*- coding: utf-8 -*-
"""
节目星图构建：把《原来是这样》各期节目建成"面向人看"的关联星图。

节点 = 每期节目（大小=时长，颜色=专题簇，hover=摘要/标签，点击看详情）
边   = 可解释的关联（类型标注 + 证据）：
    - series   同系列（如 546/547 冬眠舱上·下）
    - ref      文稿互相提及（"上期我们聊过…"）
    - tag      共享主题标签（LLM 打标）
    - semantic 语义相似（BGE 嵌入余弦；未装 BGE 时用 TF-IDF 兜底）
    - concept  共享核心概念（LLM 抽取）

输出: analysis/starmap.html —— 自包含单文件（内联 vis-network，无需外网即可打开）

用法:
    python build_starmap.py [--out analysis/starmap.html]
                            [--tags analysis/tags.json]
                            [--threshold 0.50]
                            [--no-bge]
"""
import argparse
import json
import re
from pathlib import Path

import config


# ============ 每期文稿发现 ============
class Episode:
    def __init__(self, ep, title, text, duration, path, series="", full_text=""):
        self.ep = ep
        self.title = title
        self.text = text
        self.full_text = full_text
        self.duration = duration
        self.path = path
        self.series = series
        self.tags = []
        self.concepts = []
        self.summary = ""
        self.referenced = []
        self.guests = []
        self.era = []
        self.promised = []


def pick_final_doc(ep_dir):
    """每期选代表文稿：_final.txt > _final.json > 其他 txt > _raw.json > 其他 json。"""
    cands = list(ep_dir.glob("*.txt")) + list(ep_dir.glob("*.json"))
    if not cands:
        return None
    def score(c):
        n = c.name
        if n.endswith("_final.txt"):
            return 0
        if n.endswith("_final.json"):
            return 1
        if n.endswith(".txt"):
            return 2
        if n.endswith("_raw.json") or n.endswith("_with_switches.json"):
            return 4
        return 3
    return min(cands, key=score)


def title_from_filename(name):
    m = re.match(r"^(\d+)[:：]?\s*(.*?)(_16k|_final|_refined|_split|_fixed|_raw|_with_switches)*\.(txt|json)$", name)
    if m:
        return m.group(1), m.group(2).strip()
    digits = "".join(ch for ch in name if ch.isdigit())
    return digits or name, ""


SERIES_RE = re.compile(r"[（(](上|下|中)[)）]")


def series_key(title, fname):
    m = SERIES_RE.search(fname) or SERIES_RE.search(title)
    if m:
        return SERIES_RE.sub("", title).strip(" ），(。")
    return ""


def parse_meta(doc_path):
    """从文稿解析 时长 + 纯文本。支持 txt（按行）与 json（segments）。"""
    if doc_path.suffix == ".json":
        data = json.loads(doc_path.read_text(encoding="utf-8"))
        segs = data.get("segments", [])
        dur = segs[-1]["end"] if segs else 0.0
        body = "\n".join(str(s.get("text", "")) for s in segs)
        return dur, body
    pat = re.compile(r"\[(\d+\.\d+)s\s*->\s*(\d+\.\d+)s\]")
    dur, body = 0.0, []
    for line in doc_path.read_text(encoding="utf-8").splitlines():
        m = pat.search(line)
        if m:
            dur = float(m.group(2))
            body.append(re.sub(r"^\[\d+\.\d+s\s*->\s*\d+\.\d+s\]\s*[^:]*:\s*", "", line))
        else:
            body.append(line)
    return dur, "\n".join(body)


COMMON_WORDS = {"中国", "时间", "植物", "动物", "现在", "这个", "一个", "东西", "时候",
                "方式", "问题", "感觉", "开始", "大家", "我们", "真的", "其实", "就是",
                "因为", "所以", "然后", "如果", "可能", "但是", "已经", "知道", "觉得",
                "发现", "国家", "历史", "现代", "古代", "欧洲", "世界", "比较", "很多",
                "一种", "这样", "怎么", "为什么", "什么", "不是", "还有", "可以"}


def make_title(ep, title, text):
    if title:
        return title
    try:
        import jieba.analyse
        kws = jieba.analyse.textrank(text[:8000], topK=8, withWeight=False)
        kws = [w for w in kws if len(w) >= 2 and w not in COMMON_WORDS][:3]
        if kws:
            return "、".join(kws)
    except Exception:
        pass
    return f"第{ep}期"


def discover():
    # 白名单: episodes_list.json 的有效期（正片001格式 + 番外X前缀）, 防多余目录污染星图
    valid = None
    try:
        lst_path = config.OUTPUT_DIR.parent / "episodes_list.json"
        if not lst_path.exists():
            lst_path = Path(__file__).parent / "episodes_list.json"
        lst = json.loads(lst_path.read_text(encoding="utf-8"))
        valid = set()
        for e in lst:
            if e.get("exclude") or not e.get("audio"):
                continue
            if e.get("num"):
                valid.add(f"{e['num']:03d}")
            else:
                t = e.get("title", "")
                valid.add("X" + re.sub(r'[\\/:*?"<>|\r\n]+', "", t).strip()[:10])
    except Exception as exc:
        print(f"  [警告] 白名单加载失败({exc}), 不做过滤")
    eps = []
    for ep_dir in sorted(config.OUTPUT_DIR.iterdir()):
        if not ep_dir.is_dir():
            continue
        if valid is not None and ep_dir.name not in valid:
            continue
        doc = pick_final_doc(ep_dir)
        if not doc:
            continue
        ep, title = title_from_filename(doc.name)
        dur, body = parse_meta(doc)
        e = Episode(ep=ep, title=make_title(ep, title, body), text=body,
                    duration=dur, path=doc, full_text=doc.read_text(encoding="utf-8"))
        e.series = series_key(title, doc.name)
        eps.append(e)
        print(f"  [发现] {ep}  {e.title}  {dur/60:.1f}min  {len(body)}字"
              + (f"  [系列:{e.series}]" if e.series else ""))
    return eps


# ============ 引用检测（启发式） ============
REF_PHRASES = ["上期", "上集", "上一期", "上次", "上回", "之前那期", "上次我们"]


def title_keywords(title):
    t = SERIES_RE.sub(" ", title)
    t = re.sub(r"[，。？?!！：:、\"\"''（）()\s]+", " ", t)
    return [w for w in t.split(" ") if len(w) >= 2 and w not in COMMON_WORDS][:3]


def detect_refs(eps):
    refs = []
    topics = {e.ep: title_keywords(e.title) for e in eps}
    for e in eps:
        for phrase in REF_PHRASES:
            for m in re.finditer(re.escape(phrase), e.text):
                ctx = e.text[max(0, m.start() - 5):m.start() + 35]
                for other in eps:
                    if other.ep == e.ep:
                        continue
                    if any(kw and kw in ctx for kw in topics[other.ep]):
                        refs.append((e.ep, other.ep, ctx.strip()[:50]))
                        break
    seen, uniq = set(), []
    for a, b, ctx in refs:
        if (a, b) not in seen:
            seen.add((a, b))
            uniq.append((a, b, ctx))
    return uniq


# ============ 语义相似度 ============
def _sim_from_emb(eps, emb):
    import numpy as np
    norm = emb / np.linalg.norm(emb, axis=1, keepdims=True)
    sim = norm @ norm.T
    return {(eps[i].ep, eps[j].ep): float(sim[i][j])
            for i in range(len(eps)) for j in range(i + 1, len(eps))}


def similarity_matrix(eps, use_bge=True):
    if use_bge:
        docs = [f"{e.title}。{e.summary or ''} {e.text[:800]}" for e in eps]
        try:
            from FlagEmbedding import BGEM3FlagModel
            print("  [相似度] 尝试 BGE-M3 ...")
            model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True, device="cuda")
            emb = model.encode(docs, max_length=512)["dense_vecs"]
            print("  [相似度] BGE-M3 完成")
            return _sim_from_emb(eps, emb)
        except Exception as ex:
            print(f"  [相似度] bge-m3 失败({str(ex)[:70]})")
        try:
            from sentence_transformers import SentenceTransformer
            print("  [相似度] 尝试 bge-small-zh-v1.5 ...")
            model = SentenceTransformer("BAAI/bge-small-zh-v1.5", device="cuda")
            emb = model.encode(docs, normalize_embeddings=True, batch_size=4)
            print("  [相似度] bge-small 完成")
            return _sim_from_emb(eps, emb)
        except Exception as ex:
            print(f"  [相似度] bge-small 失败({str(ex)[:70]})")
        print("  [相似度] 回退 TF-IDF")
    import jieba
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    docs = [" ".join(jieba.cut(e.text[:6000])) for e in eps]
    X = TfidfVectorizer(max_features=20000).fit_transform(docs)
    sim = cosine_similarity(X)
    return {(eps[i].ep, eps[j].ep): float(sim[i][j])
            for i in range(len(eps)) for j in range(i + 1, len(eps))}


# ============ 边构建 ============
EDGE_COLORS = {"series": "#e15759", "ref": "#edc948", "tag": "#59a14f",
               "semantic": "#4e79a7", "concept": "#b07aa1",
               "pit": "#ff7f0e", "guest": "#17becf", "era": "#8c564b"}
EDGE_CN = {"series": "同系列", "ref": "互相引用", "tag": "共享标签",
           "semantic": "语义相似", "concept": "共享概念",
           "pit": "挖坑-填坑", "guest": "同嘉宾", "era": "同年代"}
PALETTE = ["#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f",
           "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac"]


def build_edges(eps, sims, refs, threshold, top_k=None):
    edges, sem_cands = [], []
    for i in range(len(eps)):
        for j in range(i + 1, len(eps)):
            a, b = eps[i], eps[j]
            if a.series and a.series == b.series:
                edges.append({"from": a.ep, "to": b.ep, "kind": "series",
                              "weight": 1.0, "note": "同系列"})
                continue
            shared_c = set(a.concepts) & set(b.concepts)
            if len(shared_c) >= 2:
                edges.append({"from": a.ep, "to": b.ep, "kind": "concept", "weight": 0.55,
                              "note": f"共享概念:{','.join(list(shared_c)[:3])}"})
                continue
            shared_t = set(a.tags) & set(b.tags)
            if shared_t:
                edges.append({"from": a.ep, "to": b.ep, "kind": "tag",
                              "weight": min(1.0, 0.4 + 0.1 * len(shared_t)),
                              "note": f"共享标签:{','.join(list(shared_t)[:3])}"})
                continue
            shared_g = set(a.guests) & set(b.guests)
            if shared_g:
                edges.append({"from": a.ep, "to": b.ep, "kind": "guest", "weight": 0.6,
                              "note": f"同嘉宾:{','.join(list(shared_g)[:2])}"})
                continue
            shared_e = set(a.era) & set(b.era)
            if shared_e:
                edges.append({"from": a.ep, "to": b.ep, "kind": "era", "weight": 0.5,
                              "note": f"同年代:{','.join(list(shared_e)[:2])}"})
                continue
            sim = sims.get((a.ep, b.ep), sims.get((b.ep, a.ep), 0))
            if sim >= threshold:
                sem_cands.append({"from": a.ep, "to": b.ep, "weight": round(sim, 3), "sim": sim})
    sem_cands.sort(key=lambda x: -x["sim"])
    top_k = max(4, len(eps)) if top_k is None else top_k
    for c in sem_cands[:top_k]:
        edges.append({"from": c["from"], "to": c["to"], "kind": "semantic",
                      "weight": c["weight"], "note": f"语义相似:{c['weight']:.2f}"})
    have = {(e["from"], e["to"]) for e in edges}
    for x, y, ctx in refs:
        if (x, y) not in have and (y, x) not in have:
            edges.append({"from": x, "to": y, "kind": "ref", "weight": 0.9,
                          "note": "互相引用", "evidence": ctx})
    # pit 挖坑-填坑边（方向性: a 挖的坑在 b 填; 高价值独立边, 允许与已有边共存）
    have_pit = set()
    for a in eps:
        for phrase in (a.promised or []):
            if len(phrase) < 2:
                continue
            kws = [w for w in re.split(r"[/，,\s]+", phrase) if len(w) >= 2]
            for b in eps:
                if b.ep == a.ep:
                    continue
                target = " ".join(b.tags + b.concepts + b.referenced + [b.title])
                if any(kw in target for kw in kws):
                    key = (a.ep, b.ep)
                    if key not in have_pit:
                        have_pit.add(key)
                        edges.append({"from": a.ep, "to": b.ep, "kind": "pit",
                                      "weight": 1.0, "note": f"填坑:{phrase}"})
                    break  # 每个坑只连第一个匹配期
    for e in edges:
        print(f"  [边] {e['from']}-{e['to']}  {e['kind']}  w={e['weight']}  {e.get('note','')}")
    return edges


# ============ 自包含 HTML 渲染 ============
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>《原来是这样》节目星图</title>
<style>
  body {{ font-family: "Microsoft YaHei", "PingFang SC", sans-serif; margin: 0; background: #f7f8fa; }}
  #header {{ padding: 14px 24px; background: #1f2d3d; color: #fff; }}
  #header h1 {{ margin: 0; font-size: 20px; }}
  #header p {{ margin: 4px 0 0; font-size: 12px; color: #9fb3c8; }}
  #legend {{ padding: 8px 24px; font-size: 12px; background: #fff; border-bottom: 1px solid #e5e9ef; }}
  #legend span {{ display: inline-block; margin-right: 18px; }}
  .dot {{ display: inline-block; width: 12px; height: 4px; margin-right: 4px; vertical-align: middle; border-radius: 2px; }}
  #wrap {{ display: flex; height: calc(100vh - 110px); }}
  #mynetwork {{ flex: 1; background: #fff; }}
  #detail {{ width: 320px; background: #fff; border-left: 1px solid #e5e9ef; overflow-y: auto; padding: 14px; font-size: 13px; }}
  #detail h3 {{ margin: 0 0 8px; font-size: 15px; }}
  #detail .row {{ margin: 4px 0; }}
  #detail .label {{ color: #888; margin-right: 6px; }}
  #detail .tags span {{ display: inline-block; background: #eef3f8; color: #2c5f8a; border-radius: 3px; padding: 1px 6px; margin: 2px 3px 2px 0; font-size: 12px; }}
  #hint {{ color: #999; font-size: 12px; }}
</style>
</head>
<body>
<div id="header">
  <h1>《原来是这样》节目星图</h1>
  <p>节点 = 每期节目（大小=时长 · 颜色=专题簇）｜ 边 = 关联类型（悬停看证据，点击节点看详情）｜ 可拖拽、缩放</p>
</div>
<div id="legend">
  <span><i class="dot" style="background:#e15759"></i>同系列</span>
  <span><i class="dot" style="background:#edc948"></i>互相引用</span>
  <span><i class="dot" style="background:#59a14f"></i>共享标签</span>
  <span><i class="dot" style="background:#4e79a7"></i>语义相似</span>
  <span><i class="dot" style="background:#b07aa1"></i>共享概念</span>
</div>
<div id="wrap">
  <div id="mynetwork"></div>
  <div id="detail">
    <div id="hint">点击左侧节点查看节目详情</div>
  </div>
</div>
<script>
__VIS_JS__
</script>
<script>
const nodes = new vis.DataSet(__NODES__);
const edges = new vis.DataSet(__EDGES__);
const meta = __META__;
const container = document.getElementById('mynetwork');
const data = {{ nodes: nodes, edges: edges }};
const options = {{
  physics: {{ barnesHut: {{ gravitationalConstant: -28000, centralGravity: 0.25 }}, minVelocity: 0.7 }},
  interaction: {{ hover: true, tooltipDelay: 120, navigationButtons: true, keyboard: true }},
  nodes: {{ font: {{ size: 13, face: 'Microsoft YaHei' }}, borderWidth: 1, shadow: true }},
  edges: {{ font: {{ size: 9, face: 'Microsoft YaHei', align: 'middle' }}, smooth: {{ type: 'continuous' }} }},
}};
const network = new vis.Network(container, data, options);
function esc(s) {{ return String(s == null ? '' : s).replace(/&/g,'&amp;').replace(/</g,'&lt;'); }}
network.on('click', function (params) {{
  const d = document.getElementById('detail');
  if (!params.nodes.length) {{ d.innerHTML = '<div id="hint">点击左侧节点查看节目详情</div>'; return; }}
  const m = meta[params.nodes[0]];
  if (!m) return;
  const tags = (m.tags || []).map(t => '<span>' + esc(t) + '</span>').join('');
  d.innerHTML =
    '<h3>' + esc(m.ep) + ' · ' + esc(m.title) + '</h3>' +
    '<div class="row"><span class="label">时长</span>' + (m.duration/60).toFixed(1) + ' 分钟</div>' +
    (m.series ? '<div class="row"><span class="label">系列</span>' + esc(m.series) + '</div>' : '') +
    '<div class="row"><span class="label">标签</span></div><div class="tags">' + (tags || '—') + '</div>' +
    (m.concepts && m.concepts.length ? '<div class="row"><span class="label">概念</span>' + esc(m.concepts.slice(0,6).join('、')) + '</div>' : '') +
    (m.summary ? '<div class="row" style="margin-top:8px;color:#555">' + esc(m.summary) + '</div>' : '');
}});
</script>
</body>
</html>
"""


def render_html(eps, edges, vis_js: str, out_html: Path, colors=None):
    nodes = []
    for e in eps:
        size = 14 + min(46, e.duration / 55)
        color = (colors or {}).get(e.ep, "#4e79a7")
        tip = (f"<b>{e.ep} {e.title}</b><br>{e.duration/60:.1f} 分钟"
               + (f"<br>系列:{e.series}" if e.series else "")
               + f"<br>标签:{'、'.join(e.tags[:6]) or '—'}"
               + (f"<br><i>{e.summary[:150]}</i>" if e.summary else ""))
        nodes.append({"id": e.ep, "label": f"{e.ep} {e.title[:12]}",
                      "value": size, "size": size, "color": color,
                      "title": tip, "shape": "dot"})
    js_nodes = json.dumps(nodes, ensure_ascii=False)
    js_edges = json.dumps([{"from": e["from"], "to": e["to"],
                            "color": EDGE_COLORS[e["kind"]],
                            "width": 1 + 4 * e["weight"],
                            "title": f"{EDGE_CN[e['kind']]}: {e.get('note','')}",
                            "label": EDGE_CN[e["kind"]]} for e in edges],
                          ensure_ascii=False)
    js_meta = {e.ep: {"ep": e.ep, "title": e.title, "duration": round(e.duration, 1),
                      "series": e.series, "tags": e.tags, "concepts": e.concepts,
                      "summary": e.summary} for e in eps}
    html = (HTML_TEMPLATE
            .replace("__VIS_JS__", vis_js)
            .replace("__NODES__", js_nodes)
            .replace("__EDGES__", js_edges)
            .replace("__META__", json.dumps(js_meta, ensure_ascii=False)))
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(html, encoding="utf-8")
    print(f"[星图] 已生成自包含 HTML: {out_html}  ({(out_html.stat().st_size/1024):.0f} KB, "
          f"{len(eps)} 节点, {len(edges)} 边)")

    out_json = out_html.with_suffix(".json")
    out_json.write_text(json.dumps({
        "nodes": [{"id": e.ep, "title": e.title, "duration": round(e.duration, 1),
                   "series": e.series, "tags": e.tags, "concepts": e.concepts,
                   "summary": e.summary, "referenced": e.referenced,
                   "text": e.text[:3000]} for e in eps],
        "edges": edges,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[星图] 数据导出: {out_json}")


# ============ 主流程 ============
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="analysis/starmap.html")
    ap.add_argument("--tags", default="analysis/tags.json")
    ap.add_argument("--threshold", type=float, default=0.50)
    ap.add_argument("--no-bge", action="store_true")
    args = ap.parse_args()

    config.ensure_dirs()
    print("[星图] 扫描节目文稿 ...")
    eps = discover()
    if not eps:
        print("未发现任何文稿")
        return

    tags_path = config.BASE_DIR / args.tags
    if tags_path.exists():
        by_ep = {d.get("ep"): d for d in json.loads(tags_path.read_text(encoding="utf-8"))}
        for e in eps:
            d = by_ep.get(e.ep)
            if d:
                e.tags = d.get("tags", [])
                e.concepts = d.get("concepts", [])
                e.summary = d.get("summary", "")
                e.referenced = d.get("referenced", [])
                e.guests = d.get("guests", []) or []
                e.era = d.get("era", []) or []
                e.promised = d.get("promised", []) or []
    else:
        print(f"[星图] 提示: {args.tags} 不存在，仅用启发式(系列/引用) + 语义相似")

    sims = similarity_matrix(eps, use_bge=not args.no_bge)
    refs = detect_refs(eps)
    edges = build_edges(eps, sims, refs, args.threshold)

    colors = {}
    used = 0
    for s, members in sorted({e.series: [x.ep for x in eps if x.series == e.series]
                              for e in eps if e.series}.items()):
        c = PALETTE[used % len(PALETTE)]
        used += 1
        for m in members:
            colors[m] = c
    for i, e in enumerate(eps):
        colors.setdefault(e.ep, PALETTE[(used + i) % len(PALETTE)])

    vis_js_path = config.BASE_DIR / "assets" / "vis-network.min.js"
    if vis_js_path.exists():
        vis_js = f"<script>\n{vis_js_path.read_text(encoding='utf-8')}\n</script>"
    else:
        print("[星图] 警告: 未找到 assets/vis-network.min.js，改用 CDN 引用")
        vis_js = ('<script src="https://cdn.jsdelivr.net/npm/vis-network@9.1.2/dist/'
                  'vis-network.min.js"></script>')

    render_html(eps, edges, vis_js, config.BASE_DIR / args.out, colors)


if __name__ == "__main__":
    main()
