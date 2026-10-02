/* ═══════════════════════════════════════════════════════════════════════
   app.js — Locksmith Ad Killer Frontend Logic
   Talks to the Python backend via pywebview's js_api bridge
═══════════════════════════════════════════════════════════════════════ */

// ── State ──────────────────────────────────────────────────────────────
let pollInterval    = null;
let logPollInterval = null;
let prevClicks      = 0;
let allLogs         = [];
let keywords        = [];
let currentConfig   = null;

// ── Tab Switching ──────────────────────────────────────────────────────
function showTab(name) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  document.getElementById(`tab-${name}`).classList.add('active');
  document.getElementById(`nav-${name}`).classList.add('active');

  if (name === 'settings') loadSettings();
}

// ── Initialise on page load ────────────────────────────────────────────
window.addEventListener('pywebviewready', () => {
  startPolling();
  startLogPolling();
  loadSettings();
});

// Fallback for development preview in browser
if (typeof pywebview === 'undefined') {
  window.pywebview = { api: mockAPI() };
  startPolling();
  startLogPolling();
  loadSettings();
}

// ── Status Polling (every second) ─────────────────────────────────────
function startPolling() {
  pollInterval = setInterval(refreshStatus, 1000);
  refreshStatus();
}

async function refreshStatus() {
  try {
    const data = await pywebview.api.get_status();
    renderStatus(data);
  } catch (e) { /* silent */ }
}

function renderStatus(data) {
  const { stats, activity_log, bot_running } = data;

  // Status pill + dot
  const dot   = document.getElementById('status-dot');
  const label = document.getElementById('status-label');
  const pill  = document.getElementById('status-pill');

  dot.className = 'status-dot';
  if (stats.status === 'running') {
    dot.classList.add('running');
    label.textContent = 'Running';
    pill.style.borderColor = 'rgba(0,230,118,0.25)';
    pill.style.color = 'var(--accent-green)';
  } else if (stats.status === 'error') {
    dot.classList.add('error');
    label.textContent = 'Error';
    pill.style.borderColor = 'rgba(255,71,87,0.25)';
    pill.style.color = 'var(--accent-red)';
  } else {
    label.textContent = 'Stopped';
    pill.style.borderColor = '';
    pill.style.color = 'var(--text-secondary)';
  }

  // Stat counters — animate on change
  animateCounter('stat-total-clicks', stats.total_clicks);
  animateCounter('stat-cycles',       stats.cycles_done);
  animateCounter('stat-ads-found',    stats.ads_found);

  // Next cycle countdown
  const nextEl = document.getElementById('stat-next-cycle');
  if (stats.next_cycle_secs > 0 && bot_running) {
    const m = Math.floor(stats.next_cycle_secs / 60);
    const s = stats.next_cycle_secs % 60;
    nextEl.textContent = `${m}:${String(s).padStart(2,'0')}`;
  } else {
    nextEl.textContent = bot_running ? 'Now' : '—';
  }

  // Keyword
  const kwEl = document.getElementById('current-keyword');
  if (stats.current_keyword) kwEl.textContent = stats.current_keyword;

  // Proxy IP
  const ipEl = document.getElementById('current-ip');
  if (stats.current_ip && stats.current_ip !== '—') {
    ipEl.textContent = `${stats.current_ip} 🇬🇧`;
  }

  // Button states
  const btnStart = document.getElementById('btn-start');
  const btnStop  = document.getElementById('btn-stop');
  btnStart.disabled = bot_running;
  btnStop.disabled  = !bot_running;

  // Activity feed
  renderActivityFeed(activity_log);
}

// Counter animation
const displayedValues = {};
function animateCounter(id, target) {
  const el = document.getElementById(id);
  if (!el) return;
  const current = displayedValues[id] || 0;
  if (current === target) return;

  const diff  = target - current;
  const step  = Math.ceil(Math.abs(diff) / 10);
  const dir   = diff > 0 ? 1 : -1;
  let   val   = current;

  const timer = setInterval(() => {
    val += dir * step;
    if ((dir > 0 && val >= target) || (dir < 0 && val <= target)) {
      val = target;
      clearInterval(timer);
    }
    el.textContent = val.toLocaleString();
    displayedValues[id] = val;
  }, 40);
}

// ── Activity Feed ──────────────────────────────────────────────────────
function renderActivityFeed(entries) {
  const feed      = document.getElementById('activity-feed');
  const countEl   = document.getElementById('activity-count');

  if (!entries || entries.length === 0) {
    feed.innerHTML = `
      <div class="activity-empty">
        <span class="empty-icon">🕐</span>
        <p>Waiting for bot to start...</p>
      </div>`;
    countEl.textContent = '0 cycles';
    return;
  }

  countEl.textContent = `${entries.length} cycle${entries.length !== 1 ? 's' : ''}`;

  feed.innerHTML = entries.map(e => `
    <div class="activity-item">
      <span class="activity-time">${e.time}</span>
      <span class="activity-icon">${e.clicked > 0 ? '✅' : '⚪'}</span>
      <div class="activity-body">
        <div class="activity-keyword">${e.keyword}</div>
        <div class="activity-detail">Cycle #${e.cycle}</div>
      </div>
      <div class="activity-pills">
        <span class="pill pill-blue">🎯 ${e.found} found</span>
        <span class="pill pill-green">🖱️ ${e.clicked} clicked</span>
      </div>
    </div>
  `).join('');
}

// ── Log Polling ────────────────────────────────────────────────────────
function startLogPolling() {
  logPollInterval = setInterval(fetchLogs, 1500);
}

async function fetchLogs() {
  try {
    const messages = await pywebview.api.get_logs();
    if (!messages || messages.length === 0) return;

    const container = document.getElementById('log-container');
    const wasAtBottom = container.scrollHeight - container.scrollTop <= container.clientHeight + 20;

    // Remove empty placeholder
    const empty = container.querySelector('.log-empty');
    if (empty) empty.remove();

    messages.forEach(msg => {
      allLogs.push(msg);
      const div = document.createElement('div');
      div.className = `log-line ${msg.level}`;
      div.textContent = msg.message;
      container.appendChild(div);
    });

    // Keep last 500 lines
    while (container.children.length > 500) {
      container.removeChild(container.firstChild);
    }

    if (wasAtBottom) {
      container.scrollTop = container.scrollHeight;
    }
  } catch (e) { /* silent */ }
}

function clearLogs() {
  allLogs = [];
  document.getElementById('log-container').innerHTML =
    '<div class="log-empty">Logs cleared.</div>';
}

// ── Bot Controls ───────────────────────────────────────────────────────
async function startBot() {
  const noProxy = document.getElementById('chk-no-proxy').checked;
  try {
    const result = await pywebview.api.start_bot(noProxy);
    if (!result.ok) alert(result.msg);
  } catch (e) { alert('Failed to start bot: ' + e); }
}

async function stopBot() {
  try {
    await pywebview.api.stop_bot();
  } catch (e) { alert('Failed to stop bot: ' + e); }
}

// ── Settings ───────────────────────────────────────────────────────────
async function loadSettings() {
  try {
    const result = await pywebview.api.get_config();
    if (!result.ok) { console.warn(result.msg); return; }
    currentConfig = result.config;

    const p = result.config.proxy;
    const s = result.config.search;

    setVal('s-proxy-host',     p.host     || '');
    setVal('s-proxy-port',     p.port     || 7777);
    setVal('s-proxy-country',  p.country  || 'GB');
    setVal('s-proxy-username', p.username || '');
    setVal('s-proxy-password', p.password || '');
    setVal('s-proxy-city',     p.city     || 'cheltenham');

    // Proxy enabled toggle (default ON if not set)
    const proxyEnabled = p.enabled !== false;
    const chk = document.getElementById('chk-use-proxy');
    if (chk) { chk.checked = proxyEnabled; }
    toggleProxyFields();

    const interval = s.cycle_interval_minutes || 20;
    setVal('s-interval', interval);
    document.getElementById('interval-display').textContent = interval;

    keywords = [...(s.keywords || [])];
    renderKeywords();
  } catch (e) { console.warn('Could not load config:', e); }
}

function setVal(id, val) {
  const el = document.getElementById(id);
  if (el) el.value = val;
}

function renderKeywords() {
  const list = document.getElementById('keyword-list');
  list.innerHTML = keywords.map((kw, i) => `
    <div class="keyword-item">
      <span class="keyword-item-text">${kw}</span>
      <button class="keyword-delete" onclick="removeKeyword(${i})" title="Remove">✕</button>
    </div>
  `).join('');
}

function addKeyword() {
  const input = document.getElementById('new-keyword-input');
  const kw    = input.value.trim();
  if (!kw) return;
  if (keywords.includes(kw)) { input.value = ''; return; }
  keywords.push(kw);
  input.value = '';
  renderKeywords();
}

// Allow Enter key in keyword input
document.addEventListener('DOMContentLoaded', () => {
  const inp = document.getElementById('new-keyword-input');
  if (inp) inp.addEventListener('keydown', e => { if (e.key === 'Enter') addKeyword(); });
});

function removeKeyword(i) {
  keywords.splice(i, 1);
  renderKeywords();
}

async function saveSettings() {
  if (!currentConfig) return;

  const updated = JSON.parse(JSON.stringify(currentConfig));

  updated.proxy.host     = document.getElementById('s-proxy-host').value.trim();
  updated.proxy.port     = parseInt(document.getElementById('s-proxy-port').value) || 7777;
  updated.proxy.country  = document.getElementById('s-proxy-country').value.trim().toUpperCase() || 'GB';
  updated.proxy.username = document.getElementById('s-proxy-username').value.trim();
  updated.proxy.password = document.getElementById('s-proxy-password').value;
  updated.proxy.city     = document.getElementById('s-proxy-city').value.trim().toLowerCase();
  updated.proxy.enabled  = document.getElementById('chk-use-proxy').checked;

  // Sync dashboard no-proxy toggle
  const dashToggle = document.getElementById('chk-no-proxy');
  if (dashToggle) dashToggle.checked = !updated.proxy.enabled;

  updated.search.cycle_interval_minutes = parseInt(document.getElementById('s-interval').value) || 20;
  updated.search.keywords = [...keywords];

  try {
    const result = await pywebview.api.save_config(updated);
    showSaveMsg(result.ok, result.msg);
  } catch (e) { showSaveMsg(false, 'Error: ' + e); }
}

function showSaveMsg(ok, msg) {
  const el = document.getElementById('save-msg');
  el.textContent = ok ? `✅ ${msg}` : `❌ ${msg}`;
  el.className   = `save-msg ${ok ? 'success' : 'fail'}`;
  el.style.display = 'block';
  setTimeout(() => { el.style.display = 'none'; }, 3500);
}

// ── Proxy Toggle ──────────────────────────────────────────────────────
function toggleProxyFields() {
  const chk       = document.getElementById('chk-use-proxy');
  const fields    = document.getElementById('proxy-fields');
  const noSection = document.getElementById('no-proxy-section');
  const label     = document.getElementById('proxy-toggle-label');
  const dashToggle= document.getElementById('chk-no-proxy');
  const enabled   = chk ? chk.checked : true;

  if (fields)    fields.classList.toggle('disabled', !enabled);
  if (noSection) noSection.style.display = enabled ? 'none' : 'block';
  if (label)     label.textContent = enabled ? 'Proxy ON' : 'Proxy OFF';
  if (dashToggle) dashToggle.checked = !enabled;

  const result = document.getElementById('proxy-result');
  if (result) result.style.display = 'none';
}

// ── Direct Connection Test (no proxy) ─────────────────────────────────
async function testDirect() {
  const btn    = document.getElementById('btn-test-direct');
  const result = document.getElementById('proxy-result');

  btn.classList.add('testing');
  btn.querySelector('span').textContent = '🔄 Testing...';
  result.style.display = 'none';

  try {
    const data = await pywebview.api.test_direct();
    result.style.display = 'block';
    result.textContent   = data.msg;
    result.className     = `proxy-result ${data.ok ? 'success' : 'fail'}`;
  } catch (e) {
    result.style.display = 'block';
    result.textContent   = '❌ Test failed: ' + e;
    result.className     = 'proxy-result fail';
  } finally {
    btn.classList.remove('testing');
    btn.querySelector('span').textContent = '🔗 Test Direct Internet Connection';
  }
}

// ── Proxy Test ─────────────────────────────────────────────────────────
async function testProxy() {
  const btn    = document.getElementById('btn-test-proxy');
  const result = document.getElementById('proxy-result');

  btn.classList.add('testing');
  btn.querySelector('span').textContent = '🔄 Testing...';
  result.style.display = 'none';

  try {
    const data = await pywebview.api.test_proxy();
    result.style.display = 'block';
    result.textContent   = data.msg;
    result.className     = `proxy-result ${data.ok ? 'success' : 'fail'}`;
  } catch (e) {
    result.style.display = 'block';
    result.textContent   = '❌ Test failed: ' + e;
    result.className     = 'proxy-result fail';
  } finally {
    btn.classList.remove('testing');
    btn.querySelector('span').textContent = '🔍 Test Proxy Connection';
  }
}

// ── Mock API for browser testing without Python ────────────────────────
function mockAPI() {
  let clicks = 0, cycles = 0, found = 0, running = false;
  const feed = [];

  setInterval(() => {
    if (!running) return;
    clicks += Math.floor(Math.random() * 4);
    cycles++;
    found += Math.floor(Math.random() * 5);
    feed.unshift({
      time: new Date().toTimeString().slice(0,5),
      keyword: 'Locksmiths Cheltenham',
      found: Math.floor(Math.random()*4)+1,
      clicked: Math.floor(Math.random()*4)+1,
      cycle: cycles,
    });
  }, 5000);

  return {
    get_status: async () => ({
      stats: {
        total_clicks: clicks, cycles_done: cycles,
        ads_found: found, current_keyword: 'Locksmiths Cheltenham',
        current_ip: '82.10.xx.xx', status: running ? 'running' : 'stopped',
        next_cycle_secs: running ? 847 : 0,
      },
      activity_log: feed.slice(0,10),
      bot_running: running,
    }),
    get_logs:   async () => [],
    start_bot:  async () => { running = true;  return { ok: true, msg: 'Started.' }; },
    stop_bot:   async () => { running = false; return { ok: true, msg: 'Stopped.' }; },
    get_config: async () => ({
      ok: true,
      config: {
        proxy: { host:'pr.oxylabs.io', port:7777, username:'', password:'', country:'GB', city:'cheltenham' },
        search: { cycle_interval_minutes: 20, keywords: ['Locksmiths Cheltenham','Emergency locksmith Cheltenham'] },
        behavior: {},
        logging: {},
        browser: {},
      }
    }),
    save_config:  async () => ({ ok: true, msg: 'Settings saved!' }),
    test_proxy:   async () => ({ ok: true, ip: '82.10.12.34', country: 'United Kingdom', city: 'London', msg: '✅ UK Proxy OK! IP: 82.10.12.34 (London, United Kingdom)' }),
  };
}
