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
// P2 Day screen canned lists (same shapes as the API; mock only, never shown as live)
const MOCK_DAY = {
  spend: 1.84,
  people: [
    { id: 'p1', name: 'Maya', scene_count: 5, quote_count: 3, verified: true },
    { id: 'p2', name: 'Unknown', scene_count: 2, quote_count: 0, verified: false },
  ],
  facts: [
    { id: 'f1', text: 'Maya promised Q3 numbers by Friday', actors: ['Maya'] },
    { id: 'f2', text: 'Priya asked for the deck when it is ready', actors: ['Priya'] },
    { id: 'f3', text: 'Pricing discussion: keep it at forty-nine', actors: ['Jordan'] },
  ],
  followups: [
    { id: 'u1', promise: 'Maya promised Q3 numbers by Friday', person: 'Maya', status: 'pending' },
  ],
};

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
    // P2 pagination: follow next_before until null, bounded at 60 scenes total.
    // Contract: GET /scenes/today?limit=50&before=<scene_id> -> { scenes, next_before }.
    const all = [];
    const seenIds = new Set();
    const seenBefore = new Set();
    let before = null;
    while (all.length < 60) {
      const limit = Math.min(50, 60 - all.length);
      const path = '/api/v1/scenes/today?limit=' + limit + (before ? '&before=' + encodeURIComponent(before) : '');
      const res = await api(path);
      const page = Array.isArray(res) ? res : (res.scenes || []);   // array form = single page, no cursor
      const next = Array.isArray(res) ? null : (res.next_before ?? null);
      let added = 0;
      page.forEach(x => {
        if (!x || !x.id || seenIds.has(x.id)) return;
        seenIds.add(x.id);
        if (!x.quote) x.quote = null;
        all.push(x);
        added++;
      });
      // Stop on: no cursor, empty/short-circuit page, or a repeating cursor (server ignoring `before`).
      if (!next || added === 0 || page.length === 0 || next === before || seenBefore.has(next)) break;
      seenBefore.add(next);
      before = next;
    }
    const list = all.slice().sort((a, b) => new Date(b.start_ts) - new Date(a.start_ts));
    store.set('scenes', list);   // cache the full fetched list, not just page one
    setOffline(false);
    return list;
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
// Recording state comes from the server (the lens "Now" screen only shows while recording)
async function loadStatus() {
  if (CONFIG.useMock) return;
  try {
    const st = await api('/api/v1/status');
    state.recording = !!st.recording;
    state.sessionId = st.session_id || state.sessionId;
    if (typeof st.spend_usd === 'number') state.spendUsd = st.spend_usd;
  } catch {}
}
// P2 Day screen: one area's failure never kills the others. Each area is
// 'live' (fresh fetch), 'cached' (fetch failed, cached rows shown), or
// 'offline' (fetch failed, nothing cached: show an offline note, never fake data).
async function loadDay() {
  if (CONFIG.useMock) {
    state.day = { spend: MOCK_DAY.spend, spendState: 'live',
      people: MOCK_DAY.people, peopleState: 'live',
      facts: MOCK_DAY.facts, factsState: 'live',
      followups: MOCK_DAY.followups, followupsState: 'live' };
    return state.day;
  }
  const cached = store.get('day') || {};
  const day = {
    spend: typeof cached.spend === 'number' ? cached.spend : (typeof state.spendUsd === 'number' ? state.spendUsd : null),
    spendState: 'offline',
    people: Array.isArray(cached.people) ? cached.people : [], peopleState: 'offline',
    facts: Array.isArray(cached.facts) ? cached.facts : [], factsState: 'offline',
    followups: Array.isArray(cached.followups) ? cached.followups : [], followupsState: 'offline',
  };
  try { const st = await api('/api/v1/status'); if (typeof st.spend_usd === 'number') { day.spend = st.spend_usd; state.spendUsd = st.spend_usd; } day.spendState = 'live'; }
  catch { day.spendState = day.spend !== null ? 'cached' : 'offline'; }
  try { const r = await api('/api/v1/people'); day.people = r.people || []; day.peopleState = 'live'; }
  catch { day.peopleState = day.people.length ? 'cached' : 'offline'; }
  try { const r = await api('/api/v1/facts?limit=20'); day.facts = r.facts || []; day.factsState = 'live'; }
  catch { day.factsState = day.facts.length ? 'cached' : 'offline'; }
  try { const r = await api('/api/v1/followups?status=pending'); day.followups = (r.followups || []).filter(f => !f.status || f.status === 'pending'); day.followupsState = 'live'; }
  catch { day.followupsState = day.followups.length ? 'cached' : 'offline'; }
  state.day = day;
  // Cache only areas that are live or already cached (never cache an offline note as data).
  store.set('day', { spend: day.spend, people: day.people, facts: day.facts, followups: day.followups });
  return day;
}
async function endSession() {
  if (CONFIG.useMock) return true;
  if (!state.sessionId) return false;
  try { await api('/api/v1/sessions/' + encodeURIComponent(state.sessionId) + '/end', { method: 'POST', body: '{}' }); return true; } catch { return false; }
}
async function startSession() {
  if (CONFIG.useMock) return true;
  try {
    const res = await api('/api/v1/sessions', { method: 'POST', body: '{}' });
    if (res && res.id) state.sessionId = res.id;
    return true;
  } catch { return false; }
}
async function pin(sceneId) {
  if (CONFIG.useMock) return true;
  try { await api('/api/v1/pin', { method: 'POST', body: JSON.stringify(sceneId ? { scene_id: sceneId } : {}) }); return true; } catch { return false; }
}

// ---- State -----------------------------------------------------------------
const state = { screen: 'now', scenes: [], recording: true, focusIndex: 0, lastAnswer: null, day: null, spendUsd: null };
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
  // Restart path lives on Timeline (dark screen keeps any-gesture-wakes): only when stopped
  $('start-recording').hidden = state.recording;
  $('tl-footer').hidden = !state.recording;
}
function renderAnswer(question, res) {
  state.lastAnswer = res;
  $('answer-q').textContent = question;
  // Full answer text (P1: no more first-sentence truncation)
  $('answer-a').textContent = res.answer || '';
  const list = $('receipts');
  list.innerHTML = '';
  const receipts = res.receipts || [];
  $('answer-footer').textContent = receipts.length ? 'PINCH TO PIN A RECEIPT · SWIPE DOWN TO GO BACK' : 'SWIPE DOWN TO GO BACK';
  receipts.forEach((r) => {
    const b = document.createElement('button');
    b.className = 'receipt';
    b.dataset.focusable = '';
    b.dataset.action = 'pin-receipt';
    b.dataset.id = r.scene_id;
    const r1 = document.createElement('span'); r1.className = 'r1';
    const thumb = document.createElement('span'); thumb.className = 'thumb';
    if (r.thumb_url) { const img = document.createElement('img'); img.src = r.thumb_url; img.alt = ''; img.onerror = () => img.remove(); thumb.appendChild(img); }
    const quote = document.createElement('span'); quote.className = 'quote';
    quote.textContent = r.quote ? `“${r.quote}”` : '';
    r1.append(thumb, quote);
    const r2 = document.createElement('span'); r2.className = 'r2';
    const badge = document.createElement('span'); badge.className = 'badge mono';
    const verified = r.confidence === 'verified';   // P0 rule: ONLY 'verified' counts
    badge.textContent = verified ? '✓ VERIFIED' : 'REVIEW';
    badge.classList.toggle('review', !verified);
    const who = document.createElement('span'); who.className = 'who mono';
    const whoText = r.speaker && verified ? r.speaker.toUpperCase() + ' · ' : (!verified ? 'UNKNOWN · ' : '');
    who.textContent = whoText + showTime(r.timestamp);
    r2.append(badge, who);
    b.append(r1, r2);
    list.appendChild(b);
  });
}
function renderPinned(s, fb) {
  $('pinned-title').textContent = s ? s.summary : (fb && fb.summary) || 'This moment';
  $('pinned-time').textContent = s ? time(s.start_ts) : (fb && fb.timeText) || '';
  const q = $('pinned-quote');
  const quote = s ? s.quote : (fb && fb.quote) || null;
  q.textContent = quote ? `“${quote}”` : '';
  q.hidden = !quote;
}
function renderDay() {
  const d = state.day || {};
  $('day-spend').textContent = typeof d.spend === 'number' ? 'SPEND $' + d.spend.toFixed(2)
    : (d.spendState === 'cached' ? 'SPEND · CACHED' : 'SPEND · OFFLINE');
  const box = $('day-rows');
  box.innerHTML = '';
  const section = (title, stateFlag, rows, emptyText) => {
    const h = document.createElement('span');
    h.className = 'day-head mono';
    h.textContent = title + (stateFlag === 'cached' ? ' · CACHED' : stateFlag === 'offline' ? ' · OFFLINE' : '');
    box.appendChild(h);
    if (stateFlag === 'offline') {
      const r = document.createElement('span'); r.className = 'day-row dim'; r.textContent = 'OFFLINE · NOT LOADED'; box.appendChild(r);
      return;
    }
    if (!rows.length) {
      const r = document.createElement('span'); r.className = 'day-row dim'; r.textContent = emptyText; box.appendChild(r);
      return;
    }
    rows.forEach(text => {
      const r = document.createElement('span'); r.className = 'day-row'; r.textContent = text; box.appendChild(r);
    });
  };
  const people = (d.people || []).slice(0, 5).map(p => p.name + (typeof p.scene_count === 'number' ? ' · ' + p.scene_count + ' SCENES' : ''));
  section('PEOPLE', d.peopleState, people, 'NO PEOPLE TODAY');
  if ((d.people || []).length > 5) { const m = document.createElement('span'); m.className = 'day-row dim'; m.textContent = '+' + ((d.people || []).length - 5) + ' MORE'; box.appendChild(m); }
  const facts = (d.facts || []).slice(0, 4).map(f => f.text);
  section('FACTS', d.factsState, facts, 'NO FACTS TODAY');
  if ((d.facts || []).length > 4) { const m = document.createElement('span'); m.className = 'day-row dim'; m.textContent = '+' + ((d.facts || []).length - 4) + ' MORE'; box.appendChild(m); }
  const ups = (d.followups || []).slice(0, 4).map(f => (f.person ? f.person.toUpperCase() + ' · ' : '') + (f.promise || f.draft || 'FOLLOW-UP'));
  section('FOLLOW-UPS', d.followupsState, ups, 'NONE PENDING');
  if ((d.followups || []).length > 4) { const m = document.createElement('span'); m.className = 'day-row dim'; m.textContent = '+' + ((d.followups || []).length - 4) + ' MORE'; box.appendChild(m); }
}
function renderDetail(s) {
  $('detail-type').textContent = (s.type || 'scene').toUpperCase();
  $('detail-title').textContent = s.summary;
  $('detail-time').textContent = time(s.start_ts);
  const q = $('detail-quote');
  q.textContent = s.quote ? `“${s.quote}”` : '';
  q.hidden = !s.quote;
  const b = $('detail-badge');
  b.textContent = s.verified ? '✓ VERIFIED' : 'REVIEW';
  b.classList.toggle('review', !s.verified);
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
  clearPinError();   // any pin error clears on navigation
  if (screen === 'stop') { const h = $('stop-hint'); if (h) { h.textContent = 'SWIPE DOWN, THEN PINCH TO STOP'; h.style.color = ''; } }
  document.querySelectorAll('.screen').forEach(s => s.classList.toggle('active', s.id === screen));
  state.screen = screen;
  updateBanner();
  if (screen === 'now') renderNow();
  if (screen === 'timeline') renderTimeline();
  if (screen === 'day') renderDay();
  setFocus(focus);
}
function back() {
  // Back always returns to Timeline (spec §8.3); from Timeline, back to Now
  show(state.screen === 'timeline' ? 'now' : 'timeline');
}

// ---- Actions ---------------------------------------------------------------
state.pinned = new Set();
// (P1: the 1.2s flashPinned transient is gone; pin success now lands on the
// persistent #pinned screen. Only the P0 error states below remain transient.)
// ---- Transient pin/start error states (cleared on navigation or after 2.5s) --
let pinErrorTimer = null;
let pinErrorRestore = null;
function clearPinError() {
  if (pinErrorTimer) { clearTimeout(pinErrorTimer); pinErrorTimer = null; }
  if (pinErrorRestore) { const restore = pinErrorRestore; pinErrorRestore = null; restore(); }
}
function showPinNowError() {
  clearPinError();
  const button = $('pin-now'), hintEl = $('pin-now-hint');
  const originalHTML = button.innerHTML, originalHint = hintEl.textContent;
  button.classList.add('pin-failed');
  button.innerHTML = '<span>PIN FAILED</span>';
  hintEl.textContent = 'TRY AGAIN';
  pinErrorRestore = () => { button.classList.remove('pin-failed'); button.innerHTML = originalHTML; hintEl.textContent = originalHint; };
  pinErrorTimer = setTimeout(clearPinError, 2500);
}
function showReceiptPinError(button) {
  clearPinError();
  const badge = button ? button.querySelector('.badge') : null, footer = $('answer-footer');
  if (!badge) return;
  const oldBadge = badge.textContent, oldFooter = footer.textContent;
  badge.textContent = 'PIN FAILED';
  badge.classList.add('failed');
  footer.textContent = 'PIN FAILED · TRY AGAIN';
  pinErrorRestore = () => { badge.textContent = oldBadge; badge.classList.remove('failed'); footer.textContent = oldFooter; };
  pinErrorTimer = setTimeout(clearPinError, 2500);
}
let startErrorTimer = null;
function showStartError() {
  const b = $('start-recording');
  if (!b) return;
  if (b.dataset.err) {   // already showing the error: just extend the timer, keep the true original text
    clearTimeout(startErrorTimer);
    startErrorTimer = setTimeout(() => { b.textContent = 'Start recording'; b.classList.remove('danger'); delete b.dataset.err; }, 2500);
    return;
  }
  b.dataset.err = '1';
  b.textContent = 'COULDNT START · TRY AGAIN';
  b.classList.add('danger');
  startErrorTimer = setTimeout(() => { b.textContent = 'Start recording'; b.classList.remove('danger'); delete b.dataset.err; }, 2500);
}
async function activate(el) {
  const action = el.dataset.action;
  if (action === 'pin-now') {
    clearPinError();
    const s = state.scenes[0];
    if (!(await pin(s && s.id))) { showPinNowError(); return; }   // never show success on failure
    if (s) state.pinned.add(s.id);
    renderPinned(s, { summary: 'This moment', timeText: time(new Date().toISOString()), quote: null });
    show('pinned');
  }
  if (action === 'go-timeline') show('timeline');
  if (action === 'go-day') { await loadDay(); show('day'); }
  if (action === 'go-ask') show('ask');
  if (action === 'go-stop') show('stop', 0);           // "Keep recording" is focused first
  if (action === 'keep') show('now');
  if (action === 'stop') {
    let ok;
    if (CONFIG.useMock) ok = true;
    else {
      if (!state.sessionId) await loadStatus();   // refresh before giving up
      ok = state.sessionId ? await endSession() : false;
    }
    if (!ok) {   // stay on Stop, keep recording, show the failure
      const hint = $('stop-hint');
      if (hint) { hint.textContent = 'COULDNT STOP · TRY AGAIN'; hint.style.color = 'var(--red-text)'; }
      return;
    }
    state.recording = false;
    show('dark');
    $('toast').classList.add('show');
    setTimeout(() => $('toast').classList.remove('show'), 2000);
  }
  if (action === 'start-recording') {
    if (!(await startSession())) { showStartError(); return; }
    state.recording = true;
    show('now');
  }
  if (action === 'open-scene') {
    const s = state.scenes.find(x => x.id === el.dataset.id);
    if (!s) return;
    renderDetail(s);   // cached scene only, no fetch (P2 owns scenes/{id})
    show('detail');
    setFocus(0);
  }
  if (action === 'ask-chip') runAsk(el.textContent.trim());
  if (action === 'ask-input') {
    const q = el.value.trim();
    if (q) runAsk(q);
  }
  if (action === 'pin-receipt') {
    clearPinError();
    if (!(await pin(el.dataset.id))) { showReceiptPinError(el); return; }   // never show success on failure
    state.pinned.add(el.dataset.id);
    const s = state.scenes.find(x => x.id === el.dataset.id);
    const r = state.lastAnswer && state.lastAnswer.receipts && state.lastAnswer.receipts.find(x => x.scene_id === el.dataset.id);
    renderPinned(s, r ? { summary: r.quote, timeText: showTime(r.timestamp), quote: r.quote } : null);
    show('pinned');
  }
}
async function runAsk(q) {
  show('answer');
  $('answer-q').textContent = q;
  $('answer-a').textContent = 'Checking the footage…';
  $('receipts').innerHTML = '';
  const res = await ask(q);
  renderAnswer(q, res);
  setFocus(0);
  $('ask-input').value = '';
}

// ---- Keys (band gestures) ----------------------------------------------------
document.addEventListener('keydown', (e) => {
  const typing = document.activeElement && document.activeElement.tagName === 'INPUT';
  if (state.screen === 'dark') { e.preventDefault(); show('timeline'); return; }   // any gesture wakes the lens
  if (typing) {
    if (e.key === 'Escape') { e.preventDefault(); document.activeElement.blur(); return; }   // blur, do NOT go back
    if (e.key.startsWith('Arrow')) return;   // caret moves natively: no focus move, no preventDefault
    // Enter and Backspace fall through below: Enter still submits, Backspace stays native
  }
  if (e.key === 'ArrowDown' && state.screen === 'answer') { e.preventDefault(); back(); return; }
  if ((e.key === 'ArrowDown' || e.key === 'ArrowRight') && !typing) { e.preventDefault(); setFocus(state.focusIndex + 1); }
  else if ((e.key === 'ArrowUp' || e.key === 'ArrowLeft') && !typing) { e.preventDefault(); setFocus(state.focusIndex - 1); }
  else if (e.key === 'Enter') {
    const el = focusables()[state.focusIndex];
    // Pinch on an empty Ask box: let the system Composer open (dictation / handwriting)
    if (el && el.id === 'ask-input' && !el.value.trim()) return;
    e.preventDefault();
    if (el) activate(el);
  }
  else if (e.key === 'Escape' || (e.key === 'Backspace' && !typing)) { e.preventDefault(); back(); }
});
// ---- Touch / swipe (touchscreen / trackpad; mirrors the arrow model) --------
// Mapping, documented here so it stays consistent with keys: swipe left = focus
// next (ArrowRight), swipe right = focus prev (ArrowLeft), swipe up = focus prev
// (ArrowUp). Swipe down = back, NOT next: down is the established back gesture
// (spec §8.3), so it takes precedence over ArrowDown's focus-next role.
// Threshold ~40px on the dominant axis; taps (<40px both axes) fall through to
// the click listener below, so tap-to-activate is unchanged. Swipes are ignored
// while an input is focused (typing), same as the arrow keys.
let touchStartX = 0, touchStartY = 0, touchActive = false;
document.addEventListener('touchstart', (e) => {
  if (e.touches.length !== 1) { touchActive = false; return; }
  touchStartX = e.touches[0].clientX; touchStartY = e.touches[0].clientY; touchActive = true;
}, { passive: true });
document.addEventListener('touchend', (e) => {
  if (!touchActive) return;
  touchActive = false;
  const t = e.changedTouches[0];
  if (!t) return;
  if (document.activeElement && document.activeElement.tagName === 'INPUT') return;   // typing: ignore
  if (state.screen === 'dark') { show('timeline'); return; }   // any gesture wakes the lens
  const dx = t.clientX - touchStartX, dy = t.clientY - touchStartY;
  if (Math.abs(dx) < 40 && Math.abs(dy) < 40) return;   // tap, not a swipe
  if (Math.abs(dx) > Math.abs(dy)) setFocus(state.focusIndex + (dx < 0 ? 1 : -1));
  else if (dy > 0) back();
  else setFocus(state.focusIndex - 1);   // swipe up = prev
}, { passive: true });
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
        if (event === 'status' && typeof m === 'object') {
          const st = JSON.parse(m.data);
          if (typeof st.recording === 'boolean') state.recording = st.recording;
        }
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
  await loadStatus();
  show('now');   // falls back to Timeline when not recording
  setInterval(() => { if (state.screen === 'now') $('clock').textContent = new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }); }, 15000);
  connectLive();
})();
