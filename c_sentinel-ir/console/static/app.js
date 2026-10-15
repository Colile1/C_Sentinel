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

/* ---------- Demo guide ---------- */

/**
 * The two demo scripts (docs/report/demo-script.md and phase2-demo-script.md)
 * as checklists. Each step says what to show, jumps to the console screen
 * that shows it, names the files to have open, and keeps the terminal command
 * the script uses for anyone following along without the console.
 */
const DEMO_GUIDES = {
  phase1: {
    title: 'Phase 1 · the microservices platform',
    script: 'docs/report/demo-script.md',
    steps: [
      { title: 'Before recording', points: ['Run start.bat and wait for "all green", then console.bat.', 'Camera on for identification.', 'Sign in as the bootstrap admin.', 'Aim for 8 to 10 minutes.'],
        go: [['overview', 'Overview']], files: [], cmd: 'start.bat && console.bat' },
      { title: '1. One complete business workflow', points: ['Raise an incident against core-auth-db: the asset name is fetched from asset-service and snapshotted onto the incident.', 'Open it and escalate its severity to HIGH (emits INCIDENT_ESCALATED).', 'Or run the scripted five-step workflow from Operations.'],
        go: [['incidents', 'Incidents'], ['operations', 'Operations']], files: ['client/demo_workflow.py'], cmd: 'python client/demo_workflow.py' },
      { title: '2. The gateway routing and enforcing', points: ['Show the auth-login / auth-protected route split in kong.yml: login is public, everything else needs a JWT.', 'Send the three probes: no token (401 from Kong), wrong password (401 from auth-service), the burst (tail turns 429).', 'Request trace shows every call\'s correlation ID and the RateLimit headers.'],
        go: [['platform', 'Platform'], ['activity', 'Request trace']], files: ['gateway/kong.yml'], cmd: 'curl -i http://localhost:8000/api/v1/incidents' },
      { title: '3. The service registry', points: ['All three services registered with real addresses and passing checks.', 'Stop asset-service in Containers, refresh the registry: its check fails. Start it again.'],
        go: [['platform', 'Platform']], files: ['registry/README.md'], cmd: 'docker compose -f deploy/docker-compose.yml stop asset-service' },
      { title: '4. Every service in its own container', points: ['Containers lists one container and one image per service, each with its own state and health.'],
        go: [['platform', 'Platform']], files: ['deploy/docker-compose.yml'], cmd: 'docker compose -f deploy/docker-compose.yml ps' },
      { title: '5. The two patterns, in code and firing', points: ['Database per Service: each database holds only its own table. Stop asset-db and show Incidents still listing.', 'Circuit Breaker with Retry: show http_client.py, then run the circuit-breaker drill from Operations: slow retries, degraded incidents instead of 500s, near-instant once open, CIRCUIT_CLOSED after restart.'],
        go: [['platform', 'Platform'], ['incidents', 'Incidents'], ['operations', 'Operations']], files: ['docs/patterns.md', 'libs/common/http_client.py'], cmd: 'python scripts/break_asset_service.py' },
      { title: '6. Security event collection', points: ['Live stack logs: every request, auth decision and inter-service call emits one event in the soc-events.md schema.', 'Click a correlation ID to follow one workflow across all three services.', 'Grafana shows the request and authentication-failure dashboard filling.'],
        go: [['events', 'Security events', { source: 'live' }], ['overview', 'Overview (Grafana link)']], files: ['docs/soc-events.md'], cmd: 'docker compose -f deploy/docker-compose.yml logs | grep <correlation id>' },
    ],
  },
  phase2: {
    title: 'Phase 2 · SOC, knowledge graph and GraphRAG',
    script: 'docs/report/phase2-demo-script.md',
    steps: [
      { title: 'Before recording', points: ['start.bat loads the graph from the committed attack capture.', 'Have the Neo4j Browser ready (user neo4j, password from deploy/.env).'],
        go: [['overview', 'Overview'], ['graph', 'Knowledge graph']], files: ['kg/model/graph_model.md'], cmd: 'python -m kg.loader.main --file docs/evidence/step15-attack-events.jsonl' },
      { title: '1. Collect security events', points: ['The collector reads every service and the gateway on one schema, with no translation.', 'Type and service counts; follow one workflow by its correlation ID.'],
        go: [['events', 'Security events', { source: 'capture' }]], files: ['docs/soc-events.md'], cmd: 'python -m soc.collector.main' },
      { title: '2. Detection rules and alerts', points: ['The rule catalogue is read from the rule classes, so documentation cannot drift.', 'Run on Captured attack: alerts from all four rules. Multiple Failed Logins fires twice on purpose, keyed by user and by source IP.', 'Run on Normal workflow: 0 alerts. The rules stay quiet on ordinary traffic.', 'Acknowledge an alert and open its evidence.'],
        go: [['alerts', 'Detection & alerts']], files: ['soc/rules/rule_failed_logins.py'], cmd: 'python -m soc.rules.main --catalogue' },
      { title: '3. The complete workflow in one pass', points: ['Events, detection, the graph load and the RAG answer, from one command.'],
        go: [['operations', 'Operations']], files: ['scripts/run_security_workflow.py'], cmd: 'python scripts/run_security_workflow.py --skip-capture' },
      { title: '4. Explore the graph and the five queries', points: ['Alert neighbourhood: the Multiple Failed Logins alert, T1110 Brute Force, its controls and runbooks, and the user behind the events.', 'Run q1 to q5 and show each query\'s Cypher.'],
        go: [['graph', 'Knowledge graph']], files: ['kg/cypher/q4_controls_for_alert.cypher'], cmd: 'MATCH (a:Alert)-[:INDICATES]->(t:Threat)<-[:MITIGATES]-(c:Control) RETURN a, t, c' },
      { title: '5. Ask your own questions', points: ['The demo question: rule, ATT&CK technique, controls, runbooks, with all four evidence parts.', 'The other shapes: alerts for a service, threats, users, dependency impact.', 'The two refusals: a question it does not understand, and an alert the graph does not hold.'],
        go: [['ask', 'Ask GraphRAG']], files: ['rag/generation/templates.py'], cmd: 'python -m rag.generation.main --demo' },
    ],
  },
};

function renderDemo(el) {
  const saved = storage.get('localStorage', 'sentinel.demo') || {};
  const view = { phase: saved.phase || 'phase1', done: saved.done || {} };
  const persist = () => storage.set('localStorage', 'sentinel.demo', view);

  function draw() {
    const guide = DEMO_GUIDES[view.phase];
    const doneCount = guide.steps.filter((_, i) => view.done[`${view.phase}-${i}`]).length;
    el.innerHTML = `
      <p class="page-intro">Both demo scripts as checklists you can record from. Each step says what to show, jumps to the console screen that shows it, names the files to have open in your editor, and keeps the terminal command the script uses. Ticks are remembered in this browser.</p>
      <div class="section-head" style="margin-top:0">
        <div class="segmented" id="demo-phase">
          <button data-phase="phase1" class="${view.phase === 'phase1' ? 'selected' : ''}">${icon('lan', 'icon-sm')}Phase 1</button>
          <button data-phase="phase2" class="${view.phase === 'phase2' ? 'selected' : ''}">${icon('security', 'icon-sm')}Phase 2</button>
        </div>
        <div class="row"><span class="tag ${doneCount === guide.steps.length ? 'ok' : 'info'}">${doneCount} of ${guide.steps.length} done</span>
          <button class="btn btn-text" id="demo-reset">${icon('restart_alt')}Reset</button></div>
      </div>
      <div class="progress-bar bar-track" style="margin-bottom:20px"><div class="bar-fill" style="width:${(doneCount / guide.steps.length) * 100}%"></div></div>
      <div class="stack">${guide.steps.map((step, i) => {
        const key = `${view.phase}-${i}`;
        return `<div class="demo-step${view.done[key] ? ' done' : ''}">
          <button class="demo-check" data-step="${key}" aria-label="Mark ${esc(step.title)} done" aria-pressed="${view.done[key] ? 'true' : 'false'}">${view.done[key] ? icon('check') : ''}</button>
          <div class="demo-body">
            <div class="title-medium">${esc(step.title)}</div>
            <ul>${step.points.map((p) => `<li>${esc(p)}</li>`).join('')}</ul>
            <div class="row">${step.go.map(([, label], g) => `<button class="btn btn-tonal" data-go="${i}-${g}">${icon('arrow_forward')}${esc(label)}</button>`).join('')}
              ${step.files.map((f) => `<span class="tag mono" title="Have this open in your editor">${icon('description', 'icon-sm')}${esc(f)}</span>`).join('')}</div>
            <details class="disclose"><summary>Terminal equivalent</summary><pre class="code">${esc(step.cmd)}</pre></details>
          </div>
        </div>`;
      }).join('')}</div>
      <p class="body-small muted" style="margin-top:16px">Source: <span class="mono">${esc(guide.script)}</span></p>`;

    $$('#demo-phase button', el).forEach((b) => { b.onclick = () => { view.phase = b.dataset.phase; persist(); draw(); }; });
    $('#demo-reset', el).onclick = () => {
      Object.keys(view.done).filter((k) => k.startsWith(view.phase)).forEach((k) => delete view.done[k]);
      persist(); draw();
    };
    $$('[data-step]', el).forEach((b) => {
      b.onclick = () => { view.done[b.dataset.step] = !view.done[b.dataset.step]; persist(); draw(); };
    });
    $$('[data-go]', el).forEach((b) => {
      b.onclick = () => {
        const [i, g] = b.dataset.go.split('-').map(Number);
        const [route, , preset] = guide.steps[i].go[g];
        if (route === 'events' && preset) state.eventFilter = preset;
        location.hash = `#/${route}`;
      };
    });
  }
  draw();
}

/* ---------- Platform ---------- */

async function renderPlatform(el) {
  el.innerHTML = `
    <p class="page-intro">The microservices platform underneath the business screens: the Kong gateway enforcing authentication and rate limits, the Consul registry, one container per service, and one database per service. Every check here is one section of the Phase 1 demo script.</p>

    <div class="section" style="margin-top:0">
      <div class="section-head"><h2 class="title-large">Gateway enforcement</h2></div>
      <div class="grid grid-3">
        ${[
          ['no-token', 'lock', 'Call without a token', 'GET /incidents with no Authorization header. Kong refuses it with 401 before any service is reached.'],
          ['bad-login', 'password', 'Log in with a wrong password', 'The login route is the one route with no JWT check, so this 401 comes from auth-service and emits AUTH_FAILED.'],
          ['burst', 'speed', 'Burst past the rate limit', '65 concurrent wrong logins. The limit is 60 a minute, so the tail turns 429. The console\'s own gateway calls are refused for up to a minute afterwards.'],
        ].map(([kind, glyph, title, text]) => `
          <div class="card outlined stack">
            <div class="card-head" style="margin:0">${icon(glyph)}<div class="title-medium">${title}</div></div>
            <div class="body-small muted">${text}</div>
            <div><button class="btn btn-tonal" data-probe="${kind}">${icon('play_arrow')}Send</button></div>
            <div data-probe-out="${kind}"></div>
          </div>`).join('')}
      </div>
    </div>

    <div class="section">
      <div class="section-head"><h2 class="title-large">Service registry</h2>
        <div class="row"><button class="btn btn-text" id="pf-reg-refresh">${icon('refresh')}Refresh</button>
          <a class="btn btn-text" href="${esc(state.config ? state.config.tools.find((t) => t.name === 'Consul registry').url : '#')}" target="_blank" rel="noopener">${icon('open_in_new')}Consul UI</a></div></div>
      <div id="pf-registry"><div class="progress"></div></div>
    </div>

    <div class="section">
      <div class="section-head"><h2 class="title-large">Containers</h2>
        <button class="btn btn-text" id="pf-ct-refresh">${icon('refresh')}Refresh</button></div>
      <p class="page-intro" style="margin-bottom:12px">One container, one image and one lifecycle per service. Stopping a service shows it leave the Consul healthy list; stopping a database shows the other services keep serving (Database per Service); stopping asset-service is the circuit breaker's trigger.</p>
      <div id="pf-containers"><div class="progress"></div></div>
    </div>

    <div class="section">
      <div class="section-head"><h2 class="title-large">Database per Service</h2>
        <button class="btn btn-text" id="pf-db-refresh">${icon('refresh')}Refresh</button></div>
      <div class="grid grid-3" id="pf-databases"><div class="progress"></div></div>
    </div>`;

  $$('[data-probe]', el).forEach((button) => {
    button.onclick = async () => {
      const kind = button.dataset.probe;
      const out = $(`[data-probe-out="${kind}"]`, el);
      button.disabled = true;
      out.innerHTML = '<div class="row"><span class="spinner"></span>Sending…</div>';
      const r = await api(`/console/api/platform/gateway-probe/${kind}`, { method: 'POST' });
      button.disabled = false;
      if (!r.ok) { out.innerHTML = errorBanner(errorText(r)); return; }
      const d = r.data;
      const codeTag = (code) => `<span class="tag ${code >= 500 ? 'bad' : code === 429 ? 'warn' : code >= 400 ? 'info' : 'ok'}">${code}</span>`;
      out.innerHTML = kind === 'burst'
        ? `<div class="stack"><div class="row">${Object.entries(d.counts).map(([code, n]) => `${codeTag(Number(code))}<span class="body-small">× ${n}</span>`).join('')}<span class="body-small muted">in ${d.seconds}s</span></div>
            ${d.sample429 ? `<div class="body-small">A refused response: ${codeTag(429)} <span class="mono">${esc(JSON.stringify(d.sample429.body))}</span></div>` : '<div class="body-small muted">No request was refused. The window may already have been partly used; try again in a minute.</div>'}</div>`
        : `<div class="stack">${kv([['Status', codeTag(d.status)], ['Body', `<span class="mono">${esc(JSON.stringify(d.body))}</span>`], ['Correlation ID', `<span class="mono">${esc(d.correlationId || '-')}</span>`]])}</div>`;
    };
  });

  async function loadRegistry() {
    const box = $('#pf-registry');
    const r = await api('/console/api/platform/registry');
    if (!box.isConnected) return;
    if (!r.ok) { box.innerHTML = errorBanner(errorText(r), 'pf-reg-retry'); $('#pf-reg-retry').onclick = loadRegistry; return; }
    box.innerHTML = r.data.services.length ? `<div class="table-wrap"><table class="data">
      <thead><tr><th>Service</th><th>Instance</th><th>Address</th><th>Health checks</th></tr></thead>
      <tbody>${r.data.services.flatMap((s) => (s.instances.length ? s.instances : [null]).map((i) => `<tr>
        <td class="cell-title">${esc(s.name)}</td>
        ${i ? `<td class="mono">${esc(i.id)}</td><td class="mono">${esc(i.address)}:${i.port}</td>
          <td>${i.checks.map((c) => `<div class="row" style="gap:6px;margin-bottom:4px"><span class="tag ${c.status === 'passing' ? 'ok' : c.status === 'warning' ? 'warn' : 'bad'}">${esc(c.status)}</span><span class="body-small">${esc(c.name)}</span></div>`).join('')}</td>`
          : '<td colspan="3" class="muted">No registered instance</td>'}
      </tr>`)).join('')}</tbody></table></div>`
      : emptyState('hub', 'Nothing is registered', 'Each service registers itself with Consul at start-up.');
  }

  async function loadContainers() {
    const box = $('#pf-containers');
    const r = await api('/console/api/platform/containers');
    if (!box.isConnected) return;
    if (!r.ok) { box.innerHTML = errorBanner(errorText(r), 'pf-ct-retry'); $('#pf-ct-retry').onclick = loadContainers; return; }
    const stateTag = (c) => `<span class="tag ${c.state === 'running' ? (c.health && c.health !== 'healthy' ? 'warn' : 'ok') : 'bad'}">${esc(c.state)}${c.health ? ` · ${esc(c.health)}` : ''}</span>`;
    box.innerHTML = `<div class="table-wrap"><table class="data">
      <thead><tr><th>Service</th><th>State</th><th>Image</th><th>Published ports</th><th></th></tr></thead>
      <tbody>${r.data.containers.map((c) => `<tr>
        <td><div class="cell-title">${esc(c.service)}</div><div class="cell-sub mono">${esc(c.name)}</div></td>
        <td>${stateTag(c)}<div class="cell-sub">${esc(c.status)}</div></td>
        <td class="mono">${esc(c.image)}<div class="cell-sub">${esc(c.imageId)}</div></td>
        <td class="mono body-small">${c.ports.map(esc).join('<br>') || '<span class="muted">internal only</span>'}</td>
        <td class="nowrap">${r.data.controllable.includes(c.service)
          ? (c.state === 'running'
            ? `<button class="btn btn-danger-text" data-ct="${esc(c.service)}" data-verb="stop">${icon('stop_circle')}Stop</button>`
            : `<button class="btn btn-tonal" data-ct="${esc(c.service)}" data-verb="start">${icon('play_circle')}Start</button>`)
          : ''}</td>
      </tr>`).join('')}</tbody></table></div>`;
    $$('[data-ct]', box).forEach((b) => {
      b.onclick = async () => {
        const { ct, verb } = b.dataset;
        if (verb === 'stop' && !(await confirmDialog({ title: `Stop ${ct}?`, message: `Runs <span class="mono">docker compose stop ${esc(ct)}</span>. Start it again from this table when you are done.`, confirmLabel: 'Stop', danger: true }))) return;
        b.disabled = true;
        b.innerHTML = `<span class="spinner"></span>${verb === 'stop' ? 'Stopping' : 'Starting'}…`;
        const res = await api(`/console/api/platform/containers/${ct}/${verb}`, { method: 'POST' });
        if (!res.ok) { snackbar(errorText(res)); loadContainers(); return; }
        snackbar(`${ct} ${verb === 'stop' ? 'stopped' : 'started'} in ${res.data.seconds}s.`);
        loadContainers(); loadRegistry(); loadDatabases(); refreshStatus();
      };
    });
  }

  async function loadDatabases() {
    const box = $('#pf-databases');
    const r = await api('/console/api/platform/databases');
    if (!box.isConnected) return;
    if (!r.ok) { box.innerHTML = errorBanner(errorText(r)); return; }
    box.innerHTML = r.data.map((d) => `
      <div class="card outlined stack">
        <div class="card-head" style="margin:0">${icon('database')}<div><div class="title-medium">${esc(d.database)}</div><div class="body-small muted">owned by ${esc(d.service)} · role <span class="mono">${esc(d.role)}</span></div></div></div>
        ${d.error ? errorBanner(d.error)
          : d.tables.map((t) => `<div class="row spread"><span class="mono">${esc(t.table)}</span><span class="body-small muted">${t.rows} rows</span></div>`).join('') || '<div class="muted">No tables yet.</div>'}
      </div>`).join('')
      + `<div class="banner info" style="grid-column:1/-1;margin:0">${icon('info')}<div class="grow">Each service holds only its own table, so no cross-service read is possible: incident-service gets an asset's name by calling asset-service through the circuit breaker, never by reading asset_db.</div></div>`;
  }

  $('#pf-reg-refresh').onclick = loadRegistry;
  $('#pf-ct-refresh').onclick = loadContainers;
  $('#pf-db-refresh').onclick = loadDatabases;
  loadRegistry();
  loadContainers();
  loadDatabases();
}

/* ---------- Security events ---------- */

/**
 * The event-source picker. `withNormal` adds the committed capture of an
 * ordinary workflow, which the rules should raise nothing on; the graph
 * loader does not take it, so its picker leaves it out.
 */
function sourceToggle(id, value, withNormal = false) {
  const sources = [
    ['capture', 'inventory_2', 'Captured attack'],
    ...(withNormal ? [['normal', 'verified_user', 'Normal workflow']] : []),
    ['live', 'sensors', 'Live stack logs'],
  ];
  return `<div class="segmented" id="${id}" role="group" aria-label="Event source">
    ${sources.map(([key, glyph, label]) => `<button data-src="${key}" class="${value === key ? 'selected' : ''}">${icon(glyph, 'icon-sm')}${label}</button>`).join('')}
  </div>`;
}

async function renderEvents(el) {
  const filter = { source: 'capture', eventType: '', service: '', user: '', correlationId: '', ...state.eventFilter };
  state.eventFilter = {};
  el.innerHTML = `
    <p class="page-intro">The security event stream the SOC collector reads: one structured event per request, auth decision and inter-service call, in the schema Phase 2 consumes. <b>Captured attack</b> is the committed file <span class="mono">docs/evidence/step15-attack-events.jsonl</span> and needs no Docker. <b>Normal workflow</b> is <span class="mono">step12-correlated-logs.jsonl</span>, an ordinary business workflow the rules should stay quiet on. <b>Live stack logs</b> reads <span class="mono">docker compose logs</span>.</p>
    <div class="section-head">
      ${sourceToggle('ev-src', filter.source, true)}
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
        ${sourceToggle('al-src', view.source, true)}
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
    ].map(([k, v]) => `<span class="tag info">${k}: ${v}</span>`).join('')}${d.alertsRaised
      ? '<span class="tag ok">every related event resolves</span>'
      : '<span class="tag ok">no alerts: the rules stay quiet on this traffic</span>'}</div>`;
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
      <div class="section-head"><h2 class="title-large">Alert neighbourhood</h2>
        <div class="field compact" style="min-width:min(100%,360px)"><select id="g-nb-alert" aria-label="Alert to draw"><option>Loading alerts…</option></select></div></div>
      <p class="page-intro" style="margin-bottom:12px">One alert and everything around it: the events that raised it and the users behind them, the ATT&amp;CK technique it indicates, and that technique's controls, runbooks, target service and vulnerabilities. This is the chain the GraphRAG answer walks.</p>
      <div id="g-nb"><div class="progress"></div></div>
      <div id="g-nb-detail" class="section"></div>
    </div>
    <div class="section">
      <div class="section-head"><h2 class="title-large">Demonstrated queries</h2></div>
      <div class="grid grid-auto" id="g-queries"></div>
      <div id="g-run" class="section"></div>
    </div>`;

  let services = ['auth-service', 'incident-service', 'asset-service'];
  let loadSource = 'capture';

  async function loadNeighbourhoodPicker() {
    const select = $('#g-nb-alert');
    const alerts = await loadGraphAlerts(true);
    if (!select.isConnected) return;
    if (!alerts || !alerts.length) {
      select.innerHTML = '<option>No alerts in the graph</option>';
      $('#g-nb').innerHTML = emptyState('hub', alerts ? 'The graph holds no alert yet' : 'Neo4j is not reachable', alerts ? 'Load the graph above.' : 'Start the stack, then reload this screen.');
      return;
    }
    const preferred = alerts.find((a) => a.ruleName === 'Multiple Failed Logins') || alerts[0];
    select.innerHTML = alerts.map((a) => `<option value="${esc(a.alertId)}"${a === preferred ? ' selected' : ''}>${esc(a.ruleName)} · ${esc(a.alertId)}</option>`).join('');
    select.onchange = () => drawNeighbourhood(select.value);
    drawNeighbourhood(preferred.alertId);
  }

  async function drawNeighbourhood(alertId) {
    const box = $('#g-nb');
    box.innerHTML = '<div class="progress"></div>';
    $('#g-nb-detail').innerHTML = '';
    const r = await api(`/console/api/graph/neighbourhood?alertId=${encodeURIComponent(alertId)}`);
    if (!box.isConnected) return;
    if (!r.ok) { box.innerHTML = errorBanner(errorText(r)); return; }
    const render = (selectedId) => {
      box.innerHTML = neighbourhoodSvg(r.data, selectedId);
      $$('[data-node]', box).forEach((g) => {
        const open = () => { render(g.dataset.node); showNode(r.data.nodes.find((n) => n.id === g.dataset.node)); };
        g.onclick = open;
        g.onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } };
      });
    };
    render(r.data.centre);
    showNode(r.data.nodes.find((n) => n.id === r.data.centre));
  }

  function showNode(node) {
    const shown = Object.entries(node.properties).filter(([, v]) => v !== null && v !== '' && !(Array.isArray(v) && !v.length));
    $('#g-nb-detail').innerHTML = `
      <div class="card outlined stack">
        <div class="row"><span class="tag" style="background:${nodeColour(node.label)};color:var(--md-surface)">${esc(node.label)}</span><span class="title-medium">${esc(node.caption)}</span></div>
        ${kv(shown.map(([k, v]) => [k, Array.isArray(v) ? v.map((x) => `<span class="tag" style="margin:0 4px 4px 0">${esc(x)}</span>`).join('') : SEVERITIES.includes(v) ? sevTag(v) : esc(v)]))}
      </div>`;
  }

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
    loadNeighbourhoodPicker();
  };
  loadSummary();
  loadQueries();
  loadNeighbourhoodPicker();
}

/* ---------- Alert neighbourhood picture ---------- */

const NODE_COLOURS = {
  Alert: 'var(--node-alert)', Threat: 'var(--node-threat)', Control: 'var(--node-control)',
  Document: 'var(--node-document)', Event: 'var(--node-event)', User: 'var(--node-user)',
  Service: 'var(--node-service)',
};
const nodeColour = (label) => NODE_COLOURS[label] || 'var(--node-other)';
const clip = (text, n) => (text.length > n ? `${text.slice(0, n - 1)}…` : text);

/**
 * A layered drawing of an alert's neighbourhood, read left to right as the
 * chain the GraphRAG answer walks:
 *
 *   User -> Events -> Alert -> Threat -> Controls / runbooks / vulnerabilities / service
 *
 * One column per step, nodes evenly spaced, links as curves, and each gap
 * named once by its relationship type instead of a label on every line. Only
 * the last gap mixes types, so only its links are labelled individually.
 * Deterministic, so the same graph always draws the same picture - which
 * matters on a recording.
 */
function neighbourhoodSvg(data, selectedId) {
  const COLUMN_OF = { User: 0, Event: 1, Incident: 1, Alert: 2, Threat: 3 };
  const X = [70, 255, 450, 640, 800];
  const ROW = 66; const TOP = 70; const R = 14;
  const LAST_ORDER = ['Control', 'Document', 'Vulnerability', 'Service', 'Threat'];
  const byId = Object.fromEntries(data.nodes.map((n) => [n.id, n]));
  // Only the technique the alert INDICATES sits in the threat column; its
  // sub-techniques are things it links to, so they join the last column.
  const indicated = new Set(data.links
    .filter((l) => l.source === data.centre || l.target === data.centre)
    .flatMap((l) => [l.source, l.target]));
  const columnOf = (n) => {
    if (n.id === data.centre) return 2;
    if (n.label === 'Threat' && !indicated.has(n.id)) return 4;
    return COLUMN_OF[n.label] ?? 4;
  };

  const columns = [[], [], [], [], []];
  data.nodes.forEach((n) => columns[columnOf(n)].push(n));
  const rank = (n) => { const i = LAST_ORDER.indexOf(n.label); return i === -1 ? LAST_ORDER.length : i; };
  columns.forEach((col) => col.sort((a, b) => rank(a) - rank(b)
    || String(a.properties.timestamp || a.caption).localeCompare(String(b.properties.timestamp || b.caption))));

  const tallest = Math.max(...columns.map((c) => c.length), 1);
  const H = TOP + tallest * ROW + 10;
  const W = 1010;
  const pos = {};
  columns.forEach((col, c) => {
    const offset = TOP + ((tallest - col.length) * ROW) / 2;
    col.forEach((n, i) => { pos[n.id] = { x: X[c], y: offset + i * ROW + ROW / 2 - 10, column: c }; });
  });

  // Name each of the first three gaps once, by the relationship types crossing it.
  const headers = [0, 1, 2].map((gap) => {
    const types = [...new Set(data.links
      .filter((l) => Math.min(pos[l.source].column, pos[l.target].column) === gap
        && Math.abs(pos[l.source].column - pos[l.target].column) === 1)
      .map((l) => l.type))];
    return types.length ? `<text class="link-label" x="${(X[gap] + X[gap + 1]) / 2}" y="30" text-anchor="middle">${esc(types.join(' · '))}</text>` : '';
  }).join('');

  const links = data.links.map((l) => {
    let a = pos[l.source]; let b = pos[l.target];
    if (a.x > b.x) [a, b] = [b, a];
    const mid = (a.x + b.x) / 2;
    const lastGap = b.column === 4 && a.column === 3;
    return `<g><title>${esc(byId[l.source].caption)} -[:${esc(l.type)}]-> ${esc(byId[l.target].caption)}</title>
      <path class="link" fill="none" d="M${a.x} ${a.y} C${mid} ${a.y}, ${mid} ${b.y}, ${b.x} ${b.y}"/>
      ${lastGap ? `<text class="link-label" x="${b.x - R - 6}" y="${b.y - 6}" text-anchor="end">${esc(l.type)}</text>` : ''}</g>`;
  }).join('');

  const nodes = data.nodes.map((n) => {
    const p = pos[n.id]; const centre = n.id === data.centre; const r = centre ? R + 8 : R;
    const right = p.column === 4;
    const tx = right ? p.x + r + 8 : p.x;
    const ty = right ? p.y - 2 : p.y + r + 13;
    const anchor = right ? 'start' : 'middle';
    return `<g class="node${n.id === selectedId ? ' selected' : ''}" data-node="${esc(n.id)}" tabindex="0" role="button" aria-label="${esc(n.label)} ${esc(n.caption)}">
      <title>${esc(n.label)}: ${esc(n.caption)}</title>
      <circle cx="${p.x}" cy="${p.y}" r="${r}" fill="${nodeColour(n.label)}"/>
      <text class="node-label" x="${tx}" y="${ty}" text-anchor="${anchor}">${esc(n.label)}</text>
      <text x="${tx}" y="${ty + 13}" text-anchor="${anchor}">${esc(clip(n.caption, right ? 28 : 20))}</text>
    </g>`;
  }).join('') + headers;
  const labels = [...new Set(data.nodes.map((n) => n.label))];
  return `<div class="graph-wrap">
    <div class="graph-scroll"><svg class="graph-svg" viewBox="0 0 ${W} ${H}" role="group" aria-label="Graph neighbourhood of the selected alert">${links}${nodes}</svg></div>
    <div class="legend">${labels.map((l) => `<span class="legend-item"><span class="legend-swatch" style="background:${nodeColour(l)}"></span>${esc(l)}</span>`).join('')}
      <span class="legend-item">${data.nodes.length} nodes · ${data.links.length} relationships · click a node for its properties</span></div>
  </div>`;
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
    // The two refusals from the Phase 2 demo script: one the retriever does
    // not understand, and one it understands but the graph holds nothing for.
    const refusals = [
      'What is the weather in Potchefstroom?',
      'Why was alert alt-ffffffffffff created?',
    ];
    const chips = (list, glyph) => list.map((s) => `<button class="chip" type="button" data-question="${esc(s)}">${icon(glyph)}${esc(s)}</button>`).join('');
    $('#ask-suggest').innerHTML = chips(suggestions, 'lightbulb')
      + `<div class="label-small muted" style="flex-basis:100%;margin-top:8px">Questions the graph cannot answer, which it refuses rather than guesses</div>`
      + chips(refusals, 'block')
      + (alerts ? '' : `<span class="body-small muted">Neo4j is not reachable, so answers are unavailable until the stack is up.</span>`);
    $$('#ask-suggest .chip').forEach((c) => { c.onclick = () => { textarea.value = c.dataset.question; $('#ask-form').requestSubmit(); }; });
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
  demo: { title: 'Demo guide', render: renderDemo },
  platform: { title: 'Platform', render: renderPlatform },
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
