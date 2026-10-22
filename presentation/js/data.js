// El72 — platform & detection metrics for the "Proof at Scale" slide.
//
// ⚠️ PLACEHOLDER DATA. These numbers are illustrative (from a seeded demo
// dataset) and are labelled as placeholder on the slide. Replace them with a
// real capture from services/analyzer (platform_metrics.py, deal_scorer.py,
// fake_discount.py, cross_store.py) before presenting to investors.

const VOLUME = [
  { label: "products",        value: 1240, color: "var(--fg)" },
  { label: "observations(k)", value: 1200, color: "var(--fg)" },
  { label: "price drops",     value: 312,  color: "var(--accent)" },
  { label: "hist. lows",      value: 88,   color: "var(--accent)" }
];

const DETECTION = [
  { label: "deals",        value: 312, color: "var(--good)" },
  { label: "suspicious",   value: 41,  color: "var(--bad)" },
  { label: "hist. lows",   value: 88,  color: "var(--accent)" },
  { label: "alerts sent",  value: 290, color: "var(--good)" }
];

function fmtK(v) {
  return v >= 1000 ? (v / 1000).toFixed(1) + "k" : String(v);
}

// Simple vertical bar chart, heights normalized to the panel max.
function barChartSVG(items) {
  const W = 460, H = 220, pad = 24, base = H - 40;
  const n = items.length;
  const slot = (W - pad * 2) / n;
  const bw = Math.min(slot * 0.5, 64);
  const max = Math.max(...items.map(i => i.value));
  let s = "";
  s += `<line x1="${pad}" y1="${base}" x2="${W - pad}" y2="${base}" stroke="var(--hairline)" stroke-width="1"/>`;
  items.forEach((it, i) => {
    const x = pad + i * slot + (slot - bw) / 2;
    const h = (it.value / max) * (base - 20);
    const y = base - h;
    s += `<rect x="${x}" y="${y}" width="${bw}" height="${h}" fill="${it.color}" opacity="0.92"/>`;
    s += `<text x="${x + bw / 2}" y="${y - 8}" text-anchor="middle" fill="var(--fg)" font-size="15" font-family="var(--mono)" font-weight="700">${fmtK(it.value)}</text>`;
    s += `<text x="${x + bw / 2}" y="${base + 20}" text-anchor="middle" fill="var(--fg-dim)" font-size="12" font-family="var(--sans)">${it.label}</text>`;
  });
  return s;
}

function renderBenchCharts() {
  const vol = document.getElementById("bench-volume-chart");
  const det = document.getElementById("bench-detection-chart");
  const volCap = document.getElementById("bench-volume-cap");
  const detCap = document.getElementById("bench-detection-cap");
  if (vol) vol.innerHTML = barChartSVG(VOLUME);
  if (det) det.innerHTML = barChartSVG(DETECTION);
  if (volCap) volCap.textContent = "placeholder · 1,240 products · 1.2M observations";
  if (detCap) detCap.textContent = "placeholder · 312 deals detected · 41 suspicious caught";
}

renderBenchCharts();
