/* =========================================================================
   Minimal offline slide engine — no external dependencies.
   Navigation: arrow keys / space / click zones / on-screen buttons.
   Hash-synced (#/n) so a shared screen can jump to a slide.
   ========================================================================= */
(function () {
  "use strict";

  var slides = Array.prototype.slice.call(document.querySelectorAll(".slide"));
  var total = slides.length;
  var current = 0;

  var progress = document.getElementById("progress");
  var counter = document.getElementById("counter");
  var navHint = document.getElementById("nav-hint");

  function pad(n) { return (n < 10 ? "0" : "") + n; }

  var shown = -1;

  function render() {
    for (var i = 0; i < total; i++) {
      slides[i].classList.toggle("is-active", i === current);
    }
    if (progress) {
      progress.style.width = ((current + 1) / total * 100) + "%";
    }
    if (counter) {
      counter.textContent = pad(current + 1) + " / " + pad(total);
    }
    // Hide the nav hint after the first slide (cleaner for the jury).
    if (navHint) {
      navHint.style.opacity = current === 0 ? "0.7" : "0";
    }
    // Keep the URL in sync (helps a second screen / recovery).
    try {
      var target = "#/" + (current + 1);
      if (location.hash !== target) {
        history.replaceState(null, "", target);
      }
    } catch (e) { /* file:// may block history — ignore */ }

    // Tell slide scripts (motion.js, demo.js) which slide just opened, so
    // their animations replay on every visit, not only the first.
    if (shown !== current) {
      var previous = shown;
      shown = current;
      window.dispatchEvent(new CustomEvent("deck:slidechange", {
        detail: { index: current, slide: slides[current], previous: previous, previousSlide: slides[previous] || null }
      }));
    }
  }

  function go(n) {
    n = Math.max(0, Math.min(total - 1, n));
    if (n === current) { render(); return; }
    current = n;
    render();
  }
  function next() { go(current + 1); }
  function prev() { go(current - 1); }

  // Restore from hash on load (e.g. #/5).
  (function initFromHash() {
    var m = (location.hash || "").match(/#\/(\d+)/);
    if (m) { current = Math.max(0, Math.min(total - 1, parseInt(m[1], 10) - 1)); }
  })();

  // Live hash jumps (shared second screen / recovery link).
  window.addEventListener("hashchange", function () {
    var m = (location.hash || "").match(/#\/(\d+)/);
    if (m) { go(parseInt(m[1], 10) - 1); }
  });

  // Keyboard. A slide can take the keyboard while it's in control (the live
  // demo does, so the presenter's clicker drives the app, not the deck).
  document.addEventListener("keydown", function (e) {
    if (slides[current] && slides[current].hasAttribute("data-keys-captured")) return;
    if (e.defaultPrevented) return;
    switch (e.key) {
      case "ArrowRight":
      case "PageDown":
      case " ":
      case "Enter":
        e.preventDefault(); next(); break;
      case "ArrowLeft":
      case "PageUp":
        e.preventDefault(); prev(); break;
      case "Home": e.preventDefault(); go(0); break;
      case "End": e.preventDefault(); go(total - 1); break;
      default:
        // Direct jump: 1..9 -> slide n, 0 -> slide 10.
        if (e.key >= "0" && e.key <= "9") {
          var n = e.key === "0" ? 10 : parseInt(e.key, 10);
          if (n <= total) { e.preventDefault(); go(n - 1); }
        }
    }
  });

  // Click zones (left third = prev, right two-thirds = next).
  var prevZone = document.getElementById("nav-prev");
  var nextZone = document.getElementById("nav-next");
  if (prevZone) prevZone.addEventListener("click", prev);
  if (nextZone) nextZone.addEventListener("click", next);

  // On-screen buttons (for touch / BYOD laptops).
  var btnPrev = document.getElementById("btn-prev");
  var btnNext = document.getElementById("btn-next");
  if (btnPrev) btnPrev.addEventListener("click", function (e) { e.stopPropagation(); prev(); });
  if (btnNext) btnNext.addEventListener("click", function (e) { e.stopPropagation(); next(); });

  // Pages embedded in a slide (the live demo) can move the deck.
  window.addEventListener("message", function (e) {
    var d = e.data || {};
    if (d.type !== "el72:deck") return;
    if (d.action === "next") next();
    if (d.action === "prev") prev();
  });

  window.Deck = {
    next: next,
    prev: prev,
    go: go,
    current: function () { return current; },
    slide: function () { return slides[current]; }
  };

  render();
})();
