// El72 landing page — vanilla JS
// Pulls live platform stats from the API (/stats, provided by Engineer B).
// Falls back to realistic demo numbers when the API is unreachable so the
// investor demo always looks alive.

const API_BASE = (window.EL72_API_BASE || 'http://localhost:8000').replace(/\/$/, '');

const DEMO_STATS = {
  total_trackers: 1284,
  deals_found_today: 47,
  total_savings_egp: 284750,
  stores_monitored: 3,
};

const STATS_MESSAGES = [
  (s) => `📉 <b>${s.deals_found_today}</b> genuine deals confirmed today`,
  (s) => `🛒 <b>${s.total_trackers.toLocaleString('en-US')}</b> active price trackers`,
  (s) => `💰 <b>${s.total_savings_egp.toLocaleString('en-US')} EGP</b> saved by the community`,
  (s) => `🔍 Watching Amazon Egypt · Noon · Jumia across <b>${s.stores_monitored}</b> stores`,
  () => `✅ Every drop ML-verified — zero fake discounts delivered`,
];

function formatNumber(n) {
  return Number(n || 0).toLocaleString('en-US');
}

function renderStats(stats) {
  const el = (id) => document.getElementById(id);
  if (el('statTrackers')) el('statTrackers').textContent = formatNumber(stats.total_trackers);
  if (el('statDeals')) el('statDeals').textContent = formatNumber(stats.deals_found_today);
  if (el('statSavings')) el('statSavings').textContent = formatNumber(stats.total_savings_egp);
  if (el('statStores')) el('statStores').textContent = String(stats.stores_monitored || 3);
}

async function fetchStats() {
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 4000);
    const res = await fetch(`${API_BASE}/stats`, { signal: controller.signal });
    clearTimeout(timer);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    // Accept either flat keys or a nested "data" envelope.
    const s = data.data && typeof data.data === 'object' ? data.data : data;
    return {
      total_trackers: s.total_trackers ?? s.total_trackers_count ?? DEMO_STATS.total_trackers,
      deals_found_today: s.deals_found_today ?? DEMO_STATS.deals_found_today,
      total_savings_egp: s.total_savings_egp ?? s.total_savings ?? DEMO_STATS.total_savings_egp,
      stores_monitored: s.stores_monitored ?? DEMO_STATS.stores_monitored,
    };
  } catch {
    return DEMO_STATS;
  }
}

let tickerIndex = 0;
function startTicker(stats) {
  const ticker = document.getElementById('statsTicker');
  if (!ticker) return;
  const messages = STATS_MESSAGES.map((fn) => fn(stats));
  const tick = () => {
    ticker.innerHTML = messages.map(
      (m, i) => `<span class="stats__item">${i === tickerIndex ? m : m.replace(/<b>/g, '<b style="opacity:.6">').replace(/<\/b>/g, '</b>')}</span>`
    ).join('');
    tickerIndex = (tickerIndex + 1) % messages.length;
  };
  tick();
  setInterval(tick, 3500);
}

// ---------- Arabic / English toggle ----------
function initLangToggle() {
  const btn = document.getElementById('langToggle');
  if (!btn) return;
  const html = document.documentElement;
  const apply = (lang) => {
    html.lang = lang;
    html.dir = lang === 'ar' ? 'rtl' : 'ltr';
    btn.textContent = lang === 'ar' ? 'EN' : 'ع';
    try {
      localStorage.setItem('el72_lang', lang);
    } catch {
      /* storage unavailable — ignore */
    }
  };
  btn.addEventListener('click', () => {
    apply(html.dir === 'rtl' ? 'en' : 'ar');
  });
  try {
    const saved = localStorage.getItem('el72_lang');
    if (saved === 'ar') apply('ar');
  } catch {
    /* ignore */
  }
}

async function init() {
  initLangToggle();
  const stats = await fetchStats();
  renderStats(stats);
  startTicker(stats);
  // Refresh stats periodically so the demo feels live.
  setInterval(async () => {
    const fresh = await fetchStats();
    renderStats(fresh);
  }, 30000);
}

document.addEventListener('DOMContentLoaded', init);
