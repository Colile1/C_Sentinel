/*
 * app.js - the Sentinel-IR operator console.
 *
 * One file, no framework, no build step. Structure, top to bottom:
 *   1. small helpers (escaping, storage, formatting)
 *   2. HTTP: `api()` for the console's own endpoints, `gw()` for the Kong
 *      gateway - every gateway call is recorded in the request trace
 *   3. overlays: snackbar, dialog, form dialog, side sheet
 *   4. session: sign-in, sign-out, expiry
 *   5. one render function per screen, registered in ROUTES
 *   6. boot: routing, theme, status polling
 *
 * Every value that reaches innerHTML passes through `esc()`.
 *
 * Author: Colile
 */
'use strict';

/* ======================================================== 1. helpers == */

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

const icon = (name, extra = '') => `<span class="material-symbols-outlined ${extra}" aria-hidden="true">${name}</span>`;
const sevTag = (severity) => severity ? `<span class="tag sev-${esc(severity)}">${esc(severity)}</span>` : '<span class="muted">-</span>';
const STATUS_CLASS = { OPEN: 'bad', TRIAGED: 'warn', RESOLVED: 'ok', ACKNOWLEDGED: 'warn', CLOSED: 'ok' };
const statusTag = (status) => `<span class="tag ${STATUS_CLASS[status] || ''}">${esc(status)}</span>`;
const SEVERITIES = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'];
const INCIDENT_STATUSES = ['OPEN', 'TRIAGED', 'RESOLVED'];
const ALERT_STATUSES = ['OPEN', 'ACKNOWLEDGED', 'CLOSED'];

// Storage can throw (private windows, blocked site data), and the console
// must work without it - so every access is guarded.
const storage = {
  get(area, key) { try { return JSON.parse(window[area].getItem(key)); } catch { return null; } },
  set(area, key, value) { try { window[area].setItem(key, JSON.stringify(value)); } catch { /* not persisted */ } },
  del(area, key) { try { window[area].removeItem(key); } catch { /* nothing to remove */ } },
};

function fmtTime(iso) {
  if (!iso) return '-';
  const date = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`);
  if (Number.isNaN(date.getTime())) return esc(iso);
  return date.toLocaleString(undefined, { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function shortId(id) { return id && id.length > 14 ? `${id.slice(0, 13)}…` : id; }

function uuid() {
  if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}

function errorText(result) {
  const data = result.data;
  if (data && typeof data === 'object') {
    if (data.message) {
      const field = data.details && (data.details.field || data.details.parameter);
      return field ? `${data.message} (${field})` : data.message;
    }
    if (Array.isArray(data.detail)) return data.detail.map((d) => d.msg).join('; ');
  }
  return `Request failed with HTTP ${result.status}`;
}

/* =========================================================== 2. HTTP == */

const state = {
  session: storage.get('sessionStorage', 'sentinel.session'),
  config: null,
  trace: [],
  status: null,
  graphAlerts: null,
  askHistory: [],
  pendingQuestion: null,
  eventFilter: {},
};

let busyCount = 0;
function busy(on) {
  busyCount = Math.max(0, busyCount + (on ? 1 : -1));
  $('#top-progress').classList.toggle('hidden', busyCount === 0);
}

async function request(url, { method = 'GET', body, headers = {} } = {}) {
  busy(true);
  const started = performance.now();
  try {
    const response = await fetch(url, {
      method,
      headers: { ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}), ...headers },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    const text = await response.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch { data = text; }
    return { ok: response.ok, status: response.status, data, headers: response.headers, ms: Math.round(performance.now() - started) };
  } catch (error) {
    return { ok: false, status: 0, data: { message: `The console server did not answer (${error.message}).` }, headers: new Headers(), ms: 0 };
  } finally {
    busy(false);
  }
}

/** The console's own endpoints. */
const api = (path, options) => request(path, options);

/**
 * One call through the Kong gateway. A fresh correlation id is sent with every
 * call; Kong passes a client-chosen id through unchanged, so the id recorded
 * here is the one every service logged for this request.
 */
async function gw(path, { method = 'GET', body, auth = true } = {}) {
  const correlationId = uuid();
  const headers = { 'X-Correlation-ID': correlationId };
  if (auth && state.session) headers.Authorization = `Bearer ${state.session.token}`;
  const result = await request(`/gateway/api/v1/${path}`, { method, body, headers });
  const echoed = result.headers.get('x-correlation-id') || correlationId;
  state.trace.unshift({
    at: new Date().toISOString(), method, path: `/api/v1/${path}`, status: result.status,
    correlationId: echoed, ms: result.ms,
    remaining: result.headers.get('ratelimit-remaining') || result.headers.get('x-ratelimit-remaining-minute'),
  });
  state.trace = state.trace.slice(0, 300);
  result.correlationId = echoed;
  if (result.status === 401 && auth && state.session) {
    signOut(false);
    snackbar('Your session ended (token expired or rejected). Sign in again.', 'Sign in', () => signInDialog());
  }
  if (result.status === 429) snackbar('Rate limited by the gateway (60 requests a minute). Wait a moment and retry.');
  return result;
}

/* ======================================================= 3. overlays == */

let snackTimer = null;
function snackbar(message, actionLabel, onAction) {
  const bar = $('#snackbar');
  $('#snackbar-text').textContent = message;
  $$('.action', bar).forEach((b) => b.remove());
  if (actionLabel) {
    const button = document.createElement('button');
    button.className = 'action';
    button.textContent = actionLabel;
    button.onclick = () => { bar.classList.remove('show'); onAction(); };
    bar.appendChild(button);
  }
  bar.classList.add('show');
  clearTimeout(snackTimer);
  snackTimer = setTimeout(() => bar.classList.remove('show'), 6000);
}

function closeOverlay() {
  $('#overlay-host').innerHTML = '';
  document.removeEventListener('keydown', escapeCloses);
}
function escapeCloses(event) { if (event.key === 'Escape') closeOverlay(); }

function mountOverlay(html) {
  const host = $('#overlay-host');
  host.innerHTML = `<div class="scrim"></div>${html}`;
  $('.scrim', host).onclick = closeOverlay;
  document.addEventListener('keydown', escapeCloses);
  return host;
}

/**
 * A dialog. `actions` is [{label, kind, onClick}] where onClick may return a
 * promise; returning false keeps the dialog open.
 */
function dialog({ title, iconName, body, actions }) {
  const host = mountOverlay(`
    <div class="dialog" role="dialog" aria-modal="true" aria-label="${esc(title)}">
      ${iconName ? `<div class="dialog-icon">${icon(iconName)}</div>` : ''}
      <h2 class="headline-small">${esc(title)}</h2>
      <div class="dialog-body">${body}</div>
      <div class="dialog-actions">
        ${actions.map((a, i) => `<button class="btn ${a.kind || 'btn-text'}" data-action="${i}">${esc(a.label)}</button>`).join('')}
      </div>
    </div>`);
  $$('[data-action]', host).forEach((button) => {
    button.onclick = async () => {
      const action = actions[Number(button.dataset.action)];
      if (!action.onClick) return closeOverlay();
      button.disabled = true;
      const keepOpen = (await action.onClick(host)) === false;
      button.disabled = false;
      if (!keepOpen) closeOverlay();
    };
  });
  const first = $('input, select, textarea', host);
  if (first) first.focus();
  return host;
}

function fieldHtml(f) {
  const id = `f-${f.name}`;
  const span = f.span ? ' span-2' : '';
  const required = f.required ? ' required' : '';
  let control;
  if (f.type === 'select') {
    control = `<select id="${id}" name="${esc(f.name)}"${required}>${f.options.map((o) => {
      const value = typeof o === 'object' ? o.value : o;
      const label = typeof o === 'object' ? o.label : o;
      return `<option value="${esc(value)}"${String(value) === String(f.value ?? '') ? ' selected' : ''}>${esc(label)}</option>`;
    }).join('')}</select>`;
  } else if (f.type === 'textarea') {
    control = `<textarea id="${id}" name="${esc(f.name)}"${required} maxlength="${f.max || 2000}">${esc(f.value ?? '')}</textarea>`;
  } else {
    control = `<input id="${id}" name="${esc(f.name)}" type="${f.type || 'text'}" value="${esc(f.value ?? '')}"${required}${f.min ? ` minlength="${f.min}"` : ''} autocomplete="${f.autocomplete || 'off'}">`;
  }
  return `<div class="field${span}"><label for="${id}">${esc(f.label)}${f.required ? ' *' : ''}</label>${control}${f.hint ? `<span class="hint">${esc(f.hint)}</span>` : ''}</div>`;
}

/**
 * A form in a dialog. `onSubmit(values)` returns an error message to show, or
 * nothing to close the dialog.
 */
function formDialog({ title, iconName, intro, fields, submitLabel, onSubmit }) {
  const body = `
    ${intro ? `<p class="muted" style="margin-top:0">${intro}</p>` : ''}
    <form class="form-grid" id="dialog-form" novalidate>${fields.map(fieldHtml).join('')}</form>
    <div class="banner error hidden" id="form-error" style="margin:16px 0 0">${icon('error')}<div class="grow"></div></div>`;
  const host = dialog({
    title, iconName, body,
    actions: [
      { label: 'Cancel' },
      {
        label: submitLabel, kind: 'btn-filled',
        onClick: async (h) => {
          const form = $('#dialog-form', h);
          if (!form.reportValidity()) return false;
          const values = Object.fromEntries(new FormData(form).entries());
          const problem = await onSubmit(values);
          if (problem) {
            const box = $('#form-error', h);
            box.classList.remove('hidden');
            $('.grow', box).textContent = problem;
            return false;
          }
          return true;
        },
      },
    ],
  });
  $('#dialog-form', host).addEventListener('submit', (e) => { e.preventDefault(); $('[data-action="1"]', host).click(); });
  return host;
}

function confirmDialog({ title, message, confirmLabel, danger = false }) {
  return new Promise((resolve) => {
    dialog({
      title, iconName: danger ? 'warning' : 'help', body: `<p class="muted">${message}</p>`,
      actions: [
        { label: 'Cancel', onClick: () => resolve(false) },
        { label: confirmLabel, kind: danger ? 'btn-danger' : 'btn-filled', onClick: () => resolve(true) },
      ],
    });
    $('.scrim').addEventListener('click', () => resolve(false));
  });
}

function sheet({ title, subtitle, body }) {
  const host = mountOverlay(`
    <aside class="sheet" role="dialog" aria-modal="true" aria-label="${esc(title)}">
      <div class="sheet-head">
        <div style="flex:1;min-width:0">
          <div class="title-large">${esc(title)}</div>
          ${subtitle ? `<div class="body-small muted">${subtitle}</div>` : ''}
        </div>
        <button class="icon-btn" data-close aria-label="Close">${icon('close')}</button>
      </div>
      <div class="sheet-body stack">${body}</div>
    </aside>`);
  $('[data-close]', host).onclick = closeOverlay;
  return host;
}

function kv(pairs) {
  return `<dl class="kv">${pairs.filter(([, v]) => v !== undefined).map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join('')}</dl>`;
}

function emptyState(iconName, title, detail = '', actionHtml = '') {
  return `<div class="empty">${icon(iconName)}<div class="title-medium">${esc(title)}</div>${detail ? `<div>${detail}</div>` : ''}${actionHtml}</div>`;
}

function errorBanner(message, retryId) {
  return `<div class="banner error">${icon('error')}<div class="grow">${esc(message)}</div>${retryId ? `<button class="btn btn-text" id="${retryId}">Retry</button>` : ''}</div>`;
}

function correlationNote(result) {
  return result && result.correlationId
    ? `<span class="body-small muted">Correlation ID <span class="mono">${esc(result.correlationId)}</span></span>` : '';
}

/* ======================================================== 4. session == */

function isAdmin() { return state.session && state.session.role === 'admin'; }

function saveSession(session) {
  state.session = session;
  if (session) storage.set('sessionStorage', 'sentinel.session', session);
  else storage.del('sessionStorage', 'sentinel.session');
  renderUserChip();
}

function signOut(rerender = true) {
  saveSession(null);
  if (rerender) { snackbar('Signed out.'); route(); }
}

function signInDialog(after) {
  const hint = state.config ? state.config.adminUsername : 'admin';
  formDialog({
    title: 'Sign in',
    iconName: 'lock',
    intro: `Credentials are checked by auth-service through the Kong gateway, which then issues the JWT used for every call. The bootstrap admin is <span class="mono">${esc(hint)}</span>, and its password is <span class="mono">BOOTSTRAP_ADMIN_PASSWORD</span> in deploy/.env.`,
    fields: [
      { name: 'username', label: 'Username', required: true, value: hint, span: true, autocomplete: 'username' },
      { name: 'password', label: 'Password', type: 'password', required: true, span: true, autocomplete: 'current-password' },
    ],
    submitLabel: 'Sign in',
    onSubmit: async (values) => {
      const result = await gw('auth/login', { method: 'POST', body: values, auth: false });
      if (!result.ok) return errorText(result);
      const expires = Date.now() + (result.data.expires_in || 3600) * 1000;
      saveSession({ token: result.data.access_token, role: result.data.role, username: values.username, expires });
      snackbar(`Signed in as ${values.username} (${result.data.role}).`);
      if (after) after(); else route();
      return null;
    },
  });
}

function renderUserChip() {
  const chip = $('#user-chip');
  if (state.session && state.session.expires < Date.now()) saveSession(null);
  if (!state.session) {
    chip.innerHTML = `${icon('login')}<span class="user-name">Sign in</span>`;
    chip.style.paddingLeft = '12px';
    chip.onclick = () => signInDialog();
    return;
  }
  const s = state.session;
  chip.style.paddingLeft = '4px';
  chip.innerHTML = `<span class="avatar">${esc(s.username.slice(0, 1))}</span><span class="user-name">${esc(s.username)} · ${esc(s.role)}</span>`;
  chip.onclick = () => {
    const minutes = Math.max(0, Math.round((s.expires - Date.now()) / 60000));
    dialog({
      title: s.username, iconName: 'account_circle',
      body: kv([['Role', esc(s.role)], ['Token expires in', `${minutes} min`], ['Issued by', 'auth-service (HS256), validated at Kong']]),
      actions: [
        { label: 'Verify token', onClick: async () => {
          const r = await gw('auth/verify');
          if (r.ok) snackbar(`Token valid: ${r.data.username} (${r.data.role}).`);
          else if (r.status !== 401) snackbar(errorText(r));
        } },
        { label: 'Sign out', kind: 'btn-tonal', onClick: () => signOut() },
      ],
    });
  };
}

/** Render a sign-in prompt instead of a screen that needs a token. */
function needsSession(el, what) {
  if (state.session) return false;
  el.innerHTML = `
    <div class="sign-in">
      <div class="dialog-icon">${icon('lock')}</div>
      <h2 class="headline-small" style="text-align:center;margin-bottom:8px">Sign in to view ${esc(what)}</h2>
      <p class="muted" style="text-align:center">This screen calls the business services through the Kong gateway, which requires a JWT.</p>
      <div class="row" style="justify-content:center;margin-top:16px"><button class="btn btn-filled" id="inline-sign-in">${icon('login')}Sign in</button></div>
    </div>`;
  $('#inline-sign-in').onclick = () => signInDialog();
  return true;
}

/* ======================================================== 5. screens == */

/* ---------- Overview ---------- */

async function renderOverview(el) {
  el.innerHTML = `
    <p class="page-intro">One place to run Sentinel-IR. Phase 1 is the incident-reporting business (Incidents, Assets, Users) behind the Kong gateway. Phase 2 is the security layer built from its event stream: detection rules, the Neo4j knowledge graph, and GraphRAG answers with their evidence.</p>
    <div class="grid grid-4" id="ov-stats">${['Open incidents', 'Assets', 'Open alerts', 'Captured events'].map((l) => `
      <div class="card stat"><div class="stat-value">…</div><div class="stat-label">${l}</div></div>`).join('')}</div>

    <div class="section">
      <div class="section-head"><h2 class="title-large">Stack health</h2>
        <button class="btn btn-text" id="ov-refresh">${icon('refresh')}Refresh</button></div>
      <div id="ov-health"><div class="progress"></div></div>
    </div>

    <div class="section">
      <div class="section-head"><h2 class="title-large">Security workflow</h2></div>
      <div class="flow">
        ${[
          ['stream', 'Security events', 'Every request emits a structured event carrying a correlation ID.', 'events'],
          ['rule', 'Detection', 'Four rules read the stream and raise alerts.', 'alerts'],
          ['hub', 'Knowledge graph', 'Events, alerts, topology and ATT&CK are loaded into Neo4j.', 'graph'],
          ['forum', 'GraphRAG', 'Ask why an alert fired and get an answer backed by graph evidence.', 'ask'],
        ].map(([i, t, d, r], n, all) => `
          <a class="flow-step" href="#/${r}">${icon(i)}<span class="title-small">${n + 1}. ${t}</span><span class="body-small muted">${d}</span></a>
          ${n < all.length - 1 ? `<span class="flow-arrow">${icon('arrow_forward')}</span>` : ''}`).join('')}
      </div>
    </div>

    <div class="section">
      <div class="section-head"><h2 class="title-large">Tools</h2></div>
      <div class="grid grid-auto" id="ov-tools"></div>
    </div>`;

  $('#ov-refresh').onclick = () => loadHealth();
  renderTools($('#ov-tools'));
  loadHealth();
  loadOverviewStats();

  async function loadHealth() {
    const box = $('#ov-health');
    const result = await refreshStatus();
    if (!result) { box.innerHTML = errorBanner('Could not reach the console server.'); return; }
    const layers = [...new Set(result.components.map((c) => c.layer))];
    box.innerHTML = `
      ${result.up < result.total ? `<div class="banner info">${icon('info')}<div class="grow">${result.total - result.up} of ${result.total} components are not answering. Run <span class="mono">start.bat</span> in c_sentinel-ir to bring the stack up. Screens that only read the committed attack capture (events, detection, dry-run graph load) still work.</div></div>` : ''}
      <div class="grid grid-auto">${layers.map((layer) => result.components.filter((c) => c.layer === layer).map((c) => `
        <a class="health" href="${esc(c.link)}" target="_blank" rel="noopener">
          <span class="health-dot ${c.up ? 'up' : 'down'}"></span>
          <span class="health-text"><div class="title-small">${esc(c.name)}</div><div class="body-small muted">${esc(layer)} · ${esc(c.detail)}</div></span>
          ${icon('open_in_new', 'icon-sm muted')}
        </a>`).join('')).join('')}</div>`;
  }

  async function loadOverviewStats() {
    const cards = $$('#ov-stats .stat-value');
    const [events, alerts] = await Promise.all([api('/console/api/soc/events'), api('/api/v1/alerts?status=OPEN')]);
    cards[3].textContent = events.ok ? events.data.total : '-';
    cards[2].textContent = alerts.ok ? alerts.data.length : '-';
    if (!state.session) {
      [0, 1].forEach((i) => { cards[i].innerHTML = `<button class="btn btn-text" style="padding:0" data-signin>${icon('login')}Sign in</button>`; });
      $$('[data-signin]', el).forEach((b) => { b.onclick = () => signInDialog(); });
      return;
    }
    const [incidents, assets] = await Promise.all([gw('incidents?status=OPEN'), gw('assets')]);
    cards[0].textContent = incidents.ok ? incidents.data.length : '-';
    cards[1].textContent = assets.ok ? assets.data.length : '-';
  }
}

function renderTools(box) {
  if (!state.config) { box.innerHTML = ''; return; }
  box.innerHTML = state.config.tools.map((t) => `
    <a class="health" href="${esc(t.url)}" target="_blank" rel="noopener">
      ${icon(t.icon)}<span class="health-text"><div class="title-small">${esc(t.name)}</div><div class="body-small muted mono">${esc(t.url.replace(/^https?:\/\//, ''))}</div></span>${icon('open_in_new', 'icon-sm muted')}
    </a>`).join('');
}

async function refreshStatus() {
  const result = await api('/console/api/status');
  if (!result.ok) { setStatusPill(null); return null; }
  state.status = result.data;
  setStatusPill(result.data);
  return result.data;
}

function setStatusPill(status) {
  const dot = $('#status-dot');
  dot.className = 'health-dot';
  if (!status) { $('#status-text').textContent = 'Console offline'; dot.classList.add('down'); return; }
  $('#status-text').textContent = `${status.up}/${status.total} up`;
  dot.classList.add(status.up === status.total ? 'up' : 'down');
}

/* ---------- Incidents ---------- */

async function renderIncidents(el) {
  if (needsSession(el, 'incidents')) return;
  const view = { status: '', severity: '', search: '' };
  el.innerHTML = `
    <p class="page-intro">Incidents raised against organisational assets. Creating one makes incident-service call asset-service through the retry plus circuit breaker client. Escalating to HIGH or CRITICAL emits an <span class="mono">INCIDENT_ESCALATED</span> security event.</p>
    <div class="section-head">
      <div class="row">
        <label class="search">${icon('search')}<input id="inc-search" placeholder="Search title, asset, reporter" aria-label="Search incidents"></label>
        <div class="row" id="inc-status">${['', ...INCIDENT_STATUSES].map((s) => `<button class="chip${s === '' ? ' selected' : ''}" data-status="${s}">${s || 'All'}</button>`).join('')}</div>
        <div class="field compact"><select id="inc-sev" aria-label="Severity filter"><option value="">Any severity</option>${SEVERITIES.map((s) => `<option>${s}</option>`).join('')}</select></div>
      </div>
      <button class="btn btn-filled" id="inc-new">${icon('add')}New incident</button>
    </div>
    <div id="inc-table"><div class="progress"></div></div>`;

  let incidents = [];
  let assets = [];

  async function load() {
    const query = new URLSearchParams();
    if (view.status) query.set('status', view.status);
    if (view.severity) query.set('severity', view.severity);
    const [ri, ra] = await Promise.all([gw(`incidents${query.toString() ? `?${query}` : ''}`), gw('assets')]);
    if (!ri.ok) { $('#inc-table').innerHTML = errorBanner(errorText(ri), 'inc-retry'); $('#inc-retry').onclick = load; return; }
    incidents = ri.data.sort((a, b) => b.id - a.id);
    assets = ra.ok ? ra.data : [];
    draw();
  }

  function draw() {
    const needle = view.search.toLowerCase();
    const rows = incidents.filter((i) => !needle || [i.title, i.asset_name_snapshot, i.reported_by, i.description].join(' ').toLowerCase().includes(needle));
    $('#inc-table').innerHTML = rows.length ? `
      <div class="table-wrap"><table class="data">
        <thead><tr><th>ID</th><th>Incident</th><th>Asset</th><th>Severity</th><th>Status</th><th>Reported by</th><th>Updated</th></tr></thead>
        <tbody>${rows.map((i) => `
          <tr class="clickable" data-id="${i.id}">
            <td class="num">${i.id}</td>
            <td><div class="cell-title">${esc(i.title)}</div><div class="cell-sub">${esc(i.description.slice(0, 90))}${i.description.length > 90 ? '…' : ''}</div></td>
            <td>${esc(i.asset_name_snapshot || `#${i.asset_id}`)}</td>
            <td>${sevTag(i.severity)}</td><td>${statusTag(i.status)}</td>
            <td>${esc(i.reported_by)}</td><td class="nowrap body-small">${fmtTime(i.updated_at)}</td>
          </tr>`).join('')}</tbody></table></div>
      <div class="body-small muted" style="margin-top:8px">${rows.length} of ${incidents.length} incidents</div>`
      : emptyState('report', 'No incidents match', 'Change the filters, or raise a new incident.');
    $$('tr[data-id]', el).forEach((tr) => { tr.onclick = () => openIncident(Number(tr.dataset.id)); });
  }

  function openIncident(id, lastResult) {
    const i = incidents.find((x) => x.id === id);
    if (!i) return;
    const host = sheet({
      title: i.title, subtitle: `Incident #${i.id}`,
      body: `
        <div class="row">${sevTag(i.severity)} ${statusTag(i.status)}</div>
        <p style="margin:0;white-space:pre-wrap">${esc(i.description)}</p>
        ${kv([['Asset', `${esc(i.asset_name_snapshot || '-')} <span class="muted">(#${i.asset_id})</span>`], ['Reported by', esc(i.reported_by)], ['Created', fmtTime(i.created_at)], ['Updated', fmtTime(i.updated_at)]])}
        <div class="card outlined stack">
          <div class="title-small">Severity</div>
          <div class="segmented" id="sev-seg">${SEVERITIES.map((s) => `<button data-sev="${s}" class="${s === i.severity ? 'selected' : ''}">${s}</button>`).join('')}</div>
          <div class="body-small muted">PATCH /incidents/${i.id}/severity. Moving to HIGH or CRITICAL emits INCIDENT_ESCALATED.</div>
        </div>
        <div class="card outlined stack">
          <div class="title-small">Status</div>
          <div class="segmented" id="status-seg">${INCIDENT_STATUSES.map((s) => `<button data-st="${s}" class="${s === i.status ? 'selected' : ''}">${s}</button>`).join('')}</div>
        </div>
        <div class="row">
          <button class="btn btn-tonal" id="inc-edit">${icon('edit')}Edit details</button>
          ${isAdmin() ? `<button class="btn btn-danger-text" id="inc-del">${icon('delete')}Delete</button>` : ''}
        </div>
        ${correlationNote(lastResult)}`,
    });
    const apply = async (path, method, body, message) => {
      const r = await gw(path, { method, body });
      if (!r.ok) { snackbar(errorText(r)); return; }
      const index = incidents.findIndex((x) => x.id === id);
      incidents[index] = r.data;
      draw();
      snackbar(message);
      openIncident(id, r);
    };
    $$('[data-sev]', host).forEach((b) => { b.onclick = () => b.dataset.sev !== i.severity && apply(`incidents/${id}/severity`, 'PATCH', { severity: b.dataset.sev }, `Severity set to ${b.dataset.sev}.`); });
    $$('[data-st]', host).forEach((b) => { b.onclick = () => b.dataset.st !== i.status && apply(`incidents/${id}`, 'PUT', { status: b.dataset.st }, `Status set to ${b.dataset.st}.`); });
    $('#inc-edit', host).onclick = () => formDialog({
      title: `Edit incident #${id}`, iconName: 'edit',
      fields: [
        { name: 'title', label: 'Title', required: true, value: i.title, span: true },
        { name: 'description', label: 'Description', type: 'textarea', required: true, value: i.description, span: true },
      ],
      submitLabel: 'Save',
      onSubmit: async (v) => {
        const r = await gw(`incidents/${id}`, { method: 'PUT', body: v });
        if (!r.ok) return errorText(r);
        incidents[incidents.findIndex((x) => x.id === id)] = r.data;
        draw();
        snackbar('Incident updated.');
        setTimeout(() => openIncident(id, r));
        return null;
      },
    });
    const del = $('#inc-del', host);
    if (del) del.onclick = async () => {
      if (!(await confirmDialog({ title: `Delete incident #${id}?`, message: 'This removes the incident permanently. It cannot be undone.', confirmLabel: 'Delete', danger: true }))) return;
      const r = await gw(`incidents/${id}`, { method: 'DELETE' });
      if (!r.ok) { snackbar(errorText(r)); return; }
      incidents = incidents.filter((x) => x.id !== id);
      draw();
      snackbar(`Incident #${id} deleted.`);
    };
  }

  $('#inc-search').oninput = (e) => { view.search = e.target.value; draw(); };
  $$('#inc-status .chip').forEach((c) => {
    c.onclick = () => { $$('#inc-status .chip').forEach((x) => x.classList.toggle('selected', x === c)); view.status = c.dataset.status; load(); };
  });
  $('#inc-sev').onchange = (e) => { view.severity = e.target.value; load(); };
  $('#inc-new').onclick = () => {
    if (!assets.length) { snackbar('No assets registered yet. Seed the demo data from Operations first.'); return; }
    formDialog({
      title: 'Raise an incident', iconName: 'report',
      intro: 'incident-service looks the asset up in asset-service at creation time. If asset-service is down, the circuit breaker lets the incident be created with a degraded asset summary.',
      fields: [
        { name: 'title', label: 'Title', required: true, span: true },
        { name: 'description', label: 'Description', type: 'textarea', required: true, span: true },
        { name: 'severity', label: 'Severity', type: 'select', options: SEVERITIES, value: 'MEDIUM' },
        { name: 'asset_id', label: 'Asset', type: 'select', options: assets.map((a) => ({ value: a.id, label: `${a.name} (${a.criticality})` })) },
        { name: 'reported_by', label: 'Reported by', required: true, value: state.session.username, span: true },
      ],
      submitLabel: 'Raise incident',
      onSubmit: async (v) => {
        const r = await gw('incidents', { method: 'POST', body: { ...v, asset_id: Number(v.asset_id) } });
        if (!r.ok) return errorText(r);
        incidents.unshift(r.data);
        draw();
        snackbar(`Incident #${r.data.id} raised. Correlation ID ${shortId(r.correlationId)}.`, 'Trace', () => { location.hash = '#/activity'; });
        return null;
      },
    });
  };
  load();
}

/* ---------- Assets ---------- */

async function renderAssets(el) {
  if (needsSession(el, 'assets')) return;
  const view = { type: '', search: '' };
  el.innerHTML = `
    <p class="page-intro">The organisational asset register. Reading a CRITICAL asset emits an <span class="mono">ASSET_ACCESSED</span> security event. Registering, editing and removing assets need the admin role.</p>
    <div class="section-head">
      <div class="row">
        <label class="search">${icon('search')}<input id="as-search" placeholder="Search name, owner, location" aria-label="Search assets"></label>
        <div class="row" id="as-types"></div>
      </div>
      ${isAdmin() ? `<button class="btn btn-filled" id="as-new">${icon('add')}Register asset</button>` : ''}
    </div>
    <div id="as-table"><div class="progress"></div></div>`;

  let assets = [];
  let incidents = [];

  async function load() {
    const [ra, ri] = await Promise.all([gw('assets'), gw('incidents')]);
    if (!ra.ok) { $('#as-table').innerHTML = errorBanner(errorText(ra), 'as-retry'); $('#as-retry').onclick = load; return; }
    assets = ra.data;
    incidents = ri.ok ? ri.data : [];
    const types = [...new Set(assets.map((a) => a.asset_type))].sort();
    $('#as-types').innerHTML = ['', ...types].map((t) => `<button class="chip${t === view.type ? ' selected' : ''}" data-type="${esc(t)}">${esc(t || 'All types')}</button>`).join('');
    $$('#as-types .chip').forEach((c) => { c.onclick = () => { view.type = c.dataset.type; load(); }; });
    draw();
  }

  function draw() {
    const needle = view.search.toLowerCase();
    const rows = assets.filter((a) => (!view.type || a.asset_type === view.type)
      && (!needle || [a.name, a.owner, a.location, a.asset_type].join(' ').toLowerCase().includes(needle)));
    $('#as-table').innerHTML = rows.length ? `
      <div class="table-wrap"><table class="data">
        <thead><tr><th>ID</th><th>Name</th><th>Type</th><th>Criticality</th><th>Owner</th><th>Location</th><th>Incidents</th></tr></thead>
        <tbody>${rows.map((a) => `
          <tr class="clickable" data-id="${a.id}">
            <td class="num">${a.id}</td><td class="cell-title">${esc(a.name)}</td><td>${esc(a.asset_type)}</td>
            <td>${sevTag(a.criticality)}</td><td>${esc(a.owner)}</td><td>${esc(a.location)}</td>
            <td class="num">${incidents.filter((i) => i.asset_id === a.id).length}</td>
          </tr>`).join('')}</tbody></table></div>`
      : emptyState('dns', 'No assets match', isAdmin() ? 'Register one, or seed the demo data from Operations.' : 'Ask an admin to register assets.');
    $$('tr[data-id]', el).forEach((tr) => { tr.onclick = () => openAsset(Number(tr.dataset.id)); });
  }

  const assetFields = (a = {}) => [
    { name: 'name', label: 'Name', required: true, value: a.name, span: true },
    { name: 'asset_type', label: 'Type', required: true, value: a.asset_type, hint: 'e.g. database, service, server' },
    { name: 'criticality', label: 'Criticality', type: 'select', options: SEVERITIES, value: a.criticality || 'MEDIUM' },
    { name: 'owner', label: 'Owner', required: true, value: a.owner },
    { name: 'location', label: 'Location', required: true, value: a.location },
  ];

  async function openAsset(id) {
    // A direct read goes through GET /assets/{id}, which is what emits
    // ASSET_ACCESSED for a CRITICAL asset.
    const r = await gw(`assets/${id}`);
    if (!r.ok) { snackbar(errorText(r)); return; }
    const a = r.data;
    const related = incidents.filter((i) => i.asset_id === id);
    const host = sheet({
      title: a.name, subtitle: `Asset #${a.id}`,
      body: `
        <div class="row">${sevTag(a.criticality)} <span class="tag">${esc(a.asset_type)}</span></div>
        ${kv([['Owner', esc(a.owner)], ['Location', esc(a.location)], ['Created', fmtTime(a.created_at)], ['Updated', fmtTime(a.updated_at)]])}
        ${a.criticality === 'CRITICAL' ? `<div class="banner info">${icon('visibility')}<div class="grow">Opening this CRITICAL asset emitted an ASSET_ACCESSED event.</div></div>` : ''}
        <div class="title-small">Incidents on this asset (${related.length})</div>
        ${related.length ? `<div class="list">${related.map((i) => `<div class="list-item">${icon('report')}<div><div class="title-small">#${i.id} ${esc(i.title)}</div><div class="row" style="margin-top:4px">${sevTag(i.severity)} ${statusTag(i.status)}</div></div></div>`).join('')}</div>` : '<div class="muted">None.</div>'}
        ${isAdmin() ? `<div class="row"><button class="btn btn-tonal" id="as-edit">${icon('edit')}Edit</button><button class="btn btn-danger-text" id="as-del">${icon('delete')}Remove</button></div>` : ''}
        ${correlationNote(r)}`,
    });
    if (!isAdmin()) return;
    $('#as-edit', host).onclick = () => formDialog({
      title: `Edit ${a.name}`, iconName: 'edit', fields: assetFields(a), submitLabel: 'Save',
      onSubmit: async (v) => {
        const res = await gw(`assets/${id}`, { method: 'PUT', body: v });
        if (!res.ok) return errorText(res);
        snackbar('Asset updated.');
        load();
        return null;
      },
    });
    $('#as-del', host).onclick = async () => {
      if (!(await confirmDialog({ title: `Remove ${a.name}?`, message: 'The asset is removed from the register. Existing incidents keep their stored asset name.', confirmLabel: 'Remove', danger: true }))) return;
      const res = await gw(`assets/${id}`, { method: 'DELETE' });
      if (!res.ok) { snackbar(errorText(res)); return; }
      snackbar(`${a.name} removed.`);
      load();
    };
  }

  $('#as-search').oninput = (e) => { view.search = e.target.value; draw(); };
  const add = $('#as-new');
  if (add) add.onclick = () => formDialog({
    title: 'Register an asset', iconName: 'dns', fields: assetFields(), submitLabel: 'Register',
    onSubmit: async (v) => {
      const r = await gw('assets', { method: 'POST', body: v });
      if (!r.ok) return errorText(r);
      snackbar(`${r.data.name} registered.`);
      load();
      return null;
    },
  });
  load();
}

/* ---------- Users ---------- */

async function renderUsers(el) {
  if (needsSession(el, 'users')) return;
  if (!isAdmin()) {
    el.innerHTML = `<div class="banner info">${icon('admin_panel_settings')}<div class="grow">User management needs the admin role. You are signed in as <b>${esc(state.session.username)}</b> (${esc(state.session.role)}). auth-service answers a non-admin with 403.</div></div>`;
    return;
  }
  el.innerHTML = `
    <p class="page-intro">Accounts held by auth-service. Passwords are hashed and never returned. A failed login for any of these accounts emits <span class="mono">AUTH_FAILED</span>, and five in a minute fire the Multiple Failed Logins rule.</p>
    <div class="section-head"><span></span><button class="btn btn-filled" id="u-new">${icon('person_add')}Create user</button></div>
    <div id="u-table"><div class="progress"></div></div>`;

  async function load() {
    const r = await gw('auth/users');
    if (!r.ok) { $('#u-table').innerHTML = errorBanner(errorText(r)); return; }
    $('#u-table').innerHTML = `
      <div class="table-wrap"><table class="data">
        <thead><tr><th>ID</th><th>Username</th><th>Email</th><th>Role</th><th>Active</th><th>Created</th></tr></thead>
        <tbody>${r.data.map((u) => `<tr>
          <td class="num">${u.id}</td><td class="cell-title">${esc(u.username)}</td><td>${esc(u.email)}</td>
          <td><span class="tag ${u.role === 'admin' ? 'info' : ''}">${esc(u.role)}</span></td>
          <td>${u.is_active ? '<span class="tag ok">active</span>' : '<span class="tag bad">disabled</span>'}</td>
          <td class="body-small nowrap">${fmtTime(u.created_at)}</td></tr>`).join('')}</tbody></table></div>`;
  }

  $('#u-new').onclick = () => formDialog({
    title: 'Create a user', iconName: 'person_add',
    fields: [
      { name: 'username', label: 'Username', required: true },
      { name: 'role', label: 'Role', type: 'select', options: ['analyst', 'admin'], value: 'analyst' },
      { name: 'email', label: 'Email', type: 'email', required: true, span: true },
      { name: 'password', label: 'Password', type: 'password', required: true, min: 8, span: true, hint: 'auth-service rejects short passwords with 422.', autocomplete: 'new-password' },
    ],
    submitLabel: 'Create',
    onSubmit: async (v) => {
      const r = await gw('auth/users', { method: 'POST', body: v });
      if (!r.ok) return errorText(r);
      snackbar(`User ${r.data.username} created.`);
      load();
      return null;
    },
  });
  load();
}

/* ---------- Security events ---------- */

function sourceToggle(id, value) {
  return `<div class="segmented" id="${id}" role="group" aria-label="Event source">
    <button data-src="capture" class="${value === 'capture' ? 'selected' : ''}">${icon('inventory_2', 'icon-sm')}Captured attack</button>
    <button data-src="live" class="${value === 'live' ? 'selected' : ''}">${icon('sensors', 'icon-sm')}Live stack logs</button>
  </div>`;
}

async function renderEvents(el) {
  const filter = { source: 'capture', eventType: '', service: '', user: '', correlationId: '', ...state.eventFilter };
  state.eventFilter = {};
  el.innerHTML = `
    <p class="page-intro">The security event stream the SOC collector reads: one structured event per request, auth decision and inter-service call, in the schema Phase 2 consumes. <b>Captured attack</b> is the committed file <span class="mono">docs/evidence/step15-attack-events.jsonl</span> and needs no Docker. <b>Live stack logs</b> reads <span class="mono">docker compose logs</span>.</p>
    <div class="section-head">
      ${sourceToggle('ev-src', filter.source)}
      <div class="row">
        <label class="search" style="max-width:260px">${icon('person')}<input id="ev-user" placeholder="User" value="${esc(filter.user)}" aria-label="Filter by user"></label>
        <label class="search" style="max-width:340px">${icon('link')}<input id="ev-corr" placeholder="Correlation ID" value="${esc(filter.correlationId)}" aria-label="Filter by correlation ID"></label>
      </div>
    </div>
    <div class="row" id="ev-types" style="margin-bottom:8px"></div>
    <div class="row" id="ev-services" style="margin-bottom:16px"></div>
    <div id="ev-table"><div class="progress"></div></div>`;

  async function load() {
    const q = new URLSearchParams({ source: filter.source });
    if (filter.eventType) q.set('eventType', filter.eventType);
    if (filter.service) q.set('service', filter.service);
    if (filter.user) q.set('user', filter.user);
    if (filter.correlationId) q.set('correlationId', filter.correlationId);
    $('#ev-table').innerHTML = '<div class="progress"></div>';
    const r = await api(`/console/api/soc/events?${q}`);
    if (!r.ok) { $('#ev-table').innerHTML = errorBanner(errorText(r)); $('#ev-types').innerHTML = ''; $('#ev-services').innerHTML = ''; return; }
    const d = r.data;
    const chips = (facet, key, label) => [`<button class="chip${!filter[key] ? ' selected' : ''}" data-k="${key}" data-v="">${label}</button>`,
      ...Object.entries(d.facets[facet]).sort((a, b) => b[1] - a[1]).map(([v, n]) => `<button class="chip${filter[key] === v ? ' selected' : ''}" data-k="${key}" data-v="${esc(v)}">${esc(v)} <span class="count">${n}</span></button>`)].join('');
    $('#ev-types').innerHTML = chips('eventType', 'eventType', 'All types');
    $('#ev-services').innerHTML = chips('serviceName', 'service', 'All services');
    $$('#ev-types .chip, #ev-services .chip').forEach((c) => { c.onclick = () => { filter[c.dataset.k] = c.dataset.v; load(); }; });
    $('#ev-table').innerHTML = d.events.length ? `
      <div class="table-wrap"><table class="data">
        <thead><tr><th>Time</th><th>Event</th><th>Service</th><th>User</th><th>Request</th><th>Status</th><th>Correlation</th></tr></thead>
        <tbody>${d.events.map((e, n) => `
          <tr class="clickable" data-n="${n}">
            <td class="nowrap body-small">${fmtTime(e.timestamp)}</td>
            <td><div class="row" style="gap:6px"><span class="tag">${esc(e.eventType)}</span>${sevTag(e.severity)}</div><div class="cell-sub">${esc(e.message)}</div></td>
            <td>${esc(e.serviceName)}</td>
            <td>${esc(e.userId || '-')}<div class="cell-sub mono">${esc(e.sourceIp || '')}</div></td>
            <td class="mono">${esc(e.httpMethod)} ${esc(e.endpoint)}</td>
            <td class="num">${e.statusCode}</td>
            <td><button class="btn btn-text mono" style="height:28px;padding:0 6px" data-corr="${esc(e.correlationId)}" title="Show every event with this correlation ID">${esc(shortId(e.correlationId))}</button></td>
          </tr>`).join('')}</tbody></table></div>
      <div class="body-small muted" style="margin-top:8px">${d.shown} of ${d.total} events · newest first</div>`
      : emptyState('stream', 'No events match these filters');
    $$('[data-corr]', el).forEach((b) => { b.onclick = (ev) => { ev.stopPropagation(); filter.correlationId = b.dataset.corr; $('#ev-corr').value = filter.correlationId; load(); }; });
    $$('tr[data-n]', el).forEach((tr) => { tr.onclick = () => openEvent(d.events[Number(tr.dataset.n)]); });
  }

  function openEvent(e) {
    sheet({
      title: e.eventType, subtitle: esc(e.eventId),
      body: `
        <div class="row">${sevTag(e.severity)} <span class="tag">${esc(e.serviceName)}</span></div>
        ${kv([['Time', fmtTime(e.timestamp)], ['Message', esc(e.message)], ['User', esc(e.userId || '-')], ['Source IP', esc(e.sourceIp || '-')],
          ['Request', `<span class="mono">${esc(e.httpMethod)} ${esc(e.endpoint)}</span> → ${e.statusCode}`], ['Affected entity', esc(e.affectedEntity || '-')],
          ['Correlation ID', `<span class="mono">${esc(e.correlationId)}</span>`]])}
        <div class="title-small">Raw event</div><pre class="code">${esc(JSON.stringify(e, null, 2))}</pre>`,
    });
  }

  $$('#ev-src button').forEach((b) => { b.onclick = () => { $$('#ev-src button').forEach((x) => x.classList.toggle('selected', x === b)); filter.source = b.dataset.src; load(); }; });
  let debounce;
  const typed = (key) => (e) => { clearTimeout(debounce); debounce = setTimeout(() => { filter[key] = e.target.value.trim(); load(); }, 350); };
  $('#ev-user').oninput = typed('user');
  $('#ev-corr').oninput = typed('correlationId');
  load();
}

/* ---------- Detection & alerts ---------- */

async function renderAlerts(el) {
  const view = { source: 'capture', status: '' };
  el.innerHTML = `
    <p class="page-intro">Detection rules read the collected events and raise alerts in the specification's alert schema. Run detection, review the rule catalogue, and work each alert from OPEN to ACKNOWLEDGED to CLOSED. The alert list is served by the alert service's own <span class="mono">/api/v1/alerts</span> API.</p>
    <div class="card elevated stack">
      <div class="card-head" style="margin:0">${icon('play_circle')}<div class="title-medium" style="flex:1">Run detection</div></div>
      <div class="row spread">
        ${sourceToggle('al-src', view.source)}
        <button class="btn btn-filled" id="al-run">${icon('bolt')}Run all rules</button>
      </div>
      <div id="al-run-out" class="body-small muted">Running again replaces the previous evaluation.</div>
    </div>

    <div class="section">
      <div class="section-head"><h2 class="title-large">Alerts</h2>
        <div class="row" id="al-status">${['', ...ALERT_STATUSES].map((s) => `<button class="chip${s === '' ? ' selected' : ''}" data-status="${s}">${s || 'All'}</button>`).join('')}</div>
      </div>
      <div id="al-table"><div class="progress"></div></div>
    </div>

    <div class="section">
      <div class="section-head"><h2 class="title-large">Rule catalogue</h2></div>
      <div class="grid grid-2" id="al-rules"></div>
    </div>`;

  async function loadAlerts() {
    const r = await api(`/api/v1/alerts${view.status ? `?status=${view.status}` : ''}`);
    if (!r.ok) { $('#al-table').innerHTML = errorBanner(errorText(r)); return; }
    updateAlertBadge();
    $('#al-table').innerHTML = r.data.length ? `
      <div class="table-wrap"><table class="data">
        <thead><tr><th>Alert</th><th>Rule</th><th>Severity</th><th>Status</th><th>Affected</th><th>Events</th><th>Raised</th></tr></thead>
        <tbody>${r.data.map((a) => `
          <tr class="clickable" data-id="${esc(a.alertId)}">
            <td class="mono nowrap">${esc(a.alertId)}</td>
            <td><div class="cell-title">${esc(a.ruleName)}</div><div class="cell-sub">${esc(a.description.slice(0, 100))}</div></td>
            <td>${sevTag(a.severity)}</td><td>${statusTag(a.status)}</td>
            <td>${esc(a.affectedService || '-')}<div class="cell-sub">${esc(a.affectedUser || '')}</div></td>
            <td class="num">${a.relatedEvents.length}</td>
            <td class="body-small nowrap">${fmtTime(a.timestamp)}</td>
          </tr>`).join('')}</tbody></table></div>`
      : emptyState('notifications_off', view.status ? `No ${view.status} alerts` : 'No alerts yet', 'Run detection above to evaluate the rules over the event stream.');
    $$('tr[data-id]', el).forEach((tr) => { tr.onclick = () => openAlert(tr.dataset.id); });
  }

  async function openAlert(alertId) {
    const [ra, re] = await Promise.all([api(`/api/v1/alerts/${encodeURIComponent(alertId)}`), api(`/console/api/soc/alerts/${encodeURIComponent(alertId)}/events?source=${view.source}`)]);
    if (!ra.ok) { snackbar(errorText(ra)); return; }
    const a = ra.data;
    const events = re.ok ? re.data : [];
    const host = sheet({
      title: a.ruleName, subtitle: `<span class="mono">${esc(a.alertId)}</span>`,
      body: `
        <div class="row">${sevTag(a.severity)} ${statusTag(a.status)}</div>
        <p style="margin:0">${esc(a.description)}</p>
        ${kv([['Raised', fmtTime(a.timestamp)], ['Affected service', esc(a.affectedService || 'not attributed')], ['Affected user', esc(a.affectedUser || 'not attributed')], ['Affected entity', esc(a.affectedEntity || 'not attributed')]])}
        <div class="banner info">${icon('task_alt')}<div class="grow"><div class="title-small">Recommended action</div>${esc(a.recommendedAction)}</div></div>
        <div class="title-small">Move to</div>
        <div class="segmented" id="al-seg">${ALERT_STATUSES.map((s) => `<button data-st="${s}" class="${s === a.status ? 'selected' : ''}">${s}</button>`).join('')}</div>
        <div class="title-small">Evidence: ${events.length} related events</div>
        <div class="list">${events.map((e) => `<div class="list-item">${icon('bolt')}<div style="min-width:0"><div class="row" style="gap:6px"><span class="tag">${esc(e.eventType)}</span><span class="body-small muted">${fmtTime(e.timestamp)}</span></div><div class="body-small" style="margin-top:4px">${esc(e.message)}</div><div class="body-small muted mono">${esc(e.userId || '')} ${esc(e.sourceIp || '')} ${esc(e.httpMethod)} ${esc(e.endpoint)} → ${e.statusCode}</div></div></div>`).join('') || '<div class="muted">The events are not in the selected source.</div>'}</div>
        <button class="btn btn-tonal" id="al-ask">${icon('forum')}Ask GraphRAG about this kind of alert</button>`,
    });
    $$('[data-st]', host).forEach((b) => {
      b.onclick = async () => {
        if (b.dataset.st === a.status) return;
        const r = await api(`/api/v1/alerts/${encodeURIComponent(alertId)}/status`, { method: 'PATCH', body: { status: b.dataset.st } });
        if (!r.ok) { snackbar(errorText(r)); return; }
        snackbar(`Alert ${b.dataset.st.toLowerCase()}.`);
        loadAlerts();
        openAlert(alertId);
      };
    });
    $('#al-ask', host).onclick = async () => {
      // The graph loader mints its own alert ids, so ask about the graph's
      // alert from the same rule rather than this in-memory one.
      const alerts = await loadGraphAlerts();
      const match = alerts && alerts.find((g) => g.ruleName === a.ruleName);
      state.pendingQuestion = match ? `Why was alert ${match.alertId} created and what should be done?`
        : `Which alerts affect ${a.affectedService || 'auth-service'}?`;
      closeOverlay();
      location.hash = '#/ask';
    };
  }

  async function loadRules() {
    const r = await api('/console/api/soc/rules');
    if (!r.ok) { $('#al-rules').innerHTML = errorBanner(errorText(r)); return; }
    $('#al-rules').innerHTML = r.data.map((rule) => `
      <div class="card outlined stack">
        <div class="row spread"><div class="title-medium">${esc(rule.name)}</div>${sevTag(rule.severity)}</div>
        <div class="muted">${esc(rule.purpose)}</div>
        <div class="row">${rule.inputEvents.map((t) => `<span class="tag">${esc(t)}</span>`).join('')}</div>
        <div class="body-small"><b>Response:</b> ${esc(rule.recommendedAction)}</div>
      </div>`).join('');
  }

  $$('#al-src button').forEach((b) => { b.onclick = () => { $$('#al-src button').forEach((x) => x.classList.toggle('selected', x === b)); view.source = b.dataset.src; }; });
  $$('#al-status .chip').forEach((c) => { c.onclick = () => { $$('#al-status .chip').forEach((x) => x.classList.toggle('selected', x === c)); view.status = c.dataset.status; loadAlerts(); }; });
  $('#al-run').onclick = async () => {
    const out = $('#al-run-out');
    out.innerHTML = '<div class="row"><span class="spinner"></span>Evaluating rules…</div>';
    const r = await api('/console/api/soc/detect', { method: 'POST', body: { source: view.source } });
    if (!r.ok) { out.innerHTML = errorBanner(errorText(r)); return; }
    const d = r.data;
    out.innerHTML = `<div class="row">${[
      ['Events evaluated', d.eventsEvaluated], ['Alerts raised', d.alertsRaised], ['Evaluation moment', fmtTime(d.evaluationMoment)],
    ].map(([k, v]) => `<span class="tag info">${k}: ${v}</span>`).join('')}<span class="tag ok">every related event resolves</span></div>`;
    snackbar(`${d.alertsRaised} alerts raised from ${d.eventsEvaluated} events.`);
    loadAlerts();
  };
  loadAlerts();
  loadRules();
}

async function updateAlertBadge() {
  const r = await api('/api/v1/alerts?status=OPEN');
  const badge = $('#alert-badge');
  const n = r.ok ? r.data.length : 0;
  badge.textContent = n;
  badge.classList.toggle('hidden', n === 0);
}

/* ---------- Knowledge graph ---------- */

async function loadGraphAlerts(force = false) {
  if (state.graphAlerts && !force) return state.graphAlerts;
  const r = await api('/console/api/graph/alerts');
  state.graphAlerts = r.ok ? r.data : null;
  return state.graphAlerts;
}

function rowsTable(rows) {
  if (!rows.length) return emptyState('search_off', 'The query returned no rows');
  const columns = [...new Set(rows.flatMap((r) => Object.keys(r)))];
  const cell = (v) => {
    if (v === null || v === undefined) return '<span class="muted">-</span>';
    if (Array.isArray(v)) return v.length ? v.map((x) => `<span class="tag" style="margin:0 4px 4px 0">${esc(typeof x === 'object' ? JSON.stringify(x) : x)}</span>`).join('') : '<span class="muted">none</span>';
    if (typeof v === 'object') return `<span class="mono">${esc(JSON.stringify(v))}</span>`;
    return SEVERITIES.includes(v) ? sevTag(v) : esc(v);
  };
  return `<div class="table-wrap"><table class="data"><thead><tr>${columns.map((c) => `<th>${esc(c)}</th>`).join('')}</tr></thead>
    <tbody>${rows.map((r) => `<tr>${columns.map((c) => `<td>${cell(r[c])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>
    <div class="body-small muted" style="margin-top:8px">${rows.length} rows</div>`;
}

async function renderGraph(el) {
  el.innerHTML = `
    <p class="page-intro">The Neo4j knowledge graph joins the application topology, the collected events and alerts, and MITRE ATT&amp;CK threat knowledge. Reload it from an event source, see what it holds, and run the five demonstrated Cypher queries.</p>
    <div class="grid grid-2">
      <div class="card elevated stack" id="g-summary"><div class="progress"></div></div>
      <div class="card elevated stack">
        <div class="card-head" style="margin:0">${icon('upload')}<div class="title-medium">Load the graph</div></div>
        <div class="body-small muted">Runs <span class="mono">python -m kg.loader.main</span>: schema, then topology, events and alerts, then security knowledge. Every write is a MERGE, so a reload is safe.</div>
        ${sourceToggle('g-src', 'capture')}
        <label class="switch"><input type="checkbox" id="g-dry"> Dry run (count writes, no Neo4j needed)</label>
        <div><button class="btn btn-filled" id="g-load">${icon('upload')}Load</button></div>
        <div id="g-load-out"></div>
      </div>
    </div>
    <div class="section">
      <div class="section-head"><h2 class="title-large">Demonstrated queries</h2></div>
      <div class="grid grid-auto" id="g-queries"></div>
      <div id="g-run" class="section"></div>
    </div>`;

  let services = ['auth-service', 'incident-service', 'asset-service'];
  let loadSource = 'capture';

  async function loadSummary() {
    const box = $('#g-summary');
    const r = await api('/console/api/graph/summary');
    const browser = state.config ? `${state.config.tools.find((t) => t.name === 'Neo4j Browser').url}` : '#';
    if (!r.ok) {
      box.innerHTML = `<div class="card-head" style="margin:0">${icon('hub')}<div class="title-medium">Graph contents</div></div>${errorBanner(errorText(r), 'g-retry')}`;
      $('#g-retry').onclick = loadSummary;
      return;
    }
    const d = r.data;
    if (d.services && d.services.length) services = d.services;
    const max = Math.max(1, ...d.labels.map((l) => l.count));
    const total = d.labels.reduce((s, l) => s + l.count, 0);
    box.innerHTML = `
      <div class="card-head" style="margin:0">${icon('hub')}<div class="title-medium" style="flex:1">Graph contents</div>
        <a class="btn btn-text" href="${esc(browser)}" target="_blank" rel="noopener">${icon('open_in_new')}Neo4j Browser</a></div>
      <div class="row"><span class="tag info">${total} nodes</span><span class="tag info">${d.relationships} relationships</span><span class="tag">${d.labels.length} labels</span></div>
      <div>${d.labels.map((l) => `<div class="bar-row"><span class="body-small">${esc(l.label)}</span><div class="bar-track"><div class="bar-fill" style="width:${(l.count / max) * 100}%"></div></div><span class="body-small num" style="text-align:right">${l.count}</span></div>`).join('') || '<div class="muted">The graph is empty. Load it.</div>'}</div>`;
  }

  async function loadQueries() {
    const r = await api('/console/api/graph/queries');
    if (!r.ok) { $('#g-queries').innerHTML = errorBanner(errorText(r)); return; }
    $('#g-queries').innerHTML = r.data.map((q, n) => `
      <div class="card outlined clickable stack" data-q="${n}">
        <div class="row"><span class="tag info">q${n + 1}</span><span class="body-small muted mono">${esc(q.key)}</span></div>
        <div class="title-medium">${esc(q.question)}</div>
        <div class="body-small muted">${q.parameters.length ? `Needs: ${q.parameters.map(esc).join(', ')}` : 'No parameters'}</div>
      </div>`).join('');
    $$('[data-q]', el).forEach((c) => { c.onclick = () => openQuery(r.data[Number(c.dataset.q)], Number(c.dataset.q)); });
  }

  async function openQuery(q, n) {
    $$('[data-q]', el).forEach((c) => { c.style.outline = Number(c.dataset.q) === n ? '2px solid var(--md-primary)' : ''; });
    const box = $('#g-run');
    const alerts = q.parameters.includes('alertId') ? (await loadGraphAlerts(true)) || [] : [];
    if (!box.isConnected) return; // the user left the screen while the alerts loaded
    box.innerHTML = `
      <div class="card elevated stack">
        <div class="title-medium">q${n + 1}. ${esc(q.question)}</div>
        <form class="row" id="g-form">
          ${q.parameters.map((p) => p === 'service'
            ? `<div class="field compact"><label for="gp-${p}">service</label><select id="gp-${p}" name="${p}">${services.map((s) => `<option>${esc(s)}</option>`).join('')}</select></div>`
            : p === 'alertId' && alerts.length
              ? `<div class="field compact"><label for="gp-${p}">alertId</label><select id="gp-${p}" name="${p}">${alerts.map((a) => `<option value="${esc(a.alertId)}">${esc(a.alertId)} · ${esc(a.ruleName)}</option>`).join('')}</select></div>`
              : `<div class="field compact"><label for="gp-${p}">${esc(p)}</label><input id="gp-${p}" name="${p}" required></div>`).join('')}
          <button class="btn btn-filled" style="align-self:flex-end">${icon('play_arrow')}Run query</button>
        </form>
        <details class="disclose"><summary>Show Cypher</summary><pre class="code">${esc(q.cypher)}</pre></details>
        <div id="g-result"></div>
      </div>`;
    $('#g-form', box).onsubmit = async (e) => {
      e.preventDefault();
      const params = new URLSearchParams(new FormData(e.target));
      const result = $('#g-result', box);
      result.innerHTML = '<div class="progress"></div>';
      const r = await api(`/console/api/graph/queries/${q.key}?${params}`);
      result.innerHTML = r.ok ? rowsTable(r.data) : errorBanner(errorText(r));
    };
    if (!q.parameters.length || q.parameters.every((p) => p === 'service' || (p === 'alertId' && alerts.length))) $('#g-form', box).requestSubmit();
    box.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  $$('#g-src button').forEach((b) => { b.onclick = () => { $$('#g-src button').forEach((x) => x.classList.toggle('selected', x === b)); loadSource = b.dataset.src; }; });
  $('#g-load').onclick = async () => {
    const out = $('#g-load-out');
    out.innerHTML = '<div class="row"><span class="spinner"></span>Loading…</div>';
    const r = await api('/console/api/graph/load', { method: 'POST', body: { source: loadSource, dry_run: $('#g-dry').checked } });
    if (!r.ok) { out.innerHTML = errorBanner(errorText(r)); return; }
    out.innerHTML = `<pre class="console-out">${esc(r.data.output)}</pre>`;
    snackbar(r.data.exitCode === 0 ? 'Graph load finished.' : 'Graph load failed. See the output.');
    state.graphAlerts = null;
    loadSummary();
  };
  loadSummary();
  loadQueries();
}

/* ---------- Ask GraphRAG ---------- */

async function renderAsk(el) {
  el.innerHTML = `
    <p class="page-intro">Ask a security question in plain English. The retriever classifies the question, runs one Cypher query over the knowledge graph, and the answer is built only from what that query returned. All four evidence parts are shown below every answer. If the graph does not know, the answer says so.</p>
    <div class="card elevated stack">
      <form id="ask-form" class="stack">
        <div class="field"><label for="ask-q">Question</label>
          <textarea id="ask-q" style="min-height:72px" placeholder="Why was alert alt-… created and what should be done?" required></textarea></div>
        <div class="row spread">
          <label class="switch" title="Uses the Gemini API when a key is configured, and falls back to the template generator otherwise"><input type="checkbox" id="ask-llm"> Phrase with LLM (optional)</label>
          <button class="btn btn-filled" id="ask-go">${icon('send')}Ask</button>
        </div>
      </form>
      <div><div class="label-small muted" style="margin-bottom:8px">Try</div><div class="row" id="ask-suggest"><span class="spinner"></span></div></div>
    </div>
    <div id="ask-out" class="section"></div>
    <div id="ask-history" class="section"></div>`;

  const textarea = $('#ask-q');
  if (state.pendingQuestion) { textarea.value = state.pendingQuestion; state.pendingQuestion = null; setTimeout(() => $('#ask-form').requestSubmit()); }

  (async () => {
    const [alerts, summary] = await Promise.all([loadGraphAlerts(true), api('/console/api/graph/summary')]);
    const service = summary.ok && summary.data.services.includes('auth-service') ? 'auth-service' : (summary.ok && summary.data.services[0]) || 'auth-service';
    const preferred = alerts && (alerts.find((a) => a.ruleName === 'Multiple Failed Logins') || alerts[0]);
    const suggestions = [
      preferred && `Why was alert ${preferred.alertId} created and what should be done?`,
      `Which alerts affect ${service}?`,
      `Which threats target ${service} and how are they mitigated?`,
      'Which users are linked to high severity alerts?',
      'What is the impact if asset-service fails?',
    ].filter(Boolean);
    $('#ask-suggest').innerHTML = suggestions.map((s) => `<button class="chip" type="button">${icon('lightbulb')}${esc(s)}</button>`).join('')
      + (alerts ? '' : `<span class="body-small muted">Neo4j is not reachable, so answers are unavailable until the stack is up.</span>`);
    $$('#ask-suggest .chip').forEach((c, i) => { c.onclick = () => { textarea.value = suggestions[i]; $('#ask-form').requestSubmit(); }; });
  })();

  $('#ask-form').onsubmit = async (e) => {
    e.preventDefault();
    const question = textarea.value.trim();
    if (!question) return;
    const out = $('#ask-out');
    out.innerHTML = '<div class="card stack"><div class="row"><span class="spinner"></span>Retrieving evidence from the graph…</div></div>';
    const r = await api('/console/api/graph/rag/ask', { method: 'POST', body: { question, use_llm: $('#ask-llm').checked } });
    if (!r.ok) { out.innerHTML = errorBanner(errorText(r)); return; }
    state.askHistory.unshift({ question, at: new Date().toISOString(), result: r.data });
    drawAnswer(r.data);
    drawHistory();
  };

  function drawAnswer(a) {
    const ev = a.evidence;
    $('#ask-out').innerHTML = `
      <div class="stack">
        <div class="row"><span class="tag info">intent: ${esc(ev.intent)}</span><span class="tag">method: ${esc(a.method)}</span>${a.grounded ? '<span class="tag ok">grounded in graph evidence</span>' : '<span class="tag warn">not grounded: the graph holds nothing for this</span>'}</div>
        <div class="answer">${esc(a.text)}</div>
        <div class="grid grid-2">
          <div class="card outlined stack"><div class="card-head" style="margin:0">${icon('scatter_plot')}<div class="title-medium">Retrieved nodes (${ev.nodes.length})</div></div>
            ${ev.nodes.length ? `<div class="list">${ev.nodes.map((n) => `<div class="list-item"><span class="tag info">${esc(n.label)}</span><div style="min-width:0"><div class="title-small mono">${esc(n.key)}</div><div class="body-small muted" style="overflow-wrap:anywhere">${Object.entries(n.properties).filter(([, v]) => v !== null && v !== '' && !(Array.isArray(v) && !v.length)).map(([k, v]) => `${esc(k)}=${esc(Array.isArray(v) ? v.join(', ') : v)}`).join(' · ')}</div></div></div>`).join('')}</div>` : '<div class="muted">None.</div>'}
          </div>
          <div class="stack">
            <div class="card outlined stack"><div class="card-head" style="margin:0">${icon('conversion_path')}<div class="title-medium">Retrieved relationships (${ev.relationships.length})</div></div>
              ${ev.relationships.length ? `<div class="list">${ev.relationships.map((x) => `<div class="list-item mono body-small" style="overflow-wrap:anywhere">(${esc(x.start)}) -[:${esc(x.type)}]-> (${esc(x.end)})</div>`).join('')}</div>` : '<div class="muted">None.</div>'}
            </div>
            <div class="card outlined stack"><div class="card-head" style="margin:0">${icon('description')}<div class="title-medium">Source documents (${ev.documents.length})</div></div>
              ${ev.documents.length ? `<div class="list">${ev.documents.map((d) => `<div class="list-item">${icon('article')}<span>${esc(d)}</span></div>`).join('')}</div>` : '<div class="muted">None.</div>'}
            </div>
          </div>
        </div>
        <div class="card outlined stack"><div class="card-head" style="margin:0">${icon('manage_search')}<div class="title-medium">Retrieval method</div></div>
          ${kv([['Method', 'Cypher query over the Neo4j knowledge graph'], ['Intent', esc(ev.intent)], ['Query', `<span class="mono">${esc(ev.query_key || 'none')}</span>`], ['Parameters', `<span class="mono">${esc(JSON.stringify(ev.parameters))}</span>`], ['Note', ev.reason ? esc(ev.reason) : undefined]])}
          ${ev.query_text ? `<details class="disclose"><summary>Show Cypher</summary><pre class="code">${esc(ev.query_text)}</pre></details>` : ''}
          <details class="disclose"><summary>Show the CLI rendering</summary><pre class="console-out">${esc(a.rendered)}</pre></details>
        </div>
      </div>`;
  }

  function drawHistory() {
    const box = $('#ask-history');
    if (state.askHistory.length < 2) { box.innerHTML = ''; return; }
    box.innerHTML = `<div class="section-head"><h2 class="title-medium">Earlier this session</h2></div>
      <div class="list">${state.askHistory.slice(1).map((h, i) => `<div class="list-item clickable" style="cursor:pointer" data-h="${i + 1}">${icon('history')}<div><div>${esc(h.question)}</div><div class="body-small muted">${fmtTime(h.at)} · ${esc(h.result.evidence.intent)}</div></div></div>`).join('')}</div>`;
    $$('[data-h]', box).forEach((row) => { row.onclick = () => { const h = state.askHistory[Number(row.dataset.h)]; textarea.value = h.question; drawAnswer(h.result); window.scrollTo({ top: 0, behavior: 'smooth' }); }; });
  }

  if (state.askHistory.length) { drawAnswer(state.askHistory[0].result); drawHistory(); }
}

/* ---------- Operations ---------- */

async function renderOperations(el) {
  el.innerHTML = `
    <p class="page-intro">The project's own scripts, run from c_sentinel-ir exactly as you would type them in a terminal. Output appears under each card when the script finishes. Starting and stopping the Docker stack stays with <span class="mono">start.bat</span> and <span class="mono">stop.bat</span>.</p>
    <div id="op-groups"><div class="progress"></div></div>
    <div class="section"><div class="section-head"><h2 class="title-large">External tools</h2></div><div class="grid grid-auto" id="op-tools"></div></div>`;
  renderTools($('#op-tools'));
  const r = await api('/console/api/actions');
  if (!r.ok) { $('#op-groups').innerHTML = errorBanner(errorText(r)); return; }
  const groups = [...new Set(r.data.map((a) => a.group))];
  $('#op-groups').innerHTML = groups.map((g) => `
    <div class="section"><div class="section-head"><h2 class="title-large">${esc(g)}</h2></div>
      <div class="grid grid-2">${r.data.filter((a) => a.group === g).map((a) => `
        <div class="card outlined stack" id="op-${esc(a.id)}">
          <div class="row spread"><div class="title-medium">${esc(a.title)}</div><span class="tag ${a.needs === 'Nothing' ? 'ok' : 'warn'}">needs: ${esc(a.needs)}</span></div>
          <div class="muted">${esc(a.description)}</div>
          <div class="row spread"><span class="mono body-small muted">${esc(a.command)}</span><button class="btn btn-tonal" data-run="${esc(a.id)}">${icon('play_arrow')}Run</button></div>
          <div data-out></div>
        </div>`).join('')}</div></div>`).join('');

  $$('[data-run]', el).forEach((button) => {
    button.onclick = async () => {
      const action = r.data.find((a) => a.id === button.dataset.run);
      if (action.id === 'break-asset' && !(await confirmDialog({ title: 'Stop asset-service?', message: 'The drill stops the asset-service container, opens the circuit breaker, then restarts it. Incident creation is degraded while it runs.', confirmLabel: 'Run drill', danger: true }))) return;
      const out = $('[data-out]', $(`#op-${action.id}`));
      button.disabled = true;
      out.innerHTML = '<div class="row"><span class="spinner"></span>Running… this can take a minute.</div>';
      const res = await api(`/console/api/actions/${action.id}`, { method: 'POST' });
      button.disabled = false;
      if (!res.ok) { out.innerHTML = errorBanner(errorText(res)); return; }
      const ok = res.data.exitCode === 0;
      out.innerHTML = `<div class="row" style="margin-bottom:8px"><span class="tag ${ok ? 'ok' : 'bad'}">exit ${res.data.exitCode}</span><span class="body-small muted">${res.data.seconds}s</span></div><pre class="console-out">${esc(res.data.output || '(no output)')}</pre>`;
      snackbar(`${action.title}: ${ok ? 'finished' : 'failed'}.`);
    };
  });
}

/* ---------- Request trace ---------- */

function renderActivity(el) {
  el.innerHTML = `
    <p class="page-intro">Every call this console made through the Kong gateway, newest first. Each one carries a correlation ID that the gateway and all three services write to their logs and security events, so any row here can be traced across the system.</p>
    <div class="section-head"><span class="body-small muted">${state.trace.length} requests this session</span>
      <button class="btn btn-text" id="tr-clear" ${state.trace.length ? '' : 'disabled'}>${icon('delete_sweep')}Clear</button></div>
    ${state.trace.length ? `
      <div class="table-wrap"><table class="data">
        <thead><tr><th>Time</th><th>Request</th><th>Status</th><th>Latency</th><th>Rate limit left</th><th>Correlation ID</th><th></th></tr></thead>
        <tbody>${state.trace.map((t, n) => `<tr>
          <td class="nowrap body-small">${fmtTime(t.at)}</td>
          <td class="mono">${esc(t.method)} ${esc(t.path)}</td>
          <td><span class="tag ${t.status >= 500 || t.status === 0 ? 'bad' : t.status >= 400 ? 'warn' : 'ok'}">${t.status || 'no answer'}</span></td>
          <td class="num nowrap">${t.ms} ms</td><td class="num">${esc(t.remaining ?? '-')}</td>
          <td class="mono">${esc(t.correlationId)}</td>
          <td class="nowrap"><button class="icon-btn" data-copy="${n}" title="Copy correlation ID">${icon('content_copy')}</button><button class="icon-btn" data-find="${n}" title="Find in live security events">${icon('manage_search')}</button></td>
        </tr>`).join('')}</tbody></table></div>`
      : emptyState('receipt_long', 'No gateway calls yet', 'Sign in and open Incidents or Assets. Every call you make is listed here.')}`;
  const clear = $('#tr-clear');
  clear.onclick = () => { state.trace = []; renderActivity(el); };
  $$('[data-copy]', el).forEach((b) => {
    b.onclick = async () => {
      const id = state.trace[Number(b.dataset.copy)].correlationId;
      try { await navigator.clipboard.writeText(id); snackbar('Correlation ID copied.'); } catch { snackbar(id); }
    };
  });
  $$('[data-find]', el).forEach((b) => {
    b.onclick = () => { state.eventFilter = { source: 'live', correlationId: state.trace[Number(b.dataset.find)].correlationId }; location.hash = '#/events'; };
  });
}

/* ========================================================== 6. boot == */

const ROUTES = {
  overview: { title: 'Overview', render: renderOverview },
  incidents: { title: 'Incidents', render: renderIncidents },
  assets: { title: 'Assets', render: renderAssets },
  users: { title: 'Users', render: renderUsers },
  events: { title: 'Security events', render: renderEvents },
  alerts: { title: 'Detection & alerts', render: renderAlerts },
  graph: { title: 'Knowledge graph', render: renderGraph },
  ask: { title: 'Ask GraphRAG', render: renderAsk },
  operations: { title: 'Operations', render: renderOperations },
  activity: { title: 'Request trace', render: renderActivity },
};

function route() {
  const name = (location.hash.replace(/^#\/?/, '') || 'overview').split('?')[0];
  const target = ROUTES[name] || ROUTES.overview;
  closeOverlay();
  $('#drawer').classList.remove('open');
  $$('.nav-item').forEach((a) => a.classList.toggle('active', a.dataset.route === (ROUTES[name] ? name : 'overview')));
  $('#page-title').textContent = target.title;
  document.title = `${target.title} · Sentinel-IR Console`;
  renderUserChip();
  const content = $('#content');
  content.innerHTML = '';
  window.scrollTo(0, 0);
  Promise.resolve(target.render(content)).catch((error) => {
    content.innerHTML = errorBanner(`This screen failed to render: ${error.message}`);
    console.error(error);
  });
}

function applyTheme(theme) {
  if (theme) document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
  const dark = theme ? theme === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches;
  $('#theme-btn').innerHTML = icon(dark ? 'light_mode' : 'dark_mode');
}

async function boot() {
  applyTheme(storage.get('localStorage', 'sentinel.theme'));
  $('#theme-btn').onclick = () => {
    const current = document.documentElement.dataset.theme
      || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    const next = current === 'dark' ? 'light' : 'dark';
    storage.set('localStorage', 'sentinel.theme', next);
    applyTheme(next);
  };
  $('#menu-btn').onclick = (e) => { e.stopPropagation(); $('#drawer').classList.toggle('open'); };
  document.addEventListener('click', (e) => {
    const drawer = $('#drawer');
    if (drawer.classList.contains('open') && !drawer.contains(e.target)) drawer.classList.remove('open');
  });
  window.addEventListener('scroll', () => $('#appbar').classList.toggle('scrolled', window.scrollY > 4), { passive: true });
  window.addEventListener('hashchange', route);

  const config = await api('/console/api/config');
  state.config = config.ok ? config.data : null;
  route();
  refreshStatus();
  updateAlertBadge();
  setInterval(refreshStatus, 30000);
  setInterval(renderUserChip, 60000);
}

boot();
