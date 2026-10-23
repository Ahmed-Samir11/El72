# El72 Deck — Day-of Run Book

The day-of checklist for presenting the El72 deck. Runtime ≈ 13 minutes + Q&A.

---

## Pre-flight (the night before)

- [ ] Open `index.html` in Chrome/Edge, full-screen. Verify all 19 slides
      render, the intro plays, and the charts animate.
- [ ] Confirm the **placeholder numbers** are acceptable, or swap in real
      values in `js/data.js` + `index.html`.
- [ ] For the live demo slide: start the El72 app on `localhost` and confirm
      the iframe loads. (A `file://` deck can't carry a sign-in into the frame.)
- [ ] Have the **recorded clip** (scrape → detect → WhatsApp) ready to swap
      into the demo slide if going recorded-hybrid.
- [ ] Keep `fallback/replay.html` open in a second tab as the cut-to-fallback.
- [ ] Test keyboard nav (→ / PageDown / Space) and the demo start/exit.

---

## Venue setup

- [ ] Full-screen, dark room, projector calibrated (the theme is `#000` —
      avoid a washed-out projector).
- [ ] Mouse hidden; present with the keyboard (→ / Space).
- [ ] A clicker is fine, but the demo slide needs the keyboard (Enter/→).
- [ ] No internet needed — everything is offline.

---

## Timed run-of-show

| Time | Slide(s) | Notes |
|------|----------|-------|
| 0:00 | 1–2 | Cold open + graveyard. Land "30 seconds." |
| 0:40 | 3–4 | Title + intro. Let the 13s intro play. |
| 1:30 | 5 | The reveal — one pipeline. |
| 2:00 | 6 | **Demo.** Enter/→ to start; narrate the clip. |
| 4:00 | 7–8 | Proof + scale. Point at the charts. |
| 5:30 | 9–11 | Trust + the two objection slides. |
| 7:00 | 12–15 | How it works + the two AI engines. |
| 8:45 | 16–18 | Quality harness + funding + business case. |
| 10:15 | 17–18 | Roadmap + close. |
| 11:00 | 19 | Team + Q&A. |

---

## Demo script (slide 6)

- Press **Enter** (or →) to reveal the demo.
- Narrate: "El72 scrapes the price, detects the drop, scores it, and sends the
  WhatsApp alert — in seconds."
- If going recorded-hybrid, play the pre-recorded clip of the scrape →
  detect → WhatsApp flow.
- Press **→** (or the "exit demo" button) to return to the slides.

---

## Cut-to-fallback triggers

- The live demo doesn't load → open `fallback/replay.html` and play it.
- The charts don't animate → the static captions carry the numbers; move on.
- The intro doesn't play → press **R** to replay, or skip to slide 5.

---

## Recovery

- Lost your place? The counter (bottom-right) shows the slide number.
- To go home: press **Home** or `F5`.
- To replay the intro: press **R** on the intro slide.

---

## Q&A cards

- **Fake discounts:** the 4 checks in `fake_discount.py`.
- **Deal accuracy:** placeholder — point to `deal_scorer.py`.
- **Cost:** ~$0.0036 per WhatsApp alert.
- **Moat:** cross-store + B2B intelligence, not scraping.
- **Scale:** pluggable scrapers, store-agnostic analyzer.
- **Data:** TimescaleDB, 30s scrape interval.
