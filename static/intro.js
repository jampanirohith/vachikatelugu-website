/*
  Vāchika entry intro (home page, first visit of a browser session).

  The animation is the logo opening from the Reel project, re-drawn on a canvas:
  orange dot pops in, the ink stroke is drawn along the pen path, the waveform
  bars rise and breathe, then the sign
  evaporates and the site is shown. All art is self-hosted in /static/intro/.

  Sequence timings are in seconds and live in T below. The page behind the
  overlay is already rendered, so finishing or skipping only removes the overlay.
*/
(function () {
  "use strict";

  var root = document.documentElement;
  var overlay = document.getElementById("intro");
  if (!overlay || !root.classList.contains("intro-on")) return;

  var canvas = overlay.querySelector("canvas");
  var skip = overlay.querySelector("[data-intro-skip]");
  var version = overlay.getAttribute("data-v") || "";
  var ctx = canvas && canvas.getContext ? canvas.getContext("2d") : null;
  if (!ctx) { done(true); return; }

  /* ---- geometry, in the coordinates of the 1254 px logo master ------------ */
  var LOCK = { x: 330, y: 25, w: 636, h: 1182 };            /* the sign only, with a little air */
  var STROKE = { x: 353, y: 38 };
  var BARS = [
    { x: 679, y: 543, w: 47, h: 244 }, { x: 742, y: 497, w: 46, h: 355 },
    { x: 797, y: 578, w: 44, h: 193 }, { x: 850, y: 615, w: 42, h: 117 },
    { x: 900, y: 653, w: 43, h: 51 }
  ];
  var DOT = { x: 659, y: 421, w: 92, h: 90 };

  /* ---- timeline ------------------------------------------------------------ */
  var T = {
    dot: [0.15, 0.50], stroke: [0.35, 1.20], barsStart: 0.75, barStagger: 0.05, barPop: 0.26,
    beat: 1.10, evaporate: [2.30, 2.85], leave: 2.60
  };

  /* ---- easing --------------------------------------------------------------- */
  function clamp(x) { return x < 0 ? 0 : x > 1 ? 1 : x; }
  function seg(t, a, b) { return clamp((t - a) / Math.max(b - a, 1e-9)); }
  function smooth(x) { x = clamp(x); return x * x * (3 - 2 * x); }
  function easeOut(x) { x = clamp(x); return 1 - Math.pow(1 - x, 3); }
  function easeOutBack(x) { x = clamp(x); var s = 1.4; return 1 + (s + 1) * Math.pow(x - 1, 3) + s * Math.pow(x - 1, 2); }
  function easeInOut(x) { x = clamp(x); return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2; }
  function penEase(x) { x = clamp(x); return smooth(smooth(x) * 0.35 + x * 0.65); }

  /* ---- loading --------------------------------------------------------------- */
  var NAMES = ["stroke", "stroke-order", "dot", "bar-0", "bar-1", "bar-2", "bar-3", "bar-4"];
  var images = {};
  var pending = NAMES.length;
  var finished = false;
  var started = false;
  var rafId = 0;
  var startTime = 0;
  var loadTimer = window.setTimeout(function () { if (!started) done(true); }, 4000);   /* slow network: skip the intro */

  NAMES.forEach(function (name) {
    var img = new Image();
    img.onload = function () { images[name] = img; if (--pending === 0) start(); };
    img.onerror = function () { done(true); };
    img.src = "/static/intro/" + name + ".png" + (version ? "?v=" + version : "");
  });

  if (skip) skip.addEventListener("click", function (event) { event.stopPropagation(); done(false); });
  overlay.addEventListener("click", function () { done(false); });
  function onKey(event) {
    if (event.key === "Escape" || event.key === "Enter" || event.key === " ") { event.preventDefault(); done(false); }
  }
  document.addEventListener("keydown", onKey);

  /* ---- prepared pixel data -------------------------------------------------- */
  var strokeCanvas, strokeData, strokeAlpha, order, orderKey, orderCount, fullDone = 0, hiMark = 0;
  var dpr = 1, cssW = 0, cssH = 0;

  function pixelsOf(img) {
    var c = document.createElement("canvas");
    c.width = img.naturalWidth; c.height = img.naturalHeight;
    var g = c.getContext("2d", { willReadFrequently: true });
    g.drawImage(img, 0, 0);
    return { canvas: c, ctx: g, data: g.getImageData(0, 0, c.width, c.height) };
  }

  function prepare() {
    /* stroke: alpha is revealed in pen order */
    var s = pixelsOf(images["stroke"]);
    var o = pixelsOf(images["stroke-order"]);
    strokeCanvas = s; strokeData = s.data;
    var n = strokeData.data.length / 4;
    strokeAlpha = new Uint8Array(n);
    var combined = [];
    for (var i = 0; i < n; i++) {
      var a = strokeData.data[i * 4 + 3];
      strokeAlpha[i] = a;
      strokeData.data[i * 4 + 3] = 0;
      if (a > 0) combined.push((o.data.data[i * 4] * 256 + o.data.data[i * 4 + 1]) * 524288 + i);
    }
    var sorted = Float64Array.from(combined).sort();
    orderCount = sorted.length;
    order = new Uint32Array(orderCount);
    orderKey = new Float32Array(orderCount);
    for (var j = 0; j < orderCount; j++) {
      var key = Math.floor(sorted[j] / 524288);
      order[j] = sorted[j] - key * 524288;
      orderKey[j] = key / 65534;
    }
  }

  function upperBound(limit) {                          /* count of pen positions <= limit */
    var lo = 0, hi = orderCount;
    while (lo < hi) { var mid = (lo + hi) >> 1; if (orderKey[mid] <= limit) lo = mid + 1; else hi = mid; }
    return lo;
  }

  function updateStroke(t) {
    var k = seg(t, T.stroke[0], T.stroke[1]);
    var p = penEase(k) * 1.04;
    var data = strokeData.data;
    var fullTo = upperBound(p - 0.018);
    var partialTo = upperBound(p);
    var i, px;
    for (i = fullDone; i < fullTo; i++) { px = order[i]; data[px * 4 + 3] = strokeAlpha[px]; }
    fullDone = fullTo;
    for (i = fullDone; i < partialTo; i++) {
      px = order[i];
      data[px * 4 + 3] = strokeAlpha[px] * smooth((p - orderKey[i]) / 0.018);
    }
    hiMark = partialTo;
    strokeCanvas.ctx.putImageData(strokeData, 0, 0);
  }

  /* ---- drawing --------------------------------------------------------------- */
  function size() {
    dpr = Math.min(window.devicePixelRatio || 1, 2.5);
    var h = Math.min(window.innerHeight * 0.5, 440, (window.innerWidth * 0.6) * (LOCK.h / LOCK.w));
    cssH = Math.max(h, 200); cssW = cssH * (LOCK.w / LOCK.h);
    canvas.width = Math.round(cssW * dpr); canvas.height = Math.round(cssH * dpr);
    canvas.style.width = cssW + "px"; canvas.style.height = cssH + "px";
  }

  function envelope(t) {                               /* stands in for the song's loudness */
    return 0.5 + 0.32 * Math.sin(2 * Math.PI * t * 1.4) + 0.18 * Math.sin(2 * Math.PI * t * 2.9 + 1.3);
  }

  function frame(t) {
    var k = canvas.width / LOCK.w;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.setTransform(k, 0, 0, k, -LOCK.x * k, -LOCK.y * k);

    var dotK = seg(t, T.dot[0], T.dot[1]);
    var dotS = easeOutBack(dotK);
    var pulse = Math.exp(-Math.pow((t - T.beat) / 0.11, 2));
    var cx = DOT.x + DOT.w / 2, cy = DOT.y + DOT.h / 2;

    if (t >= T.stroke[0]) {
      updateStroke(t);
      ctx.drawImage(strokeCanvas.canvas, STROKE.x, STROKE.y);
    }
    BARS.forEach(function (b, i) {
      var t0 = T.barsStart + i * T.barStagger;
      var pop = easeOutBack(seg(t, t0, t0 + T.barPop));
      if (pop <= 0.01) return;
      var react = 0.62 + 0.55 * envelope(t - 0.035 * i);
      var blend = smooth(seg(t, T.barsStart + 0.3, T.barsStart + 0.5));
      var h = b.h * pop * (1 + blend * (react - 1));
      if (h < 2) return;
      ctx.drawImage(images["bar-" + i], b.x, b.y + b.h / 2 - h / 2, b.w, h);
    });

    if (dotS > 0.01) {
      var sc = Math.max(dotS * (1 + 0.16 * pulse), 0.02);
      ctx.drawImage(images["dot"], cx - DOT.w * sc / 2, cy - DOT.h * sc / 2, DOT.w * sc, DOT.h * sc);
    }

    /* evaporate: blur, drift up, fade (CSS properties, so it also works in Safari) */
    var e = easeInOut(seg(t, T.evaporate[0], T.evaporate[1]));
    canvas.style.filter = e > 0.001 ? "blur(" + (e * 12).toFixed(2) + "px)" : "";
    canvas.style.transform = e > 0.001 ? "translateY(" + (-e * 26).toFixed(1) + "px)" : "";
    canvas.style.opacity = String(1 - e);
  }

  function tick(now) {
    if (finished) return;
    var t = (now - startTime) / 1000;
    frame(t);
    if (t >= T.leave) { done(false); return; }
    rafId = window.requestAnimationFrame(tick);
  }

  function start() {
    if (finished) return;
    try { prepare(); size(); } catch (error) { done(true); return; }
    started = true;
    window.clearTimeout(loadTimer);
    window.addEventListener("resize", size);
    overlay.classList.add("is-playing");
    startTime = performance.now();
    rafId = window.requestAnimationFrame(tick);
  }

  /* ---- finish ----------------------------------------------------------------- */
  function done(immediate) {
    if (finished) return;
    finished = true;
    window.clearTimeout(loadTimer);
    window.cancelAnimationFrame(rafId);
    window.removeEventListener("resize", size);
    document.removeEventListener("keydown", onKey);
    root.classList.add("intro-done");
    if (immediate) { cleanup(); return; }
    root.classList.add("intro-leave");
    window.setTimeout(cleanup, 760);
  }

  function cleanup() {
    root.classList.remove("intro-on", "intro-leave");
    if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
  }
})();
