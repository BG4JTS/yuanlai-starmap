# -*- coding: utf-8 -*-
"""xm_refill.py — 喜马拉雅源补齐 lizhi 截断期
1) mobile API 分页拉专辑 246622 全量 track
2) 标题匹配期号 -> trackId 映射
3) 对 funasr_progress.json 的 failures + outputs 缺失期做映射覆盖率检查
用法: python3 xm_refill.py --probe   # 只做映射检查
      python3 xm_refill.py --fill    # 下载+转写补齐
"""
import argparse, json, os, re, subprocess, sys, time, urllib.request

BASE = '/hy-tmp/whisperx_project'
ALBUM_ID = 246622
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
PROGRESS = os.path.join(BASE, 'funasr_progress.json')
OUTPUTS = os.path.join(BASE, 'outputs')
AUDIO_DIR = '/hy-tmp/audio_tmp'
PY = '/hy-tmp/miniconda/envs/funasr/bin/python'
YTDLP = '/hy-tmp/miniconda/envs/funasr/bin/yt-dlp'


def fetch_tracks():
    """分页拉专辑全量 track"""
    tracks, page = [], 1
    while True:
        url = (f'https://mobile.ximalaya.com/mobile/v1/album/track?albumId={ALBUM_ID}'
               f'&isAsc=true&pageId={page}&pageSize=100')
        req = urllib.request.Request(url, headers={'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read().decode('utf-8'))
        lst = (d.get('data') or {}).get('list') or []
        if not lst:
            break
        tracks.extend(lst)
        print(f'[list] page {page}: +{len(lst)} (累计 {len(tracks)})', flush=True)
        if len(lst) < 100:
            break
        page += 1
        time.sleep(1)
    return tracks


def parse_epnum(title):
    m = re.match(r'^(\d{1,3})[：:｜|]', (title or '').strip())
    return int(m.group(1)) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--probe', action='store_true')
    ap.add_argument('--fill', action='store_true')
    args = ap.parse_args()

    tracks = fetch_tracks()
    print(f'[list] 全量 {len(tracks)} tracks', flush=True)
    epmap = {}
    for t in tracks:
        n = parse_epnum(t.get('title', ''))
        if n and n not in epmap:
            epmap[n] = t
    print(f'[map] 期号匹配: {len(epmap)} 期（范围 {min(epmap)}-{max(epmap)}）', flush=True)
    json.dump({str(k): {'trackId': v['trackId'], 'title': v['title'], 'duration': v['duration']}
               for k, v in epmap.items()}, open(os.path.join(BASE, 'xm_epmap.json'), 'w'), ensure_ascii=False)

    # 需要补齐的期：failures + outputs 缺失
    need = set()
    prog = json.load(open(PROGRESS, encoding='utf-8'))
    for f in prog.get('failures', []):
        m = re.match(r'^(\d+)$', str(f.get('num', '')))
        if m:
            need.add(int(m.group(1)))
    for e in json.load(open(os.path.join(BASE, 'episodes_list.json'), encoding='utf-8')):
        n = e.get('num')
        if n and not e.get('exclude') and e.get('audio'):
            if not os.path.exists(os.path.join(OUTPUTS, str(n), f'{n}_raw.json')):
                need.add(n)
    print(f'[need] 待补齐期数: {len(need)} -> {sorted(need)[:30]}', flush=True)

    covered = sorted(n for n in need if n in epmap)
    missing = sorted(n for n in need if n not in epmap)
    print(f'[cover] 专辑可覆盖: {len(covered)} 期 | 专辑无此期: {len(missing)} 期 {missing[:20]}', flush=True)

    if args.probe or not args.fill:
        print('[probe] 仅探测，不下载', flush=True)
        return
    # fill: 逐期 yt-dlp 下载 + 转写
    sys.path.insert(0, BASE)
    from batch_funasr import get_model, transcribe, ffprobe_duration, AUDIO_DIR as AD
    os.makedirs(AD, exist_ok=True)
    model, post = get_model()
    eps_list = {e['num']: e for e in json.load(open(os.path.join(BASE, 'episodes_list.json'), encoding='utf-8'))
                if e.get('num')}
    ok, fail = 0, 0
    for n in covered:
        t = epmap[n]
        key = str(n)
        out_json = os.path.join(OUTPUTS, key, f'{key}_raw.json')
        if os.path.exists(out_json):
            continue
        audio = os.path.join(AD, f'{key}.mp3')
        try:
            if not (os.path.exists(audio) and ffprobe_duration(audio)):
                print(f'[dl] {n}: sound/{t["trackId"]} ({t["title"][:30]})', flush=True)
                subprocess.run([YTDLP, '-q', '--no-warnings', '-o', audio,
                                f'https://www.ximalaya.com/sound/{t["trackId"]}'],
                               check=True, timeout=900)
            dur = ffprobe_duration(audio) or 0
            expect = t.get('duration') or 0
            if expect and dur < expect * 0.9:
                raise RuntimeError(f'时长不足: {dur:.0f}s < {expect}s')
            ep = eps_list.get(n, {'num': n, 'title': t['title']})
            path, nseg, d, el = transcribe(model, ep, OUTPUTS, post)
            ok += 1
            print(f'[ok] {n}: {nseg}段 {d/60:.1f}min ({el:.0f}s)', flush=True)
        except Exception as e:
            fail += 1
            print(f'[fail] {n}: {type(e).__name__}: {str(e)[:120]}', flush=True)
        time.sleep(2)
    print(f'[done] 补齐完成: 成功 {ok} 失败 {fail}', flush=True)


if __name__ == '__main__':
    main()
