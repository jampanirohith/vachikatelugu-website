/* Vāchika front end. No dependencies; everything degrades to plain HTML without it. */
(function () {
  "use strict";

  var INDEX_URL = "/search-index.json?v=__SEARCH_INDEX_VERSION__";
  var DRAWER_QUERY = "(min-width: 1100px) and (hover: hover)";
  var reducedMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ------------------------------------------------------------ helpers */
  function $(selector, root) { return (root || document).querySelector(selector); }
  function $$(selector, root) { return Array.prototype.slice.call((root || document).querySelectorAll(selector)); }
  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function norm(value) {
    return String(value == null ? "" : value).normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
  }
  function safeUrl(url) { return /^https?:\/\//i.test(url || "") ? url : ""; }
  function store(key, value) {
    try {
      if (value === undefined) return localStorage.getItem(key);
      localStorage.setItem(key, value);
    } catch (error) {}
    return null;
  }
  function debounce(fn, wait) {
    var timer;
    return function () {
      var args = arguments, self = this;
      clearTimeout(timer);
      timer = setTimeout(function () { fn.apply(self, args); }, wait);
    };
  }
  function toInt(value) {
    var n = parseInt(value, 10);
    return isNaN(n) ? null : n;
  }
  function icon(name) {
    var paths = {
      arrow: '<path d="M7 17 17 7M8.5 7H17v8.5"/>',
      note: '<path d="M9 18V5l11-2v13"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="17.5" cy="16" r="2.5"/>',
      play: '<path d="M8 5.5v13l11-6.5z" fill="currentColor" stroke="none"/>',
      link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3A4 4 0 0 0 11 18.7l1-1"/>',
      chevron: '<path d="m6 9 6 6 6-6"/>'
    };
    return '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' + paths[name] + "</svg>";
  }
  function providerIcon(kind) {
    if (kind === "spotify") {
      return '<svg class="provider-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="11" fill="currentColor"/><path d="M5.3 9.2c4.3-1.2 9.4-.7 13.2 1.5M6.2 12.4c3.6-1 7.7-.5 10.8 1.3M7.1 15.3c2.8-.7 5.9-.3 8.2 1" fill="none" stroke="#0a0a0a" stroke-width="1.5" stroke-linecap="round"/></svg>';
    }
    if (kind === "youtube") {
      return '<svg class="provider-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><rect x="1" y="4.5" width="22" height="15" rx="4.5" fill="currentColor"/><path d="M10 9v6l5.2-3z" fill="#fff"/></svg>';
    }
    return '<svg class="provider-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="11" fill="currentColor"/><circle cx="12" cy="12" r="6.2" fill="none" stroke="#fff" stroke-width="1.4"/><path d="M10.2 9v6l5-3z" fill="#fff"/></svg>';
  }
  function formatCount(value) {
    value = Math.max(0, Number(value) || 0);
    if (value >= 1e9) return (value / 1e9).toFixed(1).replace(/\.0$/, "") + "B";
    if (value >= 1e6) return (value / 1e6).toFixed(1).replace(/\.0$/, "") + "M";
    if (value >= 1e3) return (value / 1e3).toFixed(1).replace(/\.0$/, "") + "K";
    return String(Math.round(value));
  }
  function personLinks(names) {
    return (names || []).map(function (name) {
      return '<a href="/advanced-search/?q=' + encodeURIComponent(name) + '">' + esc(name) + "</a>";
    }).join(", ");
  }

  /* ---------------------------------------------------------- search index */
  var indexPromise = null;
  function loadIndex() {
    if (!indexPromise) {
      indexPromise = fetch(INDEX_URL, { credentials: "same-origin" })
        .then(function (response) {
          if (!response.ok) throw new Error("search index " + response.status);
          return response.json();
        })
        .then(prepareIndex)
        .catch(function (error) { indexPromise = null; throw error; });
    }
    return indexPromise;
  }

  function prepareIndex(data) {
    var maxima = { song: 1, album: 1, movie: 1 };
    var records = [];
    (data.songs || []).forEach(function (s) {
      var pop = Number(s.playsNum) || 0;
      maxima.song = Math.max(maxima.song, pop);
      records.push({
        type: "song", raw: s, id: s.id, title: s.title, titleN: norm(s.title), pop: pop,
        year: toInt(s.year), release: s.release || "", lang: norm(s.language) || "telugu",
        genres: (s.genres || []).concat(s.movieGenres || []).map(norm),
        href: "/song/" + s.id + "/", art: s.artwork || s.poster || "",
        sub: s.movieTitle + (s.year ? " · " + s.year : "") + ((s.artists || []).length ? " · " + s.artists.slice(0, 2).join(", ") : ""),
        meta: s.plays || "",
        hay: norm([s.movieTitle, s.albumTitle, (s.artists || []).join(" "), (s.lyricists || []).join(" "),
          (s.musicDirectors || []).join(" "), (s.genres || []).join(" "), s.language, s.year].join(" "))
      });
    });
    (data.albums || []).forEach(function (a) {
      var pop = Number(a.plays) || 0;
      maxima.album = Math.max(maxima.album, pop);
      records.push({
        type: "album", raw: a, id: a.slug, title: a.title, titleN: norm(a.title), pop: pop,
        year: toInt(a.year), release: a.release || "", lang: norm(a.language) || "telugu",
        genres: (a.genres || []).map(norm),
        href: a.path, art: a.artwork || "",
        sub: a.movieTitle + (a.year ? " · " + a.year : "") + " · " + a.songs + (a.songs === 1 ? " song" : " songs"),
        meta: pop ? formatCount(pop) : "",
        hay: norm([a.movieTitle, (a.musicDirectors || []).join(" "), (a.genres || []).join(" "), a.language, a.year].join(" "))
      });
    });
    (data.movies || []).forEach(function (m) {
      var pop = Number(m.imdbVotesNumeric) || 0;
      maxima.movie = Math.max(maxima.movie, pop);
      records.push({
        type: "movie", raw: m, id: m.slug, title: m.title, titleN: norm(m.title), pop: pop,
        year: toInt(m.year), release: m.released || (m.year ? m.year + "-01-01" : ""), lang: norm(m.originalLanguage) || "telugu",
        genres: (m.genres || []).map(norm),
        href: m.path, art: m.poster || m.artwork || "",
        sub: (m.year || "") + (m.originalLanguage ? " · " + m.originalLanguage : "") + " · " + m.songs + (m.songs === 1 ? " song" : " songs"),
        meta: m.imdbScore ? "★ " + m.imdbScore : "",
        hay: norm([m.telugu, (m.musicDirectors || []).join(" "), (m.directors || []).join(" "), (m.cast || []).join(" "),
          (m.genres || []).join(" "), m.originalLanguage, m.year, m.imdbId, m.universe, m.certification].join(" "))
      });
    });
    records.forEach(function (r) { r.popN = r.pop / maxima[r.type]; });
    var byId = {};
    (data.songs || []).forEach(function (s) { byId[s.id] = s; });
    return { records: records, songs: byId };
  }

  /* ------------------------------------------------------- search scoring */
  var TYPE_LABEL = { song: "Songs", album: "Albums", movie: "Movies" };
  var TYPE_SINGULAR = { song: "SONG", album: "ALBUM", movie: "MOVIE" };

  function emptyState() { return { q: "", type: "all", from: "", to: "", lang: "", genre: "", sort: "relevance" }; }
  function isActive(state) {
    return !!(state.q || state.from || state.to || state.lang || state.genre || state.type !== "all");
  }

  function scoreRecord(record, tokens) {
    var score = 0;
    for (var i = 0; i < tokens.length; i++) {
      var token = tokens[i], hit = 0;
      var at = record.titleN.indexOf(token);
      if (record.titleN === token) hit = 120;
      else if (at === 0) hit = 80;
      else if (at > 0 && record.titleN.charAt(at - 1) === " ") hit = 55;
      else if (at > 0) hit = 30;
      else if (record.hay.indexOf(token) !== -1) hit = 12;
      if (!hit) return 0;
      score += hit;
    }
    return score + record.popN * 6;
  }

  function runSearch(index, state) {
    var tokens = norm(state.q).split(/\s+/).filter(Boolean);
    var from = toInt(state.from), to = toInt(state.to);
    var lang = norm(state.lang), genre = norm(state.genre);
    var out = [];
    index.records.forEach(function (r) {
      if (state.type !== "all" && r.type !== state.type) return;
      if (from !== null && (r.year === null || r.year < from)) return;
      if (to !== null && (r.year === null || r.year > to)) return;
      if (lang && r.lang !== lang) return;
      if (genre && r.genres.indexOf(genre) === -1) return;
      var score = tokens.length ? scoreRecord(r, tokens) : 1 + r.popN;
      if (!score) return;
      out.push({ r: r, score: score });
    });
    var cmpTitle = function (a, b) { return a.r.titleN < b.r.titleN ? -1 : a.r.titleN > b.r.titleN ? 1 : 0; };
    var sorters = {
      relevance: function (a, b) { return b.score - a.score || cmpTitle(a, b); },
      popular: function (a, b) { return b.r.popN - a.r.popN || b.score - a.score || cmpTitle(a, b); },
      newest: function (a, b) { return (a.r.release < b.r.release ? 1 : a.r.release > b.r.release ? -1 : 0) || cmpTitle(a, b); },
      oldest: function (a, b) { return (a.r.release < b.r.release ? -1 : a.r.release > b.r.release ? 1 : 0) || cmpTitle(a, b); },
      title: cmpTitle
    };
    out.sort(sorters[state.sort] || sorters.relevance);
    return out;
  }

  /* ----------------------------------------------------- result renderers */
  function artMarkup(record, cls) {
    if (record.art) {
      return '<img class="' + cls + '" src="' + esc(safeUrl(record.art) || record.art) + '" alt="" width="56" height="56" loading="lazy" decoding="async" referrerpolicy="no-referrer">';
    }
    return '<span class="' + cls + ' sp-art" aria-hidden="true">' + icon("note") + "</span>";
  }
  function rowMarkup(entry) {
    var r = entry.r;
    return '<a class="sp-row" role="option" href="' + esc(r.href) + '" data-type="' + r.type + '" data-result>' + artMarkup(r, "sp-img") +
      '<span class="sp-copy"><span class="sp-title">' + esc(r.title) + '</span><span class="sp-sub">' + esc(TYPE_SINGULAR[r.type].charAt(0) + TYPE_SINGULAR[r.type].slice(1).toLowerCase() + " · " + r.sub) + "</span></span>" +
      '<span class="sp-meta">' + esc(r.meta) + "</span></a>";
  }
  function cardMarkup(entry) {
    var r = entry.r;
    return '<a class="advanced-result-card" href="' + esc(r.href) + '" data-type="' + r.type + '" data-result>' + artMarkup(r, "advanced-result-art") +
      '<span class="advanced-result-copy"><span class="advanced-result-type">' + TYPE_SINGULAR[r.type] + '</span><span class="advanced-result-title">' + esc(r.title) +
      '</span><span class="advanced-result-subtitle">' + esc(r.sub) + "</span></span>" + '<span class="advanced-result-arrow">' + icon("arrow") + "</span></a>";
  }

  /* ----------------------------------------------------- search controller */
  function searchUrl(state) {
    var params = new URLSearchParams();
    ["q", "type", "from", "to", "lang", "genre", "sort"].forEach(function (key) {
      var def = key === "type" ? "all" : key === "sort" ? "relevance" : "";
      if (state[key] && state[key] !== def) params.set(key, state[key]);
    });
    var text = params.toString();
    return "/advanced-search/" + (text ? "?" + text : "");
  }

  function initSearch(root, getIndex) {
    var mode = root.getAttribute("data-search-mode") || root.getAttribute("data-search-root");
    var input = $("[data-search-input]", root);
    if (!input) return;
    var optionsBox = $("[data-search-options]", root);
    var toggle = $("[data-filter-toggle]", root);
    var typeButtons = $$(".sp-type", root);
    var filters = {};
    $$("[data-filter]", root).forEach(function (el) { filters[el.getAttribute("data-filter")] = el; });
    var resetButton = $("[data-search-reset]", root);
    var popover = mode === "popover" ? $("#search-popover", root) : null;
    var targetId = root.getAttribute("data-search-target");
    var body = popover ? $("[data-search-body]", popover) : (targetId ? document.getElementById(targetId) : null);
    var countEl = mode === "page" ? $("[data-search-count]") : null;
    var emptyEl = mode === "page" ? document.getElementById("advanced-empty") : null;
    var statusEl = document.getElementById("status");
    var state = emptyState();
    var active = -1;

    function readControls() {
      state.q = input.value.trim();
      Object.keys(filters).forEach(function (key) { state[key] = filters[key].value; });
    }
    function writeControls() {
      input.value = state.q;
      Object.keys(filters).forEach(function (key) { filters[key].value = state[key]; });
      typeButtons.forEach(function (btn) {
        var on = btn.getAttribute("data-type") === state.type;
        btn.classList.toggle("is-active", on);
        btn.setAttribute("aria-pressed", on ? "true" : "false");
      });
    }
    function setOptionsOpen(open) {
      if (!optionsBox) return;
      optionsBox.hidden = !open;
      if (toggle) {
        toggle.setAttribute("aria-expanded", open ? "true" : "false");
        toggle.classList.toggle("is-active", open);
      }
    }
    function filterCount() {
      return ["from", "to", "lang", "genre"].filter(function (k) { return state[k]; }).length + (state.sort !== "relevance" ? 1 : 0);
    }
    function loadFromUrl() {
      var params = new URLSearchParams(window.location.search);
      var any = false;
      ["q", "type", "from", "to", "lang", "genre", "sort"].forEach(function (key) {
        var value = params.get(key);
        if (value != null && value !== "") { state[key] = value; any = true; }
      });
      if (["all", "song", "album", "movie"].indexOf(state.type) === -1) state.type = "all";
      if (["relevance", "popular", "newest", "oldest", "title"].indexOf(state.sort) === -1) state.sort = "relevance";
      return any;
    }
    function syncUrl() {
      if (mode === "popover" || !window.history.replaceState) return;
      var url = mode === "page" ? searchUrl(state) : (function () {
        var u = searchUrl(state).replace("/advanced-search/", window.location.pathname);
        return u;
      })();
      try { window.history.replaceState(null, "", url); } catch (error) {}
    }

    function setActive(next) {
      var rows = $$("[data-result]", body);
      if (!rows.length) { active = -1; return; }
      active = (next + rows.length) % rows.length;
      rows.forEach(function (row, i) { row.classList.toggle("is-active", i === active); row.setAttribute("aria-selected", i === active ? "true" : "false"); });
      rows[active].scrollIntoView({ block: "nearest" });
    }

    function renderPopover(results) {
      var html = "";
      var perType = state.type === "all" ? 4 : 8;
      var groups = { song: [], album: [], movie: [] };
      results.forEach(function (entry) { groups[entry.r.type].push(entry); });
      var order = state.type === "all" ? ["song", "album", "movie"] : [state.type];
      var shown = 0;
      order.forEach(function (type) {
        var list = groups[type].slice(0, perType);
        if (!list.length) return;
        shown += list.length;
        html += '<p class="sp-group">' + TYPE_LABEL[type] + "</p>" + list.map(rowMarkup).join("");
      });
      if (!shown) html = '<p class="sp-empty">No matches. Try another spelling, or widen the filters.</p>';
      else html += '<a class="sp-all" href="' + esc(searchUrl(state)) + '">See all ' + results.length + " results " + "→</a>";
      body.innerHTML = html;
      active = -1;
    }

    function renderGrouped(results) {
      var groups = { song: [], album: [], movie: [] };
      results.forEach(function (entry) { groups[entry.r.type].push(entry); });
      var html = "";
      ["song", "album", "movie"].forEach(function (type) {
        if (!groups[type].length) return;
        html += '<section class="results-group"><h2>' + TYPE_LABEL[type] + ' <small class="sub">' + groups[type].length + '</small></h2><div class="advanced-results-grid">' +
          groups[type].slice(0, 24).map(cardMarkup).join("") + "</div></section>";
      });
      body.innerHTML = html;
    }

    function renderFlat(results) {
      body.innerHTML = results.slice(0, 90).map(cardMarkup).join("");
    }

    function update(opts) {
      opts = opts || {};
      readControls();
      writeControls_types();
      if (toggle && mode === "popover") {
        toggle.classList.toggle("has-filters", filterCount() > 0);
      }
      if (mode === "popover") {
        openPopover();
        if (!isActive(state)) {
          // nothing typed yet: offer the most played songs
          getIndex().then(function (index) {
            if (isActive(readState())) return;
            var top = index.records.filter(function (r) { return r.type === "song"; }).sort(function (a, b) { return b.pop - a.pop; }).slice(0, 5)
              .map(function (r) { return { r: r }; });
            body.innerHTML = '<p class="sp-group">Most played</p>' + top.map(rowMarkup).join("");
            active = -1;
          }).catch(showError);
          return;
        }
      }
      if (!isActive(state)) {
        if (body) body.innerHTML = "";
        if (mode === "inline" && body) body.hidden = true;
        if (countEl) countEl.textContent = "Enter a term to search the archive.";
        if (emptyEl) emptyEl.hidden = true;
        if (statusEl) statusEl.textContent = "";
        if (!opts.silentUrl) syncUrl();
        return;
      }
      getIndex().then(function (index) {
        readControls();
        var results = runSearch(index, state);
        if (mode === "popover") renderPopover(results);
        else if (mode === "inline") {
          body.hidden = false;
          if (results.length) renderGrouped(results);
          else body.innerHTML = '<p class="empty">No matches. Try another spelling, or widen the filters.</p>';
        } else {
          if (results.length) renderFlat(results); else body.innerHTML = "";
          if (emptyEl) emptyEl.hidden = results.length > 0;
        }
        var text = results.length + (results.length === 1 ? " result" : " results");
        if (countEl) countEl.textContent = text + (results.length > 90 ? " (showing the first 90)" : "");
        if (statusEl) statusEl.textContent = text;
        if (!opts.silentUrl) syncUrl();
      }).catch(showError);
    }
    function readState() { readControls(); return state; }
    function writeControls_types() {
      typeButtons.forEach(function (btn) {
        var on = btn.getAttribute("data-type") === state.type;
        btn.classList.toggle("is-active", on);
        btn.setAttribute("aria-pressed", on ? "true" : "false");
      });
    }
    function showError() {
      if (body) {
        body.hidden = false;
        body.innerHTML = '<p class="sp-empty">Search is unavailable right now. Please try again in a moment.</p>';
      }
    }

    function openPopover() {
      if (!popover || !popover.hidden) return;
      popover.hidden = false;
      input.setAttribute("aria-expanded", "true");
    }
    function closePopover() {
      if (!popover || popover.hidden) return;
      popover.hidden = true;
      input.setAttribute("aria-expanded", "false");
      active = -1;
    }

    var debounced = debounce(function () { update(); }, 90);

    input.addEventListener("input", debounced);
    input.addEventListener("focus", function () {
      getIndex().catch(function () {});
      if (mode === "popover") update({ silentUrl: true });
    });
    typeButtons.forEach(function (btn) {
      btn.addEventListener("click", function () { state.type = btn.getAttribute("data-type"); update(); if (mode !== "page") input.focus(); });
    });
    Object.keys(filters).forEach(function (key) {
      filters[key].addEventListener(filters[key].tagName === "SELECT" ? "change" : "input", debounced);
    });
    if (resetButton) {
      resetButton.addEventListener("click", function () {
        var keep = state.q;
        state = emptyState();
        state.q = keep;
        writeControls();
        update();
      });
    }
    if (toggle) {
      toggle.addEventListener("click", function () {
        var open = optionsBox ? optionsBox.hidden : false;
        if (mode === "popover") openPopover();
        setOptionsOpen(open);
        if (mode === "popover") update({ silentUrl: true });
      });
    }

    root.addEventListener("submit", function (event) {
      event.preventDefault();
      readControls();
      if (mode === "popover") {
        window.location.href = searchUrl(state);
        return;
      }
      update();
      if (mode === "inline" && body && !body.hidden) body.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "start" });
    });

    if (mode === "popover") {
      input.addEventListener("keydown", function (event) {
        if (event.key === "ArrowDown") { event.preventDefault(); openPopover(); setActive(active + 1); }
        else if (event.key === "ArrowUp") { event.preventDefault(); setActive(active - 1); }
        else if (event.key === "Enter") {
          event.preventDefault();
          var rows = $$("[data-result]", body);
          if (active >= 0 && rows[active]) rows[active].click();
          else { readControls(); window.location.href = searchUrl(state); }
        } else if (event.key === "Escape") { closePopover(); }
      });
      // the popover form has no submit button, so Enter in its filter fields is handled here
      root.addEventListener("keydown", function (event) {
        if (event.key === "Enter" && event.target !== input && event.target.tagName === "INPUT") {
          event.preventDefault();
          readControls();
          window.location.href = searchUrl(state);
        }
      });
      document.addEventListener("click", function (event) {
        if (!root.contains(event.target)) closePopover();
      });
      document.addEventListener("keydown", function (event) {
        if (event.key === "Escape" && popover && !popover.hidden) { event.vkHandled = true; closePopover(); }
      });
      root.addEventListener("click", function (event) {
        if (event.target.closest && event.target.closest("[data-result], .sp-all")) closePopover();
      });
      // "/" focuses search from anywhere outside a field
      document.addEventListener("keydown", function (event) {
        var tag = (event.target.tagName || "").toLowerCase();
        if (event.key === "/" && !event.metaKey && !event.ctrlKey && tag !== "input" && tag !== "textarea" && tag !== "select") {
          event.preventDefault();
          input.focus();
          input.select();
        }
      });
    }

    // initial state
    if (mode !== "popover") {
      var hadParams = loadFromUrl();
      writeControls();
      if (mode === "page") setOptionsOpen(true);
      else if (filterCount() > 0 || state.type !== "all") setOptionsOpen(true);
      if (hadParams || isActive(state)) update({ silentUrl: true });
    }
  }

  /* ------------------------------------------------------- catalogue lists */
  function initCatalogue(config) {
    var grid = document.getElementById(config.grid);
    if (!grid) return;
    var items = $$(config.item, grid);
    var emptyEl = document.getElementById(config.empty);
    var countEl = document.getElementById(config.count);
    var summaryEl = document.getElementById(config.summary);
    var controls = {};
    Object.keys(config.controls).forEach(function (key) { controls[key] = document.getElementById(config.controls[key]); });
    var originalOrder = items.slice();

    function tokens(item, attr) { return (item.getAttribute(attr) || "").split("|"); }
    function num(item, attr) { return Number(item.getAttribute(attr)) || 0; }
    function str(item, attr) { return item.getAttribute(attr) || ""; }

    function apply() {
      var q = norm(controls.query ? controls.query.value : "");
      var qTokens = q.split(/\s+/).filter(Boolean);
      var from = controls.from ? toInt(controls.from.value) : null;
      var to = controls.to ? toInt(controls.to.value) : null;
      var sort = controls.sort ? controls.sort.value : config.defaultSort;
      var visible = [];
      items.forEach(function (item) {
        var ok = true;
        if (qTokens.length) {
          var hay = norm(config.search.map(function (attr) { return str(item, attr).replace(/\|/g, " "); }).join(" "));
          ok = qTokens.every(function (t) { return hay.indexOf(t) !== -1; });
        }
        if (ok) {
          Object.keys(config.match).forEach(function (key) {
            if (!ok || !controls[key]) return;
            var value = controls[key].value;
            if (!value) return;
            var spec = config.match[key];
            var have = tokens(item, spec.attr);
            if (have.indexOf(value) === -1) ok = false;
          });
        }
        if (ok && (from !== null || to !== null)) {
          var year = toInt(item.getAttribute("data-year"));
          if (year === null) ok = false;
          else if (from !== null && year < from) ok = false;
          else if (to !== null && year > to) ok = false;
        }
        item.hidden = !ok;
        if (ok) visible.push(item);
      });

      var byTitle = function (a, b) { var x = str(a, "data-title"), y = str(b, "data-title"); return x < y ? -1 : x > y ? 1 : 0; };
      var sorters = {
        "plays": function (a, b) { return num(b, "data-plays") - num(a, "data-plays") || byTitle(a, b); },
        "imdb-votes": function (a, b) { return num(b, "data-imdb-votes") - num(a, "data-imdb-votes") || byTitle(a, b); },
        "rating": function (a, b) { return num(b, "data-rating") - num(a, "data-rating") || num(b, "data-imdb-votes") - num(a, "data-imdb-votes") || byTitle(a, b); },
        "weighted": function (a, b) { return num(b, "data-weighted") - num(a, "data-weighted") || byTitle(a, b); },
        "release-new": function (a, b) { return str(b, "data-release") < str(a, "data-release") ? -1 : str(b, "data-release") > str(a, "data-release") ? 1 : byTitle(a, b); },
        "release-old": function (a, b) { return str(a, "data-release") < str(b, "data-release") ? -1 : str(a, "data-release") > str(b, "data-release") ? 1 : byTitle(a, b); },
        "title-az": byTitle,
        "title-za": function (a, b) { return byTitle(b, a); },
        "songs": function (a, b) { return num(b, "data-songs") - num(a, "data-songs") || byTitle(a, b); }
      };
      var sorter = sorters[sort] || sorters[config.defaultSort];
      var ordered = items.slice().sort(sorter);
      var fragment = document.createDocumentFragment();
      ordered.forEach(function (item) { fragment.appendChild(item); });
      grid.appendChild(fragment);

      var position = 0;
      var rankSorts = config.rankSorts || [];
      ordered.forEach(function (item) {
        if (item.hidden) return;
        position += 1;
        if (config.renumber) {
          var n = $(".n", item);
          if (n) n.textContent = position;
        }
        if (config.rankBadge) {
          var badge = $("[data-rank]", item);
          if (badge) badge.textContent = rankSorts.indexOf(sort) !== -1 ? position : "";
        }
      });

      var label = config.noun[visible.length === 1 ? 0 : 1];
      var text = visible.length + " " + label;
      if (countEl) countEl.textContent = text;
      if (summaryEl) summaryEl.textContent = text;
      if (emptyEl) emptyEl.hidden = visible.length > 0;
      grid.hidden = visible.length === 0;
    }

    var debounced = debounce(apply, 80);
    Object.keys(controls).forEach(function (key) {
      var el = controls[key];
      if (!el) return;
      el.addEventListener(el.tagName === "SELECT" ? "change" : "input", debounced);
    });
    var params = new URLSearchParams(window.location.search);
    if (controls.query && params.get("q")) controls.query.value = params.get("q");
    void originalOrder;
    apply();
  }

  function initCatalogues() {
    initCatalogue({
      grid: "song-grid", item: "li.song-catalog-item", empty: "song-empty", count: "song-count", summary: "song-filter-summary-count",
      controls: { query: "song-query", sort: "song-sort", artist: "song-artist", lyricist: "song-lyricist", music: "song-music", lang: "song-lang", genre: "song-genre", from: "song-from", to: "song-to" },
      match: { artist: { attr: "data-artists" }, lyricist: { attr: "data-lyricists" }, music: { attr: "data-music" }, lang: { attr: "data-lang" }, genre: { attr: "data-genre" } },
      search: ["data-title", "data-artists", "data-lyricists", "data-movie", "data-album", "data-music"],
      defaultSort: "plays", renumber: true, noun: ["song", "songs"]
    });
    initCatalogue({
      grid: "album-grid", item: "li.album-item", empty: "album-empty", count: "album-count", summary: "album-filter-summary-count",
      controls: { query: "album-query", sort: "album-sort", artist: "album-artist", genre: "album-genre", lang: "album-lang", from: "album-from", to: "album-to" },
      match: { artist: { attr: "data-artist" }, genre: { attr: "data-genre" }, lang: { attr: "data-lang" } },
      search: ["data-title", "data-artist"],
      defaultSort: "plays", noun: ["album", "albums"]
    });
    initCatalogue({
      grid: "movie-grid", item: "li.movie-item", empty: "movie-empty", count: "movie-count", summary: "movie-filter-summary-count",
      controls: { query: "movie-query", sort: "movie-sort", lang: "movie-lang", genre: "movie-genre", music: "movie-music", director: "movie-director", universe: "movie-universe", from: "movie-from", to: "movie-to" },
      match: { lang: { attr: "data-lang" }, genre: { attr: "data-genre" }, music: { attr: "data-music" }, director: { attr: "data-director" }, universe: { attr: "data-universe" } },
      search: ["data-title", "data-director", "data-music"],
      defaultSort: "imdb-votes", rankBadge: true, rankSorts: ["imdb-votes", "rating", "weighted"], noun: ["movie", "movies"]
    });
  }

  /* --------------------------------------------------------------- charts */
  function initCharts() {
    var tabs = $$("[data-chart-tab]");
    if (tabs.length) {
      var panels = $$("[data-chart-panel]");
      var select = function (name, updateHash) {
        tabs.forEach(function (tab) {
          var on = tab.getAttribute("data-chart-tab") === name;
          tab.classList.toggle("is-active", on);
          tab.setAttribute("aria-selected", on ? "true" : "false");
        });
        panels.forEach(function (panel) {
          var on = panel.getAttribute("data-chart-panel") === name;
          panel.hidden = !on;
          panel.classList.toggle("is-active", on);
        });
        if (updateHash && window.history.replaceState) {
          try { window.history.replaceState(null, "", "#" + name); } catch (error) {}
        }
      };
      tabs.forEach(function (tab) {
        tab.addEventListener("click", function () { select(tab.getAttribute("data-chart-tab"), true); });
      });
      var initial = window.location.hash.replace("#", "");
      if (tabs.some(function (t) { return t.getAttribute("data-chart-tab") === initial; })) select(initial, false);
    }
    var views = $$("[data-chart-view]");
    views.forEach(function (button) {
      button.addEventListener("click", function () {
        var name = button.getAttribute("data-chart-view");
        views.forEach(function (b) {
          var on = b === button;
          b.classList.toggle("is-active", on);
          b.setAttribute("aria-pressed", on ? "true" : "false");
        });
        $$("[data-chart-list]").forEach(function (list) { list.hidden = list.getAttribute("data-chart-list") !== name; });
      });
    });
  }

  /* ---------------------------------------------------------------- theme */
  function initTheme() {
    var button = document.getElementById("theme-toggle");
    if (!button) return;
    var root = document.documentElement;
    var sync = function () {
      var dark = root.getAttribute("data-theme") !== "light";
      button.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
      button.title = dark ? "Switch to light theme" : "Switch to dark theme";
      var meta = $('meta[name="theme-color"]');
      if (meta) meta.setAttribute("content", dark ? "#050505" : "#f3f3f1");
    };
    sync();
    button.addEventListener("click", function () {
      var next = root.getAttribute("data-theme") === "light" ? "dark" : "light";
      root.setAttribute("data-theme", next);
      store("vachikatelugu-theme", next);
      sync();
    });
  }

  /* --------------------------------------------------------------- lyrics */
  function initLyrics(scope) {
    $$("[data-lyrics]", scope).forEach(function (section) {
      var toggle = $("[data-lyrics-toggle]", section);
      var panel = $(".lyrics-panel", section);
      var times = $("[data-lyrics-times]", section);
      if (toggle) {
        var label = $("[data-label]", toggle);
        var apply = function (hidden) {
          section.classList.toggle("is-collapsed", hidden);
          toggle.setAttribute("aria-expanded", hidden ? "false" : "true");
          if (label) label.textContent = hidden ? "Show lyrics" : "Hide lyrics";
        };
        apply(store("vachikatelugu-lyrics") === "hidden");
        toggle.addEventListener("click", function () {
          var hide = !section.classList.contains("is-collapsed");
          apply(hide);
          store("vachikatelugu-lyrics", hide ? "hidden" : "shown");
        });
      }
      var sizes = [0.85, 1, 1.15, 1.3, 1.55];
      var sizeIndex = toInt(store("vachikatelugu-lyric-size"));
      if (sizeIndex === null || sizeIndex < 0 || sizeIndex >= sizes.length) sizeIndex = 1;
      section.style.setProperty("--lyric-scale", sizes[sizeIndex]);
      $$("[data-lyrics-size]", section).forEach(function (button) {
        button.addEventListener("click", function () {
          sizeIndex = Math.max(0, Math.min(sizes.length - 1, sizeIndex + toInt(button.getAttribute("data-lyrics-size"))));
          section.style.setProperty("--lyric-scale", sizes[sizeIndex]);
          store("vachikatelugu-lyric-size", String(sizeIndex));
        });
      });
      var copyButton = $("[data-lyrics-copy]", section);
      if (copyButton && panel) {
        copyButton.addEventListener("click", function () {
          var blocks = $$(".stanza, .lyrics-lines", panel).map(function (block) {
            return $$(".lyrics-text", block).map(function (line) { return line.textContent.trim(); }).join("\n");
          });
          if (!blocks.length) blocks = [panel.innerText.trim()];
          copyText(blocks.join("\n\n"), copyButton);
        });
      }
      if (panel) {
        panel.addEventListener("click", function (event) {
          var line = event.target.closest && event.target.closest(".lyrics-text");
          if (line) line.classList.toggle("is-lit");
        });
      }
      if (times && panel) {
        var applyTimes = function (on) {
          panel.classList.toggle("show-times", on);
          times.setAttribute("aria-pressed", on ? "true" : "false");
          times.classList.toggle("is-active", on);
        };
        applyTimes(store("vachikatelugu-times") === "on");
        times.addEventListener("click", function () {
          var on = !panel.classList.contains("show-times");
          applyTimes(on);
          store("vachikatelugu-times", on ? "on" : "off");
        });
      }
    });
  }

  /* ------------------------------------------------ embeds and copy link */
  function embedSrc(kind, id) {
    if (!/^[A-Za-z0-9_-]{4,40}$/.test(id || "")) return "";
    if (kind === "spotify") return "https://open.spotify.com/embed/track/" + id + "?utm_source=generator&theme=0";
    return "https://www.youtube-nocookie.com/embed/" + id + "?autoplay=1&rel=0";
  }
  function makeFrame(kind, id, title) {
    var src = embedSrc(kind, id);
    if (!src) return null;
    var frame = document.createElement("iframe");
    frame.className = kind === "spotify" ? "spotify" : "youtube";
    frame.src = src;
    frame.title = title || "Player";
    frame.loading = "lazy";
    frame.allow = "autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture";
    frame.setAttribute("allowfullscreen", "");
    return frame;
  }
  function flashCopied(button) {
    var span = $("span", button);
    var original = span ? span.textContent : "";
    button.classList.add("is-copied");
    if (span) span.textContent = "Copied";
    setTimeout(function () { button.classList.remove("is-copied"); if (span) span.textContent = original; }, 1600);
  }
  function copyText(text, button) {
    var done = function () { flashCopied(button); };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, function () { fallbackCopy(text); done(); });
    } else { fallbackCopy(text); done(); }
  }
  function fallbackCopy(text) {
    var area = document.createElement("textarea");
    area.value = text; area.setAttribute("readonly", ""); area.style.position = "fixed"; area.style.opacity = "0";
    document.body.appendChild(area); area.select();
    try { document.execCommand("copy"); } catch (error) {}
    document.body.removeChild(area);
  }

  function initActions() {
    document.addEventListener("click", function (event) {
      var embed = event.target.closest && event.target.closest("[data-embed]");
      if (embed) {
        var kind = embed.getAttribute("data-embed");
        var frame = makeFrame(kind, embed.getAttribute("data-id"), embed.getAttribute("aria-label") || "Player");
        if (!frame) return;
        if (embed.closest(".trailer")) {
          var host = embed.closest(".trailer");
          host.innerHTML = "";
          host.appendChild(frame);
        } else {
          var slot = embed.closest(".dr-actions") ? $(".dr-player", embed.closest(".drawer-body, #drawer-body")) : null;
          if (!slot) {
            var after = embed.closest(".actions");
            slot = after && after.nextElementSibling && after.nextElementSibling.classList.contains("player-embed") ? after.nextElementSibling : null;
            if (!slot && after) {
              slot = document.createElement("div");
              slot.className = "player-embed";
              after.parentNode.insertBefore(slot, after.nextSibling);
            }
          }
          if (slot) {
            slot.innerHTML = "";
            slot.appendChild(frame);
            embed.hidden = true;
          }
        }
        return;
      }
      var copy = event.target.closest && event.target.closest("[data-copy-link]");
      if (copy) {
        copyText(copy.getAttribute("data-copy-link") || window.location.href.split("#")[0], copy);
      }
    });
  }

  /* --------------------------------------------------------------- drawer */
  function initDrawer(getIndex) {
    var drawer = document.getElementById("song-drawer");
    var body = document.getElementById("drawer-body");
    var closeBtn = document.getElementById("drawer-close");
    if (!drawer || !body || !closeBtn) return;
    if (document.body.getAttribute("data-page") === "song") return;
    var media = window.matchMedia(DRAWER_QUERY);
    var scroller = $(".drawer-scroll", drawer);
    var lastFocus = null;
    var currentId = null;
    var token = 0;
    var lyricsCache = {};

    function isOpen() { return drawer.classList.contains("is-open"); }

    function markRows() {
      $$('a[aria-current="true"][data-drawer-row]').forEach(function (a) { a.removeAttribute("aria-current"); a.removeAttribute("data-drawer-row"); });
      if (!currentId) return;
      $$('.tracks a[href="/song/' + currentId + '/"]').forEach(function (a) {
        a.setAttribute("aria-current", "true");
        a.setAttribute("data-drawer-row", "");
      });
    }

    function listenLinks(s) {
      var links = [];
      if (s.spotifyUrl) links.push('<a class="listen-link spotify" href="' + esc(safeUrl(s.spotifyUrl)) + '" target="_blank" rel="noopener noreferrer">' + providerIcon("spotify") + '<span class="ll-copy"><strong>Spotify</strong><small>Open the track</small></span>' + icon("arrow").replace('class="icon"', 'class="icon ll-arrow"') + "</a>");
      if (s.ytmUrl) links.push('<a class="listen-link ytmusic" href="' + esc(safeUrl(s.ytmUrl)) + '" target="_blank" rel="noopener noreferrer">' + providerIcon("ytmusic") + '<span class="ll-copy"><strong>YouTube Music</strong><small>' + esc(s.ytmPlays || "Open the track") + "</small></span>" + icon("arrow").replace('class="icon"', 'class="icon ll-arrow"') + "</a>");
      if (s.youtubeVideoUrl) links.push('<a class="listen-link youtube" href="' + esc(safeUrl(s.youtubeVideoUrl)) + '" target="_blank" rel="noopener noreferrer">' + providerIcon("youtube") + '<span class="ll-copy"><strong>YouTube</strong><small>' + esc(s.youtubeVideoViews ? s.youtubeVideoViews + " views" : "Watch the video") + "</small></span>" + icon("arrow").replace('class="icon"', 'class="icon ll-arrow"') + "</a>");
      return links.length ? '<div class="listen-links">' + links.join("") + "</div>" : "";
    }

    function factRows(s) {
      var rows = [];
      var add = function (label, html) { if (html) rows.push("<dt>" + esc(label) + "</dt><dd>" + html + "</dd>"); };
      add((s.lyricists || []).length === 1 ? "Lyricist" : "Lyricists", personLinks(s.lyricists));
      add("Music", personLinks(s.musicDirectors));
      add("Film", '<a href="' + esc(s.moviePath) + '">' + esc(s.movieTitle) + "</a> (" + esc(s.year) + ")");
      add("Album", s.albumPath ? '<a href="' + esc(s.albumPath) + '">' + esc(s.albumTitle) + "</a>" : "");
      if (s.albumRelease) {
        var d = new Date(s.albumRelease + "T00:00:00");
        add("Album release", isNaN(d) ? esc(s.albumRelease) : esc(d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })));
      }
      add("Film language", esc(s.language));
      add("Duration", esc(s.duration));
      if (s.number != null && s.songCount) add("Track", esc(s.number + " of " + s.songCount));
      if (s.discNumber && s.discNumber !== 1) add("Disc", esc(s.discNumber));
      add((s.genres || []).length === 1 ? "Genre" : "Genres", esc((s.genres || []).join(", ")));
      add("ISRC", esc(s.isrc));
      return rows.length ? '<dl class="facts">' + rows.join("") + "</dl>" : "";
    }

    function render(s) {
      var canPlay = s.spotifyId || s.ytmId;
      var flags = (s.explicit ? ' <span class="flag">Explicit</span>' : "") + (s.instrumental ? ' <span class="flag">Instrumental</span>' : "");
      var art = s.artwork || s.poster;
      var html = "";
      html += art ? '<img class="dr-art" src="' + esc(art) + '" alt="" width="640" height="640" referrerpolicy="no-referrer" decoding="async">' : "";
      html += '<h2 class="dr-title">' + esc(s.title) + "</h2>";
      html += '<p class="dr-film">From <a href="' + esc(s.moviePath) + '">' + esc(s.movieTitle) + "</a> · " + esc(s.year) + flags + "</p>";
      if ((s.artists || []).length) html += '<p class="dr-singers">' + personLinks(s.artists) + "</p>";
      html += listenLinks(s);
      html += '<div class="dr-actions">';
      if (canPlay) html += '<button type="button" class="btn" data-embed="' + (s.spotifyId ? "spotify" : "youtube") + '" data-id="' + esc(s.spotifyId || s.ytmId) + '">' + icon("play") + "<span>Play here</span></button>";
      html += '<button type="button" class="btn" data-copy-link="' + esc(window.location.origin + "/song/" + s.id + "/") + '">' + icon("link") + "<span>Copy link</span></button></div>";
      html += '<div class="dr-player"></div>';
      var facts = factRows(s);
      if (facts) html += '<div class="dr-facts">' + facts + "</div>";
      if (s.hasLyrics) {
        html += '<div class="dr-lyrics" data-lyrics><div class="dr-lyrics-head"><h3>Lyrics</h3><button type="button" class="chip-button" data-lyrics-toggle aria-expanded="true"><span data-label>Hide lyrics</span>' + icon("chevron") + "</button></div>" +
          '<div class="lyrics-panel" aria-live="polite"><p class="dr-note">Loading lyrics…</p></div></div>';
      }
      html += '<div class="dr-footer"><a class="btn primary" href="/song/' + esc(s.id) + '/">Open the full song page ' + icon("arrow") + "</a></div>";
      body.innerHTML = html;
      initLyrics(body);
      // the drawer reuses the lyrics preference but keeps the panel visible by default on first open
      if (s.hasLyrics) loadLyrics(s);
    }

    function loadLyrics(s) {
      var panel = $(".lyrics-panel", body);
      if (!panel) return;
      var mine = token;
      var show = function (markup) {
        if (mine !== token) return;
        panel.innerHTML = markup;
      };
      if (lyricsCache[s.id]) { show(lyricsCache[s.id]); return; }
      fetch("/song/" + s.id + "/", { credentials: "same-origin" })
        .then(function (response) { if (!response.ok) throw new Error("page " + response.status); return response.text(); })
        .then(function (html) {
          var doc = new DOMParser().parseFromString(html, "text/html");
          var source = doc.querySelector("#lyrics-panel");
          if (!source) throw new Error("no lyrics");
          lyricsCache[s.id] = source.innerHTML;
          show(lyricsCache[s.id]);
        })
        .catch(function () { show('<p class="dr-note">Lyrics could not be loaded. <a href="/song/' + esc(s.id) + '/">Open the song page</a>.</p>'); });
    }

    function open(id, opener) {
      token += 1;
      var mine = token;
      return getIndex().then(function (index) {
        if (mine !== token) return;
        var song = index.songs[id];
        if (!song) { window.location.href = "/song/" + id + "/"; return; }
        if (!isOpen()) lastFocus = opener || document.activeElement;
        currentId = id;
        render(song);
        drawer.removeAttribute("inert");
        drawer.setAttribute("aria-hidden", "false");
        drawer.classList.add("is-open");
        document.body.classList.add("drawer-open");
        if (scroller) scroller.scrollTop = 0;
        markRows();
        closeBtn.focus({ preventScroll: true });
      }).catch(function () { window.location.href = "/song/" + id + "/"; });
    }

    function close(restoreFocus) {
      if (!isOpen()) return;
      token += 1;
      drawer.classList.remove("is-open");
      drawer.setAttribute("aria-hidden", "true");
      drawer.setAttribute("inert", "");
      document.body.classList.remove("drawer-open");
      currentId = null;
      markRows();
      if (restoreFocus !== false && lastFocus && document.contains(lastFocus) && lastFocus.focus) lastFocus.focus({ preventScroll: true });
      lastFocus = null;
    }

    document.addEventListener("click", function (event) {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      if (!media.matches) return;
      var link = event.target.closest && event.target.closest("a[href]");
      if (!link || drawer.contains(link) || link.target === "_blank") return;
      var match = /^\/song\/([A-Za-z0-9_-]+)\/?$/.exec(link.getAttribute("href") || "");
      if (!match) return;
      event.preventDefault();
      if (isOpen() && currentId === match[1]) return;
      open(match[1], link);
    });
    closeBtn.addEventListener("click", function () { close(true); });
    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape" || !isOpen() || event.vkHandled) return;
      close(true);
    });
    var onChange = function () { if (!media.matches) close(false); };
    if (media.addEventListener) media.addEventListener("change", onChange); else if (media.addListener) media.addListener(onChange);
  }

  /* ------------------------------------------------- reveal and 3D motion */
  function initReveal() {
    // detail pages and grids reveal the same way as the home sections
    var auto = [".song-col-main > .card", ".song-col-side > .card", ".album-layout > *", ".movie-body > section",
      ".movie-columns > div > *", ".movies-grid > li", ".albums-grid-large > li", ".filter-panel"];
    auto.forEach(function (selector) {
      $$(selector).forEach(function (el, i) {
        if (el.hasAttribute("data-reveal")) return;
        el.setAttribute("data-reveal", "");
        el.style.setProperty("--n", String(i % 5));
        var box = el.getBoundingClientRect();
        if (box.top < window.innerHeight * 0.95 && box.bottom > 0) el.classList.add("is-visible");
      });
    });
    var targets = $$("[data-reveal]");
    targets.forEach(function (section) {
      $$(".tracks > li", section).forEach(function (el, i) { el.style.setProperty("--n", Math.min(i, 12)); });
    });
    if (!targets.length) return;
    if (!("IntersectionObserver" in window) || reducedMotion) {
      targets.forEach(function (el) { el.classList.add("is-visible"); });
      return;
    }
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      });
    }, { threshold: 0.1, rootMargin: "0px 0px -6% 0px" });
    targets.forEach(function (el) { if (!el.classList.contains("is-visible")) observer.observe(el); });
  }

  // Hero: a draggable 3D stack of covers. Swipe, drag, scroll sideways or tap a cover.
  function initStage() {
    var hero = document.getElementById("hero");
    var wrap = document.getElementById("hero-stage");
    var stage = document.getElementById("stage");
    if (!hero || !wrap || !stage) return;
    var cards = $$(".stage-card", stage);
    var count = cards.length;
    if (count < 2) return;
    var pos = 0, startX = 0, startPos = 0, pointerId = null, dragging = false, suppress = false;
    var lastTouch = 0, visible = true, hovering = false, wheelAt = 0;

    function wrapOffset(d) { return ((d + count / 2) % count + count) % count - count / 2; }
    function paint() {
      cards.forEach(function (card, i) {
        var d = wrapOffset(i - pos), ad = Math.abs(d);
        card.style.setProperty("--d", d.toFixed(3));
        card.style.setProperty("--ad", ad.toFixed(3));
        card.style.zIndex = String(100 - Math.round(ad * 10));
        card.classList.toggle("is-front", ad < 0.5);
      });
    }
    function step() { return Math.max(60, cards[0].offsetWidth * 0.42); }
    function snap(delta) { pos = Math.round(pos) + (delta || 0); paint(); }

    wrap.addEventListener("pointerdown", function (event) {
      if (event.button !== 0 && event.pointerType === "mouse") return;
      pointerId = event.pointerId; startX = event.clientX; startPos = pos; dragging = false; suppress = false;
      lastTouch = Date.now();
    });
    wrap.addEventListener("pointermove", function (event) {
      if (pointerId !== event.pointerId) return;
      var dx = event.clientX - startX;
      if (!dragging && Math.abs(dx) > 7) {
        dragging = true; suppress = true;
        wrap.classList.add("is-dragging");
        try { wrap.setPointerCapture(event.pointerId); } catch (error) {}
      }
      if (dragging) { pos = startPos - dx / step(); paint(); lastTouch = Date.now(); }
    });
    function end(event) {
      if (pointerId !== event.pointerId) return;
      pointerId = null;
      if (dragging) { dragging = false; wrap.classList.remove("is-dragging"); snap(); }
      setTimeout(function () { suppress = false; }, 0);
    }
    wrap.addEventListener("pointerup", end);
    wrap.addEventListener("pointercancel", end);
    wrap.addEventListener("click", function (event) {
      var card = event.target.closest && event.target.closest(".stage-card");
      if (suppress) { event.preventDefault(); return; }
      if (card && !card.classList.contains("is-front")) {
        event.preventDefault();
        var d = wrapOffset(cards.indexOf(card) - pos);
        snap(Math.round(d));
        lastTouch = Date.now();
      }
    });
    wrap.addEventListener("wheel", function (event) {
      if (Math.abs(event.deltaX) <= Math.abs(event.deltaY) || Math.abs(event.deltaX) < 12) return;
      event.preventDefault();
      var now = Date.now();
      if (now - wheelAt < 260) return;
      wheelAt = now; lastTouch = now;
      snap(event.deltaX > 0 ? 1 : -1);
    }, { passive: false });
    paint();

    if (reducedMotion) return;
    if ("IntersectionObserver" in window) {
      new IntersectionObserver(function (entries) { visible = entries[0].isIntersecting; }).observe(hero);
    }
    wrap.addEventListener("pointerenter", function (event) { if (event.pointerType === "mouse") hovering = true; });
    wrap.addEventListener("pointerleave", function () { hovering = false; });
    setInterval(function () {
      if (!visible || hovering || dragging || document.hidden || Date.now() - lastTouch < 6000) return;
      snap(1);
    }, 3400);

    // scroll tips the stack back; the pointer tilts it (desktop)
    var frame = 0;
    function onScroll() {
      if (frame) return;
      frame = requestAnimationFrame(function () {
        frame = 0;
        var progress = Math.min(1, Math.max(0, window.scrollY / Math.max(240, hero.offsetHeight * 0.8)));
        wrap.style.setProperty("--sp", progress.toFixed(3));
      });
    }
    window.addEventListener("scroll", onScroll, { passive: true });
    if (window.matchMedia("(hover: hover)").matches) {
      hero.addEventListener("pointermove", function (event) {
        if (dragging || event.pointerType !== "mouse") return;
        var box = hero.getBoundingClientRect();
        var x = (event.clientX - box.left) / box.width - 0.5;
        var y = (event.clientY - box.top) / box.height - 0.5;
        stage.style.setProperty("--ry", (x * 18).toFixed(2) + "deg");
        stage.style.setProperty("--rx", (6 - y * 12).toFixed(2) + "deg");
      });
      hero.addEventListener("pointerleave", function () {
        stage.style.removeProperty("--ry");
        stage.style.removeProperty("--rx");
      });
    }
  }

  // Coverflow (albums) and rail (movies): items rotate in depth as they pass the centre while scrolling.
  function initFlow() {
    $$("[data-flow]").forEach(function (box) {
      var kind = box.getAttribute("data-flow");
      var items = $$(".flow-item", box);
      if (!items.length) return;
      var scope = box.closest(".home-section") || document;
      var info = $("[data-flow-info]", scope);
      var offsets = [], active = -1, queued = false, moved = false;

      function spacing() { return items.length > 1 ? Math.abs(items[1].offsetLeft - items[0].offsetLeft) || items[0].offsetWidth : items[0].offsetWidth; }
      function update() {
        queued = false;
        var center = box.scrollLeft + box.clientWidth / 2, unit = spacing(), best = 0, bestDistance = 1e9;
        items.forEach(function (item, i) {
          var o = (item.offsetLeft + item.offsetWidth / 2 - center) / unit;
          var clamp = kind === "cover" ? 1 : 2;
          item.style.setProperty("--o", o.toFixed(3));
          item.style.setProperty("--co", Math.max(-clamp, Math.min(clamp, o)).toFixed(3));
          item.style.setProperty("--ao", Math.min(Math.abs(o), 4).toFixed(3));
          item.style.setProperty("--z", String(Math.max(1, 100 - Math.round(Math.abs(o) * 10))));
          if (Math.abs(o) < bestDistance) { bestDistance = Math.abs(o); best = i; }
        });
        if (best !== active) {
          if (active >= 0) items[active].classList.remove("is-active");
          active = best;
          items[active].classList.add("is-active");
          if (info) {
            var item = items[active];
            $(".flow-title", info).textContent = item.getAttribute("data-title") || "";
            $(".flow-sub", info).textContent = item.getAttribute("data-sub") || "";
            var open = $(".flow-open", info);
            if (open && item.getAttribute("data-href")) open.setAttribute("href", item.getAttribute("data-href"));
          }
        }
      }
      function request() { if (!queued) { queued = true; requestAnimationFrame(update); } }
      function centerOn(index, smooth) {
        index = Math.max(0, Math.min(items.length - 1, index));
        var item = items[index];
        box.scrollTo({ left: item.offsetLeft + item.offsetWidth / 2 - box.clientWidth / 2, behavior: smooth === false || reducedMotion ? "auto" : "smooth" });
      }
      box.addEventListener("scroll", request, { passive: true });
      window.addEventListener("resize", request);
      update();

      if (kind !== "cover") return;
      // mouse dragging (touch scrolls natively)
      var down = null;
      box.addEventListener("pointerdown", function (event) {
        if (event.pointerType !== "mouse" || event.button !== 0) return;
        down = { x: event.clientX, left: box.scrollLeft }; moved = false;
      });
      window.addEventListener("pointermove", function (event) {
        if (!down) return;
        var dx = event.clientX - down.x;
        if (!moved && Math.abs(dx) > 5) { moved = true; box.classList.add("is-dragging"); }
        if (moved) box.scrollLeft = down.left - dx;
      });
      window.addEventListener("pointerup", function () {
        if (!down) return;
        down = null;
        if (moved) {
          box.classList.remove("is-dragging");
          centerOn(active);
          setTimeout(function () { moved = false; }, 0);
        }
      });
      box.addEventListener("click", function (event) {
        var link = event.target.closest && event.target.closest(".cf-link");
        if (!link) return;
        var item = link.closest(".flow-item");
        if (moved) { event.preventDefault(); return; }
        if (items.indexOf(item) !== active) { event.preventDefault(); centerOn(items.indexOf(item)); }
      });
      box.addEventListener("keydown", function (event) {
        if (event.key === "ArrowRight") { event.preventDefault(); centerOn(active + 1); }
        else if (event.key === "ArrowLeft") { event.preventDefault(); centerOn(active - 1); }
        else if (event.key === "Home") { event.preventDefault(); centerOn(0); }
        else if (event.key === "End") { event.preventDefault(); centerOn(items.length - 1); }
      });
      var prev = $("[data-flow-prev]", scope), next = $("[data-flow-next]", scope);
      if (prev) prev.addEventListener("click", function () { centerOn(active - 1); });
      if (next) next.addEventListener("click", function () { centerOn(active + 1); });
    });
  }

  // Artwork that tilts toward the pointer or finger.
  function initArtTilt() {
    if (reducedMotion) return;
    $$(".song-hero .art, .album-detail-art, .movie-head .poster").forEach(function (el) {
      el.setAttribute("data-tilt", "");
      function aim(event) {
        var box = el.getBoundingClientRect();
        var x = (event.clientX - box.left) / box.width - 0.5;
        var y = (event.clientY - box.top) / box.height - 0.5;
        el.classList.add("is-tilting");
        el.style.setProperty("--ty", (x * 26).toFixed(1) + "deg");
        el.style.setProperty("--tx", (-y * 26).toFixed(1) + "deg");
      }
      function rest() {
        el.classList.remove("is-tilting");
        el.style.removeProperty("--ty");
        el.style.removeProperty("--tx");
      }
      el.addEventListener("pointerdown", aim);
      el.addEventListener("pointermove", aim);
      el.addEventListener("pointerleave", rest);
      el.addEventListener("pointerup", rest);
      el.addEventListener("pointercancel", rest);
    });
    if (!window.matchMedia("(hover: hover)").matches) return;
    document.addEventListener("pointermove", function (event) {
      var wrap = event.target.closest && event.target.closest(".poster-wrap");
      $$(".poster-wrap.is-tilting").forEach(function (el) {
        if (el !== wrap) { el.classList.remove("is-tilting"); el.style.transform = ""; }
      });
      if (!wrap) return;
      var box = wrap.getBoundingClientRect();
      var x = (event.clientX - box.left) / box.width - 0.5;
      var y = (event.clientY - box.top) / box.height - 0.5;
      wrap.classList.add("is-tilting");
      wrap.style.transform = "rotateY(" + (x * 10).toFixed(2) + "deg) rotateX(" + (-y * 10).toFixed(2) + "deg) translateZ(8px)";
    }, { passive: true });
  }

  // Filter panels start collapsed on small screens so the list is the first thing you see.
  function initPanels() {
    if (!window.matchMedia("(max-width: 900px)").matches) return;
    $$(".filter-panel").forEach(function (panel) { panel.removeAttribute("open"); });
  }

  /* ----------------------------------------------------------------- boot */
  function boot() {
    initTheme();
    initActions();
    initCharts();
    initCatalogues();
    initLyrics(document);
    initPanels();
    initReveal();
    initStage();
    initFlow();
    initArtTilt();
    $$("[data-search-root]").forEach(function (root) { initSearch(root, loadIndex); });
    initDrawer(loadIndex);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
