(function () {
'use strict';
const $ = s => document.querySelector(s);
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const lsGet = k => { try { return JSON.parse(localStorage.getItem(k)); } catch (e) { return null; } };
const lsSet = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} };
const fmtDT = ms => ms ? new Date(ms).toLocaleString([], { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' }) : '';
const fmtD = ms => ms ? new Date(ms).toLocaleDateString([], { day: 'numeric', month: 'short' }) : '';
const plural = (n, a, b) => n + ' ' + (n === 1 ? a : (b || a + 's'));
const CHECK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 12.5 4.5 4.5L19 7.5"/></svg>';
const ROLE_LABEL = { name: 'Name', college: 'College', email: 'Email', phone: 'Phone', time: 'Submitted at' };
const CORE = ['name', 'college', 'email', 'phone'];

async function api(path, method, body, raw) {
  const opt = { method: method || 'GET' };
  if (raw) opt.body = raw;
  else if (body !== undefined) { opt.headers = { 'Content-Type': 'application/json' }; opt.body = JSON.stringify(body); }
  let r;
  try { r = await fetch(path, opt); } catch (e) { throw new Error('Cannot reach the server. Is it running?'); }
  let d = null;
  try { d = await r.json(); } catch (e) {}
  if (!r.ok) throw new Error((d && d.error) || 'Request failed (' + r.status + ')');
  return d;
}

const S = { events: [], summary: null, cur: 'all', q: '', view: 'table', status: 'all', rows: [], sort: { col: null, dir: 1 }, limit: 200,
  colsOpen: false, page: 'people', turnEv: null, turns: null, drawer: null, loading: true, err: '' };
let modal = null, imp = null, toastT, reqId = 0, dragging = false;

function toast(msg, err) {
  const r = $('#toastRoot');
  r.innerHTML = '<div class="toast' + (err ? ' err' : '') + '" role="status">' + esc(msg) + '</div>';
  clearTimeout(toastT);
  toastT = setTimeout(() => { r.innerHTML = ''; }, err ? 5500 : 2600);
}
const evById = id => S.events.find(e => e.id === id);
const curEv = () => S.cur === 'all' ? null : evById(S.cur);

/* ------------------------------------------------------------ loading */
async function loadEvents() {
  S.events = await api('/api/events');
  S.summary = await api('/api/summary');
  if (S.cur !== 'all' && !evById(S.cur)) S.cur = 'all';
  if (S.turnEv && !evById(S.turnEv)) S.turnEv = null;
}
async function loadPeople() {
  const id = ++reqId;
  const rows = await api('/api/people?event=' + encodeURIComponent(S.cur) + '&q=' + encodeURIComponent(S.q));
  if (id === reqId) S.rows = rows;
}
async function loadTurns() {
  if (!S.turnEv) { S.turns = null; return; }
  S.turns = await api('/api/events/' + S.turnEv + '/turns');
}
async function refresh(quiet) {
  try {
    await loadEvents();
    if (S.page === 'people') await loadPeople();
    else { if (!S.turnEv && S.events[0]) S.turnEv = S.events[0].id; await loadTurns(); }
    S.err = '';
    if (S.drawer) await loadDrawer(true);
  } catch (e) {
    S.err = e.message;
    if (!quiet) toast(e.message, true);
  }
  S.loading = false;
  paintAll();
}

/* ------------------------------------------------------------ painting */
function paintAll() {
  paintBanner();
  document.querySelectorAll('.nav a').forEach(a => a.removeAttribute('aria-current'));
  $(S.page === 'people' ? '#navPeople' : '#navTurns').setAttribute('aria-current', 'page');
  $('#pagePeople').hidden = S.page !== 'people';
  $('#pageTurns').hidden = S.page !== 'turns';
  if (S.page === 'people') { paintTabs(); paintStats(); paintTools(); paintResults(); }
  else paintTurns();
  if (S.drawer && S.drawer.data) paintDrawer();
}
function paintBanner() {
  $('#banner').innerHTML = S.err ? '<div class="banner">' + esc(S.err) + '</div>' : '';
}
function paintTabs() {
  const all = S.summary ? S.summary.people : 0;
  let h = '<button class="tab" role="tab" data-act="tab" data-ev="all" aria-selected="' + (S.cur === 'all') + '"><b>All events</b><span>' + plural(all, 'person', 'people') + '</span></button>';
  h += S.events.map(e => '<button class="tab" role="tab" data-act="tab" data-ev="' + e.id + '" aria-selected="' + (S.cur === e.id) + '"><b>' + esc(e.name) + '</b><span>' + e.came + ' / ' + e.people + ' came</span></button>').join('');
  h += '<button class="tab add" data-act="newEvent">+ New event</button>';
  $('#tabs').innerHTML = h;
}
function paintStats() {
  const el = $('#stats');
  const ev = curEv();
  if (!S.summary) { el.innerHTML = ''; return; }
  if (ev) el.innerHTML = stat(ev.people, 'People', '') + stat(ev.came, 'Came', 'ok') + stat(ev.not_yet, 'Not yet', 'wait') + stat(ev.repeats, 'Repeat entries merged', 'merge');
  else el.innerHTML = stat(S.summary.people, 'People', '') + stat(S.summary.events, 'Events', '') + stat(S.summary.came_any, 'Came to at least one', 'ok') + stat(S.summary.repeats, 'Repeat entries merged', 'merge');
}
const stat = (n, l, c) => '<div class="stat ' + c + '"><b>' + n + '</b><span>' + l + '</span></div>';

function colsFor(ev) {
  const saved = lsGet('ed:cols:' + ev.id);
  if (Array.isArray(saved)) { const ok = saved.filter(c => ev.cols.includes(c)); if (ok.length) return ok; }
  const roles = CORE.map(r => ev.map[r]).filter(c => c && ev.cols.includes(c));
  const rest = ev.cols.filter(c => !roles.includes(c));
  return ev.cols.length <= 8 ? roles.concat(rest) : roles.concat(rest).slice(0, 8);
}
function paintTools() {
  const ev = curEv();
  $('#viewSeg').hidden = !ev;
  $('#btnCols').hidden = !ev;
  document.querySelectorAll('#viewSeg button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.v === S.view)));
  if (!ev) S.view = 'table';
  const base = S.rows, came = base.filter(r => r.came).length, merged = base.filter(r => r.merged).length;
  const defs = [['all', 'Everyone', base.length], ['came', 'Came', came], ['wait', 'Not yet', base.length - came], ['merged', 'Merged repeats', merged]];
  $('#chips').hidden = S.view === 'split';
  $('#chips').innerHTML = defs.map(x => '<button class="chip" data-act="status" data-v="' + x[0] + '" aria-pressed="' + (S.status === x[0]) + '">' + x[1] + '<small>' + x[2] + '</small></button>').join('');
  $('#colPop').hidden = !(S.colsOpen && ev);
  if (S.colsOpen && ev) paintColPop(ev);
}
function paintColPop(ev) {
  const vis = colsFor(ev);
  $('#colPop').innerHTML = '<div class="head"><button class="btn small" data-act="colsAll">All</button><button class="btn small" data-act="colsKey">Name + college</button><button class="btn small" data-act="colsContact">Contact</button></div>' +
    ev.cols.map(c => '<div class="row"><label><input type="checkbox" data-col="' + esc(c) + '"' + (vis.includes(c) ? ' checked' : '') + '> ' + esc(c) + '</label><button class="btn small ghost" data-act="copyCol" data-col="' + esc(c) + '">Copy</button></div>').join('');
}
function hl(text, toks) {
  text = String(text == null ? '' : text);
  if (!toks.length || !text) return esc(text);
  const re = new RegExp('(' + toks.map(t => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|') + ')', 'gi');
  return text.split(re).map((p, i) => i % 2 ? '<mark>' + esc(p) + '</mark>' : esc(p)).join('');
}
const tokens = () => S.q.trim().toLowerCase().split(/\s+/).filter(Boolean);
function evList(r, toks) {
  return '<ul class="evlist">' + r.events.map(t => '<li>' + hl(t.name, toks) + ' <span class="tag ' + (t.came ? 'ok' : 'wait') + '">' + (t.came ? 'Came · turn ' + t.turn : 'Not yet') + '</span></li>').join('') + '</ul>';
}
function sorted(list, ev) {
  const s = S.sort; if (!s.col) return list;
  const val = r => ev ? (r.fields[s.col] || '') : (r.fields[s.col] || '');
  return list.slice().sort((a, b) => String(val(a)).localeCompare(String(val(b)), undefined, { numeric: true, sensitivity: 'base' }) * s.dir);
}
function tableHTML(list, ev, cols, toks, o) {
  o = o || {};
  if (!list.length) return '<div class="empty">' + (o.empty || 'Nothing here.') + '</div>';
  const shown = list.slice(0, S.limit);
  const heads = ev ? cols : CORE;
  let h = '<table><thead><tr>';
  if (ev) h += '<th class="chk nosort" title="Came">✓</th>';
  if (o.turn) h += '<th class="nosort">Turn</th>';
  heads.forEach(c => {
    const label = ev ? c : ROLE_LABEL[c], on = S.sort.col === c;
    h += '<th data-act="sort" data-col="' + esc(c) + '" aria-sort="' + (on ? (S.sort.dir > 0 ? 'ascending' : 'descending') : 'none') + '">' + esc(label) + (on ? (S.sort.dir > 0 ? ' ▲' : ' ▼') : '') + '</th>';
  });
  h += '<th class="nosort">Events</th>';
  if (o.checkin) h += '<th class="nosort">Checked in</th>';
  h += '</tr></thead><tbody>';
  for (const r of shown) {
    h += '<tr data-act="row" data-person="' + r.person_id + '" class="' + (r.came && ev ? 'came' : '') + '">';
    if (ev) h += '<td class="chk"><button class="tick" data-act="tick" data-person="' + r.person_id + '" data-ev="' + ev.id + '" aria-pressed="' + r.came + '" aria-label="' + (r.came ? 'Came, undo for ' : 'Mark as came: ') + esc(r.name) + '">' + CHECK + '</button></td>';
    if (o.turn) h += '<td class="turn">' + (r.turn ? '#' + r.turn : '') + '</td>';
    heads.forEach((c, i) => {
      const v = r.fields[c] || '';
      h += '<td title="' + esc(v) + '">' + hl(v, toks) + (i === 0 && r.n > 1 ? '<span class="dup" title="Filled the form ' + r.n + ' times; merged into one entry">×' + r.n + '</span>' : '') + '</td>';
    });
    h += '<td class="evcell">' + evList(r, toks) + '</td>';
    if (o.checkin) h += '<td class="mono">' + esc(fmtDT(r.came_at)) + '</td>';
    h += '</tr>';
  }
  h += '</tbody></table>';
  if (list.length > shown.length) h += '<div class="more"><button class="btn" data-act="more">Show more (' + (list.length - shown.length) + ' left)</button></div>';
  return h;
}
function keepScroll(box, fn) {
  const pos = [...box.querySelectorAll('.tablewrap')].map(x => [x.scrollTop, x.scrollLeft]);
  fn();
  box.querySelectorAll('.tablewrap').forEach((x, i) => { if (pos[i]) { x.scrollTop = pos[i][0]; x.scrollLeft = pos[i][1]; } });
}
function paintResults() {
  const box = $('#results');
  if (S.loading) { box.innerHTML = '<p class="hint"><span class="spin"></span>Loading…</p>'; return; }
  if (!S.events.length) {
    box.innerHTML = '<div class="welcome"><h1>Every event, one list of people.</h1><div class="how"><div><b>Add data</b><span>Upload an Excel or CSV file of form responses, or paste rows copied from a sheet.</span></div><div><b>Repeats merge</b><span>Someone who filled the form twice becomes one entry. You are asked before anything that looks like a re-upload.</span></div><div><b>Search, tick, turn order</b><span>Find people by name, college or event, tick who arrived, and see them in first-come order.</span></div></div><div><button class="btn primary" data-act="openImport">Add your first event</button></div></div>';
    return;
  }
  const ev = curEv(), toks = tokens();
  keepScroll(box, () => {
    const noRes = S.q.trim() ? 'No one matches “' + esc(S.q.trim()) + '”.' : 'Nothing here.';
    if (ev && !ev.cols.length) { box.innerHTML = '<div class="welcome"><h1 style="font-size:22px">No people in this event yet</h1><p class="hint">Upload the registration file or add one person.</p><div><button class="btn primary" data-act="openImport">Add data</button> <button class="btn" data-act="addPerson">Add person</button></div></div>'; return; }
    const cols = ev ? colsFor(ev) : CORE;
    if (S.view === 'split' && ev) {
      const came = sorted(S.rows.filter(r => r.came), ev).sort((a, b) => S.sort.col ? 0 : (a.turn - b.turn)), wait = sorted(S.rows.filter(r => !r.came), ev);
      box.innerHTML = '<div class="split"><div class="panel came"><h2>Came <span class="pill">' + came.length + '</span></h2><div class="tablewrap">' + tableHTML(came, ev, cols, toks, { turn: true, checkin: true, empty: S.q.trim() ? noRes : 'No one has been ticked yet.' }) + '</div></div><div class="panel wait"><h2>Not yet <span class="pill">' + wait.length + '</span></h2><div class="tablewrap">' + tableHTML(wait, ev, cols, toks, { empty: S.q.trim() ? noRes : 'Everyone has come.' }) + '</div></div></div>';
      return;
    }
    let list = S.rows;
    if (S.status === 'came') list = list.filter(r => r.came); else if (S.status === 'wait') list = list.filter(r => !r.came); else if (S.status === 'merged') list = list.filter(r => r.merged);
    list = sorted(list, ev);
    if (ev && S.status === 'came' && !S.sort.col) list = list.slice().sort((a, b) => a.turn - b.turn);
    box.innerHTML = '<div class="tablewrap">' + tableHTML(list, ev, cols, toks, { turn: ev && S.status === 'came', empty: noRes }) + '</div>';
  });
}

/* ------------------------------------------------------------ person drawer */
async function openDrawer(pid) { S.drawer = { id: pid, data: null }; await loadDrawer(); paintAll(); }
async function loadDrawer(quiet) {
  try { S.drawer.data = await api('/api/people/' + S.drawer.id); }
  catch (e) { if (!quiet) toast(e.message, true); S.drawer = null; $('#modalRoot').innerHTML = ''; }
}
function paintDrawer() {
  if (modal) return;
  const d = S.drawer.data;
  const sub = [d.college, d.email, d.phone].filter(Boolean).map(esc).join(' · ');
  const bullets = d.events.map(e => '<li><div class="evrow"><b>' + esc(e.name) + '</b> <span class="tag ' + (e.came ? 'ok' : 'wait') + '">' + (e.came ? 'Came · turn ' + e.turn + ' · ' + esc(fmtDT(e.came_at)) : 'Not yet') + '</span> <button class="btn small ' + (e.came ? '' : 'primary') + '" data-act="tick" data-person="' + d.id + '" data-ev="' + e.event_id + '">' + (e.came ? 'Undo' : 'Mark as came') + '</button></div></li>').join('');
  const tables = d.events.map(e => {
    const rows = e.cols.filter(c => e.fields[c]).map(c => {
      const alts = e.alts[c] || [];
      return '<tr><th>' + esc(c) + '</th><td>' + esc(e.fields[c]) + (alts.length ? '<span class="also">Also entered: ' + alts.map(esc).join(' · ') + '</span>' : '') + '</td></tr>';
    }).join('');
    return '<h3>' + esc(e.name) + '</h3>' + (e.n > 1 ? '<div class="notice">Filled the form <b>' + e.n + ' times</b>; merged into one entry' + (e.last_at ? ' (latest ' + esc(fmtDT(e.last_at)) + ')' : '') + '. The latest answers are shown.</div>' : '') +
      '<table class="kv"><tbody>' + rows + '</tbody></table><p class="hint">From ' + esc(e.files.join(', ')) + '</p>';
  }).join('');
  $('#modalRoot').innerHTML = '<div class="shade side" data-act="closeBg"><div class="card" role="dialog" aria-modal="true" aria-label="Details"><div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start"><div><h2>' + esc(d.name) + '</h2><p class="meta">' + sub + '</p></div><button class="btn small" data-act="closeDrawer">Close</button></div><h3>Events</h3><ul class="bullets">' + bullets + '</ul>' + tables + '</div></div>';
}
function closeAll() { modal = null; imp = null; S.drawer = null; $('#modalRoot').innerHTML = ''; }

/* ------------------------------------------------------------ actions on people */
async function tick(pid, evId) {
  const row = S.rows.find(r => r.person_id === pid);
  let was = false;
  if (S.drawer && S.drawer.data) { const e = S.drawer.data.events.find(x => x.event_id === evId); was = e ? e.came : false; }
  else if (row) was = row.came;
  try { await api('/api/events/' + evId + '/attendance', 'POST', { person_id: pid, came: !was }); }
  catch (e) { toast(e.message, true); }
  await refresh(true);
}

/* ------------------------------------------------------------ turn order page */
function paintTurns() {
  $('#turnTabs').innerHTML = S.events.map(e => '<button class="tab" role="tab" data-act="turnTab" data-ev="' + e.id + '" aria-selected="' + (S.turnEv === e.id) + '"><b>' + esc(e.name) + '</b><span>' + e.came + ' came</span></button>').join('');
  const box = $('#turnBody');
  if (!S.events.length) { box.innerHTML = '<div class="welcome"><h1 style="font-size:24px">No events yet</h1><p class="hint">Add an event first.</p></div>'; return; }
  if (!S.turns) { box.innerHTML = '<p class="hint"><span class="spin"></span>Loading…</p>'; return; }
  const t = S.turns, n = t.turns.length;
  const keepArrive = document.getElementById('arriveQ');
  const typed = keepArrive ? keepArrive.value : '';
  box.innerHTML = '<div class="turnhead"><div><h1>' + esc(t.event.name) + '</h1><p class="meta">Turn order: first come, first served. ' + plural(n, 'person', 'people') + ' ticked, ' + t.stats.not_yet + ' not yet. Drag a row, use ▲ ▼, or type a position.</p></div><div class="actions"><a class="btn" href="/api/export.xlsx?event=' + t.event.id + '">Download Excel</a><a class="btn" href="/api/export.pdf?event=' + t.event.id + '&view=split">Download PDF</a></div></div>' +
    '<div class="arrive"><label class="search"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg><input id="arriveQ" type="search" placeholder="Someone just arrived? Type their name to tick them in" autocomplete="off" value="' + esc(typed) + '"></label><div class="sug" id="sug" hidden></div></div>' +
    (n ? '<ol class="turns" id="turnList">' + t.turns.map(r => '<li class="turn" draggable="true" data-person="' + r.person_id + '" data-turn="' + r.turn + '"><span class="handle" aria-hidden="true">⋮⋮</span><span class="num">' + r.turn + '</span><div class="who"><b>' + esc(r.name) + (r.n > 1 ? ' <span class="dup">×' + r.n + '</span>' : '') + '</b><span>' + esc([r.college, r.email, r.phone].filter(Boolean).join(' · ')) + ' · came ' + esc(fmtDT(r.came_at)) + '</span></div><div class="ctl"><button class="btn small" data-act="turnUp" data-person="' + r.person_id + '" data-turn="' + r.turn + '" aria-label="Move up"' + (r.turn === 1 ? ' disabled' : '') + '>▲</button><button class="btn small" data-act="turnDown" data-person="' + r.person_id + '" data-turn="' + r.turn + '" aria-label="Move down"' + (r.turn === n ? ' disabled' : '') + '>▼</button><input type="number" min="1" max="' + n + '" value="' + r.turn + '" data-pos="' + r.person_id + '" aria-label="Turn position"><button class="btn small" data-act="turnSet" data-person="' + r.person_id + '">Move</button><button class="btn small danger" data-act="turnUndo" data-person="' + r.person_id + '">Undo came</button></div></li>').join('') + '</ol>' : '<div class="empty">No one has been ticked yet. Tick people on the People page, or search above as they arrive.</div>');
  if (keepArrive && typed) { const i = $('#arriveQ'); i.focus(); i.setSelectionRange(typed.length, typed.length); }
}
async function moveTurn(pid, to) {
  try { await api('/api/events/' + S.turnEv + '/turns/move', 'POST', { person_id: pid, to }); }
  catch (e) { toast(e.message, true); }
  await refresh(true);
}
let arriveT;
async function arriveSearch(q) {
  const sug = $('#sug'); if (!sug) return;
  if (!q.trim()) { sug.hidden = true; return; }
  const rows = (await api('/api/people?event=' + S.turnEv + '&q=' + encodeURIComponent(q))).filter(r => !r.came).slice(0, 8);
  sug.hidden = false;
  sug.innerHTML = rows.length ? rows.map(r => '<button data-act="arrive" data-person="' + r.person_id + '"><span><b>' + esc(r.name) + '</b> <span class="hint">' + esc(r.college || '') + '</span></span><span class="tag">Tick in</span></button>').join('') : '<div class="empty" style="padding:12px">No one waiting matches that.</div>';
}

/* ------------------------------------------------------------ add person */
function evColsExtra(ev) {
  const roleCols = new Set(Object.values(ev.map));
  return ev.cols.filter(c => !roleCols.has(c));
}
function openPerson() {
  if (!S.events.length) { toast('Create an event first.', true); return; }
  modal = { type: 'person', sel: new Set(S.cur !== 'all' ? [S.cur] : []) };
  paintPerson('');
}
function paintPerson(note) {
  $('#modalRoot').innerHTML = '<div class="shade" data-act="closeBg"><div class="card" role="dialog" aria-modal="true"><h2>Add a person</h2><p class="hint">Tick every event they are joining. If they are already in the list, the entries are merged instead of duplicated.</p>' + (note ? '<div class="notice">' + esc(note) + '</div>' : '') +
    '<div class="field"><span>Events</span><div class="cbs">' + S.events.map(e => '<label class="cb"><input type="checkbox" data-pev="' + e.id + '"' + (modal.sel.has(e.id) ? ' checked' : '') + '> ' + esc(e.name) + '</label>').join('') + '</div></div>' +
    '<div class="grid2">' + CORE.map(r => '<label class="field"><span>' + ROLE_LABEL[r] + (r === 'name' ? ' *' : '') + '</span><input id="pf_' + r + '" autocomplete="off"></label>').join('') + '</div><div class="grid2" id="pExtra"></div>' +
    '<label class="cb"><input type="checkbox" id="pfCame"> Already here, mark as came</label><div class="foot"><button class="btn" data-act="closeModal">Cancel</button><button class="btn" data-act="personNext">Add and next</button><button class="btn primary" data-act="personSave">Add person</button></div></div></div>';
  paintExtras();
  setTimeout(() => { const i = $('#pf_name'); if (i) i.focus(); }, 30);
}
function paintExtras() {
  const box = $('#pExtra'); if (!box) return;
  const old = {}; box.querySelectorAll('input[data-extra]').forEach(i => { old[i.dataset.extra] = i.value; });
  const names = [];
  S.events.filter(e => modal.sel.has(e.id)).forEach(e => evColsExtra(e).forEach(c => { if (!names.includes(c)) names.push(c); }));
  box.innerHTML = names.map(c => '<label class="field"><span>' + esc(c) + '</span><input data-extra="' + esc(c) + '" value="' + esc(old[c] || '') + '" autocomplete="off"></label>').join('');
}
async function savePerson(again) {
  const ids = [...modal.sel];
  if (!ids.length) { toast('Tick at least one event.', true); return; }
  const values = {}; CORE.forEach(r => { values[r] = ($('#pf_' + r).value || '').trim(); });
  if (!values.name) { toast('Enter a name.', true); return; }
  const extra = {}; document.querySelectorAll('#pExtra input[data-extra]').forEach(i => { if (i.value.trim()) extra[i.dataset.extra] = i.value.trim(); });
  try {
    const r = await api('/api/people', 'POST', { event_ids: ids, values, extra, came: $('#pfCame').checked });
    const merged = r.results.filter(x => x.merged).map(x => x.event), fresh = r.results.filter(x => !x.merged).map(x => x.event);
    let msg = '';
    if (fresh.length) msg += 'Added ' + values.name + ' to ' + fresh.join(', ') + '. ';
    if (merged.length) msg += values.name + ' was already in ' + merged.join(', ') + ', so the entries were merged.';
    await refresh(true);
    if (again) { paintPerson(msg.trim()); } else { closeAll(); toast(msg.trim()); }
  } catch (e) { toast(e.message, true); }
}

/* ------------------------------------------------------------ import wizard */
function openImport(target) {
  const pre = target || (S.cur !== 'all' ? String(S.cur) : (S.events[0] ? String(S.events[0].id) : 'new'));
  imp = { step: 'pick', target: pre, newName: '', fileName: '', sheets: [], sheetIdx: 0, headers: [], rows: [], map: {}, err: '', skipCross: false, ask: null };
  modal = { type: 'import' }; paintImport();
}
function paintImport() {
  let body = '';
  if (imp.step === 'pick') {
    const opts = S.events.map(e => '<option value="' + e.id + '"' + (imp.target === String(e.id) ? ' selected' : '') + '>' + esc(e.name) + '</option>').join('') + '<option value="new"' + (imp.target === 'new' ? ' selected' : '') + '>+ New event…</option>';
    body = '<h2>Add data</h2><label class="field"><span>Which event is this for?</span><select id="impTarget">' + opts + '</select></label><label class="field" id="newNameBox"' + (imp.target === 'new' ? '' : ' hidden') + '><span>New event name</span><input id="impNewName" placeholder="e.g. Hackathon 2026" value="' + esc(imp.newName) + '"></label>' +
      '<div class="drop" id="drop"><b>Drop an Excel or CSV file here</b><span class="hint">.xlsx or .csv</span><button class="btn primary" data-act="pickFile">Choose file</button><input type="file" id="fileIn" accept=".xlsx,.xlsm,.csv,.tsv,.txt" hidden></div>' +
      '<details><summary style="cursor:pointer;font-weight:500">Or paste rows copied from a sheet</summary><label class="field" style="margin-top:8px"><span>Include the header row</span><textarea id="paste"></textarea></label><div style="margin-top:8px"><button class="btn" data-act="usePaste">Use pasted rows</button></div></details>' +
      (imp.err ? '<div class="notice warn">' + esc(imp.err) + '</div>' : '') +
      '<p class="hint">Using a Google Form? Open its linked Google Sheet and choose File › Download › Microsoft Excel (.xlsx), then upload that file here.</p><div class="foot"><button class="btn" data-act="closeModal">Cancel</button></div>';
  } else if (imp.step === 'map') {
    const h = imp.headers;
    const sel = r => '<label class="field"><span>' + ROLE_LABEL[r] + '</span><select data-role="' + r + '"><option value="">— none —</option>' + h.map(x => '<option value="' + esc(x) + '"' + (imp.map[r] === x ? ' selected' : '') + '>' + esc(x) + '</option>').join('') + '</select></label>';
    body = '<h2>Check the columns</h2><p class="hint"><b>' + esc(imp.fileName) + '</b> · ' + plural(imp.rows.length, 'row') + '</p>' +
      (imp.sheets.length > 1 ? '<label class="field"><span>Sheet</span><select id="sheetSel">' + imp.sheets.map((s, i) => '<option value="' + i + '"' + (i === imp.sheetIdx ? ' selected' : '') + '>' + esc(s.name) + ' (' + s.count + ' rows)</option>').join('') + '</select></label>' : '') +
      '<p class="hint">These columns decide who counts as the same person when someone fills the form more than once, or joins another event. Email and phone are strongest; name plus college works when they are missing.</p><div class="grid2">' + ['name', 'college', 'email', 'phone', 'time'].map(sel).join('') + '</div>' +
      '<div class="preview"><table><thead><tr>' + h.map(x => '<th>' + esc(x) + '</th>').join('') + '</tr></thead><tbody>' + imp.rows.slice(0, 5).map(r => '<tr>' + h.map((x, i) => '<td>' + esc(r[i]) + '</td>').join('') + '</tr>').join('') + '</tbody></table></div>' +
      (imp.err ? '<div class="notice warn">' + esc(imp.err) + '</div>' : '') + '<div class="foot"><button class="btn" data-act="impBack">Back</button><button class="btn primary" data-act="impGo">Import</button></div>';
  } else if (imp.step === 'check' || imp.step === 'saving') {
    body = '<h2>' + (imp.step === 'check' ? 'Checking earlier uploads' : 'Saving') + '</h2><p class="hint"><span class="spin"></span>' + (imp.step === 'check' ? 'Comparing this file with what is already saved…' : 'Merging repeat entries and saving to the database…') + '</p>';
  } else if (imp.step === 'ask') {
    const a = imp.ask;
    body = '<h2>' + esc(a.title) + '</h2><div class="notice">' + a.msg + '</div><div class="ask">' + a.opts.map(o => '<button class="opt' + (o.rec ? ' rec' : '') + '" data-act="decide" data-v="' + esc(o.v) + '"><b>' + o.label + '</b><span>' + o.sub + '</span></button>').join('') + '</div>';
  } else if (imp.step === 'done') {
    const r = imp.result;
    body = '<h2>Imported</h2><table class="kv"><tbody><tr><th>Event</th><td>' + esc(r.event.name) + '</td></tr><tr><th>New people</th><td>' + r.new_people + '</td></tr><tr><th>Repeat entries merged</th><td>' + r.merged + '</td></tr>' + (r.skipped ? '<tr><th>Rows skipped</th><td>' + r.skipped + ' (already in this event)</td></tr>' : '') + (r.removed ? '<tr><th>Replaced file</th><td>' + esc(r.removed) + '</td></tr>' : '') + '</tbody></table><p class="hint">Saved to the database.</p><div class="foot"><button class="btn" data-act="openImport">Add another file</button><button class="btn primary" data-act="closeModal">Done</button></div>';
  }
  $('#modalRoot').innerHTML = '<div class="shade" data-act="closeBg"><div class="card" role="dialog" aria-modal="true">' + body + '</div></div>';
  wireImport();
}
function wireImport() {
  const tg = $('#impTarget');
  if (tg) tg.onchange = () => { imp.target = tg.value; $('#newNameBox').hidden = tg.value !== 'new'; };
  const nn = $('#impNewName'); if (nn) nn.oninput = () => { imp.newName = nn.value; };
  const drop = $('#drop'), fin = $('#fileIn'); if (!drop) return;
  fin.onchange = () => { if (fin.files[0]) takeFile(fin.files[0]); };
  ['dragenter', 'dragover'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add('over'); }));
  ['dragleave', 'drop'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove('over'); }));
  drop.addEventListener('drop', e => { const f = e.dataTransfer && e.dataTransfer.files[0]; if (f) takeFile(f); });
}
function targetOk() {
  if (imp.target === 'new' && !imp.newName.trim()) { imp.err = 'Give the new event a name first.'; paintImport(); return false; }
  return true;
}
function takeParsed(p) {
  imp.fileName = p.file_name; imp.sheets = p.sheets;
  setSheet(p.sheets.reduce((b, s, i) => s.count > p.sheets[b].count ? i : b, 0));
}
function setSheet(i) {
  const s = imp.sheets[i]; imp.sheetIdx = i; imp.headers = s.headers; imp.rows = s.rows; imp.map = Object.assign({}, s.map); imp.step = 'map'; imp.err = ''; paintImport();
}
async function takeFile(file) {
  imp.err = ''; if (!targetOk()) return;
  const fd = new FormData(); fd.append('file', file);
  try { takeParsed(await api('/api/parse', 'POST', undefined, fd)); }
  catch (e) { imp.err = e.message; paintImport(); }
}
async function usePaste() {
  imp.err = ''; if (!targetOk()) return;
  try { takeParsed(await api('/api/parse', 'POST', { text: ($('#paste') || {}).value || '' })); }
  catch (e) { imp.err = e.message; paintImport(); }
}
const evName = id => (evById(+id) || {}).name || '';
function importBody() {
  return { event_id: imp.target === 'new' ? null : +imp.target, new_name: imp.newName.trim(), file_name: imp.fileName, headers: imp.headers, rows: imp.rows, map: imp.map };
}
async function analyze() {
  imp.step = 'check'; paintImport();
  try {
    const r = await api('/api/import/analyze', 'POST', Object.assign(importBody(), { skip_cross: imp.skipCross }));
    const up = r.upload && ('“' + esc(r.upload.filename) + '” (uploaded ' + esc(fmtD(r.upload.uploaded_at)) + ', ' + plural(r.upload.rows, 'row') + ') in “' + esc(r.event.name) + '”');
    if (r.kind === 'cross') {
      const mine = imp.target === 'new' ? 'the new event “' + esc(imp.newName.trim()) + '”' : '“' + esc(evName(imp.target)) + '”';
      imp.ask = { title: 'Is this data already in another event?', msg: '<b>' + r.already + ' of your ' + r.total + ' rows</b> are already in ' + up + '.', crossId: r.event.id,
        opts: [{ v: 'cross-yes', rec: true, label: 'Yes, it’s the same data. Add it to “' + esc(r.event.name) + '” instead', sub: 'You’ll be asked next how to handle the rows that are already there.' },
          { v: 'cross-no', label: 'No, this is a different event', sub: 'Keep going with ' + mine + '.' }, { v: 'cancel', label: 'Cancel', sub: 'Don’t import anything.' }] };
      imp.step = 'ask'; paintImport(); return;
    }
    if (r.kind === 'same') {
      let msg = (r.same_name ? 'This file has the same name as ' : 'This looks like a newer copy of ') + up + '.';
      const opts = [];
      if (r.frac >= 0.6) {
        msg += ' <b>' + r.already + ' of your ' + r.total + ' rows</b> are already in this event.';
        if (r.new_rows > 0) opts.push({ v: 'new', rec: true, label: 'Add only the ' + plural(r.new_rows, 'new row') + ' (recommended)', sub: 'Keeps the earlier file and skips the ' + r.already + ' rows already saved.' });
        else msg += ' <b>Nothing in this file is new.</b>';
        opts.push({ v: 'replace', label: 'Replace the earlier file with this one', sub: 'Removes “' + esc(r.upload.filename) + '” and imports all ' + r.total + ' rows from this file. Attendance and turns are kept.' });
      } else {
        msg += ' Only <b>' + r.already + ' of your ' + r.total + ' rows</b> match it, so it may be an updated version.';
        opts.push({ v: 'replace', rec: true, label: 'Replace the earlier file with this one', sub: 'Removes “' + esc(r.upload.filename) + '” and imports all ' + r.total + ' rows from this file. Attendance and turns are kept.' });
      }
      opts.push({ v: 'all', label: 'Import as a separate file', sub: 'Keeps both. People who appear in both are still merged into one entry.' }, { v: 'cancel', label: 'Cancel', sub: 'Don’t import anything.' });
      imp.ask = { title: 'Is this the same file?', msg, opts, uploadId: r.upload.id };
      imp.step = 'ask'; paintImport(); return;
    }
    await commit('all');
  } catch (e) { imp.step = 'map'; imp.err = e.message; paintImport(); }
}
async function decide(v) {
  if (v === 'cancel') { closeAll(); return; }
  if (v === 'cross-yes') { imp.target = String(imp.ask.crossId); imp.skipCross = true; await analyze(); return; }
  if (v === 'cross-no') { imp.skipCross = true; await analyze(); return; }
  await commit(v, imp.ask && imp.ask.uploadId);
}
async function commit(mode, replaceId) {
  imp.step = 'saving'; paintImport();
  try {
    const r = await api('/api/import/commit', 'POST', Object.assign(importBody(), { mode, replace_upload_id: replaceId || null }));
    imp.result = r; imp.step = 'done';
    S.cur = r.event.id; S.status = 'all'; S.q = ''; $('#q').value = '';
    await refresh(true); paintImport();
  } catch (e) { imp.step = 'map'; imp.err = 'Could not save: ' + e.message; paintImport(); }
}

/* ------------------------------------------------------------ events: create / manage */
function openNewEvent() {
  modal = { type: 'newEvent' };
  $('#modalRoot').innerHTML = '<div class="shade" data-act="closeBg"><div class="card" role="dialog" aria-modal="true"><h2>New event</h2><label class="field"><span>Event name</span><input id="newEvName" placeholder="e.g. Tech Fest 2026"></label><div class="foot"><button class="btn" data-act="closeModal">Cancel</button><button class="btn primary" data-act="createEvent">Create and add data</button></div></div></div>';
  setTimeout(() => { const i = $('#newEvName'); if (i) i.focus(); }, 30);
}
async function createEvent() {
  const name = ($('#newEvName') || {}).value || '';
  if (!name.trim()) { toast('Give the event a name.', true); return; }
  try { const r = await api('/api/events', 'POST', { name }); await refresh(true); openImport(String(r.id)); }
  catch (e) { toast(e.message, true); }
}
async function openManage(id) {
  if (!S.events.length) { toast('No events yet.', true); return; }
  const eid = id || (S.cur !== 'all' ? S.cur : S.events[0].id);
  try { const d = await api('/api/events/' + eid); modal = { type: 'manage', ev: d, confirm: null }; paintManage(); }
  catch (e) { toast(e.message, true); }
}
function paintManage() {
  const d = modal.ev;
  const files = d.uploads.slice().reverse().map(u => '<div class="file"><div><b>' + esc(u.filename) + '</b><small>' + esc(fmtDT(u.uploaded_at)) + ' · ' + plural(u.rows, 'row') + '</small></div>' + (modal.confirm === 'f' + u.id ? '<span><button class="btn small danger" data-act="removeUpload" data-uid="' + u.id + '">Yes, remove</button> <button class="btn small" data-act="mCancel">No</button></span>' : '<button class="btn small" data-act="mConfirm" data-v="f' + u.id + '">Remove</button>') + '</div>').join('') || '<p class="hint">No files yet.</p>';
  $('#modalRoot').innerHTML = '<div class="shade" data-act="closeBg"><div class="card" role="dialog" aria-modal="true"><h2>Manage events</h2><label class="field"><span>Event</span><select id="mgSel">' + S.events.map(e => '<option value="' + e.id + '"' + (e.id === d.id ? ' selected' : '') + '>' + esc(e.name) + '</option>').join('') + '</select></label>' +
    '<label class="field"><span>Name</span><input id="renameIn" value="' + esc(d.name) + '"></label><div><button class="btn" data-act="rename">Save name</button></div><h3>Uploaded files</h3><div class="files">' + files + '</div><p class="hint">Removing a file takes its rows out. Attendance and turns stay with the same people.</p><h3>Delete this event</h3>' +
    (modal.confirm === 'del' ? '<div class="notice warn">This deletes the event, its files and its attendance. People who are only in this event are removed too. It cannot be undone.</div><div><button class="btn danger" data-act="deleteEvent">Yes, delete everything</button> <button class="btn" data-act="mCancel">Keep it</button></div>' : '<div><button class="btn danger" data-act="mConfirm" data-v="del">Delete event…</button></div>') + '<div class="foot"><button class="btn primary" data-act="closeModal">Done</button></div></div></div>';
}

/* ------------------------------------------------------------ downloads */
function exportUrl(kind) {
  const ev = curEv();
  const p = new URLSearchParams({ event: ev ? ev.id : 'all', q: S.q, status: S.status });
  if (ev) { colsFor(ev).forEach(c => p.append('cols', c)); if (S.view === 'split') p.set('view', 'split'); }
  return '/api/export.' + kind + '?' + p.toString();
}
async function copyText(text, ok) {
  try { await navigator.clipboard.writeText(text); toast(ok); }
  catch (e) { toast('Copy is blocked in this browser.', true); }
}

/* ------------------------------------------------------------ events wiring */
const A = {
  tab(el) { S.cur = el.dataset.ev === 'all' ? 'all' : +el.dataset.ev; S.status = 'all'; S.sort = { col: null, dir: 1 }; S.limit = 200; S.colsOpen = false; refresh(true); },
  turnTab(el) { S.turnEv = +el.dataset.ev; S.turns = null; location.hash = '#/turns/' + S.turnEv; refresh(true); },
  newEvent() { openNewEvent(); }, createEvent() { createEvent(); },
  openImport() { openImport(); }, addPerson() { openPerson(); }, manage() { openManage(); },
  view(el) { S.view = el.dataset.v; S.limit = 200; paintAll(); },
  status(el) { S.status = el.dataset.v; S.limit = 200; paintAll(); },
  sort(el) { const c = el.dataset.col; if (S.sort.col === c) S.sort.dir *= -1; else S.sort = { col: c, dir: 1 }; paintResults(); },
  more() { S.limit += 300; paintResults(); },
  tick(el, e) { e.stopPropagation(); tick(+el.dataset.person, +el.dataset.ev); },
  row(el, e) { if (e.target.closest('.tick')) return; openDrawer(+el.dataset.person); },
  toggleCols() { S.colsOpen = !S.colsOpen; paintTools(); },
  colsAll() { const ev = curEv(); lsSet('ed:cols:' + ev.id, ev.cols); paintAll(); },
  colsKey() { const ev = curEv(); const k = ['name', 'college'].map(r => ev.map[r]).filter(Boolean); lsSet('ed:cols:' + ev.id, k.length ? k : ev.cols.slice(0, 2)); paintAll(); },
  colsContact() { const ev = curEv(); const k = ['name', 'email', 'phone'].map(r => ev.map[r]).filter(Boolean); lsSet('ed:cols:' + ev.id, k.length ? k : ev.cols.slice(0, 3)); paintAll(); },
  copyCol(el) { const c = el.dataset.col; copyText(S.rows.map(r => r.fields[c] || '').join('\n'), 'Copied ' + plural(S.rows.length, 'value') + ' from “' + c + '”'); },
  exportXlsx() { location.href = exportUrl('xlsx'); }, exportPdf() { location.href = exportUrl('pdf'); },
  closeModal() { closeAll(); }, closeDrawer() { closeAll(); },
  closeBg(el, e) { if (e.target === el) closeAll(); },
  pickFile() { const f = $('#fileIn'); if (f) f.click(); }, usePaste() { usePaste(); },
  impBack() { imp.step = 'pick'; imp.err = ''; paintImport(); }, impGo() { imp.err = ''; analyze(); },
  decide(el) { decide(el.dataset.v); },
  personSave() { savePerson(false); }, personNext() { savePerson(true); },
  mConfirm(el) { modal.confirm = el.dataset.v; paintManage(); }, mCancel() { modal.confirm = null; paintManage(); },
  async rename() { const v = ($('#renameIn') || {}).value || ''; if (!v.trim()) return; try { await api('/api/events/' + modal.ev.id, 'PATCH', { name: v }); modal.ev.name = v.trim(); await refresh(true); paintManage(); toast('Name saved'); } catch (e) { toast(e.message, true); } },
  async removeUpload(el) { try { await api('/api/events/' + modal.ev.id + '/uploads/' + el.dataset.uid, 'DELETE'); modal.ev = await api('/api/events/' + modal.ev.id); modal.confirm = null; await refresh(true); paintManage(); toast('File removed'); } catch (e) { toast(e.message, true); } },
  async deleteEvent() { try { await api('/api/events/' + modal.ev.id, 'DELETE'); closeAll(); S.cur = 'all'; S.turnEv = null; await refresh(true); toast('Event deleted'); } catch (e) { toast(e.message, true); } },
  turnUp(el) { moveTurn(+el.dataset.person, +el.dataset.turn - 1); },
  turnDown(el) { moveTurn(+el.dataset.person, +el.dataset.turn + 1); },
  turnSet(el) { const i = document.querySelector('input[data-pos="' + el.dataset.person + '"]'); if (i && i.value) moveTurn(+el.dataset.person, +i.value); },
  async turnUndo(el) { try { await api('/api/events/' + S.turnEv + '/attendance', 'POST', { person_id: +el.dataset.person, came: false }); } catch (e) { toast(e.message, true); } await refresh(true); },
  async arrive(el) { try { await api('/api/events/' + S.turnEv + '/attendance', 'POST', { person_id: +el.dataset.person, came: true }); const i = $('#arriveQ'); if (i) i.value = ''; } catch (e) { toast(e.message, true); } await refresh(true); },
};
document.addEventListener('click', e => {
  if (S.colsOpen && !e.target.closest('.popwrap')) { S.colsOpen = false; paintTools(); }
  const sug = $('#sug'); if (sug && !e.target.closest('.arrive')) sug.hidden = true;
  const el = e.target.closest('[data-act]'); if (!el) return;
  const f = A[el.dataset.act]; if (f) f(el, e);
});
document.addEventListener('change', e => {
  const t = e.target;
  if (t.matches('#colPop input[data-col]')) {
    const ev = curEv(); const vis = [...document.querySelectorAll('#colPop input[data-col]')].filter(i => i.checked).map(i => i.dataset.col);
    if (!vis.length) { t.checked = true; toast('Keep at least one column.', true); return; }
    lsSet('ed:cols:' + ev.id, ev.cols.filter(c => vis.includes(c))); paintResults();
  } else if (t.matches('select[data-role]')) imp.map[t.dataset.role] = t.value;
  else if (t.id === 'sheetSel') setSheet(+t.value);
  else if (t.id === 'mgSel') openManage(+t.value);
  else if (t.matches('input[data-pev]')) { const id = +t.dataset.pev; if (t.checked) modal.sel.add(id); else modal.sel.delete(id); paintExtras(); }
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && (modal || S.drawer)) closeAll();
  else if (e.key === 'Enter' && e.target.matches && e.target.matches('#pf_name,#pf_college,#pf_email,#pf_phone,#pExtra input')) { e.preventDefault(); savePerson(false); }
  else if (e.key === 'Enter' && e.target.matches && e.target.matches('input[data-pos]')) { moveTurn(+e.target.dataset.pos, +e.target.value); }
});
let qT;
$('#q').addEventListener('input', e => { clearTimeout(qT); qT = setTimeout(async () => { S.q = e.target.value; S.limit = 200; try { await loadPeople(); } catch (er) { toast(er.message, true); } paintTools(); paintResults(); }, 200); });
document.addEventListener('input', e => { if (e.target.id === 'arriveQ') { clearTimeout(arriveT); const v = e.target.value; arriveT = setTimeout(() => arriveSearch(v).catch(() => {}), 180); } });

/* drag and drop on the turn list */
let dragId = null;
document.addEventListener('dragstart', e => { const li = e.target.closest && e.target.closest('li.turn'); if (!li) return; dragging = true; dragId = +li.dataset.person; li.classList.add('dragging'); e.dataTransfer.effectAllowed = 'move'; try { e.dataTransfer.setData('text/plain', String(dragId)); } catch (_) {} });
document.addEventListener('dragover', e => { const li = e.target.closest && e.target.closest('li.turn'); if (!li || dragId == null) return; e.preventDefault(); document.querySelectorAll('li.turn.over').forEach(x => x.classList.remove('over')); li.classList.add('over'); });
document.addEventListener('dragend', () => { dragging = false; dragId = null; document.querySelectorAll('li.turn').forEach(x => x.classList.remove('dragging', 'over')); });
document.addEventListener('drop', e => { const li = e.target.closest && e.target.closest('li.turn'); if (!li || dragId == null) return; e.preventDefault(); const pid = dragId, to = +li.dataset.turn; dragging = false; dragId = null; moveTurn(pid, to); });

/* ------------------------------------------------------------ routing and start */
function route() {
  const m = location.hash.match(/^#\/turns(?:\/(\d+))?/);
  if (m) { S.page = 'turns'; if (m[1]) S.turnEv = +m[1]; else if (!S.turnEv && S.events[0]) S.turnEv = S.events[0].id; S.turns = null; }
  else S.page = 'people';
  refresh(true);
}
window.addEventListener('hashchange', route);
setInterval(() => { if (!document.hidden && !modal && !dragging && !(document.activeElement && document.activeElement.matches && document.activeElement.matches('input[data-pos]'))) refresh(true); }, 8000);
route();
})();
