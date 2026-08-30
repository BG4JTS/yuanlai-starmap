# -*- coding: utf-8 -*-
"""batch_funasr.py — FunASR 批量转写《原来是这样》
流水线: 下载(8线程) -> FunASR(SenseVoice+VAD+CAM++) -> outputs/<num>/<num>_raw.json
用法:
  python3 batch_funasr.py --episodes 1,6,554 --out-dir funasr_test   # PoC
  python3 batch_funasr.py --episodes all                             # 全量(覆盖outputs)
"""
import argparse, json, os, re, sys, time, threading, queue, subprocess, urllib.request, traceback

BASE = os.path.dirname(os.path.abspath(__file__))
LIST_FILE = os.path.join(BASE, 'episodes_list.json')
AUDIO_DIR = '/hy-tmp/audio_tmp'
PROGRESS_FILE = os.path.join(BASE, 'funasr_progress.json')
DL_WORKERS = 20
ASR_WORKERS = 8  # GPU/CPU 多进程并行转写（10 会 OOM: 24GB 显存上限）
_HEADERS = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
            "Referer": "https://www.lizhi.fm/", "Accept": "*/*"}


def ffprobe_duration(path):
    try:
        r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                            '-of', 'json', path], capture_output=True, timeout=60)
        return float(json.loads(r.stdout)['format']['duration'])
    except Exception:
        return None

_progress = {}
_plock = threading.Lock()


def save_progress():
    with _plock:
        tmp = PROGRESS_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(_progress, f, ensure_ascii=False)
        os.replace(tmp, PROGRESS_FILE)


def update_progress(**kw):
    with _plock:
        _progress.update(kw)
    save_progress()


def ep_key(ep):
    """期号 key：正片用数字，番外用 X+标题前缀（与 batch_ingest 一致）"""
    n = ep.get('num')
    if n:
        return str(n)
    t = ep.get('title', '')
    return 'X' + re.sub(r'[\\/:*?"<>|\r\n]+', '', t).strip()[:10]


def load_episodes(sel):
    with open(LIST_FILE, encoding='utf-8') as f:
        eps = json.load(f)
    valid = [e for e in eps if not e.get('exclude') and e.get('audio') and e.get('num')]
    extra = [e for e in eps if not e.get('exclude') and e.get('audio') and not e.get('num')]
    for e in extra:
        e['_key'] = ep_key(e)
    valid = sorted(valid, key=lambda e: e['num']) + sorted(extra, key=lambda e: e['_key'])
    if sel == 'all':
        return valid
    nums = {x.strip() for x in sel.split(',')}
    out = []
    for e in valid:
        k = e.get('_key') or str(e['num'])
        if k in nums or str(e.get('num')) in nums:
            out.append(e)
    return out


def download_one(ep):
    import requests
    num = ep.get('_key') or str(ep['num'])
    url = ep['audio']
    out = os.path.join(AUDIO_DIR, f'{num}.mp3')
    if os.path.exists(out) and os.path.getsize(out) > 1e6:
        dur = ffprobe_duration(out)
        if dur is None or dur >= 900:  # 已下载且完整
            return num, 'cached'
        os.remove(out)
    for attempt in range(3):
        try:
            r = requests.get(url, headers=_HEADERS, timeout=120, stream=True, allow_redirects=True)
            if r.status_code != 200:
                if attempt == 2:
                    return num, f'http_{r.status_code}'
                continue
            with open(out, 'wb') as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
            size = os.path.getsize(out)
            if size < 1e6:
                os.remove(out)
                if attempt == 2:
                    return num, f'too_small:{size}B'
                continue
            dur = ffprobe_duration(out)
            if dur is not None and dur < 900:  # <15min = 试听截断
                os.remove(out)
                if attempt == 2:
                    return num, f'truncated:{dur:.0f}s'
                continue
            return num, f'ok_{dur/60:.0f}min' if dur else 'ok'
        except Exception as e:
            if attempt == 2:
                return num, f'fail:{type(e).__name__}'
            time.sleep(3 * (attempt + 1))
    return num, 'fail'


def get_model():
    from funasr import AutoModel
    from funasr.utils.postprocess_utils import rich_transcription_postprocess
    return AutoModel(model="iic/SenseVoiceSmall", vad_model="fsmn-vad",
                     spk_model="cam++", device="cuda"), rich_transcription_postprocess


def transcribe(model, ep, out_dir, post):
    num = ep.get('_key') or str(ep['num'])
    audio = os.path.join(AUDIO_DIR, f'{num}.mp3')
    out_dir_ep = os.path.join(out_dir, str(num))
    os.makedirs(out_dir_ep, exist_ok=True)
    out_json = os.path.join(out_dir_ep, f'{num}_raw.json')

    t0 = time.time()
    res = model.generate(input=audio, batch_size_s=300)
    sentence_info = res[0].get('sentence_info') or []
    segs = [{'start': s['start'] / 1000.0, 'end': s['end'] / 1000.0,
             'text': post(s['sentence']), 'spk': s.get('spk', -1)} for s in sentence_info]
    duration = segs[-1]['end'] if segs else 0.0
    doc = {'num': num, 'title': ep.get('title', ''), 'date': ep.get('date', ''),
           'model': 'SenseVoiceSmall+fsmn-vad+cam++', 'duration': round(duration, 2),
           'n_segments': len(segs), 'segments': segs}
    with open(out_json, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False)
    elapsed = time.time() - t0
    try:
        os.remove(audio)  # 磁盘防护: 转完即删
    except OSError:
        pass
    return out_json, len(segs), duration, elapsed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--episodes', default='all', help="all 或 1,6,554")
    ap.add_argument('--out-dir', default=os.path.join(BASE, 'outputs'))
    ap.add_argument('--skip-existing', action='store_true',
                    help='跳过已有 raw.json 的期数（默认不跳过，全量重转）')
    args = ap.parse_args()

    eps = load_episodes(args.episodes)
    total = len(eps)
    print(f'[plan] {total} 期, out={args.out_dir}', flush=True)
    os.makedirs(AUDIO_DIR, exist_ok=True)

    # 跳过已完成（仅认 FunASR 产物; 旧 faster-whisper 的 raw.json 不算, 需重转）
    def funasr_done(p):
        try:
            with open(p, encoding='utf-8') as f:
                return 'SenseVoiceSmall' in (json.load(f).get('model') or '')
        except Exception:
            return False

    todo = []
    for e in eps:
        key = e.get('_key') or str(e['num'])
        p = os.path.join(args.out_dir, key, f'{key}_raw.json')
        if args.skip_existing and os.path.exists(p) and funasr_done(p):
            continue
        todo.append(e)
    print(f'[plan] 待处理 {len(todo)} 期(已完成 {total - len(todo)}), DL={DL_WORKERS}, ASR={ASR_WORKERS}', flush=True)
    update_progress(total=total, done=total - len(todo), failed=0,
                    phase='downloading', dl_queue=len(todo), transcribed=0,
                    started_at=time.time(), failures=[])
    if not todo:
        print('[done] 全部已完成', flush=True)
        return

    t_start = time.time()

    # ===== Phase 1: 全量下载（独立于转写, 先下完再转）=====
    print(f'[dl-phase] 全量下载 {len(todo)} 期 ({DL_WORKERS} 线程)', flush=True)
    dl_status = {}
    dl_lock = threading.Lock()
    dl_cnt = [0]

    def dl_task(ep):
        num, status = download_one(ep)
        with dl_lock:
            dl_status[num] = status
            dl_cnt[0] += 1
            update_progress(dl_queue=len(todo) - dl_cnt[0])
        print(f'[dl] {num} {status}', flush=True)

    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=DL_WORKERS) as pool:
        list(as_completed([pool.submit(dl_task, e) for e in todo]))

    ok_eps, dl_fails = [], []
    for e in todo:
        key = e.get('_key') or str(e['num'])
        st = dl_status.get(key, 'missing')
        if st.startswith('ok') or st == 'cached':
            ok_eps.append(e)
        else:
            dl_fails.append(key)
            with _plock:
                _progress['failures'] = _progress.get('failures', []) + [
                    {'num': key, 'stage': 'download', 'err': st}]
                _progress['failed'] = _progress.get('failed', 0) + 1
            save_progress()
    print(f'[dl-phase] 完成: {len(ok_eps)} 可转写, {len(dl_fails)} 下载失败(喜马拉雅补齐)', flush=True)
    update_progress(phase='transcribing')

    # ===== Phase 2: 多进程并行转写（动态队列分发, 打破锁步）=====
    print(f'[asr-phase] {ASR_WORKERS} 进程并行转写 {len(ok_eps)} 期', flush=True)
    import multiprocessing as mp

    done_ctr = mp.Value('i', 0)
    fail_ctr = mp.Value('i', 0)

    # 静态分片（v9 架构, 实测 165 期/h 最优; 动态队列导致 GPU kernel 争抢反而崩）
    shards = [ok_eps[i::ASR_WORKERS] for i in range(ASR_WORKERS)]

    def asr_process_worker(worker_id, shard):
        sys.path.insert(0, BASE)
        import torch
        torch.set_num_threads(16)  # 128核/8进程=16, 防止线程超订互踩
        time.sleep(worker_id * 4)  # 错开启动相位, 打破锁步
        model, post = get_model()
        print(f'[model] pid-{os.getpid()} 就绪 ({len(shard)} 期)', flush=True)
        for ep in shard:
            key = ep.get('_key') or str(ep['num'])
            try:
                path, nseg, dur, el = transcribe(model, ep, args.out_dir, post)
                with done_ctr.get_lock():
                    done_ctr.value += 1
                speed = dur / el if el > 0 else 0
                print(f'[ok] {key}: {nseg}段 {dur/60:.1f}min ({speed:.0f}x, {el:.0f}s)', flush=True)
            except Exception as e:
                with fail_ctr.get_lock():
                    fail_ctr.value += 1
                print(f'[fail] {key}: {type(e).__name__}: {str(e)[:150]}', flush=True)

    procs = []
    for i, shard in enumerate(shards):
        if shard:
            p = mp.Process(target=asr_process_worker, args=(i, shard))
            p.start()
            procs.append(p)

    # 主进程监控线程: 定期刷进度文件
    import threading as _th
    def _monitor():
        while any(p.is_alive() for p in procs):
            update_progress(transcribed=done_ctr.value + (total - len(todo)),
                            done=done_ctr.value + (total - len(todo)), failed=fail_ctr.value,
                            phase='transcribing')
            time.sleep(10)
    _mt = _th.Thread(target=_monitor, daemon=True)
    _mt.start()

    for p in procs:
        p.join()

    update_progress(phase='done', current=None, elapsed=time.time() - t_start,
                    transcribed=done_ctr.value + (total - len(todo)),
                    done=done_ctr.value + (total - len(todo)), failed=fail_ctr.value)
    print(f'[done] 转写成功 {done_ctr.value} 失败 {fail_ctr.value}, 总耗时 {(time.time()-t_start)/60:.1f}min', flush=True)


if __name__ == '__main__':
    main()
