"""Image processing for the transect tool.

Coordinate systems
------------------
* full    – pixels of the original photo (after EXIF rotation)
* work    – photo scaled so its longest side is WORK px; tape lines and readings are stored here
* levelled – work image rotated/shifted so the tape runs horizontally along y = D/2
               (D = diagonal of the work image, so nothing is cropped)
"""
import csv
import math
import re

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

WORK = 1392          # longest side of the working image
STRIP_ZOOM = 2       # strip images are rendered at 2x work resolution
STRIP_HALF = 30      # strip half-height in work px


# ----------------------------------------------------------------------------- images

def read_full(path):
    im = cv2.imread(str(path), cv2.IMREAD_COLOR)  # applies EXIF orientation
    if im is None:
        raise ValueError(f'cannot read image {path}')
    return im


def work_scale(shape):
    return WORK / max(shape[:2])


def make_thumb(full, size=360):
    s = size / max(full.shape[:2])
    return cv2.resize(full, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)


def make_work(full):
    s = work_scale(full.shape)
    return cv2.resize(full, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)


# ----------------------------------------------------------------------------- tape line

def detect_tape(work):
    """Find the yellow tape as the strongest thin bright-yellow line. Returns (p1, p2, score) in work coords."""
    s = 600 / max(work.shape[:2])
    small = cv2.resize(work, None, fx=s, fy=s, interpolation=cv2.INTER_AREA).astype(np.float32)
    b, g, r = cv2.split(small)
    yel = np.clip(r - b, 0, None)
    h, w = yel.shape
    kern = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 9))

    def score(ang):
        M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1)
        rot = cv2.warpAffine(yel, M, (w, h))
        ridge = np.clip(cv2.morphologyEx(rot, cv2.MORPH_TOPHAT, kern) - 3, 0, None)
        prof = ridge[:, int(w * .1):int(w * .9)].sum(1)
        prof = prof - cv2.blur(prof.reshape(-1, 1), (1, 21)).ravel()
        y = int(prof.argmax())
        return prof[y], y, M

    best = max((score(a) + (a,) for a in np.arange(-90, 90, 3)), key=lambda t: t[0])
    a0 = best[3]
    best = max((score(a) + (a,) for a in np.arange(a0 - 3, a0 + 3.01, 0.25)), key=lambda t: t[0])
    sc, y, M, ang = best
    Mi = cv2.invertAffineTransform(M)
    pts = [Mi @ np.array([x, y, 1.0]) / s for x in (w * 0.2, w * 0.8)]
    return [list(map(float, pts[0])), list(map(float, pts[1]))], float(sc)


def geometry(W, H, tape):
    """Levelling transform for a photo of work size W x H with tape through points p1, p2."""
    (x1, y1), (x2, y2) = tape
    th = math.atan2(y2 - y1, x2 - x1)
    if th > math.pi / 2:
        th -= math.pi
    elif th <= -math.pi / 2:
        th += math.pi
    c, s = math.cos(th), math.sin(th)
    cx, cy = W / 2, H / 2
    D = int(math.ceil(math.hypot(W, H)))
    dline = -s * (x1 - cx) + c * (y1 - cy)   # tape offset from image centre (after rotation)
    A = np.array([[c, s, 0], [-s, c, 0]], float)
    A[:, 2] = -A[:, :2] @ [cx, cy] + [D / 2, D / 2 - dline]
    Ai = cv2.invertAffineTransform(A)
    # x-range (levelled) where the tape row lies inside the photo
    xs = np.arange(0, D, 1.0)
    p = Ai[:, :2] @ np.vstack([xs, np.full_like(xs, D / 2)]) + Ai[:, 2:3]
    inside = (p[0] >= 0) & (p[0] < W) & (p[1] >= 0) & (p[1] < H)
    x0, x1_ = (float(xs[inside].min()), float(xs[inside].max())) if inside.any() else (0.0, float(D))
    return dict(A=A, Ai=Ai, D=D, dline=dline, W=W, H=H, xmin=x0, xmax=x1_, Rn=max(W, H) / 2)


def make_strip(full, geo):
    """Levelled tape strip at STRIP_ZOOM x work resolution. Returns (image, x_offset_in_levelled)."""
    s = work_scale(full.shape)
    x0 = geo['xmin']
    Z = STRIP_ZOOM
    # full -> work -> levelled -> strip
    M = np.vstack([geo['A'], [0, 0, 1]]) @ np.diag([s, s, 1])
    M = np.array([[Z, 0, -Z * x0], [0, Z, -Z * (geo['D'] / 2 - STRIP_HALF)], [0, 0, 1]]) @ M
    w = int((geo['xmax'] - x0) * Z) + 1
    strip = cv2.warpAffine(full, M[:2], (w, 2 * STRIP_HALF * Z), flags=cv2.INTER_AREA,
                           borderValue=(40, 40, 40))
    return strip, x0


def strip_x_to_work(geo, strip_x, x_off):
    xl = strip_x / STRIP_ZOOM + x_off
    p = geo['Ai'] @ np.array([xl, geo['D'] / 2, 1.0])
    return float(p[0]), float(p[1])


def work_to_strip_x(geo, x, y, x_off):
    xl = (geo['A'] @ np.array([x, y, 1.0]))[0]
    return float((xl - x_off) * STRIP_ZOOM)


# ----------------------------------------------------------------------------- tape-value parsing

def parse_tape_value(text):
    """'760', '760cm', '7.6m', '7m', '12ft', '12ft 7in', "12'7", '12\' 7"' -> cm (float) or None."""
    t = text.strip().lower().replace(',', '.')
    t = re.sub(r'\s+', ' ', t)
    m = re.fullmatch(r"(\d+(?:\.\d+)?) ?(?:ft|feet|foot|')(?: ?(\d+(?:\.\d+)?) ?(?:in|inch|inches|\")?)?", t)
    if m:
        return (float(m.group(1)) * 12 + float(m.group(2) or 0)) * 2.54
    m = re.fullmatch(r'(\d+(?:\.\d+)?) ?m', t)
    if m:
        return float(m.group(1)) * 100
    m = re.fullmatch(r'(\d+(?:\.\d+)?) ?(?:cm)?', t)
    if m:
        return float(m.group(1))
    return None


# ----------------------------------------------------------------------------- fitting

def _undistort_u(geo, xl, k):
    """Levelled x (array) on the tape row -> normalised undistorted coordinate along the tape."""
    U = np.asarray(xl, float) - geo['D'] / 2
    V = np.full_like(U, geo['dline'])
    u, v = U.copy(), V.copy()
    Rn = geo['Rn']
    for _ in range(15):
        s = 1 + k * (u ** 2 + v ** 2) / Rn ** 2
        u, v = U / s, V / s
    return u / Rn


def _fit_one(u, cm, cfix=None):
    """cm = (a + b u) / (1 + c u). Free c with >=4 readings, else c = cfix (or 0)."""
    if cfix is None and len(u) >= 4:
        a, b, c = np.linalg.lstsq(np.vstack([np.ones_like(u), u, -cm * u]).T, cm, rcond=None)[0]
    else:
        c = cfix or 0.0
        a, b = np.linalg.lstsq(np.vstack([np.ones_like(u), u]).T, cm * (1 + c * u), rcond=None)[0]
    res = cm - (a + b * u) / (1 + c * u)
    return [float(a), float(b), float(c)], res


def fit_photos(items, k=None):
    """items: {name: (geo, readings)} with readings as [(x_work, y_work, cm), ...] (>=2 each).
    Returns dict(k, params{name:[a,b,c]}, residuals{name:[..]}, ranges{name:(cm_lo, cm_hi)})."""
    usable = {n: (g, r) for n, (g, r) in items.items() if len(r) >= 2}

    def lev_x(g, r):
        return np.array([(g['A'] @ np.array([x, y, 1.0]))[0] for x, y, _ in r])

    def total(kk):
        return sum(float(np.sum(_fit_one(_undistort_u(g, lev_x(g, r), kk), np.array([c for *_, c in r]))[1] ** 2))
                   for g, r in usable.values())

    if k is None:
        ks = np.linspace(-0.3, 0.3, 31)
        k = float(ks[int(np.argmin([total(kk) for kk in ks]))]) if usable else 0.0
    params, resid = {}, {}
    for n, (g, r) in usable.items():
        params[n], resid[n] = _fit_one(_undistort_u(g, lev_x(g, r), k), np.array([c for *_, c in r]))
    many = [p[2] for n, p in params.items() if len(usable[n][1]) >= 4]
    cmed = float(np.median(many)) if many else 0.0
    for n, (g, r) in usable.items():
        if len(r) < 4:
            params[n], resid[n] = _fit_one(_undistort_u(g, lev_x(g, r), k), np.array([c for *_, c in r]), cmed)
    ranges = {}
    for n, (g, r) in usable.items():
        a, b, c = params[n]
        us = _undistort_u(g, np.array([g['xmin'], g['xmax']]), k)
        v = (a + b * us) / (1 + c * us)
        ranges[n] = (float(min(v)), float(max(v)))
    return dict(k=k, params=params, residuals={n: [float(x) for x in v] for n, v in resid.items()}, ranges=ranges)


# ----------------------------------------------------------------------------- rendering

def render_strip(photos, fit, cm0, cm1, pxcm, vhalf, progress=None):
    """photos: list of (name, full_path, geo). Returns uint8 BGR image with x linear in tape cm."""
    k, P = fit['k'], fit['params']
    CW, CH = int(round((cm1 - cm0) * pxcm)), int(round(2 * vhalf * pxcm))
    acc = np.zeros((CH, CW, 3), np.float32)
    wsum = np.zeros((CH, CW), np.float32)
    todo = [p for p in photos if p[0] in P]
    for i, (name, path, g) in enumerate(todo):
        if progress:
            progress(i / max(1, len(todo)), f'Placing {name}')
        a, b, c = P[name]
        lo, hi = fit['ranges'][name]
        pad = 0.08 * (hi - lo)
        lo, hi = max(lo - pad, cm0), min(hi + pad, cm1)
        if hi <= lo:
            continue
        X0, X1 = int((lo - cm0) * pxcm), int(math.ceil((hi - cm0) * pxcm))
        X1 = min(X1, CW)
        Xg, Yg = np.meshgrid(np.arange(X0, X1, dtype=np.float32), np.arange(CH, dtype=np.float32))
        cm = cm0 + Xg / pxcm
        v = (Yg - CH / 2) / pxcm
        den = b - c * cm
        with np.errstate(divide='ignore', invalid='ignore'):
            u = (cm - a) / den
            w = v * (1 + c * u) / (b - a * c)
        Rn, D, dl = g['Rn'], g['D'], g['dline']
        U, V = u * Rn, w * Rn + dl
        s = 1 + k * (U ** 2 + V ** 2) / Rn ** 2
        xl, yl = U * s + D / 2, V * s + D / 2 - dl
        Ai = g['Ai']
        xw = Ai[0, 0] * xl + Ai[0, 1] * yl + Ai[0, 2]
        yw = Ai[1, 0] * xl + Ai[1, 1] * yl + Ai[1, 2]
        full = read_full(path)
        Z = 2
        img = cv2.resize(full, (g['W'] * Z, g['H'] * Z), interpolation=cv2.INTER_AREA)
        del full
        mapx = np.nan_to_num(xw * Z, nan=-1).astype(np.float32)
        mapy = np.nan_to_num(yw * Z, nan=-1).astype(np.float32)
        tile = cv2.remap(img, mapx, mapy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
        W, H = g['W'], g['H']
        # (1 + c*u) > 0 keeps us on the physical side of the perspective model; 1 + c*u = (b - a*c) / den
        valid = (xw >= 0) & (xw < W - 1) & (yw >= 0) & (yw < H - 1) & ((b - a * c) * den > 0)
        wx = np.clip(1 - np.abs(xw - W / 2) / (W / 2), 0, 1) ** 2
        wy = np.clip(1 - np.abs(yw - H / 2) / (H / 2), 0, 1) ** 0.5
        wt = np.where(valid, wx * wy + 1e-6, 0).astype(np.float32)
        acc[:, X0:X1] += tile.astype(np.float32) * wt[..., None]
        wsum[:, X0:X1] += wt
    out = np.full((CH, CW, 3), 128, np.uint8)
    nz = wsum > 0
    out[nz] = (acc[nz] / wsum[nz][:, None]).clip(0, 255).astype(np.uint8)
    holes = ~nz
    if holes.any() and holes.mean() < 0.02:
        if progress:
            progress(1.0, 'Filling small gaps')
        out = cv2.inpaint(out, holes.astype(np.uint8), 5, cv2.INPAINT_TELEA)
    return out, float(holes.mean())


# ----------------------------------------------------------------------------- data sheet

def _norm(s):
    return re.sub(r'\s+', ' ', s.strip().lower())


def read_datasheet(path):
    """Parse the benthic data-entry CSV. Returns (meta dict, segments list)."""
    with open(path, newline='', encoding='utf-8-sig', errors='replace') as fh:
        rows = list(csv.reader(fh))
    if not rows:
        raise ValueError('CSV is empty')
    hdr = [_norm(h) for h in rows[0]]

    def col(pred, default):
        for i, h in enumerate(hdr):
            if pred(h):
                return i
        return default

    i_s = col(lambda h: 'start' in h and ('measure' in h or 'cm' in h), 6)
    i_f = col(lambda h: 'finish' in h or ('end' in h and 'cm' in h), 7)
    i_maj = col(lambda h: h == 'major', 9)
    i_min = col(lambda h: h == 'minor', 10)
    i_cl = col(lambda h: 'coral length' in h, 11)
    meta_cols = {'site': col(lambda h: h == 'site', 0), 'date': col(lambda h: h == 'date', 1),
                 'time': col(lambda h: h == 'time', 2), 'group': col(lambda h: 'group' in h, 3),
                 'depth': col(lambda h: 'depth' in h, 4), 'bearing': col(lambda h: 'bearing' in h, 5)}
    meta, segs = {}, []
    width = max([i_s, i_f, i_maj, i_min, i_cl] + list(meta_cols.values())) + 1
    for r in rows[1:]:
        r = r + [''] * (width - len(r))
        if not meta and r[meta_cols['site']].strip():
            meta = {k: r[i].strip() for k, i in meta_cols.items()}
        st, fi = r[i_s].strip(), r[i_f].strip()
        major, minor, extra = r[i_maj].strip(), r[i_min].strip(), r[i_cl].strip()
        if not st:
            if segs and (major or minor):
                segs[-1]['extra'].append(f'{major} {minor}'.strip())
            continue
        try:
            s, f = float(st), float(fi)
        except ValueError:
            continue
        if f <= s:
            continue
        minors = [m for m in (minor, extra) if m and not re.fullmatch(r'[\d.]+', m)]
        segs.append(dict(s=s, f=f, major=major, minors=minors, extra=[]))
    if not segs:
        raise ValueError('No segments found in the CSV (need start/finish columns with numbers).')
    return meta, segs


# ----------------------------------------------------------------------------- markers

COLOURS = {'HC': (255, 120, 80), 'DC': (160, 160, 160), 'MA': (46, 160, 87), 'SD': (240, 210, 110),
           'RU': (160, 90, 50), 'RC': (90, 110, 130), 'SP': (230, 90, 180), 'OT': (80, 180, 220),
           'SA': (180, 120, 200), '': (255, 255, 255)}
EXTRA_COLOURS = [(120, 200, 255), (255, 200, 0), (200, 80, 80), (120, 120, 255), (0, 200, 200)]


def _font(size):
    for p in ('/System/Library/Fonts/Helvetica.ttc', '/System/Library/Fonts/SFNS.ttf',
              'C:/Windows/Fonts/arial.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
              '/Library/Fonts/Arial.ttf'):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def draw_markers(strip_bgr, segs, meta, cm0, pxcm, title_name=''):
    Image.MAX_IMAGE_PIXELS = None
    img = Image.fromarray(cv2.cvtColor(strip_bgr, cv2.COLOR_BGR2RGB))
    W, H = img.size
    X = lambda cm: int(round((cm - cm0) * pxcm))
    F_title, F_seg, F_bnd, F_rul = _font(46), _font(34), _font(30), _font(30)
    TITLE, OV, BAR, BL, FOOT = 90, 2 * 56, 90, 3 * 42 + 10, 90
    y_bar = TITLE + OV
    y_bl = y_bar + BAR
    y_img = y_bl + BL
    canvas = Image.new('RGB', (W, y_img + H + FOOT), 'white')
    canvas.paste(img, (0, y_img))
    d = ImageDraw.Draw(canvas)

    colours = dict(COLOURS)
    extra = iter(EXTRA_COLOURS * 10)
    for g in segs:
        if g['major'] not in colours:
            colours[g['major']] = next(extra)

    m = meta or {}
    bits = [title_name] if title_name else []
    if m.get('site'):
        bits.append(f"site {m['site']}")
    if m.get('group'):
        bits.append(f"transect {m['group']}")
    if m.get('date') or m.get('time'):
        bits.append(f"{m.get('date', '')} {m.get('time', '')}".strip())
    if m.get('depth'):
        bits.append(f"depth {m['depth']}")
    if m.get('bearing'):
        bits.append(f"bearing {m['bearing']}°")
    title = ', '.join(bits) + f".  Scale: {pxcm:g} px = 1 cm of tape. Lines = segment boundaries (cm)."
    d.text((20, 22), title, fill='black', font=F_title)
    lx = int(d.textlength(title, font=F_title)) + 80
    seen = []
    for g in segs:
        if g['major'] not in seen:
            seen.append(g['major'])
    for code in seen:
        d.rectangle([lx, 25, lx + 50, 70], fill=colours[code], outline='black', width=2)
        lab = code or 'not recorded'
        d.text((lx + 60, 26), lab, fill='black', font=F_title)
        lx += 60 + int(d.textlength(lab, font=F_title)) + 50

    occupied = [[], []]
    for g in segs:
        x0, x1 = X(g['s']), X(g['f'])
        col = colours[g['major']]
        d.rectangle([x0, y_bar, x1, y_bar + BAR], fill=col, outline='black', width=2)
        lab = g['major'] or '?'
        if g['minors']:
            lab += ' ' + '/'.join(g['minors'])
        if g['extra']:
            lab += ' + ' + ', '.join(g['extra'])
        tw = d.textlength(lab, font=F_seg)
        cx = (x0 + x1) / 2
        if tw + 12 <= x1 - x0:
            d.text((cx - tw / 2, y_bar + BAR / 2 - 18), lab, fill='black', font=F_seg)
        else:
            a, b = cx - tw / 2 - 8, cx + tw / 2 + 8
            lvl = next((i for i in range(2) if all(b < p or a > q for p, q in occupied[i])), 0)
            occupied[lvl].append((a, b))
            ty = y_bar - 56 * (lvl + 1) + 8
            d.line([cx, ty + 40, cx, y_bar], fill='black', width=2)
            d.rectangle([a, ty - 2, b, ty + 40], fill='white', outline=col, width=4)
            d.text((cx - tw / 2, ty), lab, fill='black', font=F_seg)

    bounds = sorted({x for g in segs for x in (g['s'], g['f'])})
    occ = [[] for _ in range(3)]
    for cm in bounds:
        x = X(cm)
        lab = f'{cm:g}'
        tw = d.textlength(lab, font=F_bnd)
        a, b = x - tw / 2 - 6, x + tw / 2 + 6
        lvl = next((i for i in range(3) if all(b < p or a > q for p, q in occ[i])), 2)
        occ[lvl].append((a, b))
        ty = y_bl + 6 + 42 * lvl
        d.line([x, y_bar + BAR, x, ty], fill='black', width=2)
        d.text((x - tw / 2, ty), lab, fill='black', font=F_bnd)
        d.line([x, ty + 36, x, y_img], fill='black', width=2)
        d.line([x, y_img, x, y_img + H], fill=(0, 0, 0), width=6)
        d.line([x, y_img, x, y_img + H], fill=(255, 255, 255), width=2)
    for cm, lab in ((bounds[0], 'START'), (bounds[-1], 'END')):
        x = X(cm)
        tw = d.textlength(lab, font=F_seg)
        xx = x + 10 if lab == 'START' else x - tw - 10
        d.rectangle([xx - 6, y_img + 10, xx + tw + 6, y_img + 56], fill='white', outline='black', width=2)
        d.text((xx, y_img + 14), lab, fill='black', font=F_seg)

    yf = y_img + H
    for cm in range(int(math.floor(cm0 / 10) * 10), int(cm0 + W / pxcm) + 1, 10):
        x = X(cm)
        if not 0 <= x < W:
            continue
        L = 60 if cm % 100 == 0 else (35 if cm % 50 == 0 else 18)
        d.line([x, yf, x, yf + L], fill='black', width=3 if cm % 100 == 0 else 1)
        if cm % 100 == 0:
            d.text((x + 6, yf + 30), f'{cm // 100} m', fill='black', font=F_rul)
    return canvas
