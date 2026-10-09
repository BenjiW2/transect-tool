"""Transect tool – local web app.

Run:  python app.py      (then open http://127.0.0.1:8765 if it doesn't open by itself)
"""
import csv
import json
import os
import re
import subprocess
import sys
import threading
import time
import traceback
import uuid
import webbrowser
from pathlib import Path

import cv2
import numpy as np
from flask import Flask, abort, jsonify, request, send_file, send_from_directory

import pipeline as pl

FROZEN = getattr(sys, 'frozen', False)          # running from the packaged Mac app
ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
_default_projects = (Path.home() / 'Documents' / 'Transect Tool') if FROZEN else ROOT / 'projects'
PROJECTS = Path(os.environ.get('TRANSECT_PROJECTS', _default_projects))
PROJECTS.mkdir(parents=True, exist_ok=True)
IMG_EXT = {'.jpg', '.jpeg', '.png', '.tif', '.tiff'}

app = Flask(__name__, static_folder=str(ROOT / 'static'), static_url_path='/static')
lock = threading.RLock()


# ----------------------------------------------------------------------------- state helpers

def pdir(pid):
    if not re.fullmatch(r'[a-z0-9]{8,32}', pid or ''):
        abort(404)
    d = PROJECTS / pid
    if not d.is_dir():
        abort(404)
    return d


def load(pid):
    with lock:
        return json.loads((pdir(pid) / 'state.json').read_text())


def save(pid, st):
    with lock:
        tmp = pdir(pid) / 'state.json.tmp'
        tmp.write_text(json.dumps(st, indent=1))
        tmp.replace(pdir(pid) / 'state.json')


def photo(st, name):
    for p in st['photos']:
        if p['name'] == name:
            return p
    abort(404)


def geo_of(p):
    return pl.geometry(p['W'], p['H'], p['tape'])


def safe_name(name):
    name = os.path.basename(name or '')
    name = re.sub(r'[^A-Za-z0-9._-]', '_', name)
    if not name or name.startswith('.'):
        abort(400, 'bad file name')
    return name


def readings_of(p):
    return [(r['x'], r['y'], r['cm']) for r in p['readings']]


def quick_fit(st):
    """Per-photo fits (no lens model) for live feedback while reading."""
    items = {p['name']: (geo_of(p), readings_of(p)) for p in st['photos']
             if p['include'] and not p['skip'] and len(p['readings']) >= 2}
    if not items:
        return {}
    f = pl.fit_photos(items, k=0.0)
    out = {}
    for n in items:
        out[n] = dict(range=f['ranges'][n], maxres=max(abs(x) for x in f['residuals'][n]))
    return out


def summary(pid, st):
    qf = quick_fit(st)
    order = [p for p in st['photos'] if p['include'] and not p['skip'] and p['name'] in qf]
    centres = [sum(qf[p['name']]['range']) / 2 for p in order]
    diffs = np.diff(centres)
    direction = np.sign(np.median(diffs)) if len(diffs) else 1
    out_of_order = set()
    for i in range(1, len(order)):
        if (centres[i] - centres[i - 1]) * direction <= 0:
            out_of_order.update({order[i]['name'], order[i - 1]['name']})
    photos = []
    for p in st['photos']:
        q = qf.get(p['name'])
        if not p['include']:
            status = 'excluded'
        elif p['skip']:
            status = 'skipped'
        elif len(p['readings']) < 2:
            status = 'todo'
        elif q['maxres'] > 2.5 or p['name'] in out_of_order:
            status = 'check'
        else:
            status = 'ok'
        geo = geo_of(p)
        photos.append(dict(
            name=p['name'], include=p['include'], skip=p['skip'], status=status,
            tape=p['tape'], tape_score=p.get('tape_score', 0), tape_manual=p.get('tape_manual', False),
            W=p['W'], H=p['H'],
            readings=[dict(raw=r['raw'], cm=r['cm'],
                           sx=pl.work_to_strip_x(geo, r['x'], r['y'], geo['xmin'])) for r in p['readings']],
            range=q['range'] if q else None, maxres=q['maxres'] if q else None,
            out_of_order=p['name'] in out_of_order))
    return dict(id=pid, name=st['name'], csv=st.get('csv'), meta=st.get('meta', {}),
                n_segments=st.get('n_segments', 0), seg_range=st.get('seg_range'),
                csv_error=st.get('csv_error'), photos=photos, build=st.get('build', {}))


# ----------------------------------------------------------------------------- routes

@app.get('/')
def index():
    return send_from_directory(ROOT / 'static', 'index.html')


@app.get('/api/projects')
def list_projects():
    out = []
    for d in sorted(PROJECTS.iterdir(), key=lambda d: d.stat().st_mtime, reverse=True):
        f = d / 'state.json'
        if f.exists():
            st = json.loads(f.read_text())
            out.append(dict(id=d.name, name=st['name'], photos=len(st['photos']),
                            created=st.get('created', '')))
    return jsonify(out)


@app.post('/api/projects')
def create_project():
    name = (request.form.get('name') or 'Transect').strip()[:80]
    pid = uuid.uuid4().hex[:12]
    d = PROJECTS / pid
    (d / 'photos').mkdir(parents=True)
    (d / 'cache').mkdir()
    (d / 'output').mkdir()
    st = dict(name=name, created=time.strftime('%Y-%m-%d %H:%M'), photos=[], build={})
    (d / 'state.json').write_text(json.dumps(st))
    return jsonify(id=pid)


@app.post('/api/projects/<pid>/csv')
def upload_csv(pid):
    d = pdir(pid)
    f = request.files.get('file')
    if not f:
        abort(400, 'no file')
    path = d / 'datasheet.csv'
    f.save(path)
    st = load(pid)
    st['csv'] = safe_name(f.filename)
    try:
        meta, segs = pl.read_datasheet(path)
        st.update(meta=meta, n_segments=len(segs), seg_range=[min(s['s'] for s in segs), max(s['f'] for s in segs)],
                  csv_error=None)
    except Exception as e:  # noqa: BLE001 – show any parse problem to the user
        st.update(csv_error=str(e), n_segments=0)
    save(pid, st)
    return jsonify(summary(pid, st))


@app.post('/api/projects/<pid>/photos')
def upload_photo(pid):
    d = pdir(pid)
    f = request.files.get('file')
    if not f:
        abort(400, 'no file')
    name = safe_name(f.filename)
    if Path(name).suffix.lower() not in IMG_EXT:
        abort(400, 'not an image')
    path = d / 'photos' / name
    f.save(path)
    try:
        full = pl.read_full(path)
    except ValueError:
        path.unlink(missing_ok=True)
        abort(400, f'could not read {name}')
    cv2.imwrite(str(d / 'cache' / f'thumb_{name}.jpg'), pl.make_thumb(full))
    work = pl.make_work(full)
    cv2.imwrite(str(d / 'cache' / f'work_{name}.jpg'), work, [cv2.IMWRITE_JPEG_QUALITY, 90])
    tape, score = pl.detect_tape(work)
    with lock:
        st = load(pid)
        st['photos'] = [p for p in st['photos'] if p['name'] != name]
        st['photos'].append(dict(name=name, include=True, skip=False, W=work.shape[1], H=work.shape[0],
                                 tape=tape, tape_score=score, tape_manual=False, readings=[]))
        st['photos'].sort(key=lambda p: p['name'])
        save(pid, st)
    return jsonify(ok=True)


@app.get('/api/projects/<pid>')
def get_project(pid):
    return jsonify(summary(pid, load(pid)))


@app.post('/api/projects/<pid>/photo/<name>')
def update_photo(pid, name):
    data = request.get_json(force=True)
    with lock:
        st = load(pid)
        p = photo(st, name)
        if 'include' in data:
            p['include'] = bool(data['include'])
        if 'skip' in data:
            p['skip'] = bool(data['skip'])
        if 'tape' in data:
            (x1, y1), (x2, y2) = data['tape']
            if (x1 - x2) ** 2 + (y1 - y2) ** 2 < 25:
                abort(400, 'Pick two points further apart along the tape.')
            p['tape'] = [[float(x1), float(y1)], [float(x2), float(y2)]]
            p['tape_manual'] = True
            (pdir(pid) / 'cache' / f'strip_{name}.jpg').unlink(missing_ok=True)
        if 'add_reading' in data:
            r = data['add_reading']
            cm = pl.parse_tape_value(str(r.get('raw', '')))
            if cm is None:
                abort(400, 'Could not understand that value. Use e.g. 760, 7.6m, 12ft 7in')
            geo = geo_of(p)
            x, y = pl.strip_x_to_work(geo, float(r['sx']), geo['xmin'])
            p['readings'].append(dict(x=x, y=y, cm=cm, raw=str(r['raw']).strip()))
        if 'delete_reading' in data:
            i = int(data['delete_reading'])
            if 0 <= i < len(p['readings']):
                p['readings'].pop(i)
        if data.get('clear_readings'):
            p['readings'] = []
        save(pid, st)
    return jsonify(summary(pid, st))


@app.get('/api/projects/<pid>/thumb/<name>')
def thumb(pid, name):
    return send_file(pdir(pid) / 'cache' / f'thumb_{safe_name(name)}.jpg')


@app.get('/api/projects/<pid>/work/<name>')
def work_image(pid, name):
    return send_file(pdir(pid) / 'cache' / f'work_{safe_name(name)}.jpg')


@app.get('/api/projects/<pid>/strip/<name>')
def strip(pid, name):
    d = pdir(pid)
    name = safe_name(name)
    f = d / 'cache' / f'strip_{name}.jpg'
    if not f.exists():
        st = load(pid)
        p = photo(st, name)
        img, _ = pl.make_strip(pl.read_full(d / 'photos' / name), geo_of(p))
        cv2.imwrite(str(f), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    resp = send_file(f)
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@app.get('/api/projects/<pid>/output/<fname>')
def output(pid, fname):
    f = pdir(pid) / 'output' / safe_name(fname)
    if not f.exists():
        abort(404)
    return send_file(f, as_attachment=request.args.get('dl') == '1')


@app.post('/api/projects/<pid>/reveal')
def reveal(pid):
    """Show the project's output files in Finder (Mac) / Explorer (Windows)."""
    out = pdir(pid) / 'output'
    files = sorted(out.glob('*_marked.jpg')) or sorted(out.iterdir())
    target = files[0] if files else out
    if sys.platform == 'darwin':
        subprocess.run(['open', '-R', str(target)], check=False)
    elif os.name == 'nt':
        subprocess.run(['explorer', '/select,', str(target)], check=False)
    else:
        subprocess.run(['xdg-open', str(out)], check=False)
    return jsonify(ok=True)


def output_path(pid, fname):
    f = pdir(pid) / 'output' / safe_name(fname)
    if not f.exists():
        abort(404)
    return f


@app.post('/api/projects/<pid>/build')
def build(pid):
    opts = request.get_json(force=True) or {}
    with lock:
        st = load(pid)
        if st.get('build', {}).get('status') == 'running':
            abort(409, 'already building')
        st['build'] = dict(status='running', progress=0, message='Starting', outputs=[], warnings=[])
        save(pid, st)
    threading.Thread(target=run_build, args=(pid, opts), daemon=True).start()
    return jsonify(ok=True)


# ----------------------------------------------------------------------------- build job

def set_build(pid, **kw):
    with lock:
        st = load(pid)
        st['build'].update(kw)
        save(pid, st)


def run_build(pid, opts):
    try:
        d = pdir(pid)
        st = load(pid)
        pxcm = float(opts.get('pxcm') or 20)
        vhalf = float(opts.get('half_width_cm') or 42)
        warnings = []
        use = [p for p in st['photos'] if p['include'] and not p['skip'] and len(p['readings']) >= 2]
        if not use:
            raise ValueError('No photos have at least 2 tape readings yet.')
        n_todo = sum(1 for p in st['photos'] if p['include'] and not p['skip'] and len(p['readings']) < 2)
        if n_todo:
            warnings.append(f'{n_todo} included photo(s) have fewer than 2 readings and were left out.')
        set_build(pid, progress=0.02, message='Fitting tape readings')
        geos = {p['name']: geo_of(p) for p in use}
        fit = pl.fit_photos({p['name']: (geos[p['name']], readings_of(p)) for p in use})
        for n, res in fit['residuals'].items():
            if max(abs(r) for r in res) > 2.5:
                warnings.append(f'{n}: readings disagree by up to {max(abs(r) for r in res):.1f} cm – check them.')

        cov_lo = min(r[0] for r in fit['ranges'].values())
        cov_hi = max(r[1] for r in fit['ranges'].values())
        segs, meta = [], st.get('meta', {})
        if (d / 'datasheet.csv').exists() and not st.get('csv_error'):
            meta, segs = pl.read_datasheet(d / 'datasheet.csv')
        if segs:
            cm0 = max(min(s['s'] for s in segs) - 20, cov_lo)
            cm1 = min(max(s['f'] for s in segs) + 5, cov_hi)
            if min(s['s'] for s in segs) < cov_lo - 1 or max(s['f'] for s in segs) > cov_hi + 1:
                warnings.append(f'The photos only cover {cov_lo:.0f}–{cov_hi:.0f} cm of tape; '
                                f'markers outside that range are drawn on blank space.')
                cm0 = min(cm0, min(s['s'] for s in segs) - 20)
                cm1 = max(cm1, max(s['f'] for s in segs) + 5)
        else:
            cm0, cm1 = cov_lo, cov_hi
            warnings.append('No usable data sheet – image made without markers.')
        if (cm1 - cm0) * pxcm > 65000:
            new = math_floor(65000 / (cm1 - cm0))
            warnings.append(f'Transect too long for {pxcm:g} px/cm in a JPEG; used {new} px/cm instead.')
            pxcm = new

        # gaps in coverage
        iv = sorted(fit['ranges'].values())
        reach = cm0
        for lo, hi in iv:
            if lo > reach + 2 and reach < cm1:
                warnings.append(f'No photo covers {reach:.0f}–{min(lo, cm1):.0f} cm (shown grey).')
            reach = max(reach, hi)
        if reach < cm1 - 2:
            warnings.append(f'No photo covers {reach:.0f}–{cm1:.0f} cm (shown grey).')

        photos = [(p['name'], d / 'photos' / p['name'], geos[p['name']]) for p in use]
        img, holes = pl.render_strip(
            photos, fit, cm0, cm1, pxcm, vhalf,
            progress=lambda f, m: set_build(pid, progress=0.05 + 0.75 * f, message=m))
        base = re.sub(r'[^A-Za-z0-9_-]+', '_', st['name']).strip('_') or 'transect'
        out = d / 'output'
        for old in out.iterdir():
            old.unlink()
        set_build(pid, progress=0.82, message='Saving clean image')
        cv2.imwrite(str(out / f'{base}_clean.jpg'), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
        outputs = [f'{base}_clean.jpg']
        if segs:
            set_build(pid, progress=0.88, message='Drawing markers')
            marked = pl.draw_markers(img, segs, meta, cm0, pxcm, st['name'])
            marked.save(out / f'{base}_marked.jpg', quality=90)
            outputs.insert(0, f'{base}_marked.jpg')
            prev_src = marked
        else:
            from PIL import Image
            prev_src = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        set_build(pid, progress=0.95, message='Making preview')
        s = 6000 / prev_src.size[0]
        prev_src.resize((6000, max(1, int(prev_src.size[1] * s)))).save(out / 'preview.jpg', quality=85)
        with open(out / f'{base}_tape_readings.csv', 'w', newline='') as fh:
            w = csv.writer(fh)
            w.writerow(['photo', 'x_px_work', 'y_px_work', 'entered', 'tape_cm', 'fit_residual_cm'])
            for p in use:
                for r, res in zip(p['readings'], fit['residuals'][p['name']]):
                    w.writerow([p['name'], f"{r['x']:.1f}", f"{r['y']:.1f}", r['raw'], f"{r['cm']:.1f}", f'{res:.2f}'])
        outputs.append(f'{base}_tape_readings.csv')
        set_build(pid, status='done', progress=1, message='Done', outputs=outputs, preview='preview.jpg',
                  warnings=warnings, pxcm=pxcm, cm0=cm0, cm1=cm1, size=[img.shape[1], img.shape[0]])
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        set_build(pid, status='error', message=str(e))


def math_floor(x):
    return max(1, int(x))


def free_port(preferred=8765):
    import socket
    for port in (preferred, 0):
        with socket.socket() as s:
            try:
                s.bind(('127.0.0.1', port))
                return s.getsockname()[1]
            except OSError:
                continue


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8765))
    url = f'http://127.0.0.1:{port}'
    print(f'\n  Transect tool running at {url}\n  (close this window or press Ctrl+C to stop)\n')
    if not os.environ.get('NO_BROWSER'):
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host='127.0.0.1', port=port, debug=False, threaded=True)
