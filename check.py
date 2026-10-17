#!/usr/bin/env python3
"""Sanity-check dist/ after a build: pages exist, internal links resolve."""
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
from db_source import load_records as load_database_records
raw = load_database_records(ROOT / "data" / "telugu_movies_master.json")

problems = []

songs = [s for m in raw for s in m["songs"]]
song_pages = {p.parent.name for p in (DIST / "song").glob("*/index.html")}
if len(song_pages) != len(songs):
    problems.append(f"{len(songs)} songs in data but {len(song_pages)} song pages")
def movie_route(movie):
    imdb_id = str(movie.get("movie_id") or "")
    if re.fullmatch(r"tt\d+", imdb_id):
        return f"/{imdb_id}/"
    slug = re.sub(r"[^a-z0-9]+", "-", str(movie.get("title") or "untitled").lower()).strip("-")
    return f"/movie/{slug}-{movie.get('release_year') or 'Unknown'}/"

def album_route(movie):
    base = movie_route(movie)
    if base.startswith("/tt"):
        return base + "album/"
    slug = re.sub(r"[^a-z0-9]+", "-", str(movie.get("title") or "untitled").lower()).strip("-")
    return f"/album/{slug}-{movie.get('release_year') or 'Unknown'}/"

expected_movie_pages = [DIST / movie_route(m).strip("/") / "index.html" for m in raw]
movie_pages = [page for page in expected_movie_pages if page.exists()]
if len(movie_pages) != len(raw):
    problems.append(f"{len(raw)} films in data but {len(movie_pages)} IMDb/slug movie pages exist")
expected_album_pages = [DIST / album_route(m).strip("/") / "index.html" for m in raw if m.get("songs")]
album_pages = [page for page in expected_album_pages if page.exists()]
if len(album_pages) != len(expected_album_pages):
    problems.append(f"{len(expected_album_pages)} soundtracks expected but {len(album_pages)} IMDb/album pages exist")
for page in (DIST / "index.html", DIST / "songs" / "index.html", DIST / "albums" / "index.html", DIST / "movies" / "index.html", DIST / "charts" / "index.html", DIST / "advanced-search" / "index.html"):
    if not page.exists():
        problems.append(f"missing required page: {page.relative_to(DIST)}")

if (DIST / "albums" / "index.html").exists():
    album_html = (DIST / "albums" / "index.html").read_text(encoding="utf-8")
    album_count = sum(1 for m in raw if m.get("songs"))
    actual_albums = album_html.count('class="album-card"')
    if actual_albums != album_count:
        problems.append(f"{album_count} soundtracks in data but {actual_albums} album cards")
if (DIST / "charts" / "index.html").exists():
    chart_html = (DIST / "charts" / "index.html").read_text(encoding="utf-8")
    actual_chart_songs = chart_html.count('class="track"><a href="/song/')
    actual_chart_albums = chart_html.count('class="track entity-chart-row"><a href=')
    actual_chart_panels = chart_html.count('data-chart-panel=')
    if actual_chart_songs != min(30, len(songs)):
        problems.append(f"expected {min(30, len(songs))} top-song chart rows but found {actual_chart_songs}")
    if actual_chart_albums < min(30, album_count):
        problems.append(f"album chart missing expected rows: found {actual_chart_albums}")
    if actual_chart_panels != 3:
        problems.append(f"expected 3 chart panels (songs, albums, movies), found {actual_chart_panels}")

# Filter controls, new movie catalogue and the richer client-side search data must be emitted.
if (DIST / "movies" / "index.html").exists():
    movies_html = (DIST / "movies" / "index.html").read_text(encoding="utf-8")
    for marker in ('id="movie-query"', 'id="movie-sort"', 'id="movie-genre"', 'id="movie-music"', 'id="movie-director"', 'id="movie-from"', 'id="movie-to"', 'class="movies-grid"'):
        if marker not in movies_html:
            problems.append(f"movies page missing expected filter/control: {marker}")
if (DIST / "albums" / "index.html").exists():
    for marker in ('id="album-query"', 'id="album-sort"', 'id="album-artist"', 'id="album-genre"', 'id="album-from"', 'id="album-to"', 'id="album-grid"'):
        if marker not in album_html:
            problems.append(f"albums page missing expected filter/control: {marker}")
if (DIST / "songs" / "index.html").exists():
    songs_html = (DIST / "songs" / "index.html").read_text(encoding="utf-8")
    for marker in ('id="song-query"', 'id="song-sort"', 'id="song-artist"', 'id="song-music"', 'id="song-genre"', 'id="song-from"', 'id="song-to"', 'id="song-grid"'):
        if marker not in songs_html:
            problems.append(f"songs page missing expected filter/control: {marker}")
if (DIST / "songs" / "index.html").exists():
    songs_html = (DIST / "songs" / "index.html").read_text(encoding="utf-8")
    actual_catalog_songs = songs_html.count('class="track song-catalog-item"')
    if actual_catalog_songs != len(songs):
        problems.append(f"songs catalogue has {actual_catalog_songs} rows but expected {len(songs)}")
if (DIST / "advanced-search" / "index.html").exists():
    advanced_html = (DIST / "advanced-search" / "index.html").read_text(encoding="utf-8")
    for marker in ('id="advanced-query"', 'id="advanced-type"', 'id="advanced-from"', 'id="advanced-to"', 'id="advanced-sort"', 'id="advanced-results"'):
        if marker not in advanced_html:
            problems.append(f"advanced search page missing expected control: {marker}")
# Validate the shared Spotify-style song drawer and IMDb-based navigation.
root_html = (DIST / "index.html").read_text(encoding="utf-8") if (DIST / "index.html").exists() else ""
css_text = (DIST / "static" / "style.css").read_text(encoding="utf-8") if (DIST / "static" / "style.css").exists() else ""
js_text = (DIST / "static" / "app.js").read_text(encoding="utf-8") if (DIST / "static" / "app.js").exists() else ""
for marker in ('id="song-drawer"', 'id="drawer-album-link"', 'id="drawer-full-details"'):
    if marker not in root_html:
        problems.append(f"global song drawer missing expected element: {marker}")
if "body.drawer-is-open #main" not in css_text or "(min-width: 1051px)" not in css_text:
    problems.append("desktop Spotify-style docked drawer layout is missing")
if "song.moviePath" not in js_text or "movie.path" not in js_text or "song.albumPath" not in js_text:
    problems.append("client navigation is missing IMDb movie/album routes")
if "initAdvancedSearch" not in js_text or "applySongFilters" not in js_text or "initChartTabs" not in js_text or "initThemeToggle" not in js_text:
    problems.append("new advanced search, songs catalogue, charts tabs or theme toggle script is missing")
for asset in ("vachika-logo-light.png", "vachika-logo-dark.png", "favicon.svg", "favicon.png"):
    if not (DIST / "static" / asset).exists():
        problems.append(f"missing brand asset: {asset}")
if "provider-icon" not in css_text or 'provider_icon("spotify")' not in (ROOT / "build.py").read_text(encoding="utf-8"):
    problems.append("Spotify / YouTube Music provider icons are missing")

if (DIST / "search-index.json").exists():
    search_data = json.loads((DIST / "search-index.json").read_text(encoding="utf-8"))
    if len(search_data.get("songs", [])) != len(songs):
        problems.append("search index song count does not match song data")
    if len(search_data.get("movies", [])) != len(raw):
        problems.append("search index movie count does not match movie data")
    if search_data.get("movies") and not all(k in search_data["movies"][0] for k in ("path", "albumPath", "imdbId")):
        problems.append("search index movie objects are missing IMDb route fields")
    if search_data.get("songs") and not all(k in search_data["songs"][0] for k in ("moviePath", "albumPath")):
        problems.append("search index song objects are missing IMDb route fields")
    if search_data.get("songs") and not all(k in search_data["songs"][0] for k in ("id", "title", "movieTitle", "artists", "artwork")):
        problems.append("search index song objects are missing fields required for search/drawer")

# Validate the final JSON schema's detail-page integrations (media metadata,
# YouTube video embeds, link dropdown and OTT availability).
movie_page_html = (DIST / movie_route(raw[0]).strip("/") / "index.html").read_text(encoding="utf-8") if raw and (DIST / movie_route(raw[0]).strip("/") / "index.html").exists() else ""
if movie_page_html:
    for marker in ('class="movie-links-dropdown"', 'Streaming availability', 'class="ott-provider-grid"', 'class="ott-provider-btn"', 'IMDb ·'):
        if marker not in movie_page_html:
            problems.append(f"movie page missing JSON-driven link/OTT detail: {marker}")
if (DIST / "song").exists():
    all_song_html = list((DIST / "song").glob("*/index.html"))
    with_video = 0
    for page in all_song_html:
        text = page.read_text(encoding="utf-8")
        if 'song-video-embed' in text:
            with_video += 1
            if 'Watch on YouTube' not in text or 'data-embed="youtube"' not in text:
                problems.append(f"{page.relative_to(DIST)}: YouTube video embed/button incomplete")
        if 'Song metadata' not in text or 'Duration (milliseconds)' not in text or 'All available track and release metadata' not in text:
            problems.append(f"{page.relative_to(DIST)}: song metadata section is incomplete")
    expected_video_songs = sum(bool((((song.get("media") or {}).get("youtube_video_song") or {}).get("video_id"))) for movie in raw for song in movie.get("songs", []))
    if with_video != expected_video_songs:
        problems.append(f"expected {expected_video_songs} song video embeds but found {with_video}")
    if (DIST / "search-index.json").exists():
        idx = json.loads((DIST / "search-index.json").read_text(encoding="utf-8"))
        if idx.get("songs") and not all(key in idx["songs"][0] for key in ("youtubeVideoUrl", "youtubeVideoId", "isrc", "durationMs")):
            problems.append("search index omits final-schema YouTube/ISRC/duration metadata")

checked = 0
for html in DIST.rglob("*.html"):
    text = html.read_text(encoding="utf-8")
    for href in re.findall(r'(?:href|src)="(/[^"]*)"', text):
        path = unquote(urlsplit(href).path)
        target = DIST / path.lstrip("/")
        if path.endswith("/"):
            target = target / "index.html"
        checked += 1
        if not target.exists():
            problems.append(f"{html.relative_to(DIST)}: broken link {href}")

for html in DIST.rglob("index.html"):
    text = html.read_text(encoding="utf-8")
    if text.count("<h1") != 1:
        problems.append(f"{html.relative_to(DIST)}: expected one h1, found {text.count('<h1')}")
    if "<title>" not in text or 'name="description"' not in text:
        problems.append(f"{html.relative_to(DIST)}: missing title or description")
    if 'id="q"' not in text or 'href="/songs/"' not in text or 'href="/albums/"' not in text or 'href="/movies/"' not in text or 'href="/charts/"' not in text or 'href="/advanced-search/"' not in text or 'id="song-drawer"' not in text or 'id="theme-toggle"' not in text:
        problems.append(f"{html.relative_to(DIST)}: missing global search or navigation")

# Repeated display titles are valid (alternate themes/versions can share a name).
# Identity and page integrity are checked using unique source track IDs above and
# the URL/link checks below, rather than incorrectly requiring unique titles.

print(f"{len(song_pages)} song pages, {len(movie_pages)} movie pages, {checked} internal links checked")
if problems:
    print("\n".join(problems))
    sys.exit(1)
print("ok")
