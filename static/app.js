(function () {
  "use strict";
  document.documentElement.classList.add("js");

  var input = document.getElementById("q");
  var searchForm = document.getElementById("global-search-form");
  var popover = document.getElementById("search-popover");
  var browse = document.getElementById("browse");
  var results = document.getElementById("results");
  var songSection = document.getElementById("song-results");
  var filmSection = document.getElementById("film-results");
  var songList = document.getElementById("song-list");
  var filmList = document.getElementById("film-list");
  var empty = document.getElementById("empty");
  var status = document.getElementById("status");
  var index = null;
  var indexPromise = null;

  function norm(value) {
    return String(value || "")
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/[^\p{L}\p{N}\p{M}]+/gu, "")
      .replace(/h/g, "")
      .replace(/w/g, "v")
      .replace(/([aeiou])\1+/g, "$1");
  }

  function loadIndex() {
    if (index) return Promise.resolve(index);
    if (indexPromise) return indexPromise;
    indexPromise = fetch("/search-index.json?v=20261016-jsonmeta3", { credentials: "same-origin" })
      .then(function (response) {
        if (!response.ok) throw new Error("Search data returned " + response.status);
        return response.json();
      })
      .then(function (data) {
        if (!data || !Array.isArray(data.songs) || !Array.isArray(data.movies)) {
          throw new Error("Search data format is invalid");
        }
        index = data;
        return index;
      })
      .catch(function (error) {
        indexPromise = null;
        console.error("Unable to load vachikatelugu search data", error);
        throw error;
      });
    return indexPromise;
  }

  function fieldsForSong(song) {
    return [song.title, song.movieTitle, song.year, (song.artists || []).join(" "),
      (song.musicDirectors || []).join(" "), (song.genres || []).join(" "), song.imdbId, song.number];
  }

  function fieldsForMovie(movie) {
    return [movie.title, movie.telugu, movie.imdbId, movie.year, (movie.genres || []).join(" "),
      (movie.musicDirectors || []).join(" "), (movie.directors || []).join(" "),
      (movie.cast || []).join(" "), movie.plot, movie.certification];
  }

  function rankItems(items, raw, getFields, limit) {
    var query = norm(raw);
    if (!query) return [];
    var tokens = String(raw).trim().split(/\s+/).map(norm).filter(function (token) { return token.length > 1; });
    var hits = [];
    items.forEach(function (item) {
      var fields = getFields(item).map(norm).filter(Boolean);
      var key = fields.join(" ");
      var score = -1;
      if (fields[0] === query || fields[0].indexOf(query) === 0) score = 0;
      else if (fields.some(function (field) { return field.indexOf(query) >= 0; })) score = 1;
      else if (key.indexOf(query) >= 0) score = 2;
      else if (tokens.length > 1 && tokens.every(function (token) { return fields.some(function (field) { return field.indexOf(token) >= 0; }); })) score = 3;
      if (score >= 0) hits.push({ item: item, score: score });
    });
    hits.sort(function (a, b) {
      var playsA = Number(a.item.playsNum || a.item.plays || 0);
      var playsB = Number(b.item.playsNum || b.item.plays || 0);
      return a.score - b.score || playsB - playsA || String(b.item.year || "").localeCompare(String(a.item.year || ""));
    });
    return hits.slice(0, limit).map(function (hit) { return hit.item; });
  }

  function rankSongs(raw, limit) {
    return rankItems((index && index.songs) || [], raw, fieldsForSong, limit || 40);
  }

  function rankMovies(raw, limit) {
    return rankItems((index && index.movies) || [], raw, fieldsForMovie, limit || 20);
  }

  function fieldsForAlbum(album) {
    return [album.title, album.year, album.imdbId, album.artist, (album.musicDirectors || []).join(" "),
      (album.genres || []).join(" "), album.release, album.songs];
  }

  function rankAlbums(raw, limit) {
    return rankItems((index && index.albums) || [], raw, fieldsForAlbum, limit || 20);
  }

  function makeElement(tag, className, text) {
    var element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined && text !== null) element.textContent = text;
    return element;
  }

  function makeSearchRow(href, number, title, subtitle, meta) {
    var li = makeElement("li", "track");
    var link = makeElement("a");
    link.href = href;
    var n = makeElement("span", "n", String(number));
    var main = makeElement("span", "main");
    main.appendChild(makeElement("span", "name", title));
    main.appendChild(makeElement("span", "sub", subtitle || ""));
    var side = makeElement("span", "meta", meta || "");
    link.appendChild(n);
    link.appendChild(main);
    link.appendChild(side);
    li.appendChild(link);
    return li;
  }

  function setPopoverOpen(open) {
    if (!popover || !input) return;
    popover.hidden = !open;
    input.setAttribute("aria-expanded", open ? "true" : "false");
  }

  function makeSuggestion(href, icon, title, subtitle) {
    var link = makeElement("a", "search-suggestion");
    link.href = href;
    link.appendChild(makeElement("span", "suggestion-icon", icon));
    var copy = makeElement("span", "suggestion-copy");
    copy.appendChild(makeElement("span", "suggestion-title", title));
    copy.appendChild(makeElement("span", "suggestion-subtitle", subtitle || ""));
    link.appendChild(copy);
    link.appendChild(makeElement("span", "suggestion-arrow", "↗"));
    return link;
  }

  function renderSuggestions(raw) {
    if (!popover || !input) return;
    var value = String(raw || "").trim();
    if (!value) {
      setPopoverOpen(false);
      popover.textContent = "";
      return;
    }
    if (!index) return;
    popover.textContent = "";
    var songs = rankSongs(value, 5);
    var movies = rankMovies(value, 3);
    var count = 0;
    if (songs.length) {
      popover.appendChild(makeElement("p", "suggestion-heading", "SONGS"));
      songs.forEach(function (song) {
        popover.appendChild(makeSuggestion("/song/" + encodeURIComponent(song.id) + "/", "♫", song.title,
          song.movieTitle + " · " + song.year));
        count += 1;
      });
    }
    if (movies.length) {
      popover.appendChild(makeElement("p", "suggestion-heading", "MOVIES"));
      movies.forEach(function (movie) {
        popover.appendChild(makeSuggestion(movie.path || ("/movie/" + encodeURIComponent(movie.slug) + "/"), "▣", movie.title,
          movie.year + " · " + movie.songs + (movie.songs === 1 ? " song" : " songs")));
        count += 1;
      });
    }
    var albums = rankAlbums(value, 3);
    if (albums.length) {
      popover.appendChild(makeElement("p", "suggestion-heading", "ALBUMS"));
      albums.forEach(function (album) {
        popover.appendChild(makeSuggestion(album.path, "◉", album.title + " soundtrack",
          album.year + " · " + album.songs + (album.songs === 1 ? " song" : " songs")));
        count += 1;
      });
    }
    if (!count) {
      popover.appendChild(makeElement("p", "suggestion-empty", "No results found. Try a song, movie, singer or music director."));
    }
    var all = makeElement("a", "suggestion-all", "See all results for “" + value + "” ↗");
    all.href = "/advanced-search/?q=" + encodeURIComponent(value);
    popover.appendChild(all);
    setPopoverOpen(true);
  }

  function renderHomeResults(raw) {
    if (!browse || !results || !songSection || !filmSection || !songList || !filmList || !empty) return;
    var query = String(raw || "").trim();
    if (!query) {
      results.hidden = true;
      browse.hidden = false;
      if (status) status.textContent = "";
      return;
    }
    if (!index) return;
    var songs = rankSongs(query, 40);
    var movies = rankMovies(query, 20);
    songList.textContent = "";
    filmList.textContent = "";
    songs.forEach(function (song, i) {
      songList.appendChild(makeSearchRow("/song/" + encodeURIComponent(song.id) + "/", i + 1,
        song.title, song.movieTitle + ", " + song.year, song.plays || ""));
    });
    movies.forEach(function (movie, i) {
      filmList.appendChild(makeSearchRow(movie.path || ("/movie/" + encodeURIComponent(movie.slug) + "/"), i + 1,
        movie.title, movie.year + (movie.genres && movie.genres.length ? " · " + movie.genres.slice(0, 2).join(", ") : ""),
        movie.songs + (movie.songs === 1 ? " song" : " songs")));
    });
    songSection.hidden = songs.length === 0;
    filmSection.hidden = movies.length === 0;
    var none = songs.length + movies.length === 0;
    empty.hidden = !none;
    empty.textContent = none ? "Nothing found for “" + query + "”. Try a movie title, a singer or part of a song title." : "";
    results.hidden = false;
    browse.hidden = true;
    if (status) status.textContent = none ? "No results" : songs.length + " songs and " + movies.length + " movies found";
  }

  if (input) {
    input.addEventListener("focus", function () {
      loadIndex().then(function () { if (input.value.trim()) renderSuggestions(input.value); }).catch(function () {});
    });
    input.addEventListener("input", function () {
      var value = input.value;
      if (!value.trim()) {
        renderSuggestions("");
        return;
      }
      loadIndex().then(function () {
        renderSuggestions(value);
      }).catch(function () {
        if (popover) {
          popover.textContent = "Search is temporarily unavailable. Press Enter to try again.";
          setPopoverOpen(true);
        }
      });
    });
    input.addEventListener("keydown", function (event) {
      if (event.key === "Escape") setPopoverOpen(false);
    });
  }

  if (searchForm) {
    // The form is intentionally allowed to submit to /?q=... on every page.
    // This makes Enter and the search button work even before JavaScript loads.
    searchForm.addEventListener("submit", function () {
      if (input) input.value = input.value.trim();
    });
  }

  document.addEventListener("click", function (event) {
    if (popover && input && !event.target.closest(".header-search")) setPopoverOpen(false);
  });

  var initialQuery = new URLSearchParams(window.location.search).get("q");
  if (input && initialQuery) {
    input.value = initialQuery;
    if (browse && results) {
      loadIndex().then(function () { renderHomeResults(initialQuery); }).catch(function () {
        results.hidden = false;
        browse.hidden = true;
        if (empty) {
          empty.hidden = false;
          empty.textContent = "Search could not load. Please refresh and try again.";
        }
      });
    }
  }

  // Album and movie filter controls progressively enhance the statically sorted grids.
  function applyAlbumFilters() {
    var grid = document.getElementById("album-grid");
    var query = document.getElementById("album-query");
    var sort = document.getElementById("album-sort");
    var artist = document.getElementById("album-artist");
    var genre = document.getElementById("album-genre");
    var from = document.getElementById("album-from");
    var to = document.getElementById("album-to");
    var count = document.getElementById("album-count");
    var noResults = document.getElementById("album-empty");
    if (!grid || !query || !sort || !artist) return;
    var cards = Array.prototype.slice.call(grid.querySelectorAll(".album-item"));
    function update() {
      var term = norm(query.value);
      var selectedArtist = artist.value;
      var selectedGenre = genre ? genre.value : "";
      var fromDate = from ? from.value : "";
      var toDate = to ? to.value : "";
      var visible = cards.filter(function (card) {
        var release = card.dataset.release || "";
        return (!term || norm(card.dataset.title).indexOf(term) >= 0)
          && (!selectedArtist || (card.dataset.artist || "").split("|").indexOf(selectedArtist) >= 0)
          && (!selectedGenre || (card.dataset.genre || "").split("|").indexOf(selectedGenre) >= 0)
          && (!fromDate || (release && release >= fromDate))
          && (!toDate || (release && release <= toDate));
      });
      var ordering = sort.value;
      visible.sort(function (a, b) {
        var av, bv;
        if (ordering === "release-new") return (b.dataset.release || "").localeCompare(a.dataset.release || "");
        if (ordering === "release-old") return (a.dataset.release || "").localeCompare(b.dataset.release || "");
        if (ordering === "title-az") return (a.dataset.title || "").localeCompare(b.dataset.title || "");
        if (ordering === "title-za") return (b.dataset.title || "").localeCompare(a.dataset.title || "");
        if (ordering === "songs") return Number(b.dataset.songs || 0) - Number(a.dataset.songs || 0);
        av = Number(a.dataset.plays || 0); bv = Number(b.dataset.plays || 0);
        return bv - av;
      });
      visible.forEach(function (card) { card.hidden = false; grid.appendChild(card); });
      cards.filter(function (card) { return visible.indexOf(card) < 0; }).forEach(function (card) { card.hidden = true; grid.appendChild(card); });
      if (count) count.textContent = visible.length + (visible.length === 1 ? " album" : " albums");
      if (noResults) noResults.hidden = visible.length > 0;
    }
    query.addEventListener("input", update);
    sort.addEventListener("change", update);
    artist.addEventListener("change", update);
    [genre, from, to].forEach(function (control) { if (control) control.addEventListener("change", update); });
    update();
  }

  function applyMovieFilters() {
    var grid = document.getElementById("movie-grid");
    var query = document.getElementById("movie-query");
    var sort = document.getElementById("movie-sort");
    var genre = document.getElementById("movie-genre");
    var music = document.getElementById("movie-music");
    var director = document.getElementById("movie-director");
    var from = document.getElementById("movie-from");
    var to = document.getElementById("movie-to");
    var count = document.getElementById("movie-count");
    var noResults = document.getElementById("movie-empty");
    if (!grid || !query || !sort || !genre || !music || !director) return;
    var cards = Array.prototype.slice.call(grid.querySelectorAll(".movie-item"));
    function update() {
      var term = norm(query.value);
      var selectedGenre = genre.value;
      var selectedMusic = music.value;
      var selectedDirector = director.value;
      var fromDate = from ? from.value : "";
      var toDate = to ? to.value : "";
      var visible = cards.filter(function (card) {
        var titleMatch = !term || norm(card.dataset.title).indexOf(term) >= 0;
        var genreMatch = !selectedGenre || (card.dataset.genre || "").split("|").indexOf(selectedGenre) >= 0;
        var musicMatch = !selectedMusic || (card.dataset.music || "").split("|").indexOf(selectedMusic) >= 0;
        var directorMatch = !selectedDirector || (card.dataset.director || "").split("|").indexOf(selectedDirector) >= 0;
        var release = card.dataset.release || "";
        var dateMatch = (!fromDate || (release && release >= fromDate)) && (!toDate || (release && release <= toDate));
        return titleMatch && genreMatch && musicMatch && directorMatch && dateMatch;
      });
      var ordering = sort.value;
      visible.sort(function (a, b) {
        if (ordering === "release-old") return (a.dataset.release || "").localeCompare(b.dataset.release || "");
        if (ordering === "title-az") return (a.dataset.title || "").localeCompare(b.dataset.title || "");
        if (ordering === "title-za") return (b.dataset.title || "").localeCompare(a.dataset.title || "");
        if (ordering === "songs") return Number(b.dataset.songs || 0) - Number(a.dataset.songs || 0);
        return (b.dataset.release || "").localeCompare(a.dataset.release || "");
      });
      visible.forEach(function (card) { card.hidden = false; grid.appendChild(card); });
      cards.filter(function (card) { return visible.indexOf(card) < 0; }).forEach(function (card) { card.hidden = true; grid.appendChild(card); });
      if (count) count.textContent = visible.length + (visible.length === 1 ? " movie" : " movies");
      if (noResults) noResults.hidden = visible.length > 0;
    }
    [query, sort, genre, music, director, from, to].forEach(function (control) {
      if (control) control.addEventListener(control.tagName === "INPUT" && control.type !== "date" ? "input" : "change", update);
    });
    update();
  }

  function applySongFilters() {
    var grid = document.getElementById("song-grid");
    var query = document.getElementById("song-query");
    var sort = document.getElementById("song-sort");
    var artist = document.getElementById("song-artist");
    var music = document.getElementById("song-music");
    var genre = document.getElementById("song-genre");
    var from = document.getElementById("song-from");
    var to = document.getElementById("song-to");
    var count = document.getElementById("song-count");
    var noResults = document.getElementById("song-empty");
    if (!grid || !query || !sort) return;
    var cards = Array.prototype.slice.call(grid.querySelectorAll(".song-catalog-item"));
    function update() {
      var term = norm(query.value);
      var selectedArtist = artist ? artist.value : "";
      var selectedMusic = music ? music.value : "";
      var selectedGenre = genre ? genre.value : "";
      var fromDate = from ? from.value : "";
      var toDate = to ? to.value : "";
      var visible = cards.filter(function (card) {
        var release = card.dataset.release || "";
        return (!term || norm([card.dataset.title, card.dataset.artists, card.dataset.music].join(" ")).indexOf(term) >= 0)
          && (!selectedArtist || (card.dataset.artists || "").split("|").indexOf(selectedArtist) >= 0)
          && (!selectedMusic || (card.dataset.music || "").split("|").indexOf(selectedMusic) >= 0)
          && (!selectedGenre || (card.dataset.genre || "").split("|").indexOf(selectedGenre) >= 0)
          && (!fromDate || (release && release >= fromDate))
          && (!toDate || (release && release <= toDate));
      });
      visible.sort(function (a, b) {
        if (sort.value === "title-az") return (a.dataset.title || "").localeCompare(b.dataset.title || "");
        if (sort.value === "title-za") return (b.dataset.title || "").localeCompare(a.dataset.title || "");
        if (sort.value === "release-old") return (a.dataset.release || "").localeCompare(b.dataset.release || "");
        if (sort.value === "release-new") return (b.dataset.release || "").localeCompare(a.dataset.release || "");
        return Number(b.dataset.plays || 0) - Number(a.dataset.plays || 0);
      });
      visible.forEach(function (card, i) { card.hidden = false; var n = card.querySelector(".n"); if (n) n.textContent = String(i + 1); grid.appendChild(card); });
      cards.filter(function (card) { return visible.indexOf(card) < 0; }).forEach(function (card) { card.hidden = true; grid.appendChild(card); });
      if (count) count.textContent = visible.length + (visible.length === 1 ? " song" : " songs");
      if (noResults) noResults.hidden = visible.length > 0;
    }
    [query, sort, artist, music, genre, from, to].forEach(function (control) {
      if (control) control.addEventListener(control.tagName === "INPUT" && control.type !== "date" ? "input" : "change", update);
    });
    update();
  }

  function initAdvancedSearch() {
    var form = document.getElementById("advanced-search-form");
    var queryEl = document.getElementById("advanced-query");
    var typeEl = document.getElementById("advanced-type");
    var fromEl = document.getElementById("advanced-from");
    var toEl = document.getElementById("advanced-to");
    var sortEl = document.getElementById("advanced-sort");
    var resultsEl = document.getElementById("advanced-results");
    var countEl = document.getElementById("advanced-count");
    var emptyEl = document.getElementById("advanced-empty");
    if (!form || !queryEl || !typeEl || !resultsEl) return;

    function toResult(type, item) {
      if (type === "song") return { type: type, item: item, title: item.title, subtitle: (item.artists || []).join(", ") + " · " + item.movieTitle + " (" + item.year + ")", path: "/song/" + encodeURIComponent(item.id) + "/", image: item.artwork || item.poster, date: item.release || item.released || "", plays: Number(item.playsNum || 0), fields: fieldsForSong(item) };
      if (type === "movie") return { type: type, item: item, title: item.title, subtitle: item.year + " · " + (item.genres || []).slice(0, 3).join(", ") + (item.imdbId ? " · " + item.imdbId : ""), path: item.path, image: item.poster || item.artwork, date: item.released || (item.year + "-01-01"), plays: Number(item.playsNum || 0), fields: fieldsForMovie(item) };
      return { type: type, item: item, title: item.title + " soundtrack", subtitle: item.year + " · " + (item.artist || "Telugu film soundtrack") + " · " + item.songs + " songs", path: item.path, image: item.artwork, date: item.release || "", plays: Number(item.plays || 0), fields: fieldsForAlbum(item) };
    }
    function resultCard(result) {
      var a = makeElement("a", "advanced-result-card"); a.href = result.path;
      if (result.image) { var img = makeElement("img", "advanced-result-art"); img.src = result.image; img.alt = ""; img.loading = "lazy"; img.referrerPolicy = "no-referrer"; a.appendChild(img); }
      else a.appendChild(makeElement("span", "advanced-result-art advanced-result-art-empty", result.type === "song" ? "♫" : "▣"));
      var content = makeElement("span", "advanced-result-copy");
      content.appendChild(makeElement("span", "advanced-result-type", result.type.toUpperCase()));
      content.appendChild(makeElement("span", "advanced-result-title", result.title));
      content.appendChild(makeElement("span", "advanced-result-subtitle", result.subtitle));
      a.appendChild(content);
      var arrow = makeElement("span", "advanced-result-arrow", "↗"); a.appendChild(arrow);
      return a;
    }
    function update() {
      if (!index) return;
      var raw = queryEl.value.trim();
      var query = norm(raw);
      var tokens = raw.split(/\s+/).map(norm).filter(function (token) { return token.length > 1; });
      var types = typeEl.value === "all" ? ["song", "album", "movie"] : [typeEl.value];
      var items = [];
      types.forEach(function (type) {
        var source = type === "song" ? index.songs : type === "movie" ? index.movies : index.albums;
        (source || []).forEach(function (item) {
          var fields = type === "song" ? fieldsForSong(item) : type === "movie" ? fieldsForMovie(item) : fieldsForAlbum(item);
          var normalizedFields = fields.map(norm).filter(Boolean);
          var match = !query || normalizedFields.some(function (field) { return field.indexOf(query) >= 0; })
            || (tokens.length > 1 && tokens.every(function (token) { return normalizedFields.some(function (field) { return field.indexOf(token) >= 0; }); }));
          var date = type === "movie" ? (item.released || (item.year + "-01-01")) : type === "album" ? (item.release || "") : (item.release || item.released || "");
          if (!match || (fromEl.value && (!date || date < fromEl.value)) || (toEl.value && (!date || date > toEl.value))) return;
          var result = toResult(type, item);
          if (query) {
            result.score = normalizedFields[0] === query ? 0 : normalizedFields[0] && normalizedFields[0].indexOf(query) === 0 ? 1 : normalizedFields.some(function (field) { return field.indexOf(query) >= 0; }) ? 2 : 3;
          } else result.score = 4;
          items.push(result);
        });
      });
      var ordering = sortEl.value;
      items.sort(function (a, b) {
        if (ordering === "title-az") return a.title.localeCompare(b.title);
        if (ordering === "title-za") return b.title.localeCompare(a.title);
        if (ordering === "newest") return (b.date || "").localeCompare(a.date || "");
        if (ordering === "oldest") return (a.date || "9999").localeCompare(b.date || "9999");
        if (ordering === "popular") return b.plays - a.plays;
        return a.score - b.score || b.plays - a.plays || a.title.localeCompare(b.title);
      });
      resultsEl.textContent = "";
      items.slice(0, 300).forEach(function (result) { resultsEl.appendChild(resultCard(result)); });
      countEl.textContent = items.length.toLocaleString() + (items.length === 1 ? " result" : " results") + (items.length > 300 ? " · showing first 300" : "");
      emptyEl.hidden = items.length > 0;
    }
    form.addEventListener("submit", function (event) { event.preventDefault(); update(); });
    queryEl.addEventListener("input", update);
    [typeEl, fromEl, toEl, sortEl].forEach(function (control) { control.addEventListener("change", update); });
    var params = new URLSearchParams(window.location.search);
    if (params.get("q")) queryEl.value = params.get("q");
    if (["song", "album", "movie", "all"].indexOf(params.get("type")) >= 0) typeEl.value = params.get("type");
    if (params.get("q") || params.get("type")) loadIndex().then(update).catch(function () { countEl.textContent = "Search database could not load. Refresh and try again."; });
    else countEl.textContent = "Enter a term to search the database.";
    // Prefetch once for this page so search covers every entry, not only suggestions.
    loadIndex().then(function () { if (queryEl.value.trim()) update(); }).catch(function () {});
  }

  function initChartTabs() {
    var tabs = Array.prototype.slice.call(document.querySelectorAll("[data-chart-tab]"));
    var panels = Array.prototype.slice.call(document.querySelectorAll("[data-chart-panel]"));
    if (!tabs.length || !panels.length) return;
    tabs.forEach(function (tab) {
      tab.addEventListener("click", function () {
        var chosen = tab.dataset.chartTab;
        tabs.forEach(function (item) { var active = item === tab; item.classList.toggle("is-active", active); item.setAttribute("aria-selected", active ? "true" : "false"); });
        panels.forEach(function (panel) { var active = panel.dataset.chartPanel === chosen; panel.classList.toggle("is-active", active); panel.hidden = !active; });
      });
    });
  }

  function initThemeToggle() {
    var button = document.getElementById("theme-toggle");
    if (!button) return;
    var root = document.documentElement;
    var icon = button.querySelector(".theme-toggle-icon");
    var saved = null;
    try { saved = localStorage.getItem("vachikatelugu-theme"); } catch (error) {}
    if (saved === "dark" || saved === "light") root.setAttribute("data-theme", saved);
    else if (window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches) root.setAttribute("data-theme", "light");
    function reflect() {
      var light = root.getAttribute("data-theme") === "light";
      button.setAttribute("aria-label", light ? "Switch to dark theme" : "Switch to light theme");
      button.title = light ? "Switch to dark theme" : "Switch to light theme";
      if (icon) icon.textContent = light ? "☾" : "☼";
    }
    button.addEventListener("click", function () {
      var next = root.getAttribute("data-theme") === "light" ? "dark" : "light";
      root.setAttribute("data-theme", next);
      try { localStorage.setItem("vachikatelugu-theme", next); } catch (error) {}
      reflect();
    });
    reflect();
  }

  applyAlbumFilters();
  applyMovieFilters();
  applySongFilters();
  initAdvancedSearch();
  initChartTabs();
  initThemeToggle();

  // Right-side Spotify-inspired details drawer. A row keeps its URL for no-JS,
  // middle-click and open-in-new-tab behaviour; a normal click opens the drawer.
  var drawer = document.getElementById("song-drawer");
  var drawerBackdrop = document.getElementById("song-drawer-backdrop");
  var drawerClose = document.getElementById("drawer-close");
  var drawerArtwork = document.getElementById("drawer-artwork");
  var drawerTitle = document.getElementById("drawer-title");
  var drawerFilm = document.getElementById("drawer-film");
  var drawerAlbumLink = document.getElementById("drawer-album-link");
  var drawerArtists = document.getElementById("drawer-artists");
  var drawerFacts = document.getElementById("drawer-facts");
  var drawerActions = document.getElementById("drawer-actions");
  var drawerPlayerArea = document.getElementById("drawer-player-area");
  var drawerFullDetails = document.getElementById("drawer-full-details");
  var previousFocus = null;

  function appendDrawerFact(label, value) {
    if (value === undefined || value === null || value === "" || (Array.isArray(value) && !value.length)) return;
    var item = makeElement("div", "drawer-fact");
    item.appendChild(makeElement("span", "drawer-fact-label", label));
    item.appendChild(makeElement("span", "drawer-fact-value", Array.isArray(value) ? value.join(", ") : String(value)));
    drawerFacts.appendChild(item);
  }

  function makeProviderIcon(provider) {
    var ns = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("class", "provider-icon " + (provider === "spotify" ? "spotify-icon" : "youtube-icon"));
    svg.setAttribute("aria-hidden", "true");
    var circle = document.createElementNS(ns, "circle"); circle.setAttribute("cx", "12"); circle.setAttribute("cy", "12"); circle.setAttribute("r", "11"); circle.setAttribute("fill", "currentColor"); svg.appendChild(circle);
    if (provider === "spotify") {
      var path = document.createElementNS(ns, "path"); path.setAttribute("d", "M5.3 9.2c4.3-1.2 9.4-.7 13.2 1.5M6.2 12.4c3.6-1 7.7-.5 10.8 1.3M7.1 15.3c2.8-.7 5.9-.3 8.2 1");
      path.setAttribute("fill", "none"); path.setAttribute("stroke", "var(--spotify-contrast,#10110f)"); path.setAttribute("stroke-width", "1.45"); path.setAttribute("stroke-linecap", "round"); svg.appendChild(path);
    } else {
      var tri = document.createElementNS(ns, "path"); tri.setAttribute("d", "M10 7.8 17 12l-7 4.2z"); tri.setAttribute("fill", "var(--youtube-contrast,#fff)"); svg.appendChild(tri);
    }
    return svg;
  }

  function appendDrawerLink(label, url, primary, provider) {
    if (!url) return;
    var anchor = makeElement("a", "btn provider-btn " + (provider === "spotify" ? "spotify-btn" : "youtube-btn") + (primary ? " primary" : ""));
    anchor.href = url;
    anchor.target = "_blank";
    anchor.rel = "noopener noreferrer";
    if (provider) anchor.appendChild(makeProviderIcon(provider));
    anchor.appendChild(makeElement("span", "provider-label", label));
    drawerActions.appendChild(anchor);
  }

  function openSongDrawer(song) {
    if (!drawer || !song) return;
    previousFocus = document.activeElement;
    drawerArtwork.hidden = !song.artwork;
    if (song.artwork) {
      drawerArtwork.src = song.artwork;
      drawerArtwork.alt = "Artwork for " + song.movieTitle + " soundtrack";
    } else {
      drawerArtwork.removeAttribute("src");
      drawerArtwork.alt = "";
    }
    drawerTitle.textContent = song.title || "Song details";
    drawerFilm.textContent = "From " + song.movieTitle + " (" + song.year + ")";
    // Keep the film title linked without constructing HTML from the data.
    var filmLink = makeElement("a", "drawer-film-link", song.movieTitle + " · " + song.year);
    filmLink.href = song.moviePath || ("/movie/" + encodeURIComponent(song.movieSlug) + "/");
    drawerFilm.textContent = "";
    drawerFilm.appendChild(document.createTextNode("From "));
    drawerFilm.appendChild(filmLink);
    if (drawerAlbumLink) {
      drawerAlbumLink.href = song.albumPath || ("/album/" + encodeURIComponent(song.movieSlug) + "/");
    }
    drawerArtists.textContent = (song.artists || []).length ? (song.artists || []).join(", ") : "Artist credits unavailable";
    drawerFacts.textContent = "";
    appendDrawerFact("Music", (song.musicDirectors || []).join(", "));
    appendDrawerFact("Duration", song.duration);
    appendDrawerFact("Track", song.number && song.songCount ? song.number + " of " + song.songCount : "");
    appendDrawerFact("YouTube Music", song.plays);
    appendDrawerFact("Genre", song.genres || []);
    drawerActions.textContent = "";
    appendDrawerLink("Open on Spotify", song.spotifyUrl, Boolean(song.spotifyUrl), "spotify");
    appendDrawerLink("Open on YouTube Music", song.ytmUrl, !song.spotifyUrl && Boolean(song.ytmUrl), "youtube");
    appendDrawerLink("Watch on YouTube", song.youtubeVideoUrl, !song.spotifyUrl && !song.ytmUrl && Boolean(song.youtubeVideoUrl), "youtube");
    appendDrawerFact("ISRC", song.isrc);
    drawerPlayerArea.textContent = "";
    if (song.spotifyId || song.ytmId) {
      var playButton = makeElement("button", "btn drawer-play-here", "Play here");
      playButton.type = "button";
      playButton.dataset.drawerPlay = song.spotifyId ? "spotify" : "youtube";
      playButton.dataset.id = song.spotifyId || song.ytmId;
      drawerActions.appendChild(playButton);
    }
    drawerFullDetails.href = "/song/" + encodeURIComponent(song.id) + "/";
    var dockedPanel = window.matchMedia && window.matchMedia("(min-width: 1051px)").matches;
    drawer.setAttribute("aria-modal", dockedPanel ? "false" : "true");
    drawer.classList.toggle("is-docked", Boolean(dockedPanel));
    drawer.classList.add("is-open");
    drawer.setAttribute("aria-hidden", "false");
    drawerBackdrop.hidden = Boolean(dockedPanel);
    document.body.classList.add("drawer-is-open");
    window.setTimeout(function () { drawerClose && drawerClose.focus(); }, 0);
  }

  function closeSongDrawer() {
    if (!drawer || !drawer.classList.contains("is-open")) return;
    drawer.classList.remove("is-open", "is-docked");
    drawer.setAttribute("aria-hidden", "true");
    drawer.setAttribute("aria-modal", "false");
    if (drawerBackdrop) drawerBackdrop.hidden = true;
    document.body.classList.remove("drawer-is-open");
    if (drawerPlayerArea) drawerPlayerArea.textContent = "";
    if (previousFocus && typeof previousFocus.focus === "function") previousFocus.focus();
  }

  function syncDrawerResponsiveMode() {
    if (!drawer || !drawer.classList.contains("is-open")) return;
    var dockedPanel = window.matchMedia && window.matchMedia("(min-width: 1051px)").matches;
    drawer.classList.toggle("is-docked", Boolean(dockedPanel));
    drawer.setAttribute("aria-modal", dockedPanel ? "false" : "true");
    if (drawerBackdrop) drawerBackdrop.hidden = Boolean(dockedPanel);
  }
  if (drawerClose) drawerClose.addEventListener("click", closeSongDrawer);
  if (drawerBackdrop) drawerBackdrop.addEventListener("click", closeSongDrawer);
  window.addEventListener("resize", syncDrawerResponsiveMode);
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      setPopoverOpen(false);
      closeSongDrawer();
    }
  });

  document.addEventListener("click", function (event) {
    var play = event.target.closest("[data-drawer-play]");
    if (play) {
      var kind = play.dataset.drawerPlay;
      var id = play.dataset.id;
      var frame = document.createElement("iframe");
      frame.allow = "autoplay; encrypted-media; fullscreen; clipboard-write";
      frame.referrerPolicy = "strict-origin-when-cross-origin";
      frame.title = kind === "spotify" ? "Spotify player" : "YouTube Music video player";
      if (kind === "spotify") {
        frame.className = "spotify";
        frame.src = "https://open.spotify.com/embed/track/" + encodeURIComponent(id) + "?utm_source=generator";
      } else {
        frame.className = "youtube";
        frame.src = "https://www.youtube-nocookie.com/embed/" + encodeURIComponent(id) + "?autoplay=1&rel=0";
      }
      drawerPlayerArea.textContent = "";
      drawerPlayerArea.appendChild(frame);
      return;
    }

    var anchor = event.target.closest("a[href]");
    if (!anchor || !drawer || anchor.closest("#song-drawer") || anchor.hasAttribute("data-full-song-link")) return;
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    var targetUrl;
    try { targetUrl = new URL(anchor.href, window.location.href); } catch (error) { return; }
    if (targetUrl.origin !== window.location.origin) return;
    var match = targetUrl.pathname.match(/^\/song\/([^/]+)\/?$/);
    if (!match) return;
    var songId;
    try { songId = decodeURIComponent(match[1]); } catch (error) { songId = match[1]; }
    event.preventDefault();
    setPopoverOpen(false);
    loadIndex().then(function () {
      var song = index.songs.find(function (item) { return item.id === songId; });
      if (song) openSongDrawer(song);
      else window.location.href = anchor.href;
    }).catch(function () { window.location.href = anchor.href; });
  });

  // Existing click-to-load player for the dedicated full song and movie pages.
  document.addEventListener("click", function (event) {
    var btn = event.target.closest("[data-embed]");
    if (!btn) return;
    var kind = btn.getAttribute("data-embed");
    var id = btn.getAttribute("data-id");
    var frame = document.createElement("iframe");
    frame.setAttribute("allow", "autoplay; encrypted-media; fullscreen; clipboard-write");
    frame.setAttribute("referrerpolicy", "strict-origin-when-cross-origin");
    if (kind === "spotify") {
      frame.className = "spotify";
      frame.title = "Spotify player";
      frame.src = "https://open.spotify.com/embed/track/" + encodeURIComponent(id) + "?utm_source=generator";
    } else {
      frame.className = "youtube";
      frame.title = "YouTube player";
      frame.src = "https://www.youtube-nocookie.com/embed/" + encodeURIComponent(id) + "?autoplay=1&rel=0";
    }
    btn.replaceWith(frame);
    frame.focus();
  });

  // Shareable song URLs for reel descriptions.
  document.addEventListener("click", function (event) {
    var btn = event.target.closest("[data-copy-link]");
    if (!btn) return;
    var url = window.location.href.split("#")[0];
    function done() {
      btn.textContent = "Link copied";
      btn.setAttribute("aria-live", "polite");
    }
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(url).then(done).catch(function () { window.prompt("Copy this song link", url); });
    } else {
      window.prompt("Copy this song link", url);
    }
  });
})();
