/* demo.js — the two embedded slides: the intro and the live El72 demo.

   Intro: plays the HyperFrames composition (intro/index.html?embed) every
   time its slide opens, rewinds when you leave, R replays.

   Demo: the El72 app (landing page / dashboard) runs in an iframe. On the
   demo slide, → / PageDown / Enter / Space reveals the frame; the presenter
   narrates while the live app is on screen. For the recorded-hybrid, swap the
   iframe for a pre-recorded clip of the scrape → detect → WhatsApp flow.
   "exit demo" is always there as an escape hatch.

   The app URL comes from ?app=… on the deck URL, else data-app on the slide.
   Serve the deck over http from the same host as the app (e.g. localhost) so
   the frame can load; a file:// deck can't carry a sign-in into the frame. */
(function () {
  "use strict";

  function send(frame, msg, origin) {
    try { frame.contentWindow.postMessage(msg, origin || "*"); } catch (_) { /* not loaded */ }
  }

  // ---- intro ------------------------------------------------------------------
  function introFrame(slide) { return slide ? slide.querySelector(".intro-frame") : null; }

  window.addEventListener("message", function (e) {
    if (e.data && e.data.type === "intro:ready" && window.Deck) {
      var f = introFrame(window.Deck.slide());
      if (f && e.source === f.contentWindow) send(f, { type: "intro:play" });
    }
  });

  // ---- demo -------------------------------------------------------------------
  var demo = document.querySelector(".demo-slide");
  var frame = demo && demo.querySelector(".demo-frame");
  var status = demo && demo.querySelector(".demo-status");
  var appUrl = demo && (new URLSearchParams(location.search).get("app") || demo.getAttribute("data-app"));
  var live = false;

  if (demo && frame && appUrl) {
    // Load the app early (hidden) so it's ready the moment the slide opens.
    frame.addEventListener("load", function () { setTimeout(reclaimFocus, 50); setTimeout(reclaimFocus, 600); });
    window.addEventListener("blur", function () { setTimeout(reclaimFocus, 0); });
    setTimeout(function () { frame.src = appUrl; }, 1200);

    var startBtn = demo.querySelector(".demo-start");
    if (startBtn) startBtn.addEventListener("click", function (e) { e.stopPropagation(); start(); });
    var exitBtn = demo.querySelector(".demo-exit");
    if (exitBtn) exitBtn.addEventListener("click", function (e) { e.stopPropagation(); if (window.Deck) window.Deck.next(); });

    // Capture phase: runs before deck.js, so Enter/→ reveal the demo here
    // instead of advancing the deck.
    document.addEventListener("keydown", function (e) {
      if (!window.Deck || window.Deck.slide() !== demo || live) return;
      if (["ArrowRight", "PageDown", "Enter", " "].indexOf(e.key) !== -1) {
        e.preventDefault();
        start();
      }
    }, true);
  }

  function reclaimFocus() {
    if (!live && frame && document.activeElement === frame) {
      frame.blur();
      window.focus();
    }
  }

  function start() {
    live = true;
    demo.classList.add("is-live");
    demo.setAttribute("data-keys-captured", "");
    document.body.classList.add("demo-live");
    frame.focus();
  }

  function leave() {
    if (!live) return;
    live = false;
    demo.classList.remove("is-live");
    demo.removeAttribute("data-keys-captured");
    document.body.classList.remove("demo-live");
    frame.blur();
    window.focus();
  }

  // ---- slide changes ----------------------------------------------------------
  window.addEventListener("deck:slidechange", function (e) {
    var s = e.detail.slide, prev = e.detail.previousSlide;
    var f = introFrame(s);
    if (f) send(f, { type: "intro:play" });
    var pf = introFrame(prev);
    if (pf) send(pf, { type: "intro:reset" });
    if (demo && prev === demo) leave();
    if (demo && s === demo) reclaimFocus();
  });

  window.addEventListener("deck:replay", function (e) {
    var f = introFrame(e.detail.slide);
    if (f) send(f, { type: "intro:play" });
  });
})();
