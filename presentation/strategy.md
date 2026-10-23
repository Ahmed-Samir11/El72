# El72 Deck — Strategy

The investor/product story for **El72 / El72**: real-time price tracking and
deal detection for Egypt. The deck is 24 slides, one idea per slide, Apple dark
theme with an **orange** accent. Runtime ≈ 12–14 minutes + Q&A.

**The through-line:** the market is full of fake discounts; El72 verifies every
price, finds the real deals, filters the fake ones, and delivers them in
seconds — on your infrastructure, at near-zero cost.

---

## The 24-slide spine (with the job of each)

| # | Slide | Job |
|---|-------|-----|
| 1 | Cold open — "It takes **30 seconds**." | Hook: the speed claim, no product name yet. |
| 2 | The graveyard of stale prices | The problem, made visceral. |
| 3 | **El72** (logo) | Name + one-liner + trust line. |
| 4 | Intro (13s motion) | The loop in motion: wall → sweep → 30s → speed → impact → alert → brand. |
| 5 | The reveal — one pipeline | The architecture in one line. |
| 6 | **Live demo** (recorded-hybrid) | Show it: scrape → detect → deal → WhatsApp. |
| 7 | Proof — one real drop | A concrete example, graded. |
| 8 | Proof at scale | The two charts (volume + detection) — placeholder, labelled. |
| 9 | **Trust, made real** | Fake discounts, caught — the trust problem solved. |
| 10 | Why not a comparison tool | Objection #1: "just compare prices." |
| 11 | **vs. the field** | Objections #2 and #3, answered. |
| 12 | How it works | The pipeline diagram. |
| 13 | Where the intelligence sits | The four engines in the analyzer. |
| 14 | Anomaly detection | MAD + Isolation Forest, in plain English. |
| 15 | Deal scoring | The 0–100 score → DEAL/WATCH/IGNORE. |
| 16 | Fake-discount detection | The 4 checks that catch bait-and-switch. |
| 17 | Cross-store intelligence | Cheapest of N stores + B2B signals. |
| 18 | The business case | Why it wins on every axis. |
| 19 | **Cost & trust** | ~$0.0036/alert + the trust line. |
| 20 | **The numbers** | The placeholder metrics, labelled. |
| 21 | Roadmap | Where it's going. |
| 22 | Close | The ask / the vision. |
| 23 | The team (3 people) | Ahmed Samir, Mohammed Hany, Loay Medhat. |

---

## The two killer objection slides

- **Slide 10 — "Why not a comparison tool?"** A comparison tool shows you three
  prices. It doesn't tell you which is real, which is a fake "was" price, or
  which is the cheapest *right now*. El72 verifies before it alerts.
- **Slide 11 — "vs. the field"** The three objections, answered:
  1. *"Just scrape and compare."* → Stale prices and fake discounts make
     naive comparison useless. El72 detects anomalies and grades deals.
  2. *"Why not a generic price tracker?"* → Generic trackers don't do
     cross-store intelligence, B2B signals, or fake-discount filtering.
  3. *"Why not just use the store's own deal page?"* → Deal pages are
     self-reported and gameable. El72 verifies against history.

---

## The numbers story

All numbers are **placeholders**, labelled on-slide. Before presenting, replace
them with real values from:
- `services/analyzer/deal_scorer.py` — deal score distribution.
- `services/analyzer/fake_discount.py` — fake-discount catch rate.
- `services/analyzer/cross_store.py` — cross-store coverage.
- `services/analyzer/ml_detector.py` — anomaly detection precision.
- `docs/platform_metrics.md` — volume, latency, cost.

The one number to lead with: **~$0.0036 per alert** (WhatsApp utility rate).

---

## Timed script (≈ 13 min)

- 0:00–0:40 — cold open + graveyard (slides 1–2).
- 0:40–1:30 — title + intro (slides 3–4).
- 1:30–2:00 — reveal (slide 5).
- 2:00–4:00 — **demo** (slide 6) — narrate the recorded clip.
- 4:00–5:30 — proof + scale (slides 7–8).
- 5:30–7:00 — trust + objections (slides 9–11).
- 7:00–9:30 — how it works + the four engines (slides 12–17).
- 9:30–11:00 — business case + cost + numbers (slides 18–20).
- 11:00–12:00 — roadmap + close (slides 21–22).
- 12:00+ — team + Q&A (slide 24).

---

## Q&A prep (top questions)

- **How do you catch fake discounts?** The 4 checks in `fake_discount.py`:
  price-below-baseline, fake "was" price, spike-then-drop, too-good-to-be-true.
- **How accurate is the deal score?** Placeholder — replace with the real
  precision/recall from `deal_scorer.py` tests.
- **What's the cost per user?** ~$0.0036 per WhatsApp alert (utility rate).
- **What's the moat?** The cross-store + B2B intelligence layer and the
  fake-discount filtering — not the scraping.
- **Can it scale to more stores?** Yes — the scraper is pluggable; the
  analyzer is store-agnostic.
- **What's the data like?** TimescaleDB time-series; 30s scrape interval.

---

## Contingency

- If the live demo fails, cut to `fallback/replay.html` (self-contained,
  ~40s, no network).
- If the charts don't render, the static captions carry the numbers.
- If asked for a number you haven't verified, say it's a placeholder and
  point to the source file.
