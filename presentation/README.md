# El72 — Real-Time Price Intelligence — Investor / Product Deck

**Apple-quality, fully-offline presentation package.** Everything here runs from
`file://` with **no network**. The deck tells the El72 / Elhaq story: real-time
price tracking and deal detection for Egypt — scrape → detect → score →
deliver. The accent is **orange** (`#f7941d`), matching the El72 logo.

> **Data note:** every metric in the deck is a **placeholder**, clearly labelled
> as such on-slide. Before presenting, swap in your real numbers (see
> `EL72_ADAPTATION_PLAN.md` for the source files they map to).

---

## What's in this folder

| Path | What it is |
|------|-----------|
| `index.html` | **The deck** — 23 slides, Apple dark theme, orange accent. Opens on a 13-second El72 motion intro, the charts animate in, and the demo slide embeds the live El72 app (recorded-hybrid: swap the iframe for a pre-recorded clip of the scrape → detect → WhatsApp flow). The last slide introduces the three-person team (headshots in `assets/team/`). |
| `css/apple-theme.css` | Apple design language (SF Pro, `#000`/`#f5f5f7`/`#f7941d`, hairlines). |
| `js/deck.js` | Minimal offline slide engine (keyboard + click + hash nav). |
| `js/data.js` | Embeds the (placeholder) volume + detection data and renders the two charts. |
| `js/motion.js` | Scroll-linked GSAP motion for the slides. |
| `js/demo.js` | Drives the two embedded slides: the intro composition and the live El72 demo. |
| `intro/` | The 13-second El72 motion intro (GSAP + HyperFrames). |
| `fallback/replay.html` | **The fallback** — self-contained animated replay of one full El72 loop (scrape → detect → score → deliver, ~40s). No server, no network. |
| `rehearsal.md` | **The day-of run book** — pre-flight, venue setup, timed run-of-show, demo script, cut-to-fallback triggers, recovery, Q&A cards. |
| `strategy.md` | The strategy: 23-slide structure, the two killer objection slides, the numbers story, timed script, Q&A prep, contingency. |
| `assets/el72-logo.svg` | The El72 mark (orange gradient). |
| `assets/el72-pipeline.svg` | The scrape → store → alert pipeline diagram. |
| `assets/el72-intelligence.svg` | The cross-store / B2B intelligence diagram. |
| `assets/team/` | Team headshots (samir.jpg, hany.jpg, loay.jpg). |
| `EL72_ADAPTATION_PLAN.md` | The adaptation plan + the decisions (accent, team, demo, data). |
| `companion-ml-verification.html` | **Companion deep-dive** — 8 slides on "how do you know a deal is real?" (the ML verification engine). Same template & engine, no charts. Standalone. |

---

## The 23-slide spine

1. Cold open — "It takes **30 seconds**."
2. The graveyard of stale prices.
3. **El72** — real-time price intelligence (logo).
4. Intro (13s motion).
5. The reveal — one pipeline.
6. **Live demo** (recorded-hybrid).
7. Proof — one real drop, caught and graded.
8. Proof at scale — the volume + detection charts.
9. **Trust, made real** — fake discounts, caught.
10. Why not a comparison tool.
11. **vs. the field** — the three objections, answered.
12. How it works — the pipeline.
13. Where the intelligence sits.
14. Anomaly detection (MAD + Isolation Forest).
15. Deal scoring (92/100).
16. Fake-discount detection.
17. Cross-store intelligence.
18. The business case.
19. **Cost & trust** — ~$0.0036 per alert.
20. **The numbers** — placeholder, labelled.
21. Roadmap.
22. Close.
23. The team (3 people).

---

## Run it

Open `index.html` directly (`file://`) — it's fully offline. For the live demo
slide, serve over `http://localhost` and start the El72 app so the frame can
load (a `file://` deck can't carry a sign-in into the frame).

To replace the placeholder numbers, edit `js/data.js` (the `VOLUME` and
`DETECTION` arrays and the captions) and the static numbers in `index.html`.
