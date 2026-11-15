// NEON File Share: the phone page. Plain HTTP on the home network, so every byte is end-to-end encrypted here
// (X25519 + HKDF-SHA256 + ChaCha20-Poly1305 from @noble, bundled offline). Protocol: src/neontorrent/share.py.
import { x25519 } from '@noble/curves/ed25519.js';
import { chacha20poly1305 } from '@noble/ciphers/chacha.js';
import { hkdf } from '@noble/hashes/hkdf.js';
import { sha256 } from '@noble/hashes/sha2.js';

const CHUNK = 1 << 20;
const te = new TextEncoder();
const td = new TextDecoder();
const $ = (id) => document.getElementById(id);

// ------------------------------------------------------------------ encoding and crypto
function b64e(u8) {
  let s = '';
  for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
function b64d(s) {
  s = String(s).replace(/-/g, '+').replace(/_/g, '/');
  while (s.length % 4) s += '=';
  const bin = atob(s);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}
function cat(...parts) {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let o = 0;
  for (const p of parts) { out.set(p, o); o += p.length; }
  return out;
}
function u64(view, at, value) { view.setUint32(at, Math.floor(value / 4294967296)); view.setUint32(at + 4, value >>> 0); }
function nonce(kind, number, index) {            // kind | file number (3 bytes) | index (8 bytes)
  const n = new Uint8Array(12);
  n[0] = kind; n[1] = (number >>> 16) & 255; n[2] = (number >>> 8) & 255; n[3] = number & 255;
  u64(new DataView(n.buffer), 4, index);
  return n;
}
function chunkAad(dir, number, index, chunks) {
  const tail = new Uint8Array(20);
  const v = new DataView(tail.buffer);
  v.setUint32(0, number); u64(v, 4, index); u64(v, 12, chunks);
  return cat(te.encode('NEON-FILE-1' + dir), tail);
}

let S = null;                // {pk, up, dn, sid, ctr}: the paired session, kept for reloads in sessionStorage
let upKey = null, dnKey = null;
const saveSession = () => sessionStorage.setItem('neon.s', JSON.stringify(S));
const sealCtl = (obj, ctr, aad) => b64e(chacha20poly1305(upKey, nonce(1, 0, ctr), aad).encrypt(te.encode(JSON.stringify(obj))));
const openCtl = (s, ctr, aad) => JSON.parse(td.decode(chacha20poly1305(dnKey, nonce(2, 0, ctr), aad).decrypt(b64d(s))));

class HttpError extends Error { constructor(status, message) { super(message); this.status = status; } }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function http(url, opts = {}, ms = 20000) {
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), ms);
  if (opts.signal) { if (opts.signal.aborted) ac.abort(); else opts.signal.addEventListener('abort', () => ac.abort()); }
  try { return await fetch(url, { ...opts, signal: ac.signal, cache: 'no-store', credentials: 'omit' }); }
  finally { clearTimeout(timer); }
}
async function postJson(url, obj) {
  const r = await http(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(obj) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new HttpError(r.status, j.error || 'HTTP ' + r.status);
  return j;
}

// control calls run one at a time: the PC refuses a counter that is not higher than the last one it saw
let queue = Promise.resolve();
function call(msg) { const run = queue.then(() => rawCall(msg)); queue = run.catch(() => {}); return run; }
async function rawCall(msg) {
  const c = ++S.ctr;
  saveSession();
  const j = await postJson('/api/c', { s: S.sid, c, d: sealCtl(msg, c, te.encode(`C${S.sid}:${c}`)) });
  const out = openCtl(j.d, j.c, te.encode(`R${S.sid}:${c}`));
  if (out.error) throw new HttpError(0, out.error);
  return out;
}

async function hello(pk, token) {
  const sk = x25519.utils.randomSecretKey();
  const pub = x25519.getPublicKey(sk);
  const okm = hkdf(sha256, x25519.getSharedSecret(sk, pk), token, cat(te.encode('NEON-SHARE-1'), pk, pub), 64);
  upKey = okm.slice(0, 32); dnKey = okm.slice(32);
  const info = te.encode(JSON.stringify({ name: deviceName(), model: MODEL }));
  const d = b64e(chacha20poly1305(upKey, nonce(1, 0, 0), cat(te.encode('H'), pk, pub)).encrypt(info));
  const j = await postJson('/api/hello', { p: b64e(pub), d });
  const reply = openCtl(j.d, j.c, te.encode(`R${j.s}:0`));     // proves the PC holds the key from the QR code
  S = { pk: b64e(pk), up: b64e(upKey), dn: b64e(dnKey), sid: j.s, ctr: 0 };
  saveSession();
  return reply;
}

// ------------------------------------------------------------------ device
function guessModel() {
  const ua = navigator.userAgent;
  let device = 'Phone', browser = '';
  let m;
  if (/iPhone/.test(ua)) device = 'iPhone';
  else if (/iPad/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)) device = 'iPad';
  else if ((m = ua.match(/Android [\d.]+;\s*([^;)]+)\)/))) device = m[1].trim() === 'K' ? 'Android phone' : m[1].trim();
  else if (/Android/.test(ua)) device = 'Android phone';
  if ((m = ua.match(/SamsungBrowser\/([\d]+)/))) browser = 'Samsung Internet ' + m[1];
  else if ((m = ua.match(/(?:CriOS|Chrome)\/([\d]+)/))) browser = 'Chrome ' + m[1];
  else if ((m = ua.match(/(?:FxiOS|Firefox)\/([\d]+)/))) browser = 'Firefox ' + m[1];
  else if ((m = ua.match(/Version\/([\d.]+).*Safari/))) browser = 'Safari ' + m[1];
  return (browser ? `${device} · ${browser}` : device).slice(0, 60);
}
const MODEL = guessModel();
const deviceName = () => localStorage.getItem('neon.name') || MODEL.split(' · ')[0];

// ------------------------------------------------------------------ formatting and files
function fmtBytes(n) {
  if (n < 1024) return `${n} B`;
  const u = ['KB', 'MB', 'GB', 'TB'];
  let i = -1;
  do { n /= 1024; i++; } while (n >= 1024 && i < u.length - 1);
  return `${n >= 100 ? n.toFixed(0) : n.toFixed(1)} ${u[i]}`;
}
function fmtEta(sec) {
  if (!isFinite(sec) || sec <= 0) return '—';
  if (sec < 60) return `about ${Math.ceil(sec)} s left`;
  if (sec < 3600) return `about ${Math.round(sec / 60)} min left`;
  return `about ${Math.floor(sec / 3600)} h ${Math.round((sec % 3600) / 60)} min left`;
}
const fmtDur = (s) => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
const EXT = {
  image: 'jpg jpeg png gif webp heic heif bmp avif tif tiff', video: 'mp4 mov mkv webm avi m4v 3gp ts',
  audio: 'mp3 m4a wav flac aac ogg opus amr', pdf: 'pdf', archive: 'zip rar 7z tar gz tgz bz2 xz iso',
  apk: 'apk apks xapk', doc: 'doc docx xls xlsx ppt pptx txt rtf odt ods csv md json',
};
const KIND = {
  image: { icon: 'image', text: 'text-primary', box: 'w-9 h-9 rounded-[8px] flex items-center justify-center mb-1 border bg-primary-container/15 border-primary-container/40 text-primary' },
  video: { icon: 'video', text: 'text-secondary', box: 'w-9 h-9 rounded-[8px] flex items-center justify-center mb-1 border bg-secondary-container/20 border-secondary/40 text-secondary' },
  audio: { icon: 'music', text: 'text-tertiary', box: 'w-9 h-9 rounded-[8px] flex items-center justify-center mb-1 border bg-tertiary/15 border-tertiary/40 text-tertiary' },
  pdf: { icon: 'pdf', text: 'text-secondary', box: 'w-9 h-9 rounded-[8px] flex items-center justify-center mb-1 border bg-secondary-container/20 border-secondary/40 text-secondary' },
  archive: { icon: 'zip', text: 'text-primary-fixed', box: 'w-9 h-9 rounded-[8px] flex items-center justify-center mb-1 border bg-primary-container/15 border-primary-container/40 text-primary' },
  apk: { icon: 'box', text: 'text-tertiary', box: 'w-9 h-9 rounded-[8px] flex items-center justify-center mb-1 border bg-tertiary/15 border-tertiary/40 text-tertiary' },
  doc: { icon: 'file', text: 'text-primary', box: 'w-9 h-9 rounded-[8px] flex items-center justify-center mb-1 border bg-primary-container/15 border-primary-container/40 text-primary' },
  other: { icon: 'file', text: 'text-on-surface-variant', box: 'w-9 h-9 rounded-[8px] flex items-center justify-center mb-1 border bg-surface-container-highest border-outline-variant text-on-surface-variant' },
};
function kindOf(name, mime) {
  const ext = (name.split('.').pop() || '').toLowerCase();
  for (const [k, list] of Object.entries(EXT)) if (name.includes('.') && list.split(' ').includes(ext)) return k;
  if (mime) for (const k of ['image', 'video', 'audio']) if (mime.startsWith(k + '/')) return k;
  return 'other';
}
const extLabel = (name) => (name.includes('.') ? name.split('.').pop().slice(0, 5).toUpperCase() : 'FILE');
const icon = (name, cls) => `<svg class="ico ${cls}"><use href="#i-${name}"/></svg>`;
function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; }

function toast(text) {
  const t = $('toast');
  t.textContent = text;
  t.classList.remove('hidden');
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => t.classList.add('hidden'), 3500);
}

// ------------------------------------------------------------------ overlay
function overlay(opts) {
  if (!opts) { $('overlay').classList.add('hidden'); overlay.kind = ''; return; }
  overlay.kind = opts.kind;
  $('ov-icon').innerHTML = icon(opts.icon || 'lock', 'w-6 h-6');
  $('ov-title').textContent = opts.title;
  $('ov-text').textContent = opts.text || '';
  const input = $('ov-input'), btn = $('ov-btn');
  input.classList.toggle('hidden', !opts.input);
  if (opts.input) { input.value = opts.input; setTimeout(() => input.focus(), 50); }
  btn.classList.toggle('hidden', !opts.button);
  btn.textContent = opts.button || '';
  btn.onclick = opts.onButton || null;
  $('overlay').classList.remove('hidden');
}

// ------------------------------------------------------------------ connection state
let mode = 'send';
let state = 'none';          // none / pending / allowed / denied / ended
let online = false;
let pcName = 'PC', pcIp = '';
let rev = -1;
let pinger = 0;

const PILL = {
  ok: 'shrink-0 flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-tertiary/10 border border-tertiary/30 text-tertiary font-label-sm text-label-sm font-semibold uppercase',
  busy: 'shrink-0 flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-primary-container/10 border border-primary-container/40 text-primary font-label-sm text-label-sm font-semibold uppercase',
  wait: 'shrink-0 flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-amber-400/10 border border-amber-400/30 text-amber-300 font-label-sm text-label-sm font-semibold uppercase',
  bad: 'shrink-0 flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-error/10 border border-error/30 text-error font-label-sm text-label-sm font-semibold uppercase',
};
const DOT = {
  ok: 'inline-block w-1.5 h-1.5 rounded-full bg-tertiary neon-pulse shrink-0',
  wait: 'inline-block w-1.5 h-1.5 rounded-full bg-amber-300 shrink-0',
  bad: 'inline-block w-1.5 h-1.5 rounded-full bg-error shrink-0',
};

function renderConn() {
  let title, sub = pcIp ? `IP: ${pcIp}` : '', pill, pillText, dot;
  if (state === 'allowed' && online) {
    title = `CONNECTED to ${pcName}`; dot = 'ok';
    if (up.running) { pill = 'ok'; pillText = 'Sending'; }
    else if (dn.running) { pill = 'busy'; pillText = 'Receiving'; }
    else { pill = 'ok'; pillText = 'Ready'; }
  } else if (state === 'pending') { title = `Waiting for ${pcName}`; sub = 'Allow this phone on the PC'; pill = 'wait'; pillText = 'Waiting'; dot = 'wait'; }
  else if (state === 'allowed') { title = `${pcName} not reachable`; sub = 'Same Wi-Fi? Retrying…'; pill = 'bad'; pillText = 'Offline'; dot = 'bad'; }
  else if (state === 'denied') { title = 'Declined by the PC'; pill = 'bad'; pillText = 'Declined'; dot = 'bad'; }
  else { title = 'Not connected'; sub = 'Scan the QR code on the PC'; pill = 'bad'; pillText = 'Offline'; dot = 'bad'; }
  $('conn-title').textContent = title;
  $('conn-sub').textContent = sub;
  $('pill').className = PILL[pill];
  $('pill').textContent = pillText;
  $('conn-dot').className = DOT[dot];
  const good = dot === 'ok';
  $('hdr-dot').className = good ? 'neon-pulse absolute inline-flex h-full w-full rounded-full bg-tertiary opacity-75' : 'absolute inline-flex h-full w-full rounded-full bg-error opacity-0';
  $('hdr-dot2').className = good ? 'relative inline-flex rounded-full h-2 w-2 bg-tertiary' : 'relative inline-flex rounded-full h-2 w-2 bg-error';
  renderButtons();
}

function applyStatus(r) {
  if (r.pc) { pcName = r.pc.name || 'PC'; pcIp = r.pc.ip || ''; }
  const prev = state;
  state = r.state;
  if (state === 'pending') {
    overlay({ kind: 'wait', icon: 'lock', title: 'Allow this phone on the PC',
      text: `${pcName} is asking whether to allow “${deviceName()}”. Accept it there; keep this page open.` });
  } else if (state === 'denied') {
    overlay({ kind: 'denied', icon: 'cancel', title: 'The PC declined this phone', text: 'If that was a mistake, scan the QR code on the PC again.' });
    stopPing();
  } else if (state === 'allowed') {
    if (prev !== 'allowed' && overlay.kind === 'wait') overlay(null);
    if (mode === 'recv' && r.rev !== rev) loadList();
    if (typeof r.trev === 'number' && r.trev > textRev) loadTexts();
  }
  renderConn();
}

async function ping() {
  if (!S) return;
  try {
    applyStatus(await call({ op: 'ping', name: deviceName(), mode }));
    online = true;
  } catch (e) {
    if (e.status === 401) return sessionEnded();
    online = false;
  }
  renderConn();
}
function startPing() { stopPing(); ping(); pinger = setInterval(ping, 2000); }
function stopPing() { clearInterval(pinger); pinger = 0; }

function sessionEnded() {
  stopPing();
  state = 'ended';
  sessionStorage.removeItem('neon.s');
  S = null;
  abortAll();
  overlay({ kind: 'ended', icon: 'qr', title: 'Session ended', text: 'The PC closed this session. Scan the QR code on the PC again to reconnect.' });
  renderConn();
}

// ------------------------------------------------------------------ tiles
// One tile for every grid: thumbnail or type icon, X at the top right, optional checkbox, progress, ✓ when done.
function makeTile(item, opts) {
  const root = el('div');
  const box = el('div', 'relative aspect-square w-full rounded-[10px] overflow-hidden bg-surface-container-highest');
  const media = el('div', 'absolute inset-0 flex flex-col items-center justify-center');
  box.appendChild(media);
  const badge = el('span', 'absolute bottom-1 left-1 px-1 rounded bg-surface-container-lowest/85 font-label-sm text-[8px] text-primary tracking-widest border border-primary-container/20');
  box.appendChild(badge);
  const shade = el('div', 'hidden absolute inset-0 bg-surface-container-lowest/45 flex items-center justify-center');
  box.appendChild(shade);
  const bar = el('div', 'absolute bottom-0 left-0 h-1 bg-gradient-to-r from-primary-container to-secondary-container transition-[width] duration-300');
  bar.style.width = '0%';
  box.appendChild(bar);
  const x = el('button', 'absolute top-1 right-1 w-6 h-6 rounded-full bg-surface-container-lowest/80 text-on-surface flex items-center justify-center active:scale-90');
  x.innerHTML = icon('x', 'w-3.5 h-3.5');
  x.setAttribute('aria-label', `Remove ${item.name}`);
  x.onclick = (e) => { e.stopPropagation(); opts.onX(item); };
  box.appendChild(x);
  let check = null;
  if (opts.onCheck) {
    check = el('button', '');
    check.setAttribute('aria-label', `Select ${item.name}`);
    check.onclick = (e) => { e.stopPropagation(); opts.onCheck(item); };
    box.appendChild(check);
  }
  root.appendChild(box);
  const meta = el('div', 'mt-1.5 px-0.5');
  const name = el('div', 'font-body-sm text-[11px] font-medium text-on-surface truncate', item.name);
  name.title = item.name;
  const sub = el('div', 'font-label-sm text-[9px] text-outline truncate');
  meta.append(name, sub);
  root.appendChild(meta);
  item.ui = { root, media, badge, shade, bar, x, check, name, sub };
  paintThumb(item);
  return root;
}

function paintThumb(item) {
  const { media, badge } = item.ui;
  media.textContent = '';
  const k = KIND[item.kind];
  if (item.thumb) {
    const img = el('img', 'w-full h-full object-cover');
    img.alt = '';
    img.decoding = 'async';
    img.onerror = () => { item.thumb = null; paintThumb(item); };
    img.src = item.thumb;
    media.appendChild(img);
    if (item.kind === 'video') {
      const play = el('div', 'absolute w-7 h-7 rounded-full bg-primary-container/90 text-surface-container-lowest flex items-center justify-center shadow-[0_0_10px_rgba(34,211,238,0.7)]');
      play.innerHTML = icon('play', 'w-4 h-4');
      media.appendChild(play);
    }
  } else {
    const b = el('div', k.box);
    b.innerHTML = icon(k.icon, 'w-5 h-5');
    media.append(b, el('span', `font-label-sm text-[9px] font-bold uppercase tracking-wider ${k.text}`, extLabel(item.name)));
  }
  badge.textContent = item.dur ? fmtDur(item.dur) : extLabel(item.name);
  badge.classList.toggle('hidden', !item.thumb);
}

const TILE = {
  idle: 'group relative flex flex-col bg-surface-container-low rounded-[14px] border border-primary-container/30 p-1.5 overflow-hidden',
  off: 'group relative flex flex-col bg-surface-container-low rounded-[14px] border border-outline-variant/40 p-1.5 overflow-hidden opacity-50',
  active: 'group relative flex flex-col bg-surface-container-low rounded-[14px] border-2 border-primary-container p-1.5 overflow-hidden shadow-[0_0_16px_rgba(34,211,238,0.5)]',
  done: 'group relative flex flex-col bg-surface-container-low rounded-[14px] border border-outline-variant/30 p-1.5 overflow-hidden opacity-70',
  bad: 'group relative flex flex-col bg-surface-container-low rounded-[14px] border border-error/40 p-1.5 overflow-hidden opacity-70',
};
const CHECK_ON = 'absolute top-1 left-1 w-6 h-6 rounded-[6px] bg-surface-container-lowest/85 border border-primary-container text-primary flex items-center justify-center';
const CHECK_OFF = 'absolute top-1 left-1 w-6 h-6 rounded-[6px] bg-surface-container-lowest/70 border border-outline text-transparent flex items-center justify-center';

function paintTile(item, done) {
  const u = item.ui;
  if (!u) return;
  const pct = item.size ? Math.min(100, Math.floor((item.moved / item.size) * 100)) : (item.state === 'done' ? 100 : 0);
  let cls = TILE.idle, sub = fmtBytes(item.size), shade = '';
  if (item.state === 'queued') sub = 'Waiting…';
  else if (item.state === 'active') { cls = TILE.active; sub = `${fmtBytes(item.moved)} / ${fmtBytes(item.size)}`; shade = 'pct'; }
  else if (item.state === 'done') { cls = TILE.done; sub = `${done} · ${fmtBytes(item.size)}`; shade = 'check'; }
  else if (item.state === 'cancelled') { cls = TILE.bad; sub = item.error || 'Cancelled'; }
  else if (item.state === 'failed') { cls = TILE.bad; sub = item.error || 'Failed'; }
  else if (item.sel === false) cls = TILE.off;
  u.root.className = cls;
  u.sub.textContent = sub;
  u.sub.className = item.state === 'done' ? 'font-label-sm text-[9px] text-tertiary truncate'
    : item.state === 'active' ? 'font-label-sm text-[9px] text-primary-fixed truncate' : 'font-label-sm text-[9px] text-outline truncate';
  u.bar.style.width = item.state === 'active' ? `${pct}%` : '0%';
  if (shade !== u.shadeKind) {
    u.shadeKind = shade;
    u.shade.classList.toggle('hidden', !shade);
    u.shade.innerHTML = shade === 'check'
      ? `<div class="w-7 h-7 rounded-full bg-tertiary/20 border border-tertiary text-tertiary flex items-center justify-center shadow-[0_0_8px_#39fb88]">${icon('check', 'w-4 h-4')}</div>`
      : shade === 'pct' ? '<span class="px-1.5 py-0.5 rounded bg-surface-container-lowest/90 font-label-sm text-[10px] font-bold text-primary"></span>' : '';
  }
  if (shade === 'pct') u.shade.firstChild.textContent = `${pct}%`;
  u.x.classList.toggle('hidden', item.state === 'done');
  if (u.check) {
    u.check.className = item.sel ? CHECK_ON : CHECK_OFF;
    u.check.innerHTML = icon('check', 'w-4 h-4');
    u.check.classList.toggle('hidden', item.state === 'active' || item.state === 'done');
  }
}

// ------------------------------------------------------------------ thumbnails made on the phone
let thumbing = false;
async function makeThumbs() {
  if (thumbing) return;
  thumbing = true;
  for (const it of picked) {
    if (it.thumbTried) continue;
    it.thumbTried = true;
    if (it.kind === 'image') { it.thumb = URL.createObjectURL(it.file); it.ownUrl = it.thumb; }
    else if (it.kind === 'video') it.thumb = await videoFrame(it);
    if (it.ui) paintThumb(it);
  }
  thumbing = false;
}
function videoFrame(it) {
  return new Promise((resolve) => {
    const v = document.createElement('video');
    const url = URL.createObjectURL(it.file);
    let finished = false;
    const finish = (data) => {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      v.removeAttribute('src'); v.load();
      URL.revokeObjectURL(url);
      resolve(data);
    };
    const timer = setTimeout(() => finish(null), 7000);
    v.muted = true; v.playsInline = true; v.preload = 'auto';
    v.onloadedmetadata = () => {
      it.dur = isFinite(v.duration) ? v.duration : 0;
      try { v.currentTime = Math.min(1, (v.duration || 1) / 10); } catch { finish(null); }
    };
    v.onseeked = () => {
      try {
        const w = v.videoWidth, h = v.videoHeight;
        if (!w || !h) return finish(null);
        const c = document.createElement('canvas'), size = 240, k = size / Math.min(w, h);
        c.width = size; c.height = size;
        c.getContext('2d').drawImage(v, (size - w * k) / 2, (size - h * k) / 2, w * k, h * k);
        finish(c.toDataURL('image/jpeg', 0.72));
      } catch { finish(null); }
    };
    v.onerror = () => finish(null);
    v.src = url;
  });
}

// ------------------------------------------------------------------ SEND (phone -> PC)
let picked = [];             // {file, name, size, kind, thumb, state, moved, n, error, ui}
const up = { running: false, cancelAll: false, batch: [], index: 0, current: null, ac: null, samples: [], total: 0, moved: 0 };

$('picker').onchange = () => {
  for (const f of $('picker').files) {
    picked.push({ file: f, name: f.name || 'file', size: f.size, kind: kindOf(f.name || '', f.type), state: 'ready', moved: 0 });
  }
  $('picker').value = '';
  if (!up.running) showSendList();
  makeThumbs();
};
$('send-clear').onclick = () => { picked.forEach(releaseThumb); picked = []; renderSend(); };
function releaseThumb(it) { if (it.ownUrl) URL.revokeObjectURL(it.ownUrl); it.ownUrl = null; }

function renderSend() {
  const grid = $('send-grid');
  grid.textContent = '';
  for (const it of picked) {
    grid.appendChild(makeTile(it, { onX: (item) => { releaseThumb(item); picked = picked.filter((p) => p !== item); renderSend(); } }));
    paintTile(it, 'Sent');
  }
  const total = picked.reduce((n, p) => n + p.size, 0);
  $('send-head').classList.toggle('hidden', !picked.length);
  $('send-summary').classList.toggle('hidden', !picked.length);
  $('send-count').textContent = `${picked.length} ${picked.length === 1 ? 'ITEM' : 'ITEMS'}`;
  $('send-total').textContent = `${picked.length} ${picked.length === 1 ? 'file' : 'files'} · ${fmtBytes(total)}`;
  $('btn-send-text').textContent = picked.length ? `SEND TO PC (${fmtBytes(total)})` : 'SEND TO PC';
  renderButtons();
}

function showSendList() {
  picked = picked.filter((p) => p.state !== 'done');
  picked.forEach((p) => { p.state = 'ready'; p.moved = 0; p.error = ''; });
  up.batch = [];
  showView();
  renderSend();
}

async function sendAll() {
  if (state !== 'allowed' || !online) return toast('The PC has not allowed this phone yet.');
  const batch = picked.filter((p) => p.state === 'ready');
  if (!batch.length || up.running) return;
  batch.forEach((p) => { p.state = 'queued'; p.moved = 0; p.error = ''; });
  Object.assign(up, { running: true, cancelAll: false, batch, index: 0, samples: [], moved: 0,
    total: batch.reduce((n, p) => n + p.size, 0) });
  showView();
  renderSending(true);
  for (let k = 0; k < batch.length && !up.cancelAll; k++) {
    if (batch[k].state !== 'queued') continue;
    up.index = k;
    await uploadOne(batch[k]);
    renderSending(false);
  }
  up.running = false; up.current = null;
  renderSending(false);
  renderConn();
  const sent = batch.filter((p) => p.state === 'done').length;
  toast(sent === batch.length ? `All ${sent} files are on the PC.` : `${sent} of ${batch.length} files sent.`);
}

async function sealChunk(it, i, chunks) {
  const data = new Uint8Array(await it.file.slice(i * CHUNK, Math.min(it.size, (i + 1) * CHUNK)).arrayBuffer());
  return chacha20poly1305(upKey, nonce(3, it.n, i), chunkAad('up', it.n, i, chunks)).encrypt(data);
}

async function uploadOne(it) {
  it.state = 'active';
  up.current = it;
  up.ac = new AbortController();
  renderSending(false);
  let chunks;
  try {
    const begin = await call({ op: 'begin', name: it.name, size: it.size });
    it.n = begin.n; chunks = begin.chunks;
  } catch (e) {
    if (e.status === 401) return sessionEnded();
    it.state = 'failed'; it.error = e.message; return;
  }
  let next = sealChunk(it, 0, chunks);
  for (let i = 0; i < chunks && it.state === 'active'; i++) {
    let body;
    try { body = await next; } catch { it.state = 'failed'; it.error = 'Could not read the file'; break; }
    if (i + 1 < chunks) next = sealChunk(it, i + 1, chunks);
    const result = await postChunk(it, i, body);
    if (result !== 'ok') break;
    const length = Math.min(CHUNK, it.size - i * CHUNK);
    it.moved += length; up.moved += length;
    tick(up, renderSending);
  }
  if (it.state === 'active') it.state = 'done';
  else if (it.state === 'cancelled' && it.n) call({ op: 'cancel', n: it.n }).catch(() => {});
}

async function postChunk(it, i, body) {
  for (let attempt = 0; attempt < 5; attempt++) {
    if (it.state !== 'active') return 'stop';
    try {
      const r = await http(`/api/up?s=${encodeURIComponent(S.sid)}&n=${it.n}&i=${i}`,
        { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body, signal: up.ac.signal }, 60000);
      if (r.ok) return 'ok';
      const j = await r.json().catch(() => ({}));
      if (r.status === 410) { it.state = 'cancelled'; it.error = 'Cancelled on the PC'; it.n = 0; return 'stop'; }
      if (r.status === 401) { sessionEnded(); return 'stop'; }
      if (r.status !== 503) { it.state = 'failed'; it.error = j.error || `Error ${r.status}`; return 'stop'; }
    } catch { /* network hiccup or abort */ }
    if (it.state !== 'active') return 'stop';
    await sleep(700 * (attempt + 1));
  }
  it.state = 'failed'; it.error = 'The PC stopped answering';
  return 'stop';
}

function cancelItem(job, it) {
  if (it.state === 'queued') it.state = 'cancelled';
  else if (it.state === 'active') { it.state = 'cancelled'; if (job.ac) job.ac.abort(); }
}
$('btn-cancel').onclick = () => {
  const job = up.running ? up : dn;
  job.cancelAll = true;
  job.batch.forEach((it) => cancelItem(job, it));
  renderAll();
};
$('btn-more').onclick = () => showSendList();
$('btn-send').onclick = () => sendAll();

function tick(job, render) {             // speed over the last 4 s, redraw at most 5 times a second
  const now = performance.now();
  job.samples.push([now, job.moved]);
  while (job.samples.length > 2 && now - job.samples[0][0] > 4000) job.samples.shift();
  if (now - (job.drawn || 0) > 200) { job.drawn = now; render(false); }
}
function speedOf(job) {
  const s = job.samples;
  if (s.length < 2) return 0;
  const [t0, b0] = s[0], [t1, b1] = s[s.length - 1];
  return t1 > t0 ? ((b1 - b0) * 1000) / (t1 - t0) : 0;
}

function renderSending(rebuild) {
  if (mode !== 'send' || (!up.running && !up.batch.length)) return;
  const grid = $('up-grid');
  if (rebuild) {
    grid.textContent = '';
    for (const it of up.batch) grid.appendChild(makeTile(it, { onX: (item) => { cancelItem(up, item); renderSending(false); } }));
  }
  up.batch.forEach((it) => paintTile(it, 'Sent'));
  const it = up.current || up.batch[up.batch.length - 1];
  const n = up.batch.length, done = up.batch.filter((p) => p.state === 'done').length;
  const queued = up.batch.filter((p) => p.state === 'queued').length;
  const speed = speedOf(up);
  $('up-name').textContent = it ? it.name : '—';
  const pct = it && it.size ? Math.floor((it.moved / it.size) * 100) : (it && it.state === 'done' ? 100 : 0);
  $('up-pct').textContent = `${pct}%`;
  $('up-index').textContent = `File ${Math.min(up.index + 1, n)} of ${n}`;
  $('up-bytes').textContent = it ? `${fmtBytes(it.moved)} / ${fmtBytes(it.size)}` : '';
  $('up-bar').style.width = `${pct}%`;
  const opct = up.total ? Math.floor((up.moved / up.total) * 100) : 100;
  $('up-overall').lastChild.textContent = ` Overall ${done}/${n}`;
  $('up-overall-bytes').textContent = `${fmtBytes(up.moved)} of ${fmtBytes(up.total)} · ${opct}%`;
  $('up-obar').style.width = `${opct}%`;
  $('up-speed').textContent = up.running && speed ? `${(speed / 1048576).toFixed(1)} MB/s` : '—';
  $('up-eta').textContent = up.running ? fmtEta((up.total - up.moved) / speed) : 'finished';
  $('up-head').textContent = `Files in transit (${n})`;
  $('up-badge').textContent = up.running ? `${done} DONE · 1 ACTIVE` : `${done} SENT`;
  $('up-queued').textContent = queued ? `${queued} QUEUED` : '';
  if (it && it !== renderSending.thumbFor) {
    renderSending.thumbFor = it;
    const box = $('up-thumb');
    box.textContent = '';
    if (it.thumb) { const img = el('img', 'w-full h-full object-cover'); img.alt = ''; img.src = it.thumb; box.appendChild(img); }
    else box.innerHTML = icon(KIND[it.kind].icon, `w-6 h-6 ${KIND[it.kind].text}`);
  }
  renderButtons();
}

// ------------------------------------------------------------------ RECEIVE (PC -> phone)
let offers = [];             // {id, name, size, mime, kind, thumb, sel, hidden, state, moved}
const dn = { running: false, cancelAll: false, batch: [], index: 0, current: null, ac: null, samples: [], total: 0, moved: 0 };

async function loadList() {
  if (state !== 'allowed') return;
  try {
    const res = await call({ op: 'list' });
    rev = res.rev;
    const old = new Map(offers.map((o) => [o.id, o]));
    offers = res.files.map((f) => old.get(f.id) || {
      id: f.id, name: f.name, size: f.size, mime: f.mime, kind: kindOf(f.name, f.mime),
      thumb: f.thumb ? `data:image/jpeg;base64,${f.thumb}` : null, sel: true, hidden: false, state: 'ready', moved: 0,
    });
    for (const f of res.files) { const o = offers.find((x) => x.id === f.id); if (!o.thumb && f.thumb) o.thumb = `data:image/jpeg;base64,${f.thumb}`; }
    renderRecv();
  } catch (e) { if (e.status === 401) sessionEnded(); }
}

function visibleOffers() { return offers.filter((o) => !o.hidden); }
function renderRecv() {
  if (mode !== 'recv') return;
  const grid = $('recv-grid');
  grid.textContent = '';
  const list = visibleOffers();
  for (const o of list) {
    grid.appendChild(makeTile(o, {
      onX: (item) => { if (item.state === 'active' || item.state === 'queued') cancelItem(dn, item); else { item.hidden = true; item.sel = false; } renderRecv(); },
      onCheck: (item) => { item.sel = !item.sel; renderRecv(); },
    }));
    paintTile(o, 'Saved');
  }
  $('recv-empty').classList.toggle('hidden', list.length > 0);
  $('recv-title').textContent = `Files from ${pcName}`;
  $('recv-sub').textContent = `${list.length} ${list.length === 1 ? 'file' : 'files'} · ${fmtBytes(list.reduce((n, o) => n + o.size, 0))}`;
  const sel = list.filter((o) => o.sel);
  $('recv-sel').textContent = `${sel.length} of ${list.length} selected`;
  $('btn-save-text').textContent = sel.length ? `SAVE TO PHONE (${fmtBytes(sel.reduce((n, o) => n + o.size, 0))})` : 'SAVE TO PHONE';
  renderDownload();
  renderButtons();
}
$('recv-all').onclick = () => {
  const list = visibleOffers().filter((o) => o.state !== 'active');
  const all = list.every((o) => o.sel);
  list.forEach((o) => { o.sel = !all; });
  renderRecv();
};

async function saveAll() {
  if (state !== 'allowed' || !online || dn.running) return;
  const batch = visibleOffers().filter((o) => o.sel);
  if (!batch.length) return;
  batch.forEach((o) => { o.state = 'queued'; o.moved = 0; o.error = ''; });
  Object.assign(dn, { running: true, cancelAll: false, batch, index: 0, samples: [], moved: 0,
    total: batch.reduce((n, o) => n + o.size, 0) });
  renderRecv();
  renderConn();
  for (let k = 0; k < batch.length && !dn.cancelAll; k++) {
    if (batch[k].state !== 'queued') continue;
    dn.index = k;
    await downloadOne(batch[k]);
    renderRecv();
  }
  dn.running = false; dn.current = null;
  batch.forEach((o) => { if (o.state === 'done') o.sel = false; });
  renderRecv();
  renderConn();
  const saved = batch.filter((o) => o.state === 'done').length;
  if (saved) toast(`${saved} ${saved === 1 ? 'file' : 'files'} saved to Downloads.`);
}
$('btn-save').onclick = () => saveAll();

async function downloadOne(o) {
  o.state = 'active';
  dn.current = o;
  dn.ac = new AbortController();
  renderDownload();
  let g;
  try { g = await call({ op: 'get', id: o.id }); } catch (e) {
    if (e.status === 401) return sessionEnded();
    o.state = 'failed'; o.error = e.message; return;
  }
  const parts = [];
  for (let i = 0; i < g.chunks && o.state === 'active'; i++) {
    let data = null;
    for (let attempt = 0; attempt < 5 && !data && o.state === 'active'; attempt++) {
      try {
        const r = await http(`/api/dl?s=${encodeURIComponent(S.sid)}&n=${g.n}&i=${i}`, { signal: dn.ac.signal }, 60000);
        if (r.status === 410) { o.state = 'cancelled'; o.error = 'Cancelled on the PC'; break; }
        if (r.status === 401) { sessionEnded(); return; }
        if (!r.ok) { const j = await r.json().catch(() => ({})); o.state = 'failed'; o.error = j.error || `Error ${r.status}`; break; }
        const sealed = new Uint8Array(await r.arrayBuffer());
        try { data = chacha20poly1305(dnKey, nonce(4, g.n, i), chunkAad('dn', g.n, i, g.chunks)).decrypt(sealed); }
        catch { o.state = 'failed'; o.error = 'Integrity check failed'; break; }
      } catch { if (o.state === 'active') await sleep(700 * (attempt + 1)); }
    }
    if (!data) { if (o.state === 'active') { o.state = 'failed'; o.error = 'The PC stopped answering'; } break; }
    parts.push(data);
    o.moved += data.length; dn.moved += data.length;
    tick(dn, renderDownload);
  }
  if (o.state === 'active') {
    saveBlob(new Blob(parts, { type: g.mime || 'application/octet-stream' }), g.name || o.name);
    o.state = 'done';
    call({ op: 'got', n: g.n }).catch(() => {});
  } else if (o.state === 'cancelled' && o.error !== 'Cancelled on the PC') {
    call({ op: 'cancel', n: g.n }).catch(() => {});
  }
}

function saveBlob(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = name; a.rel = 'noopener';
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 120000);
}

function renderDownload(rebuild) {
  if (mode !== 'recv') return;
  $('dn-card').classList.toggle('hidden', !dn.running && !dn.batch.length);
  if (!dn.batch.length) return;
  dn.batch.forEach((o) => paintTile(o, 'Saved'));
  const o = dn.current || dn.batch[dn.batch.length - 1];
  const n = dn.batch.length, done = dn.batch.filter((x) => x.state === 'done').length;
  const pct = o.size ? Math.floor((o.moved / o.size) * 100) : (o.state === 'done' ? 100 : 0);
  const opct = dn.total ? Math.floor((dn.moved / dn.total) * 100) : 100;
  const speed = speedOf(dn);
  $('dn-name').textContent = o.name;
  $('dn-index').textContent = `File ${Math.min(dn.index + 1, n)} of ${n}`;
  $('dn-bytes').textContent = `${fmtBytes(o.moved)} / ${fmtBytes(o.size)}`;
  $('dn-bar').style.width = `${pct}%`;
  $('dn-pct').textContent = `${pct}%`;
  $('dn-overall').lastChild.textContent = ` Overall ${done}/${n}`;
  $('dn-overall-bytes').textContent = `${fmtBytes(dn.moved)} of ${fmtBytes(dn.total)} · ${opct}%`;
  $('dn-obar').style.width = `${opct}%`;
  $('dn-speed').textContent = dn.running && speed ? `${(speed / 1048576).toFixed(1)} MB/s` : '—';
  $('dn-eta').textContent = dn.running ? fmtEta((dn.total - dn.moved) / speed) : 'finished';
}

function abortAll() {
  for (const job of [up, dn]) { job.cancelAll = true; job.batch.forEach((it) => cancelItem(job, it)); }
}

// ------------------------------------------------------------------ views and buttons
function showView() {
  const sending = mode === 'send' && (up.running || up.batch.length > 0);
  $('v-send').classList.toggle('hidden', mode !== 'send' || sending);
  $('v-sending').classList.toggle('hidden', !sending);
  $('v-recv').classList.toggle('hidden', mode !== 'recv');
  $('v-text').classList.toggle('hidden', mode !== 'text');
  for (const [id, m] of [['tab-send', 'send'], ['tab-recv', 'recv'], ['tab-text', 'text']]) {
    $(id).className = m === mode
      ? 'mode-tab flex items-center justify-center gap-1.5 py-2 rounded-[9px] font-label-md text-label-md font-bold uppercase bg-primary-container text-surface-container-lowest shadow-[0_0_12px_rgba(34,211,238,0.45)]'
      : 'mode-tab flex items-center justify-center gap-1.5 py-2 rounded-[9px] font-label-md text-label-md font-bold uppercase text-on-surface-variant';
  }
  renderButtons();
}
function renderButtons() {
  const busy = up.running || dn.running;
  const ready = state === 'allowed' && online;
  const show = (id, on) => $(id).classList.toggle('hidden', !on);
  const sendList = mode === 'send' && !up.running && !up.batch.length;
  show('btn-send', sendList);
  $('btn-send').disabled = !ready || !picked.some((p) => p.state === 'ready');
  show('btn-more', mode === 'send' && !up.running && up.batch.length > 0);
  show('btn-save', mode === 'recv' && !dn.running);
  $('btn-save').disabled = !ready || !visibleOffers().some((o) => o.sel);
  show('btn-cancel', (mode === 'send' && up.running) || (mode === 'recv' && dn.running));
  $('tab-send').disabled = busy; $('tab-recv').disabled = busy; $('tab-text').disabled = busy;
  renderText();
  const foot = mode === 'recv' ? [icon('folder', 'w-3.5 h-3.5'), 'Files go to your Downloads']
    : busy ? [icon('clock', 'w-3.5 h-3.5'), 'Keep this screen on until it finishes']
      : [icon('shield', 'w-3.5 h-3.5 text-tertiary'), 'Encrypted on this phone before it leaves'];
  $('foot').innerHTML = foot[0];
  $('foot').appendChild(document.createTextNode(foot[1]));
}
function renderAll() { renderSend(); renderSending(true); renderRecv(); renderConn(); }

function setMode(m) {
  if (up.running || dn.running) return;
  mode = m;
  sessionStorage.setItem('neon.mode', m);
  showView();
  if (m === 'send') { if (up.batch.length) renderSending(true); else renderSend(); }
  else if (m === 'recv') { renderRecv(); loadList(); }
  else if (m === 'text') { textUnread = 0; renderBadge(); }
  if (S) call({ op: 'ping', name: deviceName(), mode }).then(applyStatus).catch(() => {});
}
$('tab-send').onclick = () => setMode('send');
$('tab-recv').onclick = () => setMode('recv');
$('tab-text').onclick = () => setMode('text');

// ------------------------------------------------------------------ text: pasted on the phone, shown on the PC
// it travels sealed like every control message; the PC shows it as plain text with a copy button
const TEXT_MAX = 20000;
var textSending = false;   // var: renderButtons may run before this line during start-up
var textRev = 0, textUnread = 0, textLoading = false;

// text the PC sends to this phone: shown newest first, each with a Copy button and selectable by long-press
async function loadTexts() {
  if (textLoading) return;
  textLoading = true;
  try {
    const r = await call({ op: 'texts', after: textRev });
    for (const m of r.texts || []) {
      if (typeof m.n !== 'number' || m.n <= textRev || typeof m.text !== 'string') continue;
      textRev = m.n;
      addIncoming(m.text, m.at);
      if (mode !== 'text') textUnread++;
    }
    renderBadge();
  } catch (e) { /* the next heartbeat tries again */ } finally { textLoading = false; }
}
function renderBadge() {
  const b = $('text-badge');
  b.textContent = textUnread > 9 ? '9+' : String(textUnread);
  b.classList.toggle('hidden', !textUnread);
}
function copyText(text) {
  // the clipboard API needs HTTPS (INTERNET mode); on LAN fall back to a hidden textarea and the copy command
  if (window.isSecureContext && navigator.clipboard && navigator.clipboard.writeText) return navigator.clipboard.writeText(text);
  const area = el('textarea');
  area.value = text; area.setAttribute('readonly', ''); area.style.position = 'fixed'; area.style.opacity = '0';
  document.body.appendChild(area); area.select();
  const ok = document.execCommand('copy');
  area.remove();
  return ok ? Promise.resolve() : Promise.reject(new Error('copy blocked'));
}
function addIncoming(text, at) {
  const card = el('div', 'bg-surface-container-low border border-secondary/40 rounded-[12px] p-3 flex flex-col gap-1.5');
  const head = el('div', 'flex items-center justify-between gap-2');
  const when = new Date((at || Date.now() / 1000) * 1000);
  head.appendChild(el('span', 'font-label-sm text-[11px] text-outline', `${pcName} · ${when.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`));
  const btn = el('button', 'shrink-0 font-label-sm text-label-sm text-secondary border border-secondary/40 px-2.5 py-1 rounded-[8px] bg-secondary/10', 'Copy');
  btn.onclick = () => copyText(text).then(() => { btn.textContent = 'Copied'; setTimeout(() => { btn.textContent = 'Copy'; }, 1500); })
    .catch(() => toast('Copy was blocked: long-press the text and choose Copy'));
  head.appendChild(btn);
  card.appendChild(head);
  card.appendChild(el('div', 'font-body-md text-[15px] text-on-surface whitespace-pre-wrap break-words select-text', text));
  $('text-in').prepend(card);
  $('text-in-head').classList.remove('hidden');
}
function renderText() {
  const box = $('text-box'), n = box.value.length;
  $('text-count').textContent = `${n} / ${TEXT_MAX}`;
  $('text-send').disabled = textSending || !(state === 'allowed' && online) || !box.value.trim();
}
$('text-box').addEventListener('input', renderText);
$('text-clear').onclick = () => { $('text-box').value = ''; renderText(); $('text-box').focus(); };
// reading the clipboard needs a secure page (HTTPS: INTERNET mode); on LAN the phone's own long-press paste works
if (window.isSecureContext && navigator.clipboard && navigator.clipboard.readText) {
  $('text-paste').classList.remove('hidden');
  $('text-paste').onclick = async () => {
    try {
      const clip = await navigator.clipboard.readText();
      if (clip) { $('text-box').value = clip.slice(0, TEXT_MAX); renderText(); }
      else toast('The clipboard is empty');
    } catch (e) { toast('Paste was blocked: long-press the box and choose Paste'); }
  };
}
$('text-send').onclick = async () => {
  const text = $('text-box').value;
  if (!text.trim() || textSending) return;
  textSending = true; renderText();
  try {
    await call({ op: 'text', text });
    $('text-box').value = '';
    const item = el('div', 'bg-surface-container-low border border-outline-variant/40 rounded-[10px] px-3 py-2 font-body-sm text-body-sm text-on-surface-variant whitespace-pre-wrap break-words max-h-24 overflow-hidden', text.length > 300 ? text.slice(0, 300) + '…' : text);
    $('text-sent').prepend(item);
    $('text-sent-head').classList.remove('hidden');
    toast('Text sent to ' + pcName);
  } catch (e) {
    if (e.status === 401) return sessionEnded();
    toast('Not sent: ' + (e.message || 'connection lost'));
  } finally { textSending = false; renderText(); }
};

// device name: remembered on this phone, sent with every heartbeat
function showName() { $('dev-name').textContent = deviceName(); }
$('dev-edit').onclick = () => {
  const input = $('dev-input');
  input.value = deviceName();
  input.classList.remove('hidden');
  $('dev-name').classList.add('hidden');
  input.focus();
};
function commitName() {
  const input = $('dev-input');
  const v = input.value.trim().slice(0, 40);
  if (v) localStorage.setItem('neon.name', v);
  input.classList.add('hidden');
  $('dev-name').classList.remove('hidden');
  showName();
}
$('dev-input').onblur = commitName;
$('dev-input').onkeydown = (e) => { if (e.key === 'Enter') $('dev-input').blur(); };

window.addEventListener('beforeunload', (e) => { if (up.running || dn.running) { e.preventDefault(); e.returnValue = ''; } });

// ------------------------------------------------------------------ start
// INTERNET = page loaded through the Cloudflare tunnel (https); LAN = straight from the PC on this Wi-Fi.
const INTERNET = location.protocol === 'https:';
let pair = null;
let pairFrag = '';           // the QR fragment, kept so the page can hop to the LAN address with it
let hopping = false;

// Through the tunnel, ask the PC whether this phone is behind the same router. If so, load the LAN address
// (top-level navigation, same fragment). "neon.lanfail" is set first: if the LAN page does not load and the user
// goes Back, this page stays on INTERNET instead of trying again.
async function tryLan() {
  if (!INTERNET || sessionStorage.getItem('neon.lanfail')) return false;
  try {
    const r = await http('/api/where', {}, 8000);
    const j = r.ok ? await r.json() : {};
    if (!/^http:\/\/[0-9.]+:\d+\/$/.test(j.lan || '')) return false;
    sessionStorage.setItem('neon.lanfail', '1');
    sessionStorage.setItem('neon.pair', pairFrag);
    hopping = true;
    overlay({ kind: 'busy', icon: 'wifi', title: 'Same Wi-Fi found', text: 'Switching to the faster direct connection…' });
    location.href = `${j.lan}#${pairFrag}&n=${encodeURIComponent(deviceName())}`;
    return true;
  } catch { return false; }
}
window.addEventListener('pageshow', (e) => {         // Back from a LAN page that did not load
  if (e.persisted && hopping) { hopping = false; connect(); }
});

async function connect() {
  if (pair && !hopping && await tryLan()) return;
  if (pair) {
    overlay({ kind: 'busy', icon: 'lock', title: 'Connecting…', text: 'Setting up an encrypted link with the PC.' });
    try {
      applyStatus(await hello(pair.pk, pair.token));
      online = true;
      sessionStorage.removeItem('neon.pair');
    } catch (e) {
      const text = e.status === 403 ? 'This QR code was already used or is out of date. Scan the new code on the PC.'
        : e.status === 409 ? 'The PC is connected to another phone. Disconnect it on the PC first.'
          : e.status === 429 ? 'Too many tries. Wait a little and scan again.'
            : INTERNET ? 'Could not reach the PC over the internet. Is NEON Torrent still sharing?'
              : 'Could not reach the PC. Is this phone on the same Wi-Fi?';
      overlay({ kind: 'error', icon: 'wifi', title: 'Could not connect', text });
      pair = null;
      return;
    }
    pair = null;
  } else if (!S) {
    overlay({ kind: 'scan', icon: 'qr', title: 'Scan the QR code', text: 'Open NEON Torrent on your PC, go to FILE SHARING and scan its QR code with this phone’s camera.' });
    return;
  }
  startPing();
}

function boot() {
  $('hdr-path').textContent = INTERNET ? 'Internet' : 'LAN';
  let raw = location.hash.slice(1);
  if (location.hash) history.replaceState(null, '', location.pathname);       // the key leaves the address bar
  if (!raw && sessionStorage.getItem('neon.lanfail')) raw = sessionStorage.getItem('neon.pair') || '';
  const frag = new URLSearchParams(raw);
  const name = (frag.get('n') || '').trim().slice(0, 40);
  if (name && !localStorage.getItem('neon.name')) localStorage.setItem('neon.name', name);   // carried over from the tunnel page
  frag.delete('n');
  pairFrag = frag.toString();
  try { S = JSON.parse(sessionStorage.getItem('neon.s') || 'null'); } catch { S = null; }
  const k = frag.get('k'), t = frag.get('t');
  if (k && t && (!S || S.pk !== k)) {
    try { pair = { pk: b64d(k), token: b64d(t) }; } catch { pair = null; }
    if (pair && (pair.pk.length !== 32 || pair.token.length < 16)) pair = null;
    S = null;
  }
  if (S) { upKey = b64d(S.up); dnKey = b64d(S.dn); }
  mode = frag.get('m') === 'recv' ? 'recv' : frag.get('m') === 'send' ? 'send' : (sessionStorage.getItem('neon.mode') || 'send');
  showName();
  showView();
  renderSend();
  renderConn();
  if (!localStorage.getItem('neon.name') && (pair || S)) {
    overlay({ kind: 'name', icon: 'phone', title: 'Name this phone', text: 'The PC shows this name when it asks whether to allow you.',
      input: deviceName(), button: 'Continue',
      onButton: () => {
        const v = $('ov-input').value.trim().slice(0, 40);
        localStorage.setItem('neon.name', v || deviceName());
        showName();
        connect();
      } });
    $('ov-input').onkeydown = (e) => { if (e.key === 'Enter') $('ov-btn').click(); };
  } else connect();
}
boot();
