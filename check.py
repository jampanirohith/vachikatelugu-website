#!/usr/bin/env python3
"""Validate generated pages against the normalized SQLite catalogue."""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from html import unescape
from pathlib import Path
from urllib.parse import unquote, urlsplit

from build import album_path, e, load_movies, movie_path, render_lyrics_section
from db_source import database_path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"


def fail(message: str, problems: list[str]) -> None:
    problems.append(message)


def page_for_route(route: str) -> Path:
    clean = route.split("?", 1)[0].lstrip("/")
    if not clean or clean.endswith("/"):
        clean += "index.html"
    return DIST / clean


def redirects_from_dist() -> set[str]:
    path = DIST / "_redirects"
    if not path.is_file():
        return set()
    result: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        result.add(stripped.split()[0])
    return result


def catalogue_signature(movies: list[dict]) -> str:
    """Serialize the public build model while excluding circular object links."""
    result = []
    for movie in movies:
        result.append({
            "movie": {key: value for key, value in movie.items() if key not in {"songs", "albums", "album"}},
            "albums": [{
                "fields": {key: value for key, value in album.items() if key not in {"movie", "songs"}},
                "song_ids": [song["id"] for song in album.get("songs", [])],
            } for album in movie.get("albums", [])],
            "songs": [{key: value for key, value in song.items() if key not in {"movie", "album"}}
                      for song in movie.get("songs", [])],
        })
    return json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def validate_source_json_independence(expected_movies: list[dict], problems: list[str]) -> None:
    """Prove raw/serialized source columns are not a hidden catalogue dependency.

    A temporary copy of the SQLite DB has its JSON/blob columns replaced with
    valid empty JSON values. Normalized build data must remain byte-for-byte
    identical at the in-memory model level. The supplied/source DB is untouched.
    """
    source_db = database_path()
    if source_db is None:
        fail("cannot test JSON-source independence because no SQLite source is configured", problems)
        return
    source_signature = catalogue_signature(expected_movies)
    list_columns = {"genres_json", "artist_ids_json", "spotify_images_json"}
    blob_columns = {
        "movies": {"raw_json", "genres_json", "source_metadata_json", "source_status_json"},
        "albums": {"raw_json", "spotify_images_json", "source_metadata_json"},
        "songs": {"raw_json", "artist_ids_json", "genres_json", "audio_features_json", "source_metadata_json"},
        "song_media": {"extra_json"},
    }
    previous_database_path = os.environ.get("DATABASE_PATH")
    try:
        with tempfile.TemporaryDirectory(prefix="vachika-json-independence-") as temporary_dir:
            isolated_db = Path(temporary_dir) / "catalogue-test.db"
            shutil.copy2(source_db, isolated_db)
            connection = sqlite3.connect(isolated_db)
            try:
                available_tables = {row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )}
                changed_columns = []
                for table, candidates in blob_columns.items():
                    if table not in available_tables:
                        continue
                    available_columns = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
                    for column in candidates & available_columns:
                        replacement = "[]" if column in list_columns else "{}"
                        connection.execute(f'UPDATE "{table}" SET "{column}"=?', (replacement,))
                        changed_columns.append(f"{table}.{column}")
                connection.commit()
            finally:
                connection.close()

            os.environ["DATABASE_PATH"] = str(isolated_db)
            with contextlib.redirect_stdout(io.StringIO()):
                altered_movies = load_movies()
            altered_signature = catalogue_signature(altered_movies)
            if altered_signature != source_signature:
                fail("website catalogue changed when source JSON/blob columns were emptied; a hidden JSON dependency remains", problems)
            elif not changed_columns:
                fail("JSON-source independence test did not find any source JSON/blob columns to alter", problems)
    except Exception as exc:
        fail(f"could not complete the source JSON-independence test ({type(exc).__name__}): {exc}", problems)
    finally:
        if previous_database_path is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = previous_database_path


def validate_lyrics_component(problems: list[str]) -> None:
    lrc = render_lyrics_section({
        "lrc_lyrics": "[ar:Test Artist]\n[00:01.25]First line\n[00:02.50]Second <line>\n",
        "plain_lyrics": None,
    })
    if 'class="song-lyrics-section"' not in lrc or 'data-time="1.25"' not in lrc or 'data-time="2.50"' not in lrc:
        fail("LRC fixture did not render a lyrics section with timestamped lines", problems)
    if "Second &lt;line&gt;" not in lrc or "[ar:Test Artist]" in lrc:
        fail("LRC rendering does not safely escape lyric text or suppress LRC metadata tags", problems)
    plain = render_lyrics_section({"lrc_lyrics": None, "plain_lyrics": "Plain first line\nPlain second line"})
    if 'class="lyrics-plain"' not in plain or "Plain second line" not in plain:
        fail("Plain-lyrics fixture did not render readable lyrics", problems)
    if render_lyrics_section({"lrc_lyrics": None, "plain_lyrics": None}):
        fail("Empty lyrics unexpectedly rendered a lyrics section", problems)


def main() -> None:
    problems: list[str] = []
    if not DIST.is_dir():
        print("SITE CHECK FAILED: dist/ does not exist. Run build.py first.", file=sys.stderr)
        raise SystemExit(1)

    try:
        movies = load_movies()
    except Exception as exc:  # surface controlled build/check failure, not a traceback-only report
        print(f"SITE CHECK FAILED: could not load normalized SQLite data ({type(exc).__name__}): {exc}", file=sys.stderr)
        raise SystemExit(1)

    validate_source_json_independence(movies, problems)
    songs = [song for movie in movies for song in movie["songs"]]
    albums = [album for movie in movies for album in movie["albums"]]
    expected_song_ids = {song["id"] for song in songs}
    expected_movie_routes = {movie_path(movie) for movie in movies}
    expected_album_routes = {album_path(album) for album in albums}
    expected_song_routes = {f'/song/{song["id"]}/' for song in songs}

    required_pages = (
        "index.html", "songs/index.html", "albums/index.html", "movies/index.html",
        "charts/index.html", "advanced-search/index.html", "404.html",
    )
    for relative in required_pages:
        if not (DIST / relative).is_file():
            fail(f"missing required page: {relative}", problems)

    movie_pages = {movie_path(movie): page_for_route(movie_path(movie)) for movie in movies}
    album_pages = {album_path(album): page_for_route(album_path(album)) for album in albums}
    song_pages = {f'/song/{song["id"]}/': page_for_route(f'/song/{song["id"]}/') for song in songs}
    for route, page in [*movie_pages.items(), *album_pages.items(), *song_pages.items()]:
        if not page.is_file():
            fail(f"missing generated page for {route}", problems)

    # Exact route coverage: every song record makes a page, including tracks without media.
    actual_song_page_ids = {page.parent.name for page in (DIST / "song").glob("*/index.html")} if (DIST / "song").is_dir() else set()
    missing_song_ids = sorted(expected_song_ids - actual_song_page_ids)
    unexpected_song_ids = sorted(actual_song_page_ids - expected_song_ids)
    if missing_song_ids:
        fail(f"missing song pages for {len(missing_song_ids)} database song(s): {', '.join(missing_song_ids[:8])}", problems)
    if unexpected_song_ids:
        fail(f"unexpected song pages not backed by a database song: {', '.join(unexpected_song_ids[:8])}", problems)
    if len(actual_song_page_ids) != len(songs):
        fail(f"database has {len(songs)} songs but generated {len(actual_song_page_ids)} song pages", problems)

    # Public index is a compact derivative of SQLite, never a source used by the builder.
    index_path = DIST / "search-index.json"
    if not index_path.is_file():
        fail("dist/search-index.json is missing", problems)
        index = {}
    else:
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            fail(f"search-index.json is invalid JSON ({type(exc).__name__})", problems)
            index = {}
    if isinstance(index, dict):
        if len(index.get("songs", [])) != len(songs):
            fail(f"search index has {len(index.get('songs', []))} songs but SQLite has {len(songs)}", problems)
        if len(index.get("movies", [])) != len(movies):
            fail(f"search index has {len(index.get('movies', []))} movies but SQLite has {len(movies)}", problems)
        if len(index.get("albums", [])) != len(albums):
            fail(f"search index has {len(index.get('albums', []))} albums but SQLite has {len(albums)}", problems)
        indexed_song_ids = {str(song.get("id")) for song in index.get("songs", []) if isinstance(song, dict)}
        if indexed_song_ids != expected_song_ids:
            fail("search-index song IDs do not exactly match normalized SQLite song IDs", problems)
        if index.get("songs") and not all(
            key in index["songs"][0]
            for key in ("id", "title", "albumTitle", "movieTitle", "artists", "lyricists", "albumPath", "durationSec")
        ):
            fail("search-index song records are missing fields required by search/drawer", problems)
        if index.get("albums") and not all(key in index["albums"][0] for key in ("path", "title", "movieTitle", "songs")):
            fail("search-index album records are missing fields required by advanced search", problems)

    # Core catalog pages should expose exactly the normalized content count.
    songs_html_path = DIST / "songs" / "index.html"
    if songs_html_path.is_file():
        text = songs_html_path.read_text(encoding="utf-8")
        actual_rows = text.count('class="track song-catalog-item"')
        if actual_rows != len(songs):
            fail(f"song catalogue displays {actual_rows} rows but SQLite contains {len(songs)} songs", problems)
        for marker in ('id="song-query"', 'id="song-sort"', 'id="song-artist"', 'id="song-lyricist"', 'id="song-music"', 'id="song-grid"'):
            if marker not in text:
                fail(f"songs page missing expected filter/control: {marker}", problems)
        # Track genres are optional: the filter must not be a dead control when there are none.
        has_song_genres = any(song["genres"] for song in songs)
        if has_song_genres and 'id="song-genre"' not in text:
            fail("song-genre data exists but the song genre filter is missing", problems)
        if not has_song_genres and 'id="song-genre"' in text:
            fail("song genre filter is shown although the normalized song_genres table has no values", problems)

    albums_html_path = DIST / "albums" / "index.html"
    if albums_html_path.is_file():
        text = albums_html_path.read_text(encoding="utf-8")
        if text.count('class="album-card"') != len(albums):
            fail(f"album catalogue displays {text.count('class=\"album-card\"')} cards but SQLite contains {len(albums)} albums", problems)
        for marker in ('id="album-query"', 'id="album-sort"', 'id="album-artist"', 'id="album-genre"', 'id="album-grid"'):
            if marker not in text:
                fail(f"albums page missing expected filter/control: {marker}", problems)

    movies_html_path = DIST / "movies" / "index.html"
    if movies_html_path.is_file():
        text = movies_html_path.read_text(encoding="utf-8")
        for marker in ('id="movie-query"', 'id="movie-sort"', 'id="movie-genre"', 'id="movie-music"', 'id="movie-director"', 'class="movies-grid"'):
            if marker not in text:
                fail(f"movies page missing expected filter/control: {marker}", problems)

    charts_path = DIST / "charts" / "index.html"
    if charts_path.is_file():
        text = charts_path.read_text(encoding="utf-8")
        chart_song_rows = text.count('href="/song/')
        if chart_song_rows < min(30, len(songs)):
            fail(f"charts page has only {chart_song_rows} song links; expected at least {min(30, len(songs))}", problems)
        if text.count('data-chart-panel=') != 3:
            fail("charts page should contain songs, albums and movies panels", problems)

    # Every page gets canonical H1/title/description metadata and a usable global shell.
    html_files = list(DIST.rglob("*.html"))
    redirects = redirects_from_dist()
    checked_links = 0
    for html_path in html_files:
        try:
            text = html_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            fail(f"could not read {html_path.relative_to(DIST)} ({type(exc).__name__})", problems)
            continue
        if text.count("<h1") != 1:
            fail(f"{html_path.relative_to(DIST)}: expected one h1, found {text.count('<h1')}", problems)
        if "<title>" not in text or 'name="description"' not in text:
            fail(f"{html_path.relative_to(DIST)}: missing title or description", problems)
        if 'id="q"' not in text or 'id="song-drawer"' not in text or 'id="theme-toggle"' not in text:
            fail(f"{html_path.relative_to(DIST)}: global search/drawer/theme shell missing", problems)
        for href in re.findall(r'(?:href|src)="(/[^\"]*)"', text):
            path = unquote(urlsplit(unescape(href)).path)
            if not path:
                continue
            checked_links += 1
            target = page_for_route(path)
            # Static redirects are valid local destinations for pre-existing legacy URLs.
            if not target.is_file() and path not in redirects:
                fail(f"{html_path.relative_to(DIST)}: broken internal link {href}", problems)

    # Song metadata must be curated. Technical provider details belong only in buttons/player links.
    banned_visible_metadata = (
        "Spotify track ID", "Spotify URL", "Spotify preview URL", "YouTube Music video ID",
        "YouTube Music URL", "Duration (milliseconds)", "Not provided in source data",
        "Not specified in source data", "All available track and release metadata", "Source title",
    )
    lyrics_rows_present = 0
    expected_media_less = {song["id"] for song in songs if not any(song.get(k) for k in ("spotify_url", "ytm_url", "youtube_url"))}
    media_less_pages_checked = 0
    for song in songs:
        page = song_pages[f'/song/{song["id"]}/']
        if not page.is_file():
            continue
        text = page.read_text(encoding="utf-8")
        try:
            metadata_html = text.split('<section class="song-metadata-section"', 1)[1].split("</section>", 1)[0]
        except IndexError:
            fail(f"{page.relative_to(DIST)}: missing curated song metadata section", problems)
            continue
        for banned in banned_visible_metadata:
            if banned.casefold() in metadata_html.casefold():
                fail(f"{page.relative_to(DIST)}: technical or missing-data text leaked into metadata: {banned}", problems)
        if "Spotify URL" in text or "Not provided in source data" in text or "Duration (milliseconds)" in text:
            fail(f"{page.relative_to(DIST)}: old raw/missing-metadata UI remains", problems)
        should_have_lyrics = bool(song.get("lrc_lyrics") or song.get("plain_lyrics"))
        if should_have_lyrics:
            lyrics_rows_present += 1
            if 'class="song-lyrics-section"' not in text:
                fail(f"{page.relative_to(DIST)}: lyrics exist in SQLite but lyrics section is missing", problems)
        elif 'class="song-lyrics-section"' in text:
            fail(f"{page.relative_to(DIST)}: empty lyrics section is rendered without lyrics data", problems)
        if song["id"] in expected_media_less:
            media_less_pages_checked += 1
            # Media buttons are optional; the canonical page and normalized title must survive.
            if f'<h1>{e(song["title"])}</h1>' not in text:
                fail(f"{page.relative_to(DIST)}: media-less song page is missing its title", problems)

    # The actual current DB has no lyrics, but fixtures protect the future LRC/plain path.
    validate_lyrics_component(problems)

    # Verify app bundle cache parameters were built from the actual generated data/assets.
    app_js = DIST / "static" / "app.js"
    style_css = DIST / "static" / "style.css"
    if not app_js.is_file() or not style_css.is_file():
        fail("static app.js or style.css is missing from dist/static", problems)
    else:
        js_text = app_js.read_text(encoding="utf-8")
        css_text = style_css.read_text(encoding="utf-8")
        if "__SEARCH_INDEX_VERSION__" in js_text:
            fail("unresolved search-index cache version placeholder in generated app.js", problems)
        if "?v=dev" in js_text or "?v=20261016-jsonmeta3" in js_text:
            fail("stale hard-coded asset cache version remains in generated app.js", problems)
        if "song-lyricist" not in js_text or "selectedLyricist" not in js_text:
            fail("song lyricist filter is not wired into the browser filtering logic", problems)
        if "song-lyrics-section" not in css_text or "lyrics-lines" not in css_text:
            fail("lyrics styles are missing from static/style.css", problems)

    if problems:
        print("SITE CHECK FAILED:")
        for problem in problems[:80]:
            print("- " + problem)
        if len(problems) > 80:
            print(f"- ... {len(problems) - 80} additional issue(s)")
        raise SystemExit(1)

    media_less_pages_checked = len(expected_media_less)
    print(
        f"Site check passed: {len(movies)} movies, {len(albums)} albums, {len(songs)} songs "
        f"({media_less_pages_checked} without media, {lyrics_rows_present} with lyrics); "
        f"{len(html_files)} HTML files and {checked_links} internal links checked."
    )
    print("Source JSON-independence check passed: normalized catalogue output is unchanged when source JSON/blob columns are emptied.")
    print("ok")


if __name__ == "__main__":
    main()
