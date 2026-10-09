'use strict';
const $app = document.getElementById('app');
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const fmt = (x, d = 0) => (x == null ? '' : Number(x).toFixed(d));

let P = null;           // current project summary
let tab = 'photos';
let cur = null;         // photo being read
let zoom = 1;
let stripVersion = {};  // cache-busting per photo after tape fixes
let pollTimer = null;

async function api(url, opts = {}) {
  const r = await fetch(url, opts);
  if (!r.ok) {
    let msg = await r.text();
    const m = msg.match(/<p>(.*?)<\/p>/s);
    throw new Error(m ? m[1] : msg);
  }
  return r.json();
}
const post = (url, body) => api(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});

// ---------------------------------------------------------------- tape value parsing (mirrors pipeline.py)
function parseTape(text) {
  let t = text.trim().toLowerCase().replace(',', '.').replace(/\s+/g, ' ');
  let m = t.match(/^(\d+(?:\.\d+)?) ?(?:ft|feet|foot|')(?: ?(\d+(?:\.\d+)?) ?(?:in|inch|inches|")?)?$/);
  if (m) return (parseFloat(m[1]) * 12 + parseFloat(m[2] || 0)) * 2.54;
  m = t.match(/^(\d+(?:\.\d+)?) ?m$/);
  if (m) return parseFloat(m[1]) * 100;
  m = t.match(/^(\d+(?:\.\d+)?) ?(?:cm)?$/);
  if (m) return parseFloat(m[1]);
  return null;
}

// ---------------------------------------------------------------- home
async function goHome() {
  P = null; cur = null; clearInterval(pollTimer);
  history.replaceState(null, '', location.pathname);
  document.getElementById('hdrProj').textContent = '';
  const list = await api('/api/projects');
  $app.innerHTML = `
  <div class="card">
    <h2>New transect</h2>
    <div class="row" style="margin-bottom:10px">
      <label>Name <input type="text" id="nName" placeholder="e.g. NI T1 9 Oct" size="30"></label>
    </div>
    <div class="drop" id="drop">
      Drag the transect <b>photos</b> and the <b>data sheet CSV</b> here, or
      <label class="btn">choose files<input type="file" id="nFiles" multiple accept=".jpg,.jpeg,.png,.tif,.tiff,.csv" hidden></label>
      <div id="picked" class="muted" style="margin-top:8px"></div>
    </div>
    <div class="row" style="margin-top:12px">
      <button class="primary" id="nGo" disabled>Upload</button>
      <div class="bar" style="flex:1; display:none" id="upBar"><div></div></div>
      <span id="upMsg" class="muted"></span>
    </div>
  </div>
  <div class="card">
    <h2>Previous transects</h2>
    ${list.length ? `<table>${list.map(p => `<tr><td><a href="#" data-id="${esc(p.id)}">${esc(p.name)}</a></td>
      <td class="muted">${p.photos} photos</td><td class="muted">${esc(p.created)}</td></tr>`).join('')}</table>`
      : '<span class="muted">None yet.</span>'}
  </div>`;
  $app.querySelectorAll('a[data-id]').forEach(a => a.onclick = e => { e.preventDefault(); openProject(a.dataset.id); });
  let files = [];
  const show = () => {
    const csv = files.filter(f => /\.csv$/i.test(f.name)), img = files.filter(f => !/\.csv$/i.test(f.name));
    document.getElementById('picked').innerHTML =
      `${img.length} photo(s)${csv.length ? `, data sheet: <b>${esc(csv[0].name)}</b>` : ', <span class="warn">no CSV yet</span>'}`;
    document.getElementById('nGo').disabled = !img.length;
  };
  const drop = document.getElementById('drop');
  drop.ondragover = e => { e.preventDefault(); drop.classList.add('over'); };
  drop.ondragleave = () => drop.classList.remove('over');
  drop.ondrop = e => { e.preventDefault(); drop.classList.remove('over'); files = files.concat([...e.dataTransfer.files]); show(); };
  document.getElementById('nFiles').onchange = e => { files = files.concat([...e.target.files]); show(); };
  document.getElementById('nGo').onclick = () => upload(files);
}

async function upload(files) {
  const go = document.getElementById('nGo'), bar = document.getElementById('upBar'), msg = document.getElementById('upMsg');
  go.disabled = true; bar.style.display = '';
  const fd = new FormData(); fd.append('name', document.getElementById('nName').value || 'Transect');
  const {id} = await api('/api/projects', {method: 'POST', body: fd});
  const csv = files.find(f => /\.csv$/i.test(f.name));
  if (csv) { const f = new FormData(); f.append('file', csv); await api(`/api/projects/${id}/csv`, {method: 'POST', body: f}); }
  const imgs = files.filter(f => !/\.csv$/i.test(f.name)).sort((a, b) => a.name.localeCompare(b.name));
  const errors = [];
  for (let i = 0; i < imgs.length; i++) {
    msg.textContent = `Uploading & finding tape: ${imgs[i].name} (${i + 1}/${imgs.length})`;
    bar.firstElementChild.style.width = `${100 * i / imgs.length}%`;
    const f = new FormData(); f.append('file', imgs[i]);
    try { await api(`/api/projects/${id}/photos`, {method: 'POST', body: f}); }
    catch (e) { errors.push(`${imgs[i].name}: ${e.message}`); }
  }
  if (errors.length) alert('Some files could not be used:\n' + errors.join('\n'));
  openProject(id);
}

// ---------------------------------------------------------------- project
async function openProject(id, keepTab) {
  P = await api(`/api/projects/${id}`);
  if (P.build && P.build.status === 'running') poll();
  document.getElementById('hdrProj').textContent = P.name;
  if (!keepTab) tab = 'photos';
  render();
}
async function refresh() { P = await api(`/api/projects/${P.id}`); }

function render() {
  history.replaceState(null, '', `#${P.id}/${tab}${tab === 'read' && cur ? '/' + encodeURIComponent(cur) : ''}`);
  const counts = s => P.photos.filter(p => p.status === s).length;
  $app.innerHTML = `
    <div class="tabs">
      <button data-t="photos">1. Photos & data sheet</button>
      <button data-t="read">2. Read the tape <span class="muted">(${counts('ok')}/${P.photos.filter(p => p.include && !p.skip).length})</span></button>
      <button data-t="build">3. Build image</button>
    </div><div id="tabBody"></div>`;
  $app.querySelectorAll('.tabs button').forEach(b => {
    b.classList.toggle('on', b.dataset.t === tab);
    b.onclick = async () => { tab = b.dataset.t; await refresh(); render(); };
  });
  ({photos: renderPhotos, read: renderRead, build: renderBuild})[tab]();
}

function tapeSvg(p, w, h) {
  const [[x1, y1], [x2, y2]] = p.tape;
  // extend the line across the picture
  const dx = x2 - x1, dy = y2 - y1, L = Math.hypot(dx, dy) || 1, ext = Math.hypot(p.W, p.H);
  const ax = x1 - dx / L * ext, ay = y1 - dy / L * ext, bx = x1 + dx / L * ext, by = y1 + dy / L * ext;
  return `<svg viewBox="0 0 ${p.W} ${p.H}" preserveAspectRatio="none">
    <line x1="${ax}" y1="${ay}" x2="${bx}" y2="${by}" stroke="#ff2d55" stroke-width="2.5" vector-effect="non-scaling-stroke" stroke-dasharray="7 5"/></svg>`;
}

// ---------------------------------------------------------------- tab 1
function renderPhotos() {
  const body = document.getElementById('tabBody');
  const csvLine = P.csv_error ? `<span class="err">Problem reading ${esc(P.csv)}: ${esc(P.csv_error)}</span>`
    : P.csv ? `<b>${esc(P.csv)}</b>: ${P.n_segments} segments from ${fmt(P.seg_range[0])} to ${fmt(P.seg_range[1])} cm`
            : '<span class="warn">No data sheet uploaded – the image will have no markers.</span>';
  body.innerHTML = `
    <div class="card">
      <h2>Data sheet</h2>
      <div class="row">${csvLine}
        <label class="btn">${P.csv ? 'Replace' : 'Add'} CSV<input type="file" id="csvIn" accept=".csv" hidden></label></div>
    </div>
    <div class="card">
      <h2>Photos (${P.photos.length})</h2>
      <p class="muted">Untick anything that isn't a photo of the transect (e.g. photos of the datasheet). The dashed red line shows where the
      tape was found – if it's wrong you can fix it in step 2. Photos are used in file-name order.</p>
      <div class="row" style="margin-bottom:10px">
        <label class="btn">Add more photos<input type="file" id="moreIn" multiple accept=".jpg,.jpeg,.png,.tif,.tiff" hidden></label>
        <span id="moreMsg" class="muted"></span>
      </div>
      <div class="grid">${P.photos.map(p => `
        <div class="ph ${p.include ? '' : 'off'}">
          <div class="imgwrap"><img src="/api/projects/${P.id}/thumb/${encodeURIComponent(p.name)}" loading="lazy">${tapeSvg(p)}</div>
          <div class="row" style="justify-content:space-between; margin-top:4px">
            <label><input type="checkbox" data-n="${esc(p.name)}" ${p.include ? 'checked' : ''}> ${esc(p.name)}</label>
            <span class="badge b-${p.status}">${p.status}</span>
          </div>
        </div>`).join('')}
      </div>
      <div style="margin-top:14px"><button class="primary" id="toRead">Next: read the tape →</button></div>
    </div>`;
  body.querySelectorAll('input[type=checkbox][data-n]').forEach(cb => cb.onchange = async () => {
    P = await post(`/api/projects/${P.id}/photo/${encodeURIComponent(cb.dataset.n)}`, {include: cb.checked});
    cb.closest('.ph').classList.toggle('off', !cb.checked);
  });
  document.getElementById('csvIn').onchange = async e => {
    const f = new FormData(); f.append('file', e.target.files[0]);
    P = await api(`/api/projects/${P.id}/csv`, {method: 'POST', body: f}); render();
  };
  document.getElementById('moreIn').onchange = async e => {
    const files = [...e.target.files];
    for (let i = 0; i < files.length; i++) {
      document.getElementById('moreMsg').textContent = `Uploading ${i + 1}/${files.length}…`;
      const f = new FormData(); f.append('file', files[i]);
      try { await api(`/api/projects/${P.id}/photos`, {method: 'POST', body: f}); } catch (err) { alert(err.message); }
    }
    await refresh(); render();
  };
  document.getElementById('toRead').onclick = () => { tab = 'read'; render(); };
}

// ---------------------------------------------------------------- tab 2
function readable() { return P.photos.filter(p => p.include); }

function renderRead() {
  const list = readable();
  if (!list.length) { document.getElementById('tabBody').innerHTML = '<div class="card">No photos included.</div>'; return; }
  if (!cur || !list.find(p => p.name === cur)) cur = (list.find(p => p.status === 'todo') || list[0]).name;
  const p = list.find(q => q.name === cur), i = list.indexOf(p);
  const prev = list.slice(0, i).reverse().find(q => q.range), next = list.slice(i + 1).find(q => q.range);
  const hint = [prev && `previous photo (${esc(prev.name)}) covers ${fmt(prev.range[0])}–${fmt(prev.range[1])} cm`,
                next && `next photo (${esc(next.name)}) covers ${fmt(next.range[0])}–${fmt(next.range[1])} cm`].filter(Boolean).join('; ');
  history.replaceState(null, '', `#${P.id}/read/${encodeURIComponent(cur)}`);
  const v = stripVersion[p.name] || 0;
  document.getElementById('tabBody').innerHTML = `
  <div class="reader">
    <div class="plist">${list.map(q => `<div data-n="${esc(q.name)}" class="${q.name === cur ? 'sel' : ''}">
        <span>${esc(q.name)}</span><span class="badge b-${q.status}">${q.skip ? 'skip' : q.readings.length}</span></div>`).join('')}</div>
    <div>
      <div class="card">
        <div class="row" style="justify-content:space-between">
          <div class="row"><h2 style="margin:0">${esc(p.name)}</h2> <span class="badge b-${p.status}">${p.status}</span>
            ${p.range ? `<span class="muted">this photo: ${fmt(p.range[0])}–${fmt(p.range[1])} cm</span>` : ''}</div>
          <div class="row">
            <button id="bPrev" ${i ? '' : 'disabled'}>← Prev</button>
            <button id="bNext" ${i < list.length - 1 ? '' : 'disabled'}>Next →</button>
          </div>
        </div>
        <p class="muted" style="margin:6px 0">${hint || '&nbsp;'}</p>
        ${p.skip ? `<p class="warn">This photo is marked as skipped (tape unreadable) and won't be used.</p>` : ''}
        ${p.out_of_order ? `<p class="warn">⚠ This photo's tape values don't follow on from its neighbours – check the readings (e.g. wrong metre).</p>` : ''}
        ${p.maxres > 2.5 ? `<p class="warn">⚠ The readings in this photo disagree with each other by up to ${fmt(p.maxres, 1)} cm – one is probably mistyped or misplaced.</p>` : ''}
        <div class="row" style="margin-bottom:8px">
          <span>Zoom</span>${[0.5, 0.75, 1, 1.5, 2].map(z => `<button data-z="${z}" ${z === zoom ? 'class="primary"' : ''}>${z * 100}%</button>`).join('')}
          <span class="muted">Click exactly on the tick mark of a number you can read, then type its value.</span>
        </div>
        <div class="stripbox" id="sbox">
          <div class="stripinner" id="sin">
            <img id="simg" src="/api/projects/${P.id}/strip/${encodeURIComponent(p.name)}?v=${v}" draggable="false">
          </div>
        </div>
        <div class="row" style="margin-top:12px; align-items:flex-start; gap:24px">
          <div>
            <b>Readings</b> <span class="muted">(at least 2, ideally 3–5 spread along the photo)</span>
            <table id="rtab">${p.readings.length ? p.readings.map((r, j) => `
              <tr><td>${esc(r.raw)}</td><td class="muted">= ${fmt(r.cm, 1)} cm</td><td><button data-del="${j}">delete</button></td></tr>`).join('')
              : '<tr><td class="muted">none yet</td></tr>'}</table>
          </div>
          <div>
            <div class="ctx" id="ctx" title="Click to fix the tape line">
              <img src="/api/projects/${P.id}/thumb/${encodeURIComponent(p.name)}">${tapeSvg(p)}</div>
            <div class="row" style="margin-top:6px">
              <button id="bFix">Fix tape line</button>
              <button id="bSkip">${p.skip ? 'Un-skip' : 'Skip photo'}</button>
            </div>
          </div>
          <div class="help" style="max-width:520px">
            <b>What to type</b> – the full distance along the tape:<br>
            • Metric side: black <b>10 … 90</b> are tens of cm within the metre; the red <b>N m</b> is the metre mark.
              e.g. the "60" after the red "7 m" → type <b>760</b> (or <b>7.6m</b>). The red "7 m" itself → <b>7m</b>.<br>
            • Imperial side (tape flipped over): red <b>N FT</b> marks whole feet; black <b>1–11</b> are inches.
              e.g. the "7" after red "12 FT" → type <b>12ft 7in</b> (or <b>12'7</b>). It's converted to cm for you.<br>
            Keys: <kbd>Enter</kbd> save, <kbd>Esc</kbd> cancel, <kbd>←</kbd>/<kbd>→</kbd> previous/next photo.
          </div>
        </div>
      </div>
    </div>
  </div>`;

  document.querySelector('.plist .sel')?.scrollIntoView({block: 'nearest'});
  const img = document.getElementById('simg'), sin = document.getElementById('sin');
  const place = () => {
    img.style.width = `${img.naturalWidth * zoom}px`;
    sin.querySelectorAll('.mk').forEach(m => m.remove());
    p.readings.forEach(r => {
      const m = document.createElement('div'); m.className = 'mk'; m.style.left = `${r.sx * zoom}px`;
      m.innerHTML = `<span>${esc(r.raw)}</span>`; sin.appendChild(m);
    });
  };
  img.onload = place; if (img.complete && img.naturalWidth) place();
  sin.onclick = e => {
    if (e.target.closest('.pop')) return;
    const rect = img.getBoundingClientRect();
    const sx = (e.clientX - rect.left) / zoom;
    openPop(p, sx, e.clientX - sin.getBoundingClientRect().left, e.clientY - rect.top);
  };
  document.querySelectorAll('.plist div').forEach(d => d.onclick = () => { cur = d.dataset.n; renderRead(); });
  document.querySelectorAll('button[data-z]').forEach(b => b.onclick = () => {
    const box = document.getElementById('sbox'), frac = (box.scrollLeft + box.clientWidth / 2) / (img.naturalWidth * zoom);
    zoom = parseFloat(b.dataset.z); renderRead();
    const nb = document.getElementById('sbox'); requestAnimationFrame(() => nb.scrollLeft = frac * img.naturalWidth * zoom - nb.clientWidth / 2);
  });
  document.querySelectorAll('button[data-del]').forEach(b => b.onclick = async () => {
    P = await post(`/api/projects/${P.id}/photo/${encodeURIComponent(p.name)}`, {delete_reading: +b.dataset.del}); renderRead();
  });
  document.getElementById('bPrev').onclick = () => { cur = list[i - 1].name; renderRead(); };
  document.getElementById('bNext').onclick = () => { cur = list[i + 1].name; renderRead(); };
  document.getElementById('bSkip').onclick = async () => {
    P = await post(`/api/projects/${P.id}/photo/${encodeURIComponent(p.name)}`, {skip: !p.skip}); renderRead();
  };
  document.getElementById('bFix').onclick = document.getElementById('ctx').onclick = () => fixTape(p);
}

function openPop(p, sx, left, top) {
  document.querySelectorAll('.pop').forEach(x => x.remove());
  const sin = document.getElementById('sin');
  const pop = document.createElement('div'); pop.className = 'pop';
  pop.style.left = `${Math.max(0, left - 70)}px`; pop.style.top = `${Math.max(0, top + 12)}px`;
  pop.innerHTML = `<input type="text" placeholder="e.g. 760 or 12ft 7in"><div class="parsed">&nbsp;</div>`;
  sin.appendChild(pop);
  const mk = document.createElement('div'); mk.className = 'mk'; mk.style.left = `${sx * zoom}px`; mk.style.borderColor = '#ffd60a';
  sin.appendChild(mk);
  const inp = pop.querySelector('input'), out = pop.querySelector('.parsed');
  inp.focus();
  inp.oninput = () => { const v = parseTape(inp.value); out.textContent = v == null ? (inp.value ? 'not understood' : ' ') : `= ${v.toFixed(1)} cm`; };
  const close = () => { pop.remove(); mk.remove(); };
  inp.onkeydown = async e => {
    e.stopPropagation();
    if (e.key === 'Escape') close();
    if (e.key === 'Enter') {
      if (parseTape(inp.value) == null) { out.textContent = 'not understood – try 760, 7.6m or 12ft 7in'; return; }
      try {
        P = await post(`/api/projects/${P.id}/photo/${encodeURIComponent(p.name)}`, {add_reading: {sx, raw: inp.value}});
        const box = document.getElementById('sbox'), sl = box.scrollLeft;
        renderRead(); document.getElementById('sbox').scrollLeft = sl;
      } catch (err) { out.textContent = err.message; }
    }
  };
}

function fixTape(p) {
  const m = document.createElement('div'); m.className = 'modal';
  m.innerHTML = `<div class="box">
    <div class="row" style="justify-content:space-between; margin-bottom:8px">
      <b>Click two points on the tape, as far apart as you can.</b>
      <div class="row"><button id="fxReset">Reset</button><button id="fxCancel">Cancel</button><button class="primary" id="fxSave" disabled>Save</button></div>
    </div>
    <div class="fixwrap" id="fxw"><img id="fximg" src="/api/projects/${P.id}/work/${encodeURIComponent(p.name)}"><svg id="fxsvg"></svg></div>
  </div>`;
  document.body.appendChild(m);
  let pts = [];
  const img = m.querySelector('#fximg'), svg = m.querySelector('#fxsvg');
  const draw = () => {
    svg.setAttribute('viewBox', `0 0 ${p.W} ${p.H}`);
    svg.innerHTML = pts.map(([x, y]) => `<circle cx="${x}" cy="${y}" r="${p.W / 120}" fill="#ff2d55"/>`).join('') +
      (pts.length === 2 ? `<line x1="${pts[0][0]}" y1="${pts[0][1]}" x2="${pts[1][0]}" y2="${pts[1][1]}" stroke="#ff2d55" stroke-width="${p.W / 300}"/>` : '');
    m.querySelector('#fxSave').disabled = pts.length !== 2;
  };
  m.querySelector('#fxw').onclick = e => {
    if (pts.length >= 2) return;
    const r = img.getBoundingClientRect();
    pts.push([(e.clientX - r.left) / r.width * p.W, (e.clientY - r.top) / r.height * p.H]); draw();
  };
  m.querySelector('#fxReset').onclick = () => { pts = []; draw(); };
  m.querySelector('#fxCancel').onclick = () => m.remove();
  m.querySelector('#fxSave').onclick = async () => {
    try {
      P = await post(`/api/projects/${P.id}/photo/${encodeURIComponent(p.name)}`, {tape: pts});
      stripVersion[p.name] = (stripVersion[p.name] || 0) + 1; m.remove(); renderRead();
    } catch (err) { alert(err.message); }
  };
  draw();
}

document.addEventListener('keydown', e => {
  if (tab !== 'read' || !P || document.activeElement.tagName === 'INPUT' || document.querySelector('.modal')) return;
  if (e.key === 'ArrowLeft') document.getElementById('bPrev')?.click();
  if (e.key === 'ArrowRight') document.getElementById('bNext')?.click();
});

// ---------------------------------------------------------------- tab 3
function renderBuild() {
  const inc = P.photos.filter(p => p.include && !p.skip);
  const n = s => inc.filter(p => p.status === s).length;
  const b = P.build || {};
  document.getElementById('tabBody').innerHTML = `
  <div class="card">
    <h2>Build the image</h2>
    <p>${n('ok')} photo(s) ready, <span class="${n('check') ? 'warn' : ''}">${n('check')} to check</span>,
       <span class="${n('todo') ? 'warn' : ''}">${n('todo')} without enough readings</span> (those are left out),
       ${P.photos.filter(p => p.skip && p.include).length} skipped.</p>
    <div class="row">
      <label>Pixels per cm <input type="number" id="oPx" value="${b.pxcm || 20}" min="2" max="60" style="width:70px"></label>
      <label>Width each side of tape (cm) <input type="number" id="oHw" value="42" min="10" max="150" style="width:70px"></label>
      <button class="primary" id="bBuild" ${b.status === 'running' ? 'disabled' : ''}>Build</button>
    </div>
    <p class="muted">20 px/cm makes a 20 m transect about 40,000 px wide (≈30 MB). Takes about a minute.</p>
    <div id="bstat"></div>
  </div>`;
  document.getElementById('bBuild').onclick = async () => {
    try {
      await post(`/api/projects/${P.id}/build`, {pxcm: +document.getElementById('oPx').value, half_width_cm: +document.getElementById('oHw').value});
      poll();
    } catch (err) { alert(err.message); }
  };
  showBuild();
  if (b.status === 'running') poll();
}

function showBuild() {
  const b = P.build || {}, el = document.getElementById('bstat');
  if (!el || !b.status) return;
  if (b.status === 'running') {
    el.innerHTML = `<div class="bar" style="margin-top:10px"><div style="width:${100 * b.progress}%"></div></div><p class="muted">${esc(b.message)}</p>`;
  } else if (b.status === 'error') {
    el.innerHTML = `<p class="err">Build failed: ${esc(b.message)}</p>`;
  } else if (b.status === 'done') {
    const u = f => `/api/projects/${P.id}/output/${encodeURIComponent(f)}`;
    const inApp = !!(window.pywebview && window.pywebview.api);
    const cls = f => `btn ${/marked/.test(f) ? 'primary' : ''}`;
    const buttons = inApp
      ? b.outputs.map(f => `<button class="${cls(f)}" data-save="${esc(f)}">Save ${esc(f)}…</button>`).join('')
      : b.outputs.map(f => `<a class="${cls(f)}" href="${u(f)}?dl=1">Download ${esc(f)}</a>`).join('');
    el.innerHTML = `
      ${(b.warnings || []).map(w => `<p class="warn">⚠ ${esc(w)}</p>`).join('')}
      <p>Done: ${b.size[0].toLocaleString()} × ${b.size[1].toLocaleString()} px, tape ${fmt(b.cm0)}–${fmt(b.cm1)} cm at ${b.pxcm} px/cm.</p>
      <div class="row" style="margin-bottom:10px">${buttons}<button id="bReveal">Show files in Finder</button><span id="saveMsg" class="muted"></span></div>
      <div class="preview"><img src="${u(b.preview)}?t=${Date.now()}"></div>
      <p class="muted">Preview is reduced – save the full image to zoom in.</p>`;
    el.querySelectorAll('button[data-save]').forEach(btn => btn.onclick = async () => {
      const r = await window.pywebview.api.save_output(P.id, btn.dataset.save);
      if (r && r.saved) document.getElementById('saveMsg').textContent = `Saved to ${r.path}`;
    });
    document.getElementById('bReveal').onclick = () => post(`/api/projects/${P.id}/reveal`, {});
  }
}
// the app window's bridge can arrive after the page renders – redraw the build buttons when it does
window.addEventListener('pywebviewready', () => { if (P && tab === 'build') showBuild(); });

function poll() {
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    await refresh();
    if (tab === 'build') { document.getElementById('bBuild') && (document.getElementById('bBuild').disabled = P.build.status === 'running'); showBuild(); }
    if (P.build.status !== 'running') clearInterval(pollTimer);
  }, 1000);
}

// open straight into a project if the URL says so (e.g. after a refresh): #<project>/<tab>
(function start() {
  const m = location.hash.match(/^#([a-z0-9]+)\/(photos|read|build)(?:\/(.+))?$/);
  if (m) { tab = m[2]; cur = m[3] ? decodeURIComponent(m[3]) : null; openProject(m[1], true).catch(goHome); } else goHome();
})();
