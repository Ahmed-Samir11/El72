# El72 / Elhaq — Adapting the DevOpsDays deck

**Source:** `presentation copy/` — the "Self-Improving PR Review Agent" (HGM / MergeFlow)
DevOpsDays Cairo 2026 deck. Apple dark theme, 20-slide engine, real-data charts, a
13-second motion intro, a live MergeFlow demo, and a self-contained replay fallback.

**Target:** an investor/audience deck for **Elhaq (El72)** — the real-time price-tracking
& deal-detection platform (Egypt). Same engine, same polish, new theme, new assets,
new story.

This document is the **plan** for the changes. It is grouped by the four axes requested:
**theme, colors, assets, content** — plus the structural/data/demo work those four imply.

---

## 0. Strategy in one paragraph

Keep the *machine* (slide engine `js/deck.js`, motion `js/motion.js`, chart renderer
`js/data.js`, offline `file://` guarantee, the Apple layout system in `css/apple-theme.css`)
and **reskin + rewrite** the *content*. The HGM deck is a research story (ICLR, "the loop
learns from your team"); El72 is a **product + business** story ("we find real deals and
verify them, delivered on WhatsApp, and the data is the moat"). Every HGM slide has a direct
El72 analogue — see the slide map in §4. The single biggest change is the **accent color**
(Apple blue → El72 gold/orange) and the **intro animation** (MergeFlow mark → El72 mark).

---

## 1. Theme

The Apple theme is the asset to *keep*. It is generic and high-quality. Only the brand
specifics change.

- **Keep:** SF Pro system font stack, `#000` base, `#f5f5f7` text, hairline borders, cards,
  the `rise` stagger, progress bar, counter, nav zones, all component classes
  (`.metric-row`, `.proof-*`, `.tech-*`, `.pipeline`, `.roadmap`, `.team`, `.compare`,
  `.principle`, `.arch-compare`). These are content-agnostic.
- **Change:** the accent, the backdrop wash, and the semantic mapping (see §2).
- **Keep the offline guarantee.** The current El72 `presentation/index.html` loads
  Google Fonts + Lucide from a CDN. The Apple deck must **not** adopt that — it is built to
  run from `file://` with **no network** (venue has no internet). So:
  - No `fonts.googleapis.com`, no `unpkg.com/lucide`.
  - Keep the SF Pro / system font stack (already offline-safe).
  - If icons are wanted, **vendor** a small sprite into the folder (or draw marks in inline
    SVG, as the intro already does). Do not add a CDN `<script>`.
- **Reconcile the two existing palettes.** There are two El72 palettes in play:
  - the old `presentation/index.html`: `#070f14` bg, green `#10b981`, gold `#f59e0b`.
  - the logo `logo/El72.svg`: warm gold/orange gradient (`rgb(246,114,21)→rgb(251,215,36)`).
  Pick **one** primary. Recommendation: **gold/orange as the accent** (matches the logo),
  dark near-black base, keep green/red for good/bad. Drop the old green-primary.

---

## 2. Colors

All colors live in `css/apple-theme.css :root` and are duplicated in `intro/index.html :root`.
Change both in lockstep.

| Token | HGM (now) | El72 (proposed) | Rationale |
|---|---|---|---|
| `--bg` | `#000000` | `#050505` (or `#070707`) | near-black, slightly warm |
| `--fg` | `#f5f5f7` | `#f5f5f7` (keep) | — |
| `--fg-dim` | `#a1a1a6` | keep | — |
| `--fg-faint` | `#6e6e73` | keep | — |
| `--accent` | `#0a84ff` (Apple blue) | **`#f59e0b`** (gold) — or `#f7941d` | matches logo |
| `--accent-soft` | `rgba(10,132,255,.16)` | `rgba(245,158,11,.16)` | derived |
| `--good` | `#30d158` | keep (a **real deal** = green) | semantic |
| `--bad` | `#ff453a` | keep (a **fake discount** = red) | semantic |
| `--warn` | `#ffd60a` | keep (suspicious / caution) | semantic |
| backdrop (`html,body` + `body::before`) | violet-navy wash (`#1e1a5c`, cyan+violet radials) | **warm amber wash**: `radial-gradient(... #3a2408 ...)` + faint gold/amber radials | warm, on-brand |
| `.demo-start`, `.loop .node.reward`, `.pipe-stage.us`, `.arch-card.us`, etc. | blue glow `rgba(10,132,255,…)` | gold glow `rgba(245,158,11,…)` | every `accent` reference |
| team `.co-*` brand colors (EFG/HERE/Fawry/Cyshield/DEPI) | per-company hex | **replace** with El72 team/brand set (see §5) | HGM companies |

Concrete edits:
- `css/apple-theme.css`: update the `:root` block, the two `body` background gradients, and
  every literal `rgba(10,132,255, …)` / `#0a84ff` reference (search `0a84ff` and `10, 132, 255`).
- `intro/index.html`: update its own `:root` block **and** the hard-coded gradient stops
  (`#A497FF`, `#22D3EE`, `#6F5CF6`, `#67E8F9`) that build the MergeFlow mark — these must
  become the El72 gold/orange ramp.
- Charts in `js/data.js` use `var(--good)` / `var(--accent)` / `var(--warn)` CSS vars, so
  they recolor automatically — no per-chart edits needed.

---

## 3. Assets

| Asset | Status | Action |
|---|---|---|
| `logo/El72.svg` (+ `El72_framed.svg`) | **Available** | New primary mark. Export a PNG (and keep SVG for inline). Use in title slide + intro + close. |
| `assets/agent-llm-harness.png`, `assets/agent-hgm-loop.png`, `assets/make_hgm_diagram.py` | HGM-specific | **Replace** with an El72 **architecture diagram** (Scraper → Redis Streams → Analyzer/ML → TimescaleDB → WhatsApp). Regenerate with a small script (Pillow/SVG) in the same "two-panel: static pipeline vs. the intelligence layer" style as the HGM pair. |
| `assets/pr196.png` | HGM PR screenshot | **Replace** with a real **fake-discount** artifact: a store's inflated-then-"discounted" price, or screenshots of the dead competitors (Yaoota 503 / Kanbkam). (Repo already has `screenshots/amazon_eg.png`, `elbadrgroup.png` to repurpose.) |
| `assets/team/*.jpg` (samir/hany/loay/emad/yosry) + loose root `*.jpeg`/`MohammadEmad.png` | HGM team headshots | **Replace** with El72 team headshots (5 members, same `assets/team/` layout). Delete the loose root jpegs once moved. |
| `intro/` (HyperFrames composition: `index.html`, `player.js`, `gsap.min.js`, `meta.json`, `hyperframes.json`) | MergeFlow 13s intro | **Rewrite** the beats + mark (see §6). Keep the GSAP engine + player; change copy, stats, and the logo lockup. |
| `fallback/replay.html` | HGM PR-review replay | **Rewrite** as an El72 replay: a price spike → anomaly → deal score → fake-discount check → WhatsApp alert. Keep the self-contained, no-network design. |
| `data/run_data.json` + `js/data.js` | HGM run data + charts | **Replace** with El72 platform metrics / deal data (see §7). |
| `assets/asd.png` | unclear/scratch | Audit; likely remove. |
| `serve.py` | generic static server | **Keep** (offline-safe, disables caching). |

New assets to **produce**:
- El72 mark as PNG (from `logo/El72.svg`) for the title/close slides.
- One architecture diagram (2 panels) to replace the HGM diagram pair.
- One "fake discount" visual for the pain slide (chart or screenshot).
- 5 El72 team headshots.

---

## 4. Content — slide-by-slide map

The HGM arc is: *catch → pain → title → intro → demo → proof → proof@scale → human →
"why not X" → "vs. tools" → how it works → where it sits → 4 technical slides → business →
responsible → numbers → roadmap → close → team.*

El72 keeps the **exact same spine** but swaps the subject from "PR review agent" to
"price-intelligence product." 20 slides.

| # | HGM slide | → El72 slide | New headline / content | Assets / data |
|---|---|---|---|---|
| 1 | Cold open — "The lead quit" | **The fake discount** | Kicker "A story from last week". Headline: **"The 40k 'deal' was 42k."** Pullquote from a burned buyer. Turn: the problem isn't scraping — **it's that nobody verifies the price.** | none |
| 2 | Pain, made real — PR #196 | **The graveyard** | "A typo. No error. The wrong model." → **"Two trackers. Both dead."** Left: the bait-and-switch pattern (inflate → "sale"). Right: Yaoota (503, dead) + Kanbkam (dormant since 2022). Footnote: passive comparison sites failed because they can't see across stores. | fake-discount chart / competitor screenshots |
| 3 | Title | **Title** | Brand: "El72 · Price Intelligence". Headline: **"Seize the deal before it's gone."** Lede: real-time price tracking + AI-verified deals, delivered on WhatsApp. Cred: "Elhaq". | El72 mark |
| 4 | Intro (13s) | **Intro (13s)** | Rebuild beats: (1) a price wall of tracked items, (2) El72 mark + "Verified in seconds, not weeks", (3) business impact (real deals / fewer fake alerts / cost per alert), (4) the WhatsApp alert, (5) El72 logo lockup. | new `intro/` |
| 5 | The reveal (live demo) | **The reveal** | "Watch it work." A live price drop → detected → graded → **WhatsApp alert in seconds**. | none |
| 6 | Live demo (MergeFlow) | **Live demo (El72 app)** | Embed the El72 **Flutter/web dashboard** (or landing page) instead of MergeFlow: a tracker, its price-history chart, a confirmed deal, the WhatsApp alert. Tour: dashboard → price history → deals feed → alert. | rewire `js/demo.js`, `data-app` → El72 URL |
| 7 | The Proof (mutations) | **The proof (real deals)** | "It changed — exactly as you asked." → **"It caught a real deal — and rejected a fake one."** Show 2–3 real examples: a genuine drop (score 80+) and a flagged fake discount (penalty applied). | real deal records (seed/demo data) |
| 8 | Proof at scale (benchmarks) | **Proof at scale (platform metrics)** | "It holds up at scale" → **"It holds up across the market."** Two panels: (a) volume — products tracked / price observations / days of coverage; (b) detection — deals detected vs. suspicious discounts caught. | `platform_metrics.py` numbers |
| 8b | The Human Pilot (rubric) | **Trust, made real** *(or drop)* | HGM's "3 reviewers × 10 PRs" has no El72 analogue. Options: (a) **drop** it (tightest deck); (b) repurpose as **"Why buyers trust us"** — the verification stack (MAD + Isolation Forest + deal score + fake-discount penalty) as a distribution of "genuine / fair / suspicious". Recommend **(b)** only if we have real numbers; else drop. | optional |
| 9 | Why Not Just Claude? | **Why not just a comparison site?** | "Claude is a great reviewer, also static" → **"A comparison site is a snapshot. We're a detector."** Two cards: *stateless comparison* (one store's page, no history, no cross-store, no verification) vs. *El72* (cross-store, historical baseline, ML verification, WhatsApp). | none |
| 9b | vs. Famous Quality Tools | **vs. the field** | Comparison table. Columns: **Yaoota · Kanbkam · "Notify me" (Amazon/Noon) · generic scraper · El72**. Rows: Cross-store intelligence ✓/✗, Historical baseline, Fake-discount detection, ML anomaly scoring, WhatsApp delivery, Cost-controlled alerts. El72 = the only column with all ✓. | none |
| 10 | How It Works (the loop) | **How it works (the pipeline)** | The `.loop` diagram becomes the data flow: **Scraper (Playwright) → Redis Streams → Analyzer (ML) → TimescaleDB → Notification (WhatsApp)**, with the "confirmed deal" branch highlighted. | none |
| 11 | Where HGM Sits (diagram) | **Where the intelligence sits** | Two-panel diagram: left = the **static pipeline** (scrape → store → alert); right = the **intelligence layer** wrapped around it (MAD + Isolation Forest + deal score + fake-discount + cross-store). "Swap the scraper; keep the intelligence." | new architecture diagram |
| 12 | The Reward Function | **Anomaly detection** (tech 1/4) | "The reward is a function, not a vibe" → **"Detection is a function, not a guess."** Two-tier: **Layer 1 MAD** (sub-ms fast path) + **Layer 2 Isolation Forest** (deep, historical). Show the `score_prices()` formula + threshold. | `ml_detector.py` |
| 12b | Selection (Thompson Sampling) | **Deal scoring** (tech 2/4) | Beta-posterior/Thompson → **Deal Quality Score 0–100** with the real weights: historical discount (35), percentile (25), cross-store advantage (20), historical low (15), duration (5), **suspicious-discount penalty (−30)**. Grades 80→Excellent … 0→No deal. | `deal_scorer.py` |
| 13 | The Confidence Gate | **Fake-discount detection** (tech 3/4) | Confidence/ECE → **The suspicious-discount signal**: reference price ≥10% above median, current <8% below median, competitors ≥3% cheaper, not near historical min, recent spike ≥10%. "A signal, not a fraud verdict." | `fake_discount.py` |
| 14 | Self-Improve | **Cross-store intelligence** (tech 4/4) | Prompt mutation → **cross-store comparison**: cheapest/most expensive store, market min/max/avg, spread, historical-low status (market-wide + per-store). "The data no single store will show you." | `cross_store.py` |
| 15 | The Whole Story (business) | **The business case** | Pipeline + compounding → **Revenue streams**: `.pipeline` = user → tracker → verified deal → **WhatsApp** → purchase. `.compound-row` = (a) **Credits** (pay-as-you-track), (b) **Fast-Lane** (zero-delay), (c) **B2B demand data** (highest margin). Footnote: WhatsApp utility rate keeps cost ~$0.0036/msg. | `business_research.md` |
| 16 | Responsible AI | **Cost & trust by design** | Principle→code table → **Principle → real code**: cost control (utility-rate templates, rate limiting → `billing`/`notification`), trust (fake-discount penalty → `fake_discount.py`), data sovereignty (local TimescaleDB/Postgres), transparency (every alert is explainable → `deal_scorer.py` reasons). | none |
| 17 | The Numbers | **The numbers** | 105 tests / 1 GPU / 3 min / 8192 → **7** microservices · **30s** scrape interval · **4** store scrapers · **97%** test coverage · **$0.0036** per alert. | `README`, `platform_metrics` |
| 18 | Roadmap | **Roadmap** | Pilot/Tune/Extend → **Phase 1 (done)**: auth, scraping, ML detection, WhatsApp. **Phase 2**: billing/credits, analytics dashboard, mobile companion, multi-language (Arabic/RTL). **Next**: LSTM/GAN models, multi-region, rate limiting. | `README` roadmap |
| 19 | Close | **Close** | "The human is the reward signal" → **"Seize the deal before it's gone."** Subhead: real-time price intelligence, verified, delivered on WhatsApp. | El72 mark |
| 20 | The Team | **The Team** | 5 HGM members → **El72 team** (names + roles + headshots). Keep the `.team` layout + `co-*` glow, remap colors to El72. | new headshots |

**Drop / keep decision:**
- **Keep** `index.html` as the single main deck (20 slides).
- **Drop** `index-with-pr.html` (the HGM PR #196 detour) — no El72 analogue.
- **Drop** `index-hgm-vs-finetuning.html` (HGM vs. fine-tuning deep dive) — no El72 analogue.
- Optionally **keep one companion** deep-dive if the audience is technical: e.g.
  "How the ML verification works" (MAD + Isolation Forest + deal score + fake discount) as a
  5–7 slide standalone. Low priority.

---

## 5. Team (content + assets)

- The HGM `.team` block hard-codes 5 people (Ahmed Samir, Mohammed Hany, Loay Medhat,
  Mohammad Emad, Yousry Ramadan) with company color classes `co-efg/co-here/co-fawry/co-cyshield/co-depi`.
- **Replace** with the El72 team: collect 5 names + one-line roles + headshots into
  `assets/team/`. Add a `co-*` class per member (or drop the per-company glow and use a
  single accent).
- Delete the loose root images (`hany.jpeg`, `loay.jpeg`, `samir.jpeg`, `yosry.jpeg`,
  `MohammadEmad.png`) once the new set is in `assets/team/`.

> **Open item:** El72 team names/roles/headshots are not in the repo docs — need to be
> supplied before this slide can be finalized.

---

## 6. Intro animation (`intro/`)

Rewrite the 13-second composition. Keep the GSAP timeline + `player.js` + `meta.json`;
change the beats, copy, stats, and the mark.

| Beat | HGM | → El72 |
|---|---|---|
| 1 | PR queue fills, "9 months" wait | A **wall of tracked items**; a price tick flips red→green; "the deal is live" |
| 2 | MergeFlow mark + "100 PRs · 24 min" | **El72 mark** + "Verified in seconds" + stat: "30s scrape · 4 stores · 97% coverage" |
| 3 | DORA impact (lead time / CFR / reviewer load) | **Business impact**: real deals found / fake alerts filtered / **$0.0036 per alert** |
| 4 | "Your rules" editor (money.md) | **The WhatsApp alert** card: neutral utility-rate text, "entered your price range" |
| 5 | MergeFlow logo lockup + "Powered by HGM" | **El72 logo lockup** + "Real-time price intelligence" |

- Replace every MergeFlow SVG mark (`#mark`, `#mark2`) with the El72 mark (inline SVG from
  `logo/El72.svg`, gold/orange gradient stops).
- Update `<title>` and `data-composition-id` (`mergeflow-intro` → `el72-intro`).
- `npm run render` (FFmpeg) to make the MP4; `npm run check` to lint.

---

## 7. Data & charts (`js/data.js`, `data/run_data.json`)

The chart renderer is generic (SVG grouped bars, calibration, line) driven by CSS vars, so
it recolors for free. Only the **data** changes.

- **Replace** `data/run_data.json` (HGM tree/calibration/utility) with an El72 metrics object, e.g.:
  - `platform`: products tracked, stores tracked, price observations, days of coverage,
    categories, deals detected, historical lows, **suspicious discounts caught**, avg movement.
  - `detection`: deals vs. suspicious-discount counts (the "it rejected a fake one" proof).
- **Update** `js/data.js`:
  - `RUN` → El72 platform/detection numbers.
  - `BENCH` (SWE-PRBench / Qodo) → two El72 panels (volume + detection), or a
    "genuine vs. flagged" distribution.
  - `benchCaptions()` → El72 captions.
- Source the numbers from `services/analyzer/platform_metrics.py`, `deal_scorer.py`,
  `fake_discount.py`, `cross_store.py` so they are **real**, not placeholders (the deck's
  whole credibility rests on "the data is real"). Use the seeded demo dataset for a
  deterministic, reproducible capture.

---

## 8. Live demo & fallback

- **`js/demo.js`:** rewire from MergeFlow to the El72 app.
  - `data-app` → the El72 dashboard/landing URL (e.g. `http://localhost:3000` landing page
    or the Flutter web build).
  - The guided tour steps → El72 screens: dashboard → price history → deals feed → WhatsApp
    alert.
  - The `mergeflow:tour` postMessage protocol must be mirrored by the El72 app (or the tour
    is driven by the deck's own clicker over the iframe). **This is the highest-effort item**
    and needs the El72 frontend to cooperate.
- **`fallback/replay.html`:** rewrite as a self-contained El72 replay (~30–40s): a price
  spike appears → MAD flags it → Isolation Forest confirms → deal score computed →
  fake-discount check passes → **WhatsApp alert fires**. No network, no server. Keep the
  "always available" guarantee.
- **`serve.py`:** keep. Serve over `localhost` (not `127.0.0.1`) if the demo needs a cookie.

> **Open item:** decide **live vs. recorded** demo. Live (Docker + DBs) is higher impact but
> riskier; a hybrid (live landing page + recorded scrape/WhatsApp) is safest. The replay
> fallback covers total failure.

---

## 9. Copy / tone

- HGM voice: research, "the loop," "your team's feedback," ICLR/HGM.
- El72 voice: **product + market + money.** Lead with the consumer pain (fake discounts),
  the moat (cross-store + verification + WhatsApp), and the revenue (credits, fast-lane,
  B2B data).
- Keep the deck's signature moves: one idea per slide, huge numbers, a "killer" comparison
  slide (vs. the field), and a business-case close.
- Numbers to keep **real and cited** (from the analyzer code), matching the source deck's
  "no placeholders" promise.

---

## 10. File-level checklist

- [ ] `css/apple-theme.css` — `:root` tokens, backdrop gradients, all `#0a84ff` /
      `rgba(10,132,255,…)` → gold; team `co-*` colors.
- [ ] `index.html` — all 20 slides rewritten per §4; `<title>`; `data-app`; team block.
- [ ] `intro/index.html` — beats, copy, stats, El72 mark, `:root`, gradient stops, title.
- [ ] `js/data.js` — `RUN`/`BENCH`/captions → El72 metrics.
- [ ] `data/run_data.json` — El72 metrics object.
- [ ] `js/demo.js` — `data-app` + tour → El72 app.
- [ ] `fallback/replay.html` — El72 replay.
- [ ] `assets/` — El72 mark PNG, architecture diagram, fake-discount visual, `team/`.
- [ ] Remove: `index-with-pr.html`, `index-hgm-vs-finetuning.html`, HGM diagram PNGs,
      `pr196.png`, `make_hgm_diagram.py`, loose root team jpegs, `assets/asd.png`.
- [ ] `README.md` — rewrite to describe the El72 deck (files, editions, data source).
- [ ] `rehearsal.md` / `strategy.md` — rewrite run-of-show + Q&A for El72 (investor
      questions: moat, CAC, WhatsApp cost, data access, "why can't Amazon add a button").

---

## 11. Locked decisions

1. **Accent hue:** **orange `#f7941d`** (with gold `#fbd724` highlight). ✅ Applied to
   `css/apple-theme.css` + `intro/index.html` (theme pass done).
2. **Team:** **3 members** — keep **Ahmed Samir, Mohammed Hany, Loay Medhat**; remove
   Yousry Ramadan and Mohammad Emad. (Headshots + roles still to be supplied.)
3. **Live demo:** **recorded hybrid** — live landing page / dashboard on screen, with the
   scrape → detect → WhatsApp flow as a **pre-recorded** clip. The replay fallback covers
   total failure. (Lowest-risk; no live Docker/DB dependency on stage.)
4. **Slide 8b:** **keep** — repurpose as **"Trust, made real"** (the verification stack as a
   genuine / fair / suspicious distribution).
5. **Companion deep-dive:** **build** a standalone **"How the ML verification works"** deck
   (MAD + Isolation Forest + deal score + fake-discount) as a 5–7 slide technical companion.
6. **Data:** use **placeholder numbers, clearly labelled as placeholder** (a visible
   "placeholder data" tag on every metrics slide). Do **not** claim "real data" — the
   source deck's "no placeholders" promise is dropped for El72 until real captures exist.

---

## 12. Build sequence (progress)

1. **Theme pass** (§1–2): recolor `css/apple-theme.css` + `intro/index.html` to orange. ✅ DONE.
2. **Content pass** (§4): rewrite `index.html` slide-by-slide. Deck is now "El72" textually.
3. **Assets** (§3): drop in El72 mark, architecture diagram, fake-discount visual, 3-person team.
4. **Data** (§7): **placeholder** metrics into `run_data.json` + `js/data.js`, labelled as
   placeholder; verify charts render.
5. **Intro** (§6): rebuild the 13s composition (El72 beats + mark); render MP4.
6. **Demo + fallback** (§8): recorded-hybrid demo, rewrite `replay.html`.
7. **Companion** (§11.5): build the "ML verification" standalone deck.
8. **Docs** (§10): rewrite `README.md`, `rehearsal.md`, `strategy.md`; delete dead files.
