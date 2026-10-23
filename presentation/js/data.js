// El72 — platform & detection metrics for the "Proof at Scale" slide.
//
// Numbers from the 90-day seeded validation dataset (seed 7242):
// 12 products · 4 stores · 4,320 observations · 90 days.

const VOLUME = [
  { label: "products",        value: 12,   color: "var(--fg)" },
  { label: "observations(k)", value: 4.3,  color: "var(--fg)" },
  { label: "price drops",     value: 2101, color: "var(--accent)" },
  { label: "hist. lows",      value: 395,  color: "var(--accent)" }
];

const DETECTION = [
  { label: "deals",        value: 4,   color: "var(--good)" },
  { label: "suspicious",   value: 40,  color: "var(--bad)" },
  { label: "hist. lows",   value: 395, color: "var(--accent)" },
  { label: "alerts sent",  value: 4,   color: "var(--good)" }
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
  if (volCap) volCap.textContent = "90-day validation · 12 products · 4,320 observations";
  if (detCap) detCap.textContent = "90-day validation · 4 deals detected · 40 suspicious caught";
}

renderBenchCharts();
