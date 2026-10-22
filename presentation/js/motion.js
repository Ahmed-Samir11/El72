/* motion.js — motion graphics for the deck, driven by GSAP.

   Every time a slide opens, its timeline plays from the start; leaving the
   slide reverts it, so a re-visit (or a jump back mid-animation) always
   starts clean. The data never changes — only how it arrives. Charts are
   the SVGs data.js already rendered and the HTML bars already on the
   slides; this file animates them in place.

   R replays the current slide's motion. prefers-reduced-motion skips it. */
(function () {
  "use strict";
  if (!window.gsap) return;
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  var EASE = "power3.out";
  var active = null; // { slide, ctx, restore[] }

  // ---- helpers ------------------------------------------------------------
  function $$(root, sel) { return Array.prototype.slice.call(root.querySelectorAll(sel)); }

  /* Count a number up from 0, keeping its prefix, suffix, decimals and
     thousands separators: "0.528", "45.1%", "30s", "8192", "−0.40". */
  function countUp(tl, el, at, duration) {
    var final = el.getAttribute("data-final");
    if (final == null) { final = el.textContent; el.setAttribute("data-final", final); }
    var m = final.match(/^([^\d−-]*)([−-]?)(\d[\d,]*)(\.\d+)?(.*)$/);
    if (!m) return;
    var neg = m[2], intPart = m[3], dec = m[4] || "", tail = m[5];
    var decimals = dec ? dec.length - 1 : 0;
    var target = parseFloat(intPart.replace(/,/g, "") + dec);
    var commas = intPart.indexOf(",") !== -1;
    var o = { v: 0 };
    el.textContent = m[1] + neg + (0).toFixed(decimals) + tail;
    tl.to(o, {
      v: target, duration: duration || 1.1, ease: "power2.out",
      onUpdate: function () {
        var s = o.v.toFixed(decimals);
        if (commas) s = s.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
        el.textContent = m[1] + neg + s + tail;
      }
    }, at);
    active.restore.push(function () { el.textContent = final; });
  }

  // ---- per-slide timelines (keyed by data-title) ---------------------------
  var MOTION = {
    "The Cost": function (tl, s) {
      tl.from($$(s, ".metric"), { y: 50, opacity: 0, duration: 0.7, stagger: 0.15, ease: EASE }, 0.25)
        .from($$(s, ".metric .num"), { y: -60, opacity: 0, duration: 0.9, stagger: 0.15, ease: "bounce.out" }, 0.45);
    },

    "The Proof": function (tl, s) {
      tl.from($$(s, ".mutation"), { y: 40, opacity: 0, duration: 0.6, stagger: 0.25, ease: EASE }, 0.3)
        .from($$(s, ".mut-added"), { backgroundColor: "rgba(48,209,88,0.35)", duration: 1.2, stagger: 0.25, ease: "power1.out" }, 0.8);
    },

    "The Proof at Scale": function (tl, s) {
      $$(s, "svg").forEach(function (svg, p) {
        var rects = $$(svg, "rect");
        rects.forEach(function (r, i) {
          var y = +r.getAttribute("y"), h = +r.getAttribute("height");
          // Bars come in pairs (baseline, evolved) per metric: grow the pair,
          // baseline first, evolved right after it.
          var at = 0.35 + p * 0.25 + Math.floor(i / 2) * 0.18 + (i % 2) * 0.12;
          tl.fromTo(r, { attr: { y: y + h, height: 0 } }, { attr: { y: y, height: h }, duration: 0.8, ease: EASE }, at);
        });
        $$(svg, "text").forEach(function (t) {
          var txt = t.textContent;
          if (/^[+−-]?\d/.test(txt) && !/pts?$/.test(txt)) {
            tl.from(t, { opacity: 0, duration: 0.3 }, 0.9 + p * 0.25);
            countUp(tl, t, 0.9 + p * 0.25, 1.0);
          } else if (/pts?$/.test(txt)) {
            tl.from(t, { opacity: 0, y: 10, duration: 0.45, ease: "back.out(2.5)" }, 1.7 + p * 0.25);
          }
        });
      });
      tl.from($$(s, ".bench-cap"), { opacity: 0, y: 12, duration: 0.5, stagger: 0.2 }, 1.9);
    },

    "The Human Pilot": function (tl, s) {
      $$(s, ".pilot-col").forEach(function (col, c) {
        tl.from(col.querySelector(".pilot-colhead"), { opacity: 0, y: 12, duration: 0.4 }, 0.3 + c * 0.15);
        $$(col, ".pilot-bar").forEach(function (bar, i) {
          var fill = bar.querySelector(".pilot-fill");
          var at = 0.45 + c * 0.15 + i * 0.12;
          tl.from(fill, { width: 0, duration: 0.9, ease: EASE }, at);
          countUp(tl, bar.querySelector(".pilot-val"), at, 0.9);
        });
      });
    },

    "Why Not Just Claude?": function (tl, s) {
      tl.from($$(s, ".arch-card"), { y: 40, opacity: 0, duration: 0.6, stagger: 0.2, ease: EASE }, 0.3)
        .from($$(s, ".arch-card li"), { x: -16, opacity: 0, duration: 0.4, stagger: 0.07 }, 0.6);
    },

    "vs. Famous Quality Tools": function (tl, s) {
      tl.from($$(s, "table.compare tbody tr"), { x: -30, opacity: 0, duration: 0.5, stagger: 0.12, ease: EASE }, 0.35)
        .from($$(s, "td.ours-col"), { scale: 0, opacity: 0, duration: 0.45, stagger: 0.12, ease: "back.out(3)" }, 0.75);
    },

    "How It Works": function (tl, s) {
      var steps = $$(s, ".loop > *");
      tl.from(steps, { y: 24, opacity: 0, duration: 0.45, stagger: 0.16, ease: EASE }, 0.3);
      var reward = s.querySelector(".node.reward");
      if (reward) tl.fromTo(reward, { boxShadow: "0 0 0 0 rgba(10,132,255,0)" }, { boxShadow: "0 0 0 10px rgba(10,132,255,0.28)", duration: 0.5, yoyo: true, repeat: 3, ease: "sine.inOut" }, ">-0.1");
    },

    "The Reward Function": function (tl, s) {
      tl.from($$(s, ".weight-cell"), { y: 30, opacity: 0, duration: 0.5, stagger: 0.1, ease: "back.out(2)" }, 0.4);
      $$(s, ".weight-cell .v").forEach(function (v, i) { countUp(tl, v, 0.45 + i * 0.1, 0.8); });
      tl.from($$(s, ".worked .w-line"), { x: -14, opacity: 0, duration: 0.35, stagger: 0.18 }, 0.9);
      $$(s, ".worked .res").forEach(function (r) { countUp(tl, r, 1.5, 0.9); });
    },

    "Selection": function (tl, s) {
      tl.from($$(s, ".worked"), { y: 30, opacity: 0, duration: 0.5, stagger: 0.2, ease: EASE }, 0.4);
      $$(s, ".worked .res").forEach(function (r) { countUp(tl, r, 0.6, 1.0); });
      var scale = s.querySelector(".scale-line b");
      if (scale) {
        // "800 evals · 56 prompt variants" — two numbers in one line.
        var final = scale.textContent, o = { a: 0, b: 0 };
        tl.to(o, { a: 800, b: 56, duration: 1.2, ease: "power2.out", onUpdate: function () {
          scale.textContent = Math.round(o.a) + " evals · " + Math.round(o.b) + " prompt variants";
        } }, 0.9);
        active.restore.push(function () { scale.textContent = final; });
      }
    },

    "The Confidence Gate": function (tl, s) {
      tl.from($$(s, ".formula"), { opacity: 0, y: 20, duration: 0.5, stagger: 0.15 }, 0.35);
      $$(s, ".res").forEach(function (r) { countUp(tl, r, 0.8, 1.0); });
      tl.from($$(s, ".worked"), { opacity: 0, y: 20, duration: 0.5 }, 1.0);
    },

    "Self-Improve": function (tl, s) {
      tl.from($$(s, ".worked"), { x: 40, opacity: 0, duration: 0.55, stagger: 0.2, ease: EASE }, 0.45);
    },

    "The Whole Story": function (tl, s) {
      var parts = $$(s, ".pipeline > *");
      tl.from(parts, { x: -30, opacity: 0, duration: 0.4, stagger: 0.1, ease: EASE }, 0.3);
      var us = s.querySelector(".pipe-stage.us");
      if (us) tl.fromTo(us, { scale: 1 }, { scale: 1.08, duration: 0.35, yoyo: true, repeat: 1, ease: "sine.inOut" }, ">");
      tl.from(s.querySelector(".pipe-loop .loop-arrow"), { rotation: -360, duration: 1.1, ease: "power2.out" }, ">-0.2")
        .from($$(s, ".compound"), { y: 40, opacity: 0, duration: 0.55, stagger: 0.15, ease: EASE }, "<")
        .from($$(s, ".compound .c-arrow"), { y: function (i, el) { return el.textContent === "↑" ? 30 : -30; }, opacity: 0, duration: 0.7, stagger: 0.15, ease: "bounce.out" }, "<0.2");
    },

    "Responsible AI": function (tl, s) {
      tl.from($$(s, "table.principle tbody tr"), { x: -24, opacity: 0, duration: 0.45, stagger: 0.1, ease: EASE }, 0.35);
    },

    "The Numbers": function (tl, s) {
      tl.from($$(s, ".number"), { y: 40, opacity: 0, duration: 0.6, stagger: 0.12, ease: EASE }, 0.3);
      $$(s, ".number .big").forEach(function (b, i) { countUp(tl, b, 0.4 + i * 0.12, 1.3); });
    },

    "Roadmap": function (tl, s) {
      tl.from($$(s, ".roadmap .step"), { y: 40, opacity: 0, duration: 0.6, stagger: 0.18, ease: EASE }, 0.3);
    },

    "The Team": function (tl, s) {
      tl.from($$(s, ".member"), { y: 50, opacity: 0, duration: 0.6, stagger: 0.12, ease: EASE }, 0.3)
        .from($$(s, ".member .avatar"), { scale: 0.6, duration: 0.6, stagger: 0.12, ease: "back.out(2.2)" }, 0.35);
    }
  };

  // ---- lifecycle -------------------------------------------------------------
  function stop() {
    if (!active) return;
    active.ctx.revert();
    active.restore.forEach(function (f) { f(); });
    active = null;
  }

  function play(slide) {
    stop();
    if (!slide || reduce) return;
    var build = MOTION[slide.getAttribute("data-title")];
    if (!build) return;
    active = { slide: slide, restore: [], ctx: null };
    active.ctx = gsap.context(function () {
      var tl = gsap.timeline();
      build(tl, slide);
    }, slide);
  }

  window.addEventListener("deck:slidechange", function (e) { play(e.detail.slide); });

  document.addEventListener("keydown", function (e) {
    if ((e.key === "r" || e.key === "R") && window.Deck && !e.ctrlKey && !e.metaKey) {
      var slide = window.Deck.slide();
      if (slide && slide.hasAttribute("data-keys-captured")) return;
      play(slide);
      window.dispatchEvent(new CustomEvent("deck:replay", { detail: { slide: slide } }));
    }
  });

  // deck.js announced the first slide before this file loaded. data.js
  // draws the charts on DOMContentLoaded, so wait for that too.
  function first() { if (window.Deck) play(window.Deck.slide()); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", first);
  else first();
})();
