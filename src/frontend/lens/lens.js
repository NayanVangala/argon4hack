// Scene Lens: the in-glasses glance layer (spec §8).
// Band gestures arrive as keys: swipes = arrow keys, pinch = Enter, back = Escape.
// Test on a laptop with the arrow keys + Enter.

// ---- Config ----------------------------------------------------------------
// When Nayan's backend is up: useMock = false and set baseUrl. Never put a real token in the repo.
const CONFIG = {
  useMock: true,
  baseUrl: '',          // e.g. 'http://localhost:8000'
  token: '',            // provided at runtime via QR pairing (spec §4.5), not hard-coded
};
// Point at a server without editing code: index.html?api=http://localhost:8000&token=...
(function readUrlParams() {
  const p = new URLSearchParams(location.search);
  if (p.get('api')) { CONFIG.useMock = false; CONFIG.baseUrl = p.get('api').replace(/\/$/, ''); }
  if (p.get('token')) CONFIG.token = p.get('token');
})();

// ---- Mock data (same shapes as the API, §4.5) --------------------------------
function at(h, m) { const d = new Date(); d.setHours(h, m, 0, 0); return d.toISOString(); }
const MOCK_SCENES = [
  { id: 's8', start_ts: at(16, 5),  end_ts: at(16, 20), summary: 'Coffee with Priya', quote: "Send me the deck when it's ready.", type: 'conversation', verified: true },
  { id: 's7', start_ts: at(15, 40), end_ts: at(15, 43), summary: 'Someone suggests keeping the price', quote: "Let's keep it at forty-nine.", type: 'quote', verified: false },
  { id: 's6', start_ts: at(15, 10), end_ts: at(15, 18), summary: 'Pricing discussion', quote: 'What if we drop the price to 49?', type: 'conversation', verified: true },
  { id: 's5', start_ts: at(14, 31), end_ts: at(14, 34), summary: 'Whiteboard session', quote: null, type: 'action', verified: false },
  { id: 's4', start_ts: at(14, 14), end_ts: at(14, 26), summary: 'Maya on the Q3 numbers', quote: "I'll send the Q3 numbers by Friday.", type: 'conversation', verified: true },
  { id: 's3', start_ts: at(13, 30), end_ts: at(13, 34), summary: 'Standup with Jordan and Priya', quote: "I'll take the onboarding bug.", type: 'conversation', verified: true },
  { id: 's2', start_ts: at(12, 40), end_ts: at(12, 55), summary: 'Lunch at the Ferry Building', quote: null, type: 'location', verified: true },
];
function mockAsk(q) {
  q = q.toLowerCase();
  if (q.includes('maya') || (q.includes('promise') && !q.includes(' i '))) return {
    answer: 'The Q3 numbers by Friday.',
    receipts: [{ scene_id: 's4', timestamp: '2:14 PM', quote: "I'll send the Q3 numbers by Friday.", confidence: 'verified', speaker: 'Maya' }] };
  if (q.includes('pricing') || q.includes('price') || q.includes('49')) return {
    answer: 'At 3:10 PM, with Jordan.',
    receipts: [{ scene_id: 's6', timestamp: '3:10 PM', quote: 'What if we drop the price to 49?', confidence: 'verified', speaker: 'Jordan' }] };
  if (q.includes('promise')) return {
    answer: 'To send Priya the deck.',
    receipts: [{ scene_id: 's8', timestamp: '4:05 PM', quote: "Send me the deck when it's ready.", confidence: 'verified', speaker: 'Priya' }] };
  return { answer: "I don't have a record of that.", receipts: [] };
}

// ---- API -------------------------------------------------------------------
async function api(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (CONFIG.token) headers.Authorization = 'Bearer ' + CONFIG.token;
  const res = await fetch(CONFIG.baseUrl + path, { ...opts, headers });
  if (!res.ok) throw new Error('HTTP ' + res.status);
  return res.json();
}
const store = {
  get(k) { try { return JSON.parse(localStorage.getItem(k)); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
};
async function loadScenes() {
  if (CONFIG.useMock) return MOCK_SCENES;
  try {
    const res = await api('/api/v1/scenes/today');
    const list = Array.isArray(res) ? res : (res.scenes || []);   // server wraps it: { scenes, next_before }
    list.forEach(x => { if (!x.quote) x.quote = null; });
    store.set('scenes', list);
    setOffline(false);
    return list.slice().sort((a, b) => new Date(b.start_ts) - new Date(a.start_ts));
  } catch {
    setOffline(true);
    return store.get('scenes') || [];
  }
}
async function ask(query) {
  if (CONFIG.useMock) { await new Promise(r => setTimeout(r, 700)); return mockAsk(query); }
  try { return await api('/api/v1/ask', { method: 'POST', body: JSON.stringify({ query }) }); }
  catch { return { answer: "Can't reach your memory right now.", receipts: [] }; }
}
async function pin(sceneId) {
  if (CONFIG.useMock) return;
  try { await api('/api/v1/pin', { method: 'POST', body: JSON.stringify(sceneId ? { scene_id: sceneId } : {}) }); } catch {}
}

// ---- State -----------------------------------------------------------------
const state = { screen: 'now', scenes: [], recording: true, focusIndex: 0, lastAnswer: null };
const $ = (id) => document.getElementById(id);
const time = (iso) => new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
// Receipts may carry "2:14 PM" (mock) or an ISO timestamp (server)
const showTime = (t) => (t && !isNaN(Date.parse(t)) && /T\d/.test(t)) ? time(t) : (t || '');
const MAX_CARDS = 20;

function setOffline(on) { state.offline = on; updateBanner(); }
function updateBanner() { $('offline').classList.toggle('show', !!state.offline && state.screen === 'timeline'); }

// ---- Rendering -------------------------------------------------------------
function renderNow() {
  const s = state.scenes[0];
  $('clock').textContent = new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  $('now-kicker').textContent = `NOW · SCENE ${state.scenes.length}`;
  $('now-title').textContent = s ? s.summary : 'Waiting for the first scene…';
}
function renderTimeline() {
  const cards = $('cards');
  cards.innerHTML = '';
  const shown = state.scenes.slice(0, MAX_CARDS);
  $('scene-count').textContent = `${state.scenes.length} SCENES`;
  $('empty').hidden = shown.length > 0;
  shown.forEach((s, i) => {
    const b = document.createElement('button');
    b.className = 'card';
    b.dataset.focusable = '';
    b.dataset.action = 'open-scene';
    b.dataset.id = s.id;
    const thumb = document.createElement('span');
    thumb.className = 'thumb';
    if (s.thumb_url) { const img = document.createElement('img'); img.src = s.thumb_url; img.alt = ''; img.onerror = () => img.remove(); thumb.appendChild(img); }
    else thumb.style.background = i % 2 ? 'var(--block-dim)' : 'var(--block)';
    const t = document.createElement('span'); t.className = 't';
    const title = document.createElement('b'); title.textContent = s.summary;
    const meta = document.createElement('span'); meta.className = 'mono';
    meta.textContent = time(s.start_ts);
    if (state.pinned && state.pinned.has(s.id)) { const tick = document.createElement('span'); tick.className = 'tick'; tick.textContent = ' · ✓ PINNED'; meta.appendChild(tick); }
    else if (s.verified) { const tick = document.createElement('span'); tick.className = 'tick'; tick.textContent = ' · ✓'; meta.appendChild(tick); }
    t.append(title, meta); b.append(thumb, t); cards.appendChild(b);
  });
  const extra = state.scenes.length - shown.length;
  $('tl-footer').textContent = shown.length === 0 ? 'START RECORDING FROM YOUR PHONE'
    : extra > 0 ? `+${extra} EARLIER · SWIPE TO SCROLL` : 'SWIPE TO SCROLL · PINCH TO OPEN';
}
function renderAnswer(question, res) {
  state.lastAnswer = res;
  $('answer-q').textContent = question;
  // One glance: first sentence only (longer belongs on the phone)
  const first = (res.answer || '').split(/(?<=[.!?])\s/)[0];
  $('answer-a').textContent = first;
  const r = res.receipts && res.receipts[0];
  $('receipt').hidden = !r;
  $('answer-footer').textContent = r ? 'PINCH TO PIN · SWIPE DOWN TO GO BACK' : 'SWIPE DOWN TO GO BACK';
  if (!r) return;
  $('receipt').dataset.id = r.scene_id;
  $('receipt-quote').textContent = `“${r.quote}”`;
  const verified = (r.confidence || 'verified') === 'verified';
  $('receipt-badge').textContent = verified ? '✓ VERIFIED' : 'REVIEW';
  $('receipt-badge').classList.toggle('review', !verified);
  const who = r.speaker && verified ? r.speaker.toUpperCase() + ' · ' : (!verified ? 'UNKNOWN · ' : '');
  $('receipt-who').textContent = who + showTime(r.timestamp);
  const thumb = $('receipt-thumb'); thumb.innerHTML = '';
  if (r.thumb_url) { const img = document.createElement('img'); img.src = r.thumb_url; img.alt = ''; img.onerror = () => img.remove(); thumb.appendChild(img); }
}

// ---- Focus = the whole input model -----------------------------------------
function focusables() { return [...document.querySelectorAll(`#${state.screen} [data-focusable]:not([hidden])`)].filter(el => el.offsetParent !== null); }
function setFocus(i) {
  const els = focusables();
  if (!els.length) return;
  state.focusIndex = Math.max(0, Math.min(els.length - 1, i));
  els.forEach((el, j) => el.classList.toggle('focused', j === state.focusIndex));
  const el = els[state.focusIndex];
  $('ask-wrap').classList.toggle('focused', el.id === 'ask-input');
  el.focus({ preventScroll: true });
  el.scrollIntoView({ block: 'nearest' });
}
function show(screen, focus = 0) {
  if (screen === 'now' && !state.recording) screen = 'timeline';
  document.querySelectorAll('.screen').forEach(s => s.classList.toggle('active', s.id === screen));
  state.screen = screen;
  updateBanner();
  if (screen === 'now') renderNow();
  if (screen === 'timeline') renderTimeline();
  setFocus(focus);
}
function back() {
  // Back always returns to Timeline (spec §8.3); from Timeline, back to Now
  show(state.screen === 'timeline' ? 'now' : 'timeline');
}

// ---- Actions ---------------------------------------------------------------
state.pinned = new Set();
function flashPinned(button, hintEl, label, savedTo) {
  if (button.classList.contains('pinned')) return;   // already showing the confirm
  const original = button.innerHTML, hint = hintEl && hintEl.textContent;
  button.classList.add('pinned');
  button.innerHTML = '<svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="#000" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg><span>' + label + '</span>';
  if (hintEl) { hintEl.textContent = 'SAVED TO ' + savedTo; hintEl.classList.add('blue'); }
  setTimeout(() => {   // transient confirm, 1.2s (spec §8.3)
    button.classList.remove('pinned'); button.innerHTML = original;
    if (hintEl) { hintEl.textContent = hint; hintEl.classList.remove('blue'); }
  }, 1200);
}
async function activate(el) {
  const action = el.dataset.action;
  if (action === 'pin-now') {
    const s = state.scenes[0];
    if (s) state.pinned.add(s.id);
    flashPinned(el, $('pin-now-hint'), 'Pinned', s ? time(s.start_ts) : 'NOW');
    pin(s && s.id);
  }
  if (action === 'go-timeline') show('timeline');
  if (action === 'go-ask') show('ask');
  if (action === 'go-stop') show('stop', 0);           // "Keep recording" is focused first
  if (action === 'keep') show('now');
  if (action === 'stop') {
    state.recording = false;
    show('dark');
    $('toast').classList.add('show');
    setTimeout(() => $('toast').classList.remove('show'), 2000);
  }
  if (action === 'open-scene') {
    const s = state.scenes.find(x => x.id === el.dataset.id);
    if (!s) return;
    show('answer');
    renderAnswer(`SCENE · ${time(s.start_ts)}`, { answer: s.summary, receipts: s.quote ? [{ scene_id: s.id, timestamp: time(s.start_ts), quote: s.quote, confidence: s.verified ? 'verified' : 'review', speaker: null }] : [] });
    setFocus(0);
  }
  if (action === 'ask-chip') runAsk(el.textContent.trim());
  if (action === 'ask-input') {
    const q = el.value.trim();
    if (q) runAsk(q);
  }
  if (action === 'pin-receipt') {
    state.pinned.add(el.dataset.id);
    const badge = $('receipt-badge');
    if (badge.dataset.flashing) return;
    badge.dataset.flashing = '1';
    const old = badge.textContent;
    badge.textContent = '✓ PINNED';
    setTimeout(() => { badge.textContent = old; delete badge.dataset.flashing; }, 1200);
    pin(el.dataset.id);
  }
}
async function runAsk(q) {
  show('answer');
  $('answer-q').textContent = q;
  $('answer-a').textContent = 'Checking the footage…';
  $('receipt').hidden = true;
  const res = await ask(q);
  renderAnswer(q, res);
  setFocus(0);
  $('ask-input').value = '';
}

// ---- Keys (band gestures) ----------------------------------------------------
document.addEventListener('keydown', (e) => {
  const typing = document.activeElement && document.activeElement.tagName === 'INPUT';
  if (state.screen === 'dark') { e.preventDefault(); show('timeline'); return; }   // any gesture wakes the lens
  if (e.key === 'ArrowDown' && state.screen === 'answer') { e.preventDefault(); back(); return; }
  if (e.key === 'ArrowDown' || e.key === 'ArrowRight' && !typing) { e.preventDefault(); setFocus(state.focusIndex + 1); }
  else if (e.key === 'ArrowUp' || e.key === 'ArrowLeft' && !typing) { e.preventDefault(); setFocus(state.focusIndex - 1); }
  else if (e.key === 'Enter') {
    const el = focusables()[state.focusIndex];
    // Pinch on an empty Ask box: let the system Composer open (dictation / handwriting)
    if (el && el.id === 'ask-input' && !el.value.trim()) return;
    e.preventDefault();
    if (el) activate(el);
  }
  else if (e.key === 'Escape' || (e.key === 'Backspace' && !typing)) { e.preventDefault(); back(); }
});
// Taps/clicks work too (handy on a laptop)
document.addEventListener('click', (e) => {
  const el = e.target.closest('[data-focusable]');
  if (!el) return;
  const i = focusables().indexOf(el);
  if (i >= 0) setFocus(i);
  if (el.tagName !== 'INPUT') activate(el);
});

// When the Composer hands back dictated text, ask right away (no second pinch needed)
$('ask-input').addEventListener('change', (e) => {
  const q = e.target.value.trim();
  if (q && state.screen === 'ask') runAsk(q);
});

// ---- Live updates ------------------------------------------------------------
function connectLive() {
  if (CONFIG.useMock || !CONFIG.baseUrl) return;
  try {
    const url = CONFIG.baseUrl.replace(/^http/, 'ws') + '/api/v1/live' + (CONFIG.token ? '?token=' + encodeURIComponent(CONFIG.token) : '');
    const ws = new WebSocket(url);
    ws.onmessage = (m) => {
      try {
        const { event, scene } = JSON.parse(m.data);
        if (event === 'scene' && scene) {
          scene.id = scene.id || scene.scene_id;   // spec uses both names
          state.scenes = [scene, ...state.scenes.filter(x => x.id !== scene.id)];   // newest first, no duplicates
          if (state.screen === 'now') renderNow();
          if (state.screen === 'timeline') { const i = state.focusIndex; renderTimeline(); setFocus(i); }
        }
      } catch {}
    };
    ws.onclose = () => setTimeout(connectLive, 3000);
  } catch {}
}

// ---- Start -------------------------------------------------------------------
(async function start() {
  state.scenes = await loadScenes();
  show('now');
  setInterval(() => { if (state.screen === 'now') $('clock').textContent = new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }); }, 15000);
  connectLive();
})();
