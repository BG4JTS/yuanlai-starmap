# -*- coding: utf-8 -*-
"""export_db.py — 本地数据 → Supabase 全量导入
导入: episodes(全字段) → edges(8类星图边) → pits(挖坑, source=llm)
用法:
  python export_db.py --dry-run
  python export_db.py --url https://xxx.supabase.co --key eyJ... [--episodes-only]
数据源: outputs/<key>/<key>_raw.json + analysis/tags.json + analysis/starmap.json + episodes_full_673.json
"""
import argparse, json, os, re, sys, time
from pathlib import Path

BASE = Path(r"D:\dataset\server\backup\final_backup_20260830")
LIST = BASE / "episodes_full_673.json"
OUTPUTS = BASE / "outputs"
TAGS = BASE / "analysis" / "tags.json"
STARMAP = BASE / "analysis" / "starmap.json"


def clean_title(m):
    """去期号前缀 (title), title_raw 保留原始"""
    t = m.get('title', '')
    if m.get('num'):
        return re.sub(r'^\d{1,3}[：:｜|]\s*', '', t).strip() or t
    return t


def ep_key(m):
    n = m.get("num")
    if n:
        return f"{n:03d}"
    return "X" + re.sub(r'[\\/:*?"<>|\r\n]+', "", m.get("title", "")).strip()[:10]


def load_episodes_meta():
    eps = json.load(open(LIST, encoding="utf-8"))
    return [e for e in eps if not e.get("exclude") and (e.get("audio") or e.get("trackId"))]


def build_episodes_rows(metas, tags_by_ep):
    rows = []
    for m in metas:
        key = ep_key(m)
        raw = OUTPUTS / key / f"{key}_raw.json"
        duration_sec = word_count = None
        if raw.exists():
            try:
                segs = json.loads(raw.read_text(encoding="utf-8")).get("segments", [])
                if segs:
                    duration_sec = int(segs[-1].get("end", 0))
                    word_count = sum(len(s.get("text", "")) for s in segs)
            except Exception:
                pass
        t = tags_by_ep.get(key, {})
        tid = m.get("trackId")
        xm_page = f"https://www.ximalaya.com/sound/{tid}" if tid else None
        rows.append({
            "num": m.get("num"),
            "title": clean_title(m),
            "title_raw": m.get("title", ""),
            "publish_date": None,
            "audio_url": None,
            "platforms": {"ximalaya": xm_page} if xm_page else None,
            "duration_sec": duration_sec,
            "word_count": word_count,
            "summary": t.get("summary"),
            "tags": t.get("tags") or [],
            "concepts": t.get("concepts") or [],
            "referenced": t.get("referenced") or [],
            "guests": t.get("guests") or [],
            "era": t.get("era") or [],
            "promised": t.get("promised") or [],
        })
    return rows


def rest(url, key, method, body=None, prefer="resolution=merge-duplicates,return=minimal"):
    import requests
    headers = {"Authorization": f"Bearer {key}", "apikey": key,
               "Content-Type": "application/json", "Prefer": prefer}
    if method == "GET":
        r = requests.get(url, headers=headers, timeout=60)
    else:
        r = requests.request(method, url, headers=headers, json=body, timeout=120)
    return r


def import_episodes(url, key, rows):
    """正片 upsert（on_conflict=num）；番外（num=null）按 title PATCH 增量更新"""
    import requests
    from urllib.parse import quote
    headers = {"Authorization": f"Bearer {key}", "apikey": key,
               "Content-Type": "application/json",
               "Prefer": "resolution=merge-duplicates,return=minimal"}
    main_rows = [r for r in rows if r.get("num") is not None]
    extra_rows = [r for r in rows if r.get("num") is None]
    total, patch_fail = 0, 0
    for i in range(0, len(main_rows), 100):
        batch = main_rows[i:i + 100]
        r = requests.post(f"{url}/rest/v1/episodes?on_conflict=num",
                          headers=headers, json=batch, timeout=120)
        if r.status_code >= 400:
            print(f"  episodes 批次 {i//100+1} 失败: {r.status_code} {r.text[:180]}")
        else:
            total += len(batch)
            print(f"  episodes 批次 {i//100+1}: upsert {len(batch)}")
        time.sleep(0.3)
    for r0 in extra_rows:
        t = r0.get("title", "")
        try:
            # PATCH 按 title；return=representation 判断是否有匹配行
            pr = requests.patch(f"{url}/rest/v1/episodes?title=eq.{quote(t)}",
                                headers={**headers, "Prefer": "return=representation"},
                                json={k: v for k, v in r0.items() if k != "title"}, timeout=60)
            if pr.status_code >= 400:
                patch_fail += 1
                print(f"  番外 PATCH 失败: {t[:20]} {pr.status_code} {pr.text[:100]}")
            elif not pr.json():
                # 无匹配行 → INSERT（干净表首装/清空后重导兼容）
                ir = requests.post(f"{url}/rest/v1/episodes", headers=headers,
                                   json=[r0], timeout=60)
                if ir.status_code >= 400:
                    patch_fail += 1
                    print(f"  番外 INSERT 失败: {t[:20]} {ir.status_code} {ir.text[:120]}")
                else:
                    total += 1
            else:
                total += 1
        except Exception:
            patch_fail += 1
    print(f"episodes 导入完成: {total}（正片 upsert {len(main_rows)} + 番外 patch {len(extra_rows)-patch_fail}）")
    return total


def build_key_id_map(url, key):
    """ep key -> episodes.id（正片按 num, 番外按 title 匹配）"""
    r = rest(f"{url}/rest/v1/episodes?select=id,num,title&order=id.asc", key, "GET")
    if r.status_code >= 400:
        raise SystemExit(f"查询 episodes 失败: {r.status_code} {r.text[:180]}")
    rows = r.json()
    by_num = {row["num"]: row["id"] for row in rows if row.get("num") is not None}
    by_title = {row["title"]: row["id"] for row in rows}
    metas = load_episodes_meta()
    key2id = {}
    for m in metas:
        k = ep_key(m)
        if m.get("num") is not None and m["num"] in by_num:
            key2id[k] = by_num[m["num"]]
        elif m.get("title") in by_title:
            key2id[k] = by_title[m["title"]]
    print(f"key->id 映射: {len(key2id)} / {len(metas)}")
    return key2id


def build_edge_rows(starmap, key2id):
    rows, skipped = [], 0
    seen = set()
    for e in starmap.get("edges", []):
        a, b, kind = key2id.get(e.get("from")), key2id.get(e.get("to")), e.get("kind")
        if not a or not b or a == b:
            skipped += 1
            continue
        pk = (a, b, kind)
        if pk in seen:
            skipped += 1
            continue
        seen.add(pk)
        rows.append({"ep_a": a, "ep_b": b, "kind": kind,
                     "weight": e.get("weight"), "evidence": (e.get("note") or "")[:200]})
    return rows, skipped


def import_edges(url, key, edge_rows):
    total = 0
    for i in range(0, len(edge_rows), 200):
        batch = edge_rows[i:i + 200]
        r = rest(f"{url}/rest/v1/edges", key, "POST", body=batch,
                 prefer="resolution=merge-duplicates,return=minimal")
        if r.status_code >= 400:
            print(f"  edges 批次 {i//200+1} 失败: {r.status_code} {r.text[:180]}")
        else:
            total += len(batch)
            print(f"  edges 批次 {i//200+1}: +{len(batch)}")
        time.sleep(0.2)
    print(f"edges 导入完成: {total}")
    return total


def build_pit_rows(starmap, key2id):
    """pit 边 → pits（挖坑记录, 已填状态）"""
    rows, skipped = [], 0
    seen = set()
    for e in starmap.get("edges", []):
        if e.get("kind") != "pit":
            continue
        a, b = key2id.get(e.get("from")), key2id.get(e.get("to"))
        if not a or not b or a == b:
            skipped += 1
            continue
        phrase = (e.get("note") or "").replace("填坑:", "").strip() or "未命名坑"
        pk = (a, phrase)
        if pk in seen:
            skipped += 1
            continue
        seen.add(pk)
        rows.append({"episode_id": a, "content": phrase, "status": "filled",
                     "source": "llm", "filled_by": b})
    return rows, skipped


def import_pits(url, key, pit_rows):
    total = 0
    for i in range(0, len(pit_rows), 100):
        batch = pit_rows[i:i + 100]
        r = rest(f"{url}/rest/v1/pits", key, "POST", body=batch,
                 prefer="resolution=merge-duplicates,return=minimal")
        if r.status_code >= 400:
            print(f"  pits 批次 {i//100+1} 失败: {r.status_code} {r.text[:180]}")
        else:
            total += len(batch)
            print(f"  pits 批次 {i//100+1}: +{len(batch)}")
        time.sleep(0.2)
    print(f"pits 导入完成: {total}")
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("SUPABASE_URL", "https://zxcuxbwsmoycwiwnhvps.supabase.co"))
    ap.add_argument("--key", default=os.environ.get("SUPABASE_SERVICE_KEY", ""))
    ap.add_argument("--episodes-only", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not args.key:
        raise SystemExit("缺 --key（service_role）")

    metas = load_episodes_meta()
    tags = json.load(open(TAGS, encoding="utf-8"))
    tags_by_ep = {x.get("ep"): x for x in tags if isinstance(x, dict)}
    rows = build_episodes_rows(metas, tags_by_ep)
    print(f"episodes 目标: {len(rows)} 行")

    if args.dry_run:
        for r in rows[:3]:
            print("  样例:", json.dumps(r, ensure_ascii=False)[:160])
        return

    import_episodes(args.url, args.key, rows)
    if args.episodes_only:
        return

    key2id = build_key_id_map(args.url, args.key)
    starmap = json.load(open(STARMAP, encoding="utf-8"))
    edge_rows, sk1 = build_edge_rows(starmap, key2id)
    print(f"edges: {len(edge_rows)} 行 (跳过 {sk1})")
    import_edges(args.url, args.key, edge_rows)

    pit_rows, sk2 = build_pit_rows(starmap, key2id)
    print(f"pits: {len(pit_rows)} 行 (跳过 {sk2})")
    import_pits(args.url, args.key, pit_rows)
    print("ALL_IMPORTED")


if __name__ == "__main__":
    main()
