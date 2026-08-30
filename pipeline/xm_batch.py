# -*- coding: utf-8 -*-
"""xm_batch.py — 喜马拉雅源补转写（673 期全集的缺口期）
Phase 1: yt-dlp 并行下载缺口期音频（xmcdn 直链）
Phase 2: FunASR 4 进程转写 → outputs/<key>/<key>_raw.json
"""
import json, os, re, subprocess, sys, time
import multiprocessing as mp

BASE = '/hy-tmp/whisperx_project'
LIST_FILE = os.path.join(BASE, 'episodes_full_673.json')
OUTPUTS = os.path.join(BASE, 'outputs')
AUDIO_DIR = '/hy-tmp/audio_tmp_xm'
PY = '/hy-tmp/miniconda/envs/funasr/bin/python'
YTDLP = '/hy-tmp/miniconda/envs/funasr/bin/yt-dlp'
DL_WORKERS = 8
ASR_WORKERS = 4
PROGRESS = os.path.join(BASE, 'xm_progress.json')

_progress = {}
_plock = __import__('threading').Lock()


def save_progress():
    with _plock:
        tmp = PROGRESS + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(_progress, f, ensure_ascii=False)
        os.replace(tmp, PROGRESS)


def update_progress(**kw):
    with _plock:
        _progress.update(kw)
    save_progress()


def ep_key(m):
    n = m.get('num')
    if n:
        return f"{n:03d}"
    t = m.get('title', '')
    return 'X' + re.sub(r'[\\/:*?"<>|\r\n]+', '', t).strip()[:10]


def ffprobe_duration(path):
    try:
        r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                            '-of', 'json', path], capture_output=True, timeout=60)
        return float(json.loads(r.stdout)['format']['duration'])
    except Exception:
        return None


def download_one(m, key):
    audio = os.path.join(AUDIO_DIR, f'{key}.mp3')
    expect = m.get('duration') or 0
    for attempt in range(3):
        try:
            if os.path.exists(audio) and os.path.getsize(audio) > 1e6:
                dur = ffprobe_duration(audio)
                if dur and (not expect or dur >= expect * 0.9):
                    return 'cached'
                os.remove(audio)
            subprocess.run([YTDLP, '-q', '--no-warnings', '-o', audio,
                            f'https://www.ximalaya.com/sound/{m["trackId"]}'],
                           check=True, timeout=900)
            dur = ffprobe_duration(audio) or 0
            if expect and dur and dur < expect * 0.9:
                os.remove(audio)
                if attempt == 2:
                    return f'truncated:{dur:.0f}s/{expect}s'
                continue
            return 'ok'
        except Exception as e:
            if attempt == 2:
                return f'fail:{type(e).__name__}:{str(e)[:60]}'
            time.sleep(3 * (attempt + 1))
    return 'fail'


def transcribe_one(model, post, m, key):
    audio = os.path.join(AUDIO_DIR, f'{key}.mp3')
    out_dir = os.path.join(OUTPUTS, key)
    out_json = os.path.join(out_dir, f'{key}_raw.json')
    t0 = time.time()
    res = model.generate(input=audio, batch_size_s=300)
    segs = [{'start': s['start'] / 1000.0, 'end': s['end'] / 1000.0,
             'text': post(s['sentence']), 'spk': s.get('spk', -1)}
            for s in (res[0].get('sentence_info') or [])]
    doc = {'num': m.get('num'), 'title': m.get('title', ''), 'key': key,
           'model': 'SenseVoiceSmall+fsmn-vad+cam++', 'source': 'ximalaya',
           'duration': round(segs[-1]['end'], 2) if segs else 0,
           'n_segments': len(segs), 'segments': segs}
    os.makedirs(out_dir, exist_ok=True)
    with open(out_json, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False)
    try:
        os.remove(audio)
    except OSError:
        pass
    return len(segs), time.time() - t0


def main():
    os.makedirs(AUDIO_DIR, exist_ok=True)
    eps = json.load(open(LIST_FILE, encoding='utf-8'))
    todo = []
    for m in eps:
        key = ep_key(m)
        if not os.path.exists(os.path.join(OUTPUTS, key, f'{key}_raw.json')):
            todo.append((m, key))
    print(f'[plan] 清单 {len(eps)} 期, 待转写 {len(todo)} 期', flush=True)
    if not todo:
        print('[done] 无缺口', flush=True)
        return
    update_progress(total=len(todo), done=0, failed=0, phase='downloading',
                    started_at=time.time(), failures=[])

    t_start = time.time()

    # ===== Phase 1: 并行下载 =====
    print(f'[dl-phase] {len(todo)} 期 ({DL_WORKERS} 线程 yt-dlp)', flush=True)
    dl_status, dl_ok = {}, []
    dl_lock = __import__('threading').Lock()
    dl_cnt = [0]
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def dl_task(item):
        m, key = item
        st = download_one(m, key)
        with dl_lock:
            dl_status[key] = st
            dl_cnt[0] += 1
            update_progress(dl_queue=len(todo) - dl_cnt[0])
        print(f'[dl] {key} {st}', flush=True)

    with ThreadPoolExecutor(max_workers=DL_WORKERS) as pool:
        list(as_completed([pool.submit(dl_task, it) for it in todo]))

    for m, key in todo:
        st = dl_status.get(key, 'missing')
        if st.startswith('ok') or st == 'cached':
            dl_ok.append((m, key))
        else:
            with _plock:
                _progress['failures'] = _progress.get('failures', []) + [
                    {'key': key, 'stage': 'download', 'err': st}]
                _progress['failed'] = _progress.get('failed', 0) + 1
            save_progress()
    print(f'[dl-phase] 可转写 {len(dl_ok)} 期, 失败 {len(todo) - len(dl_ok)} 期', flush=True)
    update_progress(phase='transcribing')

    # ===== Phase 2: FunASR 多进程转写 =====
    print(f'[asr-phase] {ASR_WORKERS} 进程转写 {len(dl_ok)} 期', flush=True)
    done_ctr = mp.Value('i', 0)
    fail_ctr = mp.Value('i', 0)

    def asr_worker(worker_id, shard):
        sys.path.insert(0, BASE)
        import torch
        torch.set_num_threads(12)
        from funasr import AutoModel
        from funasr.utils.postprocess_utils import rich_transcription_postprocess
        model = AutoModel(model="iic/SenseVoiceSmall", vad_model="fsmn-vad",
                          spk_model="cam++", device="cuda")
        post = rich_transcription_postprocess
        print(f'[model] w{worker_id} 就绪 ({len(shard)} 期)', flush=True)
        for m, key in shard:
            try:
                nseg, el = transcribe_one(model, post, m, key)
                with done_ctr.get_lock():
                    done_ctr.value += 1
                print(f'[ok] {key}: {nseg}段 ({el:.0f}s)', flush=True)
            except Exception as e:
                with fail_ctr.get_lock():
                    fail_ctr.value += 1
                print(f'[fail] {key}: {type(e).__name__}: {str(e)[:120]}', flush=True)

    shards = [dl_ok[i::ASR_WORKERS] for i in range(ASR_WORKERS)]
    procs = []
    for i, shard in enumerate(shards):
        if shard:
            p = mp.Process(target=asr_worker, args=(i, shard))
            p.start()
            procs.append(p)

    import threading as _th
    def _mon():
        while any(p.is_alive() for p in procs):
            update_progress(done=done_ctr.value, failed=fail_ctr.value,
                            phase='transcribing')
            time.sleep(15)
    _th.Thread(target=_mon, daemon=True).start()

    for p in procs:
        p.join()
    update_progress(phase='done', elapsed=time.time() - t_start,
                    done=done_ctr.value, failed=fail_ctr.value)
    print(f'[done] 转写成功 {done_ctr.value} 失败 {fail_ctr.value}, '
          f'总耗时 {(time.time()-t_start)/60:.1f}min', flush=True)


if __name__ == '__main__':
    main()
