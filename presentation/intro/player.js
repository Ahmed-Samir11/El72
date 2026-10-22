/* Live player for the intro composition inside the deck.
   Only active with ?embed in the URL — HyperFrames' own preview/render
   drive the registered timeline themselves and never load it that way.

   Parent → intro:  { type: "intro:play" }   restart from 0
                    { type: "intro:reset" }  rewind and hold the first frame
   Intro → parent:  { type: "intro:done" }   reached 13 s                    */
(function () {
  "use strict";
  var params = new URLSearchParams(location.search);
  if (!params.has("embed")) return;

  var W = 1920, H = 1080;
  var root = document.getElementById("root");
  var tl = window.__timelines && window.__timelines["el72-intro"];
  if (!root || !tl) return;

  var html = document.documentElement;
  html.style.width = html.style.height = "100%";
  document.body.style.width = "100vw";
  document.body.style.height = "100vh";
  // Let the deck's own backdrop show through, so intro and slides share one
  // background at any screen size.
  html.style.background = document.body.style.background = root.style.background = "transparent";
  var ambient = document.getElementById("ambient");
  if (ambient) ambient.style.display = "none";
  root.style.position = "absolute";
  root.style.transformOrigin = "0 0";

  function fit() {
    var s = Math.min(innerWidth / W, innerHeight / H);
    root.style.transform = "scale(" + s + ")";
    root.style.left = (innerWidth - W * s) / 2 + "px";
    root.style.top = (innerHeight - H * s) / 2 + "px";
  }
  addEventListener("resize", fit);
  fit();

  tl.eventCallback("onComplete", function () {
    if (parent !== window) parent.postMessage({ type: "intro:done" }, "*");
  });

  addEventListener("message", function (e) {
    var type = e.data && e.data.type;
    if (type === "intro:play") tl.restart();
    if (type === "intro:reset") tl.pause(0);
  });

  if (params.has("autoplay")) tl.restart();
  if (parent !== window) parent.postMessage({ type: "intro:ready" }, "*");
})();
