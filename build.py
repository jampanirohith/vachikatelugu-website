#!/usr/bin/env python3
"""Build the static site into dist/. Standard library only.

    python3 build.py

Site URL (used for canonical links, Open Graph and sitemap.xml) is read from,
in order: the SITE_URL environment variable, "url" in site.json, CF_PAGES_URL.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import unicodedata
from datetime import datetime
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent
from db_source import load_database_catalogue
CONFIG = ROOT / "site.json"
STATIC = ROOT / "static"
DIST = ROOT / "dist"

ASSET_VERSION = "dev"
SEARCH_INDEX_VERSION = "dev"

FONT_URL = (
    "https://fonts.googleapis.com/css2?family=Anek+Telugu:wdth,wght@75..125,300..800&display=swap"
)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def e(value) -> str:
    return escape("" if value is None else str(value), quote=True)


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


_QUOTE = "\"“”"
_TITLE_RULES = [
    re.compile(rf"\s*[\(\[]\s*From\s+[{_QUOTE}][^{_QUOTE}]*[{_QUOTE}]\s*[\)\]]", re.I),
    re.compile(rf"\s+-\s+From\s+[{_QUOTE}][^{_QUOTE}]*[{_QUOTE}]\s*$", re.I),
    re.compile(r"\s*[\(\[]\s*Telugu\s*[\)\]]", re.I),
    re.compile(r"\s+-\s+Telugu(\s+Version)?\s*$", re.I),
]


def clean_title(title: str) -> str:
    out = title
    for rule in _TITLE_RULES:
        out = rule.sub("", out)
    out = re.sub(r"\s+-\s*$", "", out).strip()
    # "You’Re" -> "You’re" (contraction suffixes that arrive capitalised)
    out = re.sub(r"(?<=[A-Za-z])([’'])(Re|S|Ll|Ve|D|T|M)\b", lambda m: m.group(1) + m.group(2).lower(), out)
    return out or title


def clean_artist(name: str) -> str:
    """Drop bracketed notes such as 'Puyush Kapoor (English Lyrics Dsp)'."""
    return re.sub(r"\s*\([^)]*\)", "", name).strip() or name


def parse_plays(text):
    if not text:
        return 0
    m = re.match(r"([\d.]+)\s*([KMB]?)", text)
    if not m:
        return 0
    return float(m.group(1)) * {"": 1, "K": 1e3, "M": 1e6, "B": 1e9}[m.group(2)]


def duration_secs(text: str) -> int:
    mins, secs = text.split(":")
    return int(mins) * 60 + int(secs)


def iso_duration(text: str) -> str:
    total = duration_secs(text)
    return f"PT{total // 60}M{total % 60}S"


def fmt_date(text):
    if not text:
        return ""
    try:
        d = datetime.strptime(text[:10], "%Y-%m-%d")
    except ValueError:
        return text
    return f"{d.day} {d:%B %Y}"


def people(names) -> str:
    """Comma-separated links that run a site search for each name."""
    return ", ".join(f'<a href="/?q={e(quote(n))}">{e(n)}</a>' for n in names)


def quote(text: str) -> str:
    from urllib.parse import quote as q
    return q(text, safe="")


def movie_path(movie) -> str:
    """Use the IMDb ID as the stable movie route, falling back to the title slug."""
    imdb_id = str(movie.get("imdb_id") or "")
    if re.fullmatch(r"tt\d+", imdb_id):
        return f"/{imdb_id}/"
    return f"/movie/{movie['slug']}/"


def album_path(entity) -> str:
    """Canonical album route, based on the local database album identity."""
    album = entity if isinstance(entity, dict) and entity.get("album_id") else None
    if album is None and isinstance(entity, dict):
        album = entity.get("album")
        if not (isinstance(album, dict) and album.get("album_id")):
            albums = entity.get("albums") or []
            album = albums[0] if albums else None
    if isinstance(album, dict) and album.get("slug"):
        return f"/album/{album['slug']}/"
    movie = entity.get("movie") if isinstance(entity, dict) and entity.get("movie") else entity
    if isinstance(movie, dict) and movie.get("imdb_id"):
        return movie_path(movie) + "album/"
    return "/albums/"


def album_art(album, movie=None):
    """Return an actual album image, or a movie-poster fallback with correct context."""
    movie = movie or (album.get("movie") if isinstance(album, dict) else None) or {}
    return ((album or {}).get("artwork") or (album or {}).get("artwork_small") or movie.get("poster"))


def movie_primary_album(movie):
    album = movie.get("album")
    return album if isinstance(album, dict) else {}


# --------------------------------------------------------------------------
# data
# --------------------------------------------------------------------------

def load_movies():
    """Build the site's in-memory model from normalized SQLite columns/relations.

    No page content is read from movies.raw_json, albums.raw_json, songs.raw_json,
    or a sidecar catalogue JSON file. Database relationship tables are authoritative.
    """
    catalogue = load_database_catalogue()
    movies, movie_by_id, albums, album_by_id = [], {}, [], {}
    used_movie_slugs, used_album_slugs = set(), set()

    def text_or_none(value):
        if value is None:
            return None
        text = str(value).strip()
        if not text or text.casefold() in {"n/a", "na", "not available", "not provided", "not specified", "unknown", "null", "none", "undefined"}:
            return None
        return text

    def tri_bool(value):
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip().casefold()
            if normalized in {"1", "true", "yes", "y"}:
                return True
            if normalized in {"0", "false", "no", "n"}:
                return False
            return None
        try:
            return bool(int(value))
        except (TypeError, ValueError):
            return bool(value)

    language_names = {
        "te": "Telugu", "hi": "Hindi", "ta": "Tamil", "ml": "Malayalam",
        "kn": "Kannada", "en": "English", "bn": "Bengali", "mr": "Marathi",
        "ur": "Urdu", "sa": "Sanskrit", "pa": "Punjabi", "gu": "Gujarati",
    }

    def display_language(value):
        text = text_or_none(value)
        return language_names.get(text.casefold(), text) if text else None

    def unique_slug(base, used):
        base = slugify(base) or "untitled"
        result = base
        counter = 2
        while result in used:
            result = f"{base}-{counter}"
            counter += 1
        used.add(result)
        return result

    def names_for(movie, role):
        return [clean_artist(str(person).strip()) for person in movie["people"].get(role, []) if text_or_none(person)]

    for row in catalogue["movies"]:
        title = str(row.get("title") or "Untitled film").strip()
        year = str(row.get("release_year") or "Unknown")
        slug = unique_slug(f"{title}-{year}", used_movie_slugs)
        urls = dict(row.get("links") or {})
        for key, field in (("imdb", "imdb_url"), ("tmdb", "tmdb_url"), ("wikipedia", "wikipedia_url"),
                           ("wikipedia_soundtrack", "wikipedia_soundtrack_url")):
            urls.setdefault(key, row.get(field))
        movie = {
            "imdb_id": str(row.get("imdb_id") or ""), "slug": slug, "title": title,
            "telugu": text_or_none(row.get("title_telugu")) or "", "year": year,
            # The normalized schema only stores the release year; do not invent an exact date.
            "released": None, "original_language": display_language(row.get("original_language")),
            "cinematic_universe": text_or_none(row.get("cinematic_universe")),
            "genres": list(row.get("genres") or []),
            "certification": text_or_none(row.get("certification")) or "",
            "plot": text_or_none(row.get("plot_summary")) or "",
            "runtime_minutes": row.get("runtime_minutes"),
            "poster": row.get("poster_url"), "backdrop": row.get("backdrop_url"),
            "title_logo": row.get("title_logo_url"),
            "music_directors": names_for(row, "music_director"),
            "directors": names_for(row, "director"), "cast": names_for(row, "cast"),
            "cinematographers": names_for(row, "cinematographer"),
            "production_banners": names_for(row, "production_banner"),
            "additional_people": [],
            "trailer": text_or_none(row.get("trailer_youtube_id")),
            "imdb_score": text_or_none(row.get("imdb_score")),
            "imdb_votes": text_or_none(row.get("imdb_votes")),
            "imdb_votes_numeric": row.get("imdb_votes_numeric"),
            "urls": urls, "ott_availability": list(row.get("ott_availability") or []),
            "albums": [], "album": {}, "songs": [],
        }
        known_roles = {"music_director", "director", "cast", "cinematographer", "production_banner"}
        role_labels = {
            "writer": "Writers", "screenwriter": "Screenwriters", "producer": "Producers",
            "editor": "Editors", "story": "Story", "composer": "Composers",
            "lyricist": "Lyricists", "choreographer": "Choreographers", "production_designer": "Production design",
        }
        for role, raw_names in (row.get("people") or {}).items():
            if role in known_roles:
                continue
            extra_names = []
            seen_extra = set()
            for raw_name in raw_names:
                name = clean_artist(str(raw_name).strip())
                if name and name.casefold() not in seen_extra:
                    seen_extra.add(name.casefold())
                    extra_names.append(name)
            if extra_names:
                label = role_labels.get(role, role.replace("_", " ").strip().title())
                movie["additional_people"].append({"label": label, "names": extra_names})
        movie_by_id[movie["imdb_id"]] = movie
        movies.append(movie)

    # Build each actual album as its own entity and route; do not assume one album per film.
    for row in catalogue["albums"]:
        movie = movie_by_id.get(row.get("movie_id"))
        if not movie:
            continue
        album_title = (text_or_none(row.get("title")) or text_or_none(row.get("spotify_album_title"))
                       or text_or_none(row.get("youtube_album_title")) or f'{movie["title"]} soundtrack')
        album = {
            "album_id": row.get("album_id"), "movie_id": row.get("movie_id"),
            "title": album_title, "slug": unique_slug(
                f'{album_title}-{movie["year"]}-{str(row.get("album_id") or "")[-6:]}', used_album_slugs
            ),
            "released": text_or_none(row.get("release_date")),
            "label": text_or_none(row.get("label")), "upc": text_or_none(row.get("upc_barcode")),
            "spotify_popularity": row.get("spotify_popularity"),
            "copyright_c": text_or_none(row.get("copyright_c")),
            "copyright_p": text_or_none(row.get("copyright_p")),
            "artwork": row.get("artwork_hd_640"), "artwork_small": row.get("artwork_300"),
            "spotify_id": text_or_none(row.get("spotify_album_id")),
            "ytm_id": text_or_none(row.get("youtube_album_id")),
            "spotify_title": text_or_none(row.get("spotify_album_title")),
            "ytm_title": text_or_none(row.get("youtube_album_title")),
            "spotify_url": row.get("spotify_url"), "ytm_url": row.get("youtube_music_url"),
            "spotify_total_tracks": row.get("spotify_total_tracks"),
            "declared_total_tracks": row.get("declared_total_tracks") or 0,
            "spotify_saved_to_library": row.get("spotify_saved_to_library"),
            "movie": movie, "songs": [],
        }
        movie["albums"].append(album)
        album_by_id[album["album_id"]] = album
        albums.append(album)

    for raw in catalogue["songs"]:
        movie = movie_by_id.get(raw.get("movie_id"))
        album = album_by_id.get(raw.get("album_id"))
        if not movie or not album or album.get("movie_id") != raw.get("movie_id"):
            raise RuntimeError(f"Song {raw.get('song_id')!r} has inconsistent normalized movie/album relationships")
        if not str(raw.get("song_id") or "").strip() or not str(raw.get("title") or "").strip():
            raise RuntimeError("A processed song row is missing song_id or title")
        title = clean_title(str(raw["title"]).strip())
        number = None
        for number_value in (raw.get("track_number"), raw.get("track_number_original")):
            if number_value is not None:
                try:
                    number = int(number_value)
                    break
                except (TypeError, ValueError):
                    continue
        original_number = raw.get("track_number_original")

        media = raw.get("media") or {}
        spotify = media.get("spotify") or media.get("spotify_track") or {}
        ytm = media.get("youtube_music") or media.get("ytmusic") or {}
        youtube = media.get("youtube") or media.get("youtube_video") or media.get("youtube_video_song") or {}
        spotify_uri = text_or_none(raw.get("spotify_uri"))
        spotify_uri_match = re.fullmatch(r"spotify:track:([A-Za-z0-9]+)", spotify_uri or "")
        spotify_id = text_or_none(spotify.get("external_id")) or (spotify_uri_match.group(1) if spotify_uri_match else None)
        ytm_id = text_or_none(ytm.get("external_id"))
        youtube_id = text_or_none(youtube.get("external_id"))
        spotify_url = text_or_none(spotify.get("url")) or (f"https://open.spotify.com/track/{spotify_id}" if spotify_id else None)
        ytm_url = text_or_none(ytm.get("url")) or (f"https://music.youtube.com/watch?v={ytm_id}" if ytm_id else None)
        youtube_url = text_or_none(youtube.get("url")) or (f"https://www.youtube.com/watch?v={youtube_id}" if youtube_id else None)

        sec = raw.get("duration_sec")
        ms = raw.get("duration_ms")
        try:
            sec = int(sec) if sec is not None else (int(ms) // 1000 if ms is not None else None)
        except (TypeError, ValueError):
            sec = None
        try:
            ms = int(ms) if ms is not None else (sec * 1000 if sec is not None else None)
        except (TypeError, ValueError):
            ms = sec * 1000 if sec is not None else None
        duration = text_or_none(raw.get("duration_formatted"))
        if not duration and sec is not None and sec >= 0:
            duration = f"{sec // 60}:{sec % 60:02d}"
        if duration and not re.fullmatch(r"\d{1,4}:\d{2}", duration):
            duration = f"{sec // 60}:{sec % 60:02d}" if sec is not None and sec >= 0 else ""
        duration = duration or ""

        artist_credits = raw.get("artist_credits") or []
        artist_names, seen_artist_names = [], set()
        for credit in artist_credits:
            name = clean_artist(str(credit.get("name") or "").strip())
            if name and name.casefold() not in seen_artist_names:
                seen_artist_names.add(name.casefold())
                artist_names.append(name)
        lyricist_credits = raw.get("lyricist_credits") or []
        lyricist_names, seen_lyricists = [], set()
        for credit in lyricist_credits:
            name = str(credit.get("name") or "").strip()
            if name and name.casefold() not in seen_lyricists:
                seen_lyricists.add(name.casefold())
                lyricist_names.append(name)

        ytm_views = text_or_none(ytm.get("views_text"))
        youtube_views = text_or_none(youtube.get("views_text"))
        explicit_value = raw.get("is_explicit")
        bonus_value = raw.get("is_bonus_track")
        all_media_ids = []
        for media_row in media.values():
            external_id = text_or_none(media_row.get("external_id"))
            if external_id and external_id not in all_media_ids:
                all_media_ids.append(external_id)
        preferred_legacy_id = spotify_id or ytm_id or youtube_id
        song = {
            "id": str(raw.get("song_id") or ""), "song_id": str(raw.get("song_id") or ""),
            "legacy_ids": all_media_ids, "legacy_preferred_id": preferred_legacy_id,
            "title": title, "raw_title": str(raw.get("title") or "").strip(),
            "number": number, "original_number": original_number,
            "disc_number": raw.get("disc_number"), "artists": artist_names,
            "artist_credits": artist_credits, "lyricists": lyricist_names,
            "genres": list(raw.get("genres") or []),
            "song_flavor": (lambda flavor: None if flavor and flavor.casefold() in {"film soundtrack", "soundtrack"} else flavor)(text_or_none(raw.get("song_flavor"))),
            "duration": duration, "duration_sec": sec, "duration_ms": ms,
            "explicit": tri_bool(explicit_value),
            "bonus_track": tri_bool(bonus_value),
            "isrc_code": text_or_none(raw.get("isrc_code")),
            "data_source": text_or_none(raw.get("data_source")),
            "spotify_id": spotify_id, "spotify_url": spotify_url,
            "spotify_preview_url": text_or_none(spotify.get("preview_url")),
            "spotify_popularity": spotify.get("popularity"),
            "ytm_id": ytm_id, "ytm_url": ytm_url, "ytm_views": ytm_views,
            "plays": ytm_views, "plays_num": parse_plays(ytm_views),
            "youtube_video_id": youtube_id, "youtube_url": youtube_url,
            "youtube_video_title": text_or_none(youtube.get("video_title")),
            "youtube_video_views": youtube_views,
            "lrc_lyrics": text_or_none(raw.get("lrc_lyrics")),
            "plain_lyrics": text_or_none(raw.get("plain_lyrics")),
            "lrclib_id": text_or_none(raw.get("lrclib_id")),
            "lyrics_status": text_or_none(raw.get("lyrics_status")),
            "lyrics_type": text_or_none(raw.get("lyrics_type")),
            "movie": movie, "album": album,
        }
        movie["songs"].append(song)
        album["songs"].append(song)

    # The primary album is a convenience for movie-card art and legacy links only;
    # each song and each generated album page points to its real album entity.
    for movie in movies:
        movie["songs"].sort(key=lambda song: (song.get("disc_number") or 1,
                                                   song.get("number") if song.get("number") is not None else 2147483647,
                                                   song["title"].casefold(), song["id"]))
        movie["albums"].sort(key=lambda album: (-len(album["songs"]), album["title"].casefold(), album["album_id"] or ""))
        movie["album"] = movie["albums"][0] if movie["albums"] else {}
        for album in movie["albums"]:
            album["songs"].sort(key=lambda song: (song.get("disc_number") or 1,
                                                     song.get("number") if song.get("number") is not None else 2147483647,
                                                     song["title"].casefold(), song["id"]))
            album["actual_total_tracks"] = len(album["songs"])
        if movie["album"]:
            if movie["album"].get("spotify_url"):
                movie["urls"]["spotify_album"] = movie["album"]["spotify_url"]
            if movie["album"].get("ytm_url"):
                movie["urls"]["youtube_music_album"] = movie["album"]["ytm_url"]
        else:
            movie["album"] = {
                "album_id": None, "title": f'{movie["title"]} soundtrack', "slug": "",
                "released": None, "label": None, "upc": None, "copyright_c": None,
                "copyright_p": None, "artwork": None, "artwork_small": None,
                "spotify_id": None, "ytm_id": None, "spotify_url": None, "ytm_url": None,
                "songs": [], "movie": movie,
            }
    # Use actual relationship counts rather than potentially stale denormalized counters.
    for movie in movies:
        movie["database_song_count"] = len(movie["songs"])

    return movies


# --------------------------------------------------------------------------
# page chrome
# --------------------------------------------------------------------------

def layout(cfg, site_url, *, title, desc, path, body, og_type="website", og_image=None,
           jsonld=None, noindex=False):
    full_title = title if title == cfg["name"] else f"{title} | {cfg['name']}"
    head = [
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{e(full_title)}</title>",
        f'<meta name="description" content="{e(desc)}">',
        '<meta name="color-scheme" content="dark light">',
        '<link rel="icon" href="/static/favicon.png" type="image/png">',
    ]
    if noindex:
        head.append('<meta name="robots" content="noindex">')
    if site_url and not noindex:
        head.append(f'<link rel="canonical" href="{e(site_url + path)}">')
        head.append(f'<meta property="og:url" content="{e(site_url + path)}">')
    head += [
        f'<meta property="og:site_name" content="{e(cfg["name"])}">',
        f'<meta property="og:type" content="{og_type}">',
        f'<meta property="og:title" content="{e(title)}">',
        f'<meta property="og:description" content="{e(desc)}">',
    ]
    if og_image:
        head.append(f'<meta property="og:image" content="{e(og_image)}">')
        head.append('<meta name="twitter:card" content="summary_large_image">')
    head += [
        '<link rel="preconnect" href="https://fonts.googleapis.com">',
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>',
        f'<link rel="stylesheet" href="{FONT_URL}">',
        f'<link rel="stylesheet" href="/static/style.css?v={e(ASSET_VERSION)}">',
        f'<script src="/static/app.js?v={e(ASSET_VERSION)}" defer></script>',
    ]
    if jsonld:
        blob = json.dumps(jsonld, ensure_ascii=False).replace("<", "\\u003c")
        head.append(f'<script type="application/ld+json">{blob}</script>')

    return f"""<!doctype html>
<html lang="en">
<head>
{chr(10).join(head)}
</head>
<body>
<header class="site-header">
  <div class="header-inner">
    <a class="brand" href="/" aria-label="Vachika home"><img class="brand-wordmark" src="/static/vachika-wordmark.png" alt="Vachika" width="160" height="37"><span class="brand-badge" aria-hidden="true">MUSIC</span></a>
    <nav class="site-nav" aria-label="Main navigation">
      <a class="nav-link{' active' if path == '/' else ''}" href="/">Home</a>
      <a class="nav-link{' active' if path == '/songs/' else ''}" href="/songs/">Songs</a>
      <a class="nav-link{' active' if path == '/albums/' or path.startswith('/album/') or path.endswith('/album/') else ''}" href="/albums/">Albums</a>
      <a class="nav-link{' active' if path == '/movies/' or path.startswith('/movie/') or (path.startswith('/tt') and not path.endswith('/album/')) else ''}" href="/movies/">Movies</a>
      <a class="nav-link{' active' if path == '/charts/' else ''}" href="/charts/">Charts</a>
    </nav>
    <form role="search" action="/advanced-search/" method="get" class="search header-search" id="global-search-form">
      <label class="sr" for="q">Search songs, films, albums and artists</label>
      <input id="q" name="q" type="search" placeholder="Search songs, films, albums…" autocomplete="off" enterkeyhint="search" aria-controls="search-popover" aria-expanded="false">
      <button type="submit" aria-label="Search"><span aria-hidden="true">⌕</span></button>
      <a class="advanced-search-link" href="/advanced-search/" aria-label="Open advanced database search">Advanced</a>
      <div id="search-popover" class="search-popover" hidden role="status" aria-label="Search suggestions"></div>
    </form>
    <button type="button" class="theme-toggle" id="theme-toggle" aria-label="Switch theme" title="Switch between dark and light theme"><span class="theme-toggle-icon" aria-hidden="true">☼</span></button>
  </div>
</header>
<main id="main">
{body}
</main>
<div id="song-drawer-backdrop" class="drawer-backdrop" hidden></div>
<aside id="song-drawer" class="song-drawer" aria-hidden="true" aria-labelledby="drawer-title" role="dialog" aria-modal="false">
  <div class="drawer-topline"><span class="eyebrow">NOW EXPLORING</span><button type="button" class="drawer-close" id="drawer-close" aria-label="Close song details">×</button></div>
  <img id="drawer-artwork" class="drawer-artwork" alt="" width="640" height="640" hidden>
  <p class="eyebrow drawer-kicker">TELUGU SOUNDTRACK</p>
  <h2 id="drawer-title">Song details</h2>
  <p class="drawer-film" id="drawer-film"></p>
  <p class="drawer-album-link"><a id="drawer-album-link" href="/albums/">Open soundtrack album ↗</a></p>
  <p class="drawer-artists" id="drawer-artists"></p>
  <div class="drawer-facts" id="drawer-facts"></div>
  <div class="drawer-actions" id="drawer-actions"></div>
  <div id="drawer-player-area" class="drawer-player-area"></div>
  <a id="drawer-full-details" class="btn drawer-full-details" href="/" data-full-song-link>Open full song page ↗</a>
</aside>
<footer class="site-footer">
  <p>Song audio, artwork and film details belong to their owners. Play links go to Spotify and YouTube Music.</p>
  <p>Film data and images from TMDB. This site uses the TMDB API but is not endorsed or certified by TMDB.</p>
</footer>
</body>
</html>
"""


def img(src, alt, cls, w, h, eager=False):
    if not src:
        return ""
    loading = "eager" if eager else "lazy"
    return (f'<img class="{cls}" src="{e(src)}" alt="{e(alt)}" width="{w}" height="{h}" '
            f'loading="{loading}" decoding="async" referrerpolicy="no-referrer">')


def song_row(song, *, rank=None, current=False, show_movie=True, show_plays=False, filterable=False):
    number = rank if rank is not None else song.get("number")
    number_markup = f'<span class="n">{e(number)}</span>' if number not in (None, "") else ""
    sub = f'{e(song["movie"]["title"])}, {e(song["movie"]["year"])}' if show_movie else ""
    if not show_movie and song["artists"]:
        sub = e(", ".join(song["artists"][:3]))
    plays = f'<span class="plays">{e(song["plays"])}</span>' if show_plays and song["plays"] else ""
    cur = ' aria-current="true"' if current else ""
    movie = song["movie"]
    artwork = album_art(song.get("album"), movie)
    cover = (f'<img class="track-artwork" src="{e(artwork)}" alt="" width="48" height="48" loading="lazy" decoding="async" referrerpolicy="no-referrer">'
             if artwork else '<span class="track-artwork track-artwork-empty" aria-hidden="true">♪</span>')
    filter_attrs = ""
    if filterable:
        filter_attrs = (f' class="track song-catalog-item" data-title="{e(song["title"].lower())}" '
            f'data-artists="{e("|".join(song["artists"]).lower())}" data-lyricists="{e("|".join(song["lyricists"]).lower())}" '
            f'data-music="{e("|".join(movie["music_directors"]).lower())}" data-album="{e(song["album"]["title"].lower())}" '
            f'data-genre="{e("|".join(song["genres"]).lower())}" data-release="{e(movie["released"] or (movie["year"] + "-01-01"))}" '
            f'data-year="{e(movie["year"])}" data-plays="{song["plays_num"]}" data-songid="{e(song["id"])}"')
    else:
        filter_attrs = ' class="track"'
    return (
        f'<li{filter_attrs}><a href="/song/{e(song["id"])}/"{cur}>'
        f'{number_markup}{cover}'
        f'<span class="main"><span class="name">{e(song["title"])}</span>'
        f'<span class="sub">{sub}</span></span>'
        f'<span class="meta">{f'<span class="dur">{e(song["duration"])}</span>' if song.get("duration") and song["duration"] != "—" else ""}{plays}</span>'
        f"</a></li>"
    )


def facts(rows):
    items = "".join(f"<dt>{e(k)}</dt><dd>{v}</dd>" for k, v in rows if v)
    return f'<dl class="facts">{items}</dl>'


def provider_icon(provider: str) -> str:
    """Small inline provider marks; these accompany text labels for accessibility."""
    if provider == "spotify":
        return ('<svg class="provider-icon spotify-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
                '<circle cx="12" cy="12" r="11" fill="currentColor"/><path d="M5.3 9.2c4.3-1.2 9.4-.7 13.2 1.5M6.2 12.4c3.6-1 7.7-.5 10.8 1.3M7.1 15.3c2.8-.7 5.9-.3 8.2 1" '
                'fill="none" stroke="var(--spotify-contrast,#10110f)" stroke-width="1.45" stroke-linecap="round"/></svg>')
    return ('<svg class="provider-icon youtube-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
            '<circle cx="12" cy="12" r="11" fill="currentColor"/><path d="M10 7.8 17 12l-7 4.2z" fill="var(--youtube-contrast,#fff)"/></svg>')


def listen_links(song):
    out = []
    if song.get("spotify_url"):
        out.append(f'<a class="btn provider-btn spotify-btn" href="{e(song["spotify_url"])}" rel="noopener noreferrer" target="_blank">{provider_icon("spotify")}<span>Open on Spotify</span></a>')
    if song.get("ytm_url"):
        out.append(f'<a class="btn provider-btn youtube-btn" href="{e(song["ytm_url"])}" rel="noopener noreferrer" target="_blank">{provider_icon("youtube")}<span>Open on YouTube Music</span></a>')
    if song.get("youtube_url"):
        out.append(f'<a class="btn provider-btn youtube-video-btn" href="{e(song["youtube_url"])}" rel="noopener noreferrer" target="_blank">{provider_icon("youtube")}<span>Watch on YouTube</span></a>')
    return "".join(out)


def player(song):
    if song.get("spotify_id"):
        kind, ident = "spotify", song["spotify_id"]
    elif song.get("ytm_id"):
        kind, ident = "youtube", song["ytm_id"]
    else:
        return ""
    return (f'<div class="player"><button type="button" class="btn" data-embed="{kind}" '
            f'data-id="{e(ident)}">Play here</button></div>')


def youtube_video_block(song):
    video_id = song.get("youtube_video_id")
    if not video_id:
        return ""
    thumb = f'https://i.ytimg.com/vi/{e(video_id)}/hqdefault.jpg'
    title = song.get("youtube_video_title") or song["title"]
    views = f'<span class="video-views">{e(song["youtube_video_views"])} views</span>' if song.get("youtube_video_views") else ""
    return (
        f'<section class="song-video-section"><div class="section-heading"><div><p class="eyebrow">YOUTUBE VIDEO</p><h2>Song video</h2></div>{views}</div>'
        f'<p class="song-video-title">{e(title)}</p>'
        f'<div class="trailer song-video-embed"><button type="button" data-embed="youtube" data-id="{e(video_id)}" aria-label="Play YouTube video for {e(song["title"])}"><img src="{thumb}" alt="" width="480" height="360" loading="lazy" decoding="async" referrerpolicy="no-referrer"><span class="play">Play video</span></button></div>'
        f'<div class="actions"><a class="btn provider-btn youtube-video-btn" href="{e(song.get("youtube_url") or "")}" rel="noopener noreferrer" target="_blank">{provider_icon("youtube")}<span>Watch on YouTube</span></a></div></section>'
    )


def provider_search_url(provider, title):
    from urllib.parse import quote as url_quote
    q = url_quote(title, safe="")
    key = str(provider or "").strip().lower()
    if "netflix" in key:
        return f"https://www.netflix.com/search?q={q}"
    if "sony liv" in key:
        return f"https://www.sonyliv.com/search?q={q}"
    if "zee5" in key:
        return f"https://www.zee5.com/search?q={q}"
    if "hotstar" in key:
        return f"https://www.hotstar.com/in/search?q={q}"
    if "apple tv" in key:
        return f"https://tv.apple.com/search?term={q}"
    if "youtube" in key:
        return f"https://www.youtube.com/results?search_query={q}"
    if "amazon" in key or "prime video" in key or "ultraplaybox" in key:
        return f"https://www.primevideo.com/search?phrase={q}"
    if "sun nxt" in key:
        return f"https://www.google.com/search?q={url_quote('site:sunnxt.com ' + title, safe='')}"
    if "vi movies" in key:
        return f"https://www.google.com/search?q={url_quote('site:myvi.in/entertainment ' + title, safe='')}"
    return f"https://www.google.com/search?q={url_quote(provider + ' ' + title, safe='')}"


def ott_provider_icon(provider):
    p = str(provider or "").lower()
    if "netflix" in p:
        label, cls = "N", "ott-logo-netflix"
    elif "amazon" in p or "ultraplaybox" in p:
        label, cls = "prime", "ott-logo-prime"
    elif "apple" in p:
        label, cls = "tv", "ott-logo-apple"
    elif "youtube" in p:
        label, cls = "▶", "ott-logo-youtube"
    elif "zee5" in p:
        label, cls = "ZEE5", "ott-logo-zee5"
    elif "sony liv" in p:
        label, cls = "SONY\nLIV", "ott-logo-sonyliv"
    elif "hotstar" in p:
        label, cls = "Jio", "ott-logo-hotstar"
    elif "sun nxt" in p:
        label, cls = "SUN", "ott-logo-sunnxt"
    elif p.startswith("vi"):
        label, cls = "Vi", "ott-logo-vi"
    else:
        label, cls = (str(provider or "?")[:4].upper(), "ott-logo-generic")
    return f'<span class="ott-logo {cls}" aria-hidden="true">{e(label).replace(chr(10), "<br>")}</span>'


def ott_buttons(movie):
    entries = movie.get("ott_availability") or []
    if not entries:
        return '<p class="empty">No streaming availability listed in the current data.</p>'
    out = []
    for entry in entries:
        provider = str(entry.get("provider") or "Streaming provider")
        mode = str(entry.get("type") or "flatrate").lower()
        if mode in ("rent", "rent/buy"):
            verb = "Rent on"
        elif mode == "buy":
            verb = "Buy on"
        elif mode in ("free", "ads", "free with ads"):
            verb = "Watch on"
        else:
            verb = "Stream on"
        out.append(f'<a class="ott-provider-btn" href="{e(provider_search_url(provider, movie["title"]))}" target="_blank" rel="noopener noreferrer">{ott_provider_icon(provider)}<span class="ott-provider-copy"><strong>{e(verb)} {e(provider)}</strong><small>{e("Subscription" if mode == "flatrate" else mode.replace("_", " ").title())}</small></span><span class="ott-arrow" aria-hidden="true">↗</span></a>')
    return "".join(out)


def movie_links_dropdown(movie):
    urls = movie.get("urls") or {}
    labels = [("imdb", "IMDb"), ("tmdb", "TMDB"), ("wikipedia", "Wikipedia"),
              ("wikipedia_soundtrack", "Wikipedia soundtrack"),
              ("spotify_album", "Spotify soundtrack"), ("youtube_music_album", "YouTube Music soundtrack")]
    links = []
    for key, label in labels:
        url = urls.get(key)
        if url:
            links.append(f'<a href="{e(url)}" target="_blank" rel="noopener noreferrer">{e(label)} <span aria-hidden="true">↗</span></a>')
    if not links:
        return ""
    return '<details class="movie-links-dropdown"><summary class="btn">More links <span aria-hidden="true">⌄</span></summary><div class="movie-links-menu">' + "".join(links) + '</div></details>'



# --------------------------------------------------------------------------
# pages
# --------------------------------------------------------------------------

def format_count(value) -> str:
    """Compactly format aggregate play counts for display."""
    value = max(0, float(value or 0))
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}".rstrip("0").rstrip(".") + "B"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}".rstrip("0").rstrip(".") + "M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}".rstrip("0").rstrip(".") + "K"
    return f"{int(value):,}"


def album_total_plays(movie) -> float:
    """Sum captured YouTube Music plays for every track in a film soundtrack."""
    return sum(song["plays_num"] for song in movie["songs"])


def album_card(album, *, eager=False, filterable=False):
    movie = album["movie"]
    artwork = album_art(album, movie)
    count = len(album["songs"])
    total = album_total_plays(album)
    loading = "eager" if eager else "lazy"
    actual_cover = bool(album.get("artwork") or album.get("artwork_small"))
    alt = f'Album artwork for {album["title"]}' if actual_cover else f'Movie poster for {movie["title"]}; album artwork unavailable'
    cover = (f'<img class="album-cover{" album-cover-fallback" if not actual_cover and artwork else ""}" src="{e(artwork)}" alt="{e(alt)}" '
             f'width="640" height="640" loading="{loading}" decoding="async" referrerpolicy="no-referrer">'
             if artwork else '<span class="album-cover album-cover-empty" aria-hidden="true">♪</span>')
    released = album["released"] or (movie["year"] + "-01-01")
    artists = "|".join(movie["music_directors"])
    genres = "|".join(movie["genres"])
    wrapper_class = ' class="album-item"'
    attrs = (f'{wrapper_class} data-title="{e((album["title"] + " " + movie["title"]).lower())}" data-year="{e(movie["year"])}" '
             f'data-release="{e(released)}" data-artist="{e(artists.lower())}" data-plays="{total}" '
             f'data-songs="{count}" data-genre="{e(genres.lower())}"')
    return (
        f'<li{attrs}><a class="album-card" href="{e(album_path(album))}">'
        f'{cover}<span class="album-card-title">{e(album["title"])}</span>'
        f'<span class="sub">{e(movie["title"])} · {e(movie["year"])} · {count} {"song" if count == 1 else "songs"}</span>'
        f'<span class="album-plays">{e(format_count(total))} combined plays</span>'
        f'</a></li>'
    )


def movie_card(movie, *, eager=False):
    artwork = movie["poster"] or album_art(movie.get("album"), movie)
    count = len(movie["songs"])
    genres = "|".join(movie["genres"])
    music = "|".join(movie["music_directors"])
    directors = "|".join(movie["directors"])
    release = movie["released"] or (movie["year"] + "-01-01")
    loading = "eager" if eager else "lazy"
    cover = (f'<img class="movie-cover" src="{e(artwork)}" alt="Poster for {e(movie["title"])}" width="500" height="750" '
             f'loading="{loading}" decoding="async" referrerpolicy="no-referrer">'
             if artwork else '<span class="movie-cover movie-cover-empty" aria-hidden="true">▣</span>')
    return (
        f'<li class="movie-item" data-title="{e(movie["title"].lower())}" data-release="{e(release)}" '
        f'data-year="{e(movie["year"])}" data-genre="{e(genres.lower())}" data-music="{e(music.lower())}" '
        f'data-director="{e(directors.lower())}" data-songs="{count}">'
        f'<a class="movie-card" href="{e(movie_path(movie))}">{cover}'
        f'<span class="movie-card-title">{e(movie["title"])}</span>'
        f'<span class="sub">{e(movie["year"])} · {count} {"song" if count == 1 else "songs"}</span>'
        f'<span class="movie-card-genre">{e(", ".join(movie["genres"][:2]))}</span>'
        f'</a></li>'
    )


def home_page(cfg, site_url, movies):
    all_songs = [s for m in movies for s in m["songs"]]
    all_albums = [album for movie in movies for album in movie["albums"]]
    with_songs = [m for m in movies if m["songs"]]
    top_songs = sorted(all_songs, key=lambda s: s["plays_num"], reverse=True)[:5]
    popular_albums = sorted(all_albums, key=album_total_plays, reverse=True)[:6]
    top_rows = "".join(song_row(song, rank=i + 1, show_plays=True) for i, song in enumerate(top_songs))
    album_items = "".join(album_card(movie, eager=i < 3) for i, movie in enumerate(popular_albums))

    body = f"""
<section class="home-intro wrap">
  <p class="eyebrow">TELUGU SOUNDTRACK ARCHIVE</p>
  <h1>Every song has a story.</h1>
  <p class="lede">Discover songs, albums and the films behind them.</p>
  <div class="home-stats"><span>{len(all_songs)} songs</span><span>{len(all_albums)} albums</span></div>
</section>

<div id="results" class="wrap search-results" hidden>
  <section id="song-results" hidden><h2>Songs</h2><ol class="tracks" id="song-list"></ol></section>
  <section id="film-results" hidden><h2>Films</h2><ol class="tracks" id="film-list"></ol></section>
  <p id="empty" class="empty" hidden></p>
</div>
<p id="status" class="sr" role="status" aria-live="polite"></p>

<div id="browse" class="wrap">
  <section class="home-section">
    <div class="section-heading"><div><p class="eyebrow">PLAY COUNT LEADERS</p><h2>Charts</h2></div><a class="text-link" href="/charts/">View all charts <span aria-hidden="true">↗</span></a></div>
    <ol class="tracks">{top_rows}</ol>
  </section>
  <section class="home-section">
    <div class="section-heading"><div><p class="eyebrow">TRACKS ADD UP</p><h2>Popular albums</h2></div><a class="text-link" href="/albums/">Explore all albums <span aria-hidden="true">↗</span></a></div>
    <p class="section-note">Ranked by the combined plays of each soundtrack's songs.</p>
    <ul class="albums-grid">{album_items}</ul>
  </section>
</div>
"""
    return layout(cfg, site_url, title=cfg["name"],
                  desc=f'{cfg["tagline"]}. Explore {len(all_songs)} songs, {len(all_albums)} albums and song charts.',
                  path="/", body=body)


def albums_page(cfg, site_url, movies):
    albums = sorted((album for movie in movies for album in movie["albums"]), key=album_total_plays, reverse=True)
    items = "".join(album_card(album, eager=i < 4, filterable=True) for i, album in enumerate(albums))
    total_plays = sum(album_total_plays(album) for album in albums)
    artists = sorted({artist for album in albums for artist in album["movie"]["music_directors"] if artist}, key=str.casefold)
    artist_options = "".join(f'<option value="{e(a.lower())}">{e(a)}</option>' for a in artists)
    genres = sorted({genre for album in albums for genre in album["movie"]["genres"] if genre}, key=str.casefold)
    body = f"""
<section class="page-intro wrap">
  <p class="eyebrow">SOUNDTRACK LIBRARY</p>
  <h1>Albums</h1>
  <p class="lede">Explore {len(albums)} soundtrack albums from the database, with album-level tracklists and listening links.</p>
  <p class="intro-meta">{len(albums)} albums <span aria-hidden="true">·</span> {e(format_count(total_plays))} combined track plays in the current data</p>
</section>
<section class="wrap page-section">
  <details class="filter-panel" id="album-filter-panel" open>
    <summary class="filter-panel-summary"><span class="filter-summary-label">Filters and sorting</span><span class="filter-summary-count" id="album-filter-summary-count">{len(albums)} albums</span><span class="filter-summary-chevron" aria-hidden="true"></span></summary>
    <div class="filter-bar" id="album-filters" aria-label="Filter albums">
    <label class="filter-search">Find an album<input id="album-query" type="search" placeholder="Album or film title" autocomplete="off"></label>
    <label>Sort by<select id="album-sort"><option value="plays">Most played</option><option value="release-new">Newest release</option><option value="release-old">Oldest release</option><option value="title-az">Title A–Z</option><option value="title-za">Title Z–A</option><option value="songs">Most songs</option></select></label>
    <label>Music director<select id="album-artist"><option value="">All artists</option>{artist_options}</select></label>
    <label>Movie genre<select id="album-genre"><option value="">All genres</option>{"".join(f'<option value="{e(g.lower())}">{e(g)}</option>' for g in genres)}</select></label>
    <label>Released from<input type="date" id="album-from" aria-label="Album release from date"></label>
    <label>Released to<input type="date" id="album-to" aria-label="Album release to date"></label>
      <p class="filter-count" id="album-count" aria-live="polite">{len(albums)} albums</p>
    </div>
  </details>
  <ul class="albums-grid albums-grid-large" id="album-grid">{items}</ul>
  <p class="empty" id="album-empty" hidden>No albums match those filters. Try a different title, artist or sort option.</p>
  <p class="data-note">Play counts are captured provider snapshots, not live analytics. Album totals add the listed YouTube Music plays for songs on that album; missing counts contribute zero. Release sorting uses an album release date where available and otherwise the film release year.</p>
</section>
"""
    return layout(cfg, site_url, title="Telugu soundtrack albums", desc="Browse Telugu soundtrack albums by combined song plays, release date, title and music director.", path="/albums/", body=body)


def movies_page(cfg, site_url, movies):
    ordered = sorted(movies, key=lambda m: (m["released"] or (m["year"] + "-01-01")), reverse=True)
    items = "".join(movie_card(movie, eager=i < 4) for i, movie in enumerate(ordered))
    genres = sorted({genre for movie in movies for genre in movie["genres"] if genre}, key=str.casefold)
    artists = sorted({a for movie in movies for a in movie["music_directors"] if a}, key=str.casefold)
    directors = sorted({a for movie in movies for a in movie["directors"] if a}, key=str.casefold)
    genre_options = "".join(f'<option value="{e(g.lower())}">{e(g)}</option>' for g in genres)
    artist_options = "".join(f'<option value="{e(a.lower())}">{e(a)}</option>' for a in artists)
    director_options = "".join(f'<option value="{e(a.lower())}">{e(a)}</option>' for a in directors)
    body = f"""
<section class="page-intro wrap">
  <p class="eyebrow">FILMOGRAPHY</p>
  <h1>Movies</h1>
  <p class="lede">Browse films and jump into each movie's soundtrack, song credits and music links.</p>
  <p class="intro-meta">{len(movies)} movies in the database</p>
</section>
<section class="wrap page-section">
  <details class="filter-panel" id="movie-filter-panel" open>
    <summary class="filter-panel-summary"><span class="filter-summary-label">Filters and sorting</span><span class="filter-summary-count" id="movie-filter-summary-count">{len(movies)} movies</span><span class="filter-summary-chevron" aria-hidden="true"></span></summary>
    <div class="filter-bar movie-filter-bar" id="movie-filters" aria-label="Filter movies">
    <label class="filter-search">Find a movie<input id="movie-query" type="search" placeholder="Movie title" autocomplete="off"></label>
    <label>Sort by<select id="movie-sort"><option value="release-new">Newest release</option><option value="release-old">Oldest release</option><option value="title-az">Title A–Z</option><option value="title-za">Title Z–A</option><option value="songs">Most songs</option></select></label>
    <label>Genre<select id="movie-genre"><option value="">All genres</option>{genre_options}</select></label>
    <label>Music director<select id="movie-music"><option value="">All music directors</option>{artist_options}</select></label>
    <label>Director<select id="movie-director"><option value="">All directors</option>{director_options}</select></label>
    <label>Released from<input type="date" id="movie-from" aria-label="Movie release from date"></label>
    <label>Released to<input type="date" id="movie-to" aria-label="Movie release to date"></label>
      <p class="filter-count" id="movie-count" aria-live="polite">{len(movies)} movies</p>
    </div>
  </details>
  <ul class="movies-grid" id="movie-grid">{items}</ul>
  <p class="empty" id="movie-empty" hidden>No movies match those filters. Try changing the title, genre or director.</p>
</section>
"""
    return layout(cfg, site_url, title="Telugu movies", desc="Browse Telugu films by release date, genre, director and music director, and explore each movie soundtrack.", path="/movies/", body=body)


def songs_page(cfg, site_url, movies):
    songs = [song for movie in movies for song in movie["songs"]]
    songs.sort(key=lambda song: song["plays_num"], reverse=True)
    artists = sorted({artist for song in songs for artist in song["artists"] if artist}, key=str.casefold)
    genres = sorted({genre for song in songs for genre in song["genres"] if genre}, key=str.casefold)
    lyricists = sorted({lyricist for song in songs for lyricist in song["lyricists"] if lyricist}, key=str.casefold)
    music_directors = sorted({artist for movie in movies for artist in movie["music_directors"] if artist}, key=str.casefold)
    artist_options = "".join(f'<option value="{e(a.lower())}">{e(a)}</option>' for a in artists)
    genre_options = "".join(f'<option value="{e(g.lower())}">{e(g)}</option>' for g in genres)
    genre_filter_markup = (f'<label>Track genre<select id="song-genre"><option value="">All track genres</option>{genre_options}</select></label>' if genres else "")
    lyricist_options = "".join(f'<option value="{e(a.lower())}">{e(a)}</option>' for a in lyricists)
    music_options = "".join(f'<option value="{e(a.lower())}">{e(a)}</option>' for a in music_directors)
    rows = "".join(song_row(song, rank=i + 1, show_movie=True, show_plays=True, filterable=True) for i, song in enumerate(songs))
    body = f"""
<section class="page-intro wrap">
  <p class="eyebrow">THE FULL TRACK LIBRARY</p>
  <h1>Songs</h1>
  <p class="lede">Search every song in the database, browse by singer or lyricist, and narrow the list by available track genres and movie release year.</p>
  <p class="intro-meta">{len(songs)} songs across {len(movies)} movies</p>
</section>
<section class="wrap page-section">
  <details class="filter-panel" id="song-filter-panel" open>
    <summary class="filter-panel-summary"><span class="filter-summary-label">Filters and sorting</span><span class="filter-summary-count" id="song-filter-summary-count">{len(songs)} songs</span><span class="filter-summary-chevron" aria-hidden="true"></span></summary>
    <div class="filter-bar song-filter-bar" id="song-filters" aria-label="Filter songs">
    <label class="filter-search">Search songs<input id="song-query" type="search" placeholder="Song, film or singer" autocomplete="off"></label>
    <label>Sort by<select id="song-sort"><option value="plays">Most played</option><option value="release-new">Newest movie</option><option value="release-old">Oldest movie</option><option value="title-az">Title A–Z</option><option value="title-za">Title Z–A</option></select></label>
    <label>Singer / artist<select id="song-artist"><option value="">All singers</option>{artist_options}</select></label>
    <label>Lyricist<select id="song-lyricist"><option value="">All lyricists</option>{lyricist_options}</select></label>
    <label>Music director<select id="song-music"><option value="">All music directors</option>{music_options}</select></label>
    {genre_filter_markup}
    <label>Movie released from<input id="song-from" type="date" aria-label="Movie release from date"></label>
    <label>Movie released to<input id="song-to" type="date" aria-label="Movie release to date"></label>
      <p class="filter-count" id="song-count" aria-live="polite">{len(songs)} songs</p>
    </div>
  </details>
  <ol class="tracks chart-tracks" id="song-grid">{rows}</ol>
  <p class="empty" id="song-empty" hidden>No songs match those filters. Try a different artist, genre or release range.</p>
</section>
"""
    return layout(cfg, site_url, title="Telugu songs library", desc=f"Search and filter all {len(songs)} Telugu movie songs by singer, music director, genre, plays and release date.", path="/songs/", body=body)


def advanced_search_page(cfg, site_url):
    body = """
<section class="page-intro wrap advanced-search-intro">
  <p class="eyebrow">SEARCH THE ENTIRE DATABASE</p>
  <h1>Advanced search</h1>
  <p class="lede">Search songs, movies and soundtrack albums together, or narrow the results to one type.</p>
</section>
<section class="wrap page-section advanced-search-page">
  <form id="advanced-search-form" class="advanced-search-controls" role="search">
    <label class="advanced-query-label">Search term<input id="advanced-query" type="search" placeholder="Try a title, singer, director, genre or IMDb ID" autocomplete="off" autofocus></label>
    <button type="submit" class="btn primary advanced-submit">Search database</button>
    <details class="filter-panel advanced-options-panel" id="advanced-options-panel" open>
      <summary class="filter-panel-summary"><span class="filter-summary-label">Search options</span><span class="filter-summary-detail">Type, dates and sorting</span><span class="filter-summary-chevron" aria-hidden="true"></span></summary>
      <div class="advanced-search-options">
        <label>Search type<select id="advanced-type"><option value="all">Everything</option><option value="song">Songs</option><option value="album">Albums</option><option value="movie">Movies</option></select></label>
        <label>Release from<input id="advanced-from" type="date"></label>
        <label>Release to<input id="advanced-to" type="date"></label>
        <label>Sort results<select id="advanced-sort"><option value="relevance">Best match</option><option value="popular">Most played</option><option value="newest">Newest first</option><option value="oldest">Oldest first</option><option value="title-az">Title A–Z</option><option value="title-za">Title Z–A</option></select></label>
      </div>
    </details>
  </form>
  <div class="advanced-results-head"><h2>Results</h2><p id="advanced-count" class="filter-count" aria-live="polite">Enter a term to search the database.</p></div>
  <div id="advanced-results" class="advanced-results-grid" aria-live="polite"></div>
  <p id="advanced-empty" class="empty" hidden>No matching records. Try a broader term, another type, or adjust the release-date range.</p>
</section>
"""
    return layout(cfg, site_url, title="Advanced database search", desc="Search Telugu songs, albums and movies in Vachika with type, release-date and sorting filters.", path="/advanced-search/", body=body)


def chart_entity_row(entity, rank, kind):
    if kind == "album":
        album = entity
        movie = album["movie"]
        artwork = album_art(album, movie)
        path = album_path(album)
        count = len(album["songs"])
        total = album_total_plays(album)
        title = album["title"]
        subtitle = f'{movie["title"]} · {movie["year"]} · {count} {"song" if count == 1 else "songs"}'
    else:
        movie = entity
        artwork = movie["poster"] or album_art(movie.get("album"), movie)
        path = movie_path(movie)
        count = len(movie["songs"])
        total = album_total_plays(movie)
        title = movie["title"]
        subtitle = f'{movie["year"]} · {count} {"song" if count == 1 else "songs"} · {len(movie["albums"])} {"album" if len(movie["albums"]) == 1 else "albums"}'
    cover = (f'<img class="track-artwork" src="{e(artwork)}" alt="" width="48" height="48" loading="lazy" decoding="async" referrerpolicy="no-referrer">' if artwork else '<span class="track-artwork track-artwork-empty" aria-hidden="true">♪</span>')
    return f'<li class="track entity-chart-row"><a href="{e(path)}"><span class="n">{rank}</span>{cover}<span class="main"><span class="name">{e(title)}</span><span class="sub">{e(subtitle)}</span></span><span class="meta"><span class="plays">{e(format_count(total))} plays</span></span></a></li>'


def charts_page(cfg, site_url, movies):
    songs = sorted((s for movie in movies for s in movie["songs"]), key=lambda s: s["plays_num"], reverse=True)
    albums = sorted((album for movie in movies for album in movie["albums"]), key=album_total_plays, reverse=True)
    movies_ranked = sorted(movies, key=album_total_plays, reverse=True)
    song_rows = "".join(song_row(song, rank=i + 1, show_plays=True) for i, song in enumerate(songs[:30]))
    album_rows = "".join(chart_entity_row(album, i + 1, "album") for i, album in enumerate(albums[:30]))
    movie_rows = "".join(chart_entity_row(movie, i + 1, "movie") for i, movie in enumerate(movies_ranked[:30]))
    body = f"""
<section class="page-intro wrap">
  <p class="eyebrow">DATABASE RANKINGS</p>
  <h1>Charts</h1>
  <p class="lede">Explore the most-played songs, soundtrack albums and movies with the strongest combined song plays in the current dataset.</p>
  <p class="intro-meta">{len(songs)} songs · {len(albums)} albums · {len(movies)} movies <span>·</span> Snapshot-based, not live</p>
</section>
<section class="wrap page-section charts-section">
  <div class="chart-tabs" role="tablist" aria-label="Chart type">
    <button class="chart-tab is-active" type="button" role="tab" aria-selected="true" data-chart-tab="songs">Songs</button>
    <button class="chart-tab" type="button" role="tab" aria-selected="false" data-chart-tab="albums">Albums</button>
    <button class="chart-tab" type="button" role="tab" aria-selected="false" data-chart-tab="movies">Movies</button>
  </div>
  <section class="chart-panel is-active" data-chart-panel="songs" role="tabpanel">
    <div class="section-heading"><div><p class="eyebrow">TRACK LEADERS</p><h2>Most-played songs</h2></div><a class="text-link" href="/songs/">Browse all songs ↗</a></div>
    <ol class="tracks chart-tracks">{song_rows}</ol>
  </section>
  <section class="chart-panel" data-chart-panel="albums" role="tabpanel" hidden>
    <div class="section-heading"><div><p class="eyebrow">SOUNDTRACK LEADERS</p><h2>Popular albums</h2></div><a class="text-link" href="/albums/">Browse all albums ↗</a></div>
    <ol class="tracks entity-chart-list">{album_rows}</ol>
  </section>
  <section class="chart-panel" data-chart-panel="movies" role="tabpanel" hidden>
    <div class="section-heading"><div><p class="eyebrow">FILM SOUNDTRACK LEADERS</p><h2>Popular movies</h2></div><a class="text-link" href="/movies/">Browse all movies ↗</a></div>
    <ol class="tracks entity-chart-list">{movie_rows}</ol>
  </section>
  <p class="data-note">Songs are ranked by captured YouTube Music plays. Album and movie charts sum available song-level YouTube Music play snapshots; missing counts contribute zero.</p>
</section>
"""
    return layout(cfg, site_url, title="Telugu music charts", desc="Charts for Telugu songs, soundtrack albums and movies ranked using play counts in the current database.", path="/charts/", body=body)


def render_lyrics_section(song):
    """Render lyric text only when populated; keep LRC timestamp data per line."""
    lrc = song.get("lrc_lyrics")
    plain = song.get("plain_lyrics")
    if not lrc and not plain:
        return ""
    if lrc:
        rendered = []
        timestamp_re = re.compile(r"\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\]")
        for raw_line in lrc.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            timestamps = list(timestamp_re.finditer(line))
            text = timestamp_re.sub("", line).strip()
            # Ignore LRC metadata tags such as [ar:], [ti:], [by:] rather than
            # printing parser directives as if they were lyric lines.
            if not text or re.fullmatch(r"\[[A-Za-z]+:.*\]", text):
                continue
            if timestamps:
                for match in timestamps:
                    minutes, seconds = int(match.group(1)), int(match.group(2))
                    fraction = (match.group(3) or "0")
                    centiseconds = int((fraction + "00")[:2])
                    total_seconds = minutes * 60 + seconds + centiseconds / 100
                    visible_time = f"{minutes}:{seconds:02d}"
                    rendered.append(
                        f'<li class="lyrics-line" data-time="{total_seconds:.2f}"><time class="lyrics-timestamp">{visible_time}</time><span>{e(text)}</span></li>'
                    )
            else:
                rendered.append(f'<li class="lyrics-line lyrics-line-untimed"><span>{e(text)}</span></li>')
        if not rendered:
            # Malformed LRC should still degrade to readable text without raw timestamps.
            cleaned = timestamp_re.sub("", lrc).strip()
            source = cleaned or plain or ""
            content = "".join(f'<p>{e(line)}</p>' for line in source.splitlines() if line.strip())
            if not content:
                return ""
            lyrics_markup = f'<div class="lyrics-plain">{content}</div>'
            label = "Lyrics"
        else:
            lyrics_markup = '<ol class="lyrics-lines">' + "".join(rendered) + "</ol>"
            label = "LRC lyrics"
    else:
        content = "".join(f'<p>{e(line)}</p>' for line in (plain or "").splitlines() if line.strip())
        if not content:
            return ""
        lyrics_markup = f'<div class="lyrics-plain">{content}</div>'
        label = "Plain lyrics"
    return (
        '<section class="song-lyrics-section" aria-labelledby="song-lyrics-heading">'
        f'<div class="section-heading"><div><p class="eyebrow">LYRICS</p><h2 id="song-lyrics-heading">Lyrics</h2></div><span class="lyrics-format">{e(label)}</span></div>'
        f'<div class="lyrics-panel">{lyrics_markup}</div>'
        '</section>'
    )


def song_page(cfg, site_url, song):
    m = song["movie"]
    album = song["album"]
    art = album_art(album, m)
    credits = song["artists"]
    lyricist_names = song["lyricists"]
    album_song_count = len(album["songs"])
    desc_bits = [f'{song["title"]} from {m["title"]} ({m["year"]}).']
    if m["music_directors"]:
        desc_bits.append("Music by " + ", ".join(m["music_directors"][:3]) + ".")
    if credits:
        desc_bits.append("Artists: " + ", ".join(credits[:4]) + ".")
    if lyricist_names:
        desc_bits.append("Lyrics by " + ", ".join(lyricist_names[:3]) + ".")
    if song.get("duration") and song["duration"] != "—":
        desc_bits.append(f'Duration {song["duration"]}.')
    providers = []
    if song.get("spotify_url"):
        providers.append("Spotify")
    if song.get("ytm_url"):
        providers.append("YouTube Music")
    if song.get("youtube_url"):
        providers.append("YouTube")
    if providers:
        desc_bits.append("Listen on " + ", ".join(providers) + ".")

    others = "".join(song_row(other, current=(other["id"] == song["id"]), show_movie=False, show_plays=True) for other in album["songs"] if other["id"] != song["id"])
    about_rows = [
        ("Director", people(m["directors"])),
        ("Starring", people(m["cast"][:6])),
        ("Movie genres", e(", ".join(m["genres"]))),
        ("Release year", e(m["year"])),
        ("Language", e(m["original_language"])),
        ("IMDb rating", e(m["imdb_score"])),
    ]
    about = facts(about_rows)
    explicit = '<span class="flag">Explicit</span>' if song["explicit"] is True else ""

    artist_role_groups = {}
    for credit in song.get("artist_credits") or []:
        name = str(credit.get("name") or "").strip()
        role = str(credit.get("role") or "artist").strip().lower().replace("-", "_").replace(" ", "_")
        if name:
            artist_role_groups.setdefault(role or "artist", [])
            if name.casefold() not in {existing.casefold() for existing in artist_role_groups[role or "artist"]}:
                artist_role_groups[role or "artist"].append(name)
    artist_role_labels = {
        "artist": "Artists", "singer": "Singers", "vocalist": "Vocalists",
        "composer": "Composers", "performer": "Performers", "rapper": "Rappers",
        "musician": "Musicians", "producer": "Producers",
    }
    artist_metadata_rows = [
        (artist_role_labels.get(role, role.replace("_", " ").title() + ("s" if len(names) != 1 else "")), people(names))
        for role, names in artist_role_groups.items() if names
    ]
    if not artist_metadata_rows and credits:
        artist_metadata_rows.append(("Artists", people(credits)))
    metadata = artist_metadata_rows + [
        ("Lyricist" if len(lyricist_names) == 1 else "Lyricists", people(lyricist_names)),
        ("Album", f'<a href="{e(album_path(album))}">{e(album["title"])}</a>' if album.get("album_id") else ""),
        ("Duration", e(song["duration"] if song["duration"] != "—" else "")),
        ("Track number", e(song["number"] if song.get("number") is not None else "")),
        ("Disc", e(song["disc_number"] if song.get("disc_number") not in (None, 1) else "")),
        ("Genre" if len(song["genres"]) == 1 else "Genres", e(", ".join(song["genres"]))),
        ("Song style", e(song.get("song_flavor") or "")),
        ("Bonus track", "Yes" if song["bonus_track"] is True else ""),
    ]
    metadata_markup = facts(metadata)
    video_block = youtube_video_block(song)
    theme_art = art or m["backdrop"] or m["poster"]
    lyrics_block = render_lyrics_section(song)
    more_album = "".join(
        f'<li><a href="{e(album_path(other_album))}">{e(other_album["title"])}</a></li>'
        for other_album in m["albums"] if other_album.get("album_id") != album.get("album_id")
    )
    other_albums_block = (
        f'<section class="song-other-albums"><h2>Other albums from {e(m["title"])}</h2><ul>{more_album}</ul></section>'
        if more_album else ""
    )
    body = f"""
<article class="wrap song detail-art-theme" style="--artwork-url: url('{e(theme_art or "")}')">
  <div class="song-head" style="--artwork-url: url('{e(art or "")}')">
    {img(art, "Artwork for " + album["title"] if album.get("artwork") or album.get("artwork_small") else "Movie poster for " + m["title"], "art", 640, 640, eager=True)}
    <div class="song-main">
      <p class="eyebrow">SONG</p>
      <h1>{e(song["title"])}</h1>
      <p class="from">From <a href="{e(movie_path(m))}">{e(m["title"])}</a>, {e(m["year"])} {explicit}</p>
      {f'<p class="song-credit-line">{e(", ".join(credits))}</p>' if credits else ''}
      <div class="actions">{listen_links(song)}<button type="button" class="btn" data-copy-link>Copy song link</button></div>
      {player(song)}
      <p><a class="text-link" href="{e(album_path(album))}">Open {e(album["title"])} album ↗</a></p>
    </div>
  </div>

  <section class="song-metadata-section">
    <div class="section-heading"><div><p class="eyebrow">TRACK INFORMATION</p><h2>Song metadata</h2></div></div>
    {metadata_markup}
  </section>

  {lyrics_block}
  {video_block}

  <section class="song-film-context">
    <h2>About the film</h2>
    {f'<p class="plot">{e(m["plot"])}</p>' if m["plot"] else ''}
    {about}
    <p><a href="{e(movie_path(m))}">All songs and details for {e(m["title"])}</a></p>
  </section>

  {other_albums_block}
  <section>
    <div class="section-heading"><div><p class="eyebrow">ALBUM TRACKLIST</p><h2>More from {e(album["title"])}</h2></div><a class="text-link" href="{e(album_path(album))}">Album page ↗</a></div>
    {f'<ol class="tracks">{others}</ol>' if others else '<p class="section-note">This is the only track currently listed for this album.</p>'}
  </section>
</article>
"""
    duration_schema = None
    if song.get("duration_sec") is not None and song["duration_sec"] >= 0:
        duration_schema = f'PT{song["duration_sec"] // 60}M{song["duration_sec"] % 60}S'
    ld = {
        "@context": "https://schema.org", "@type": "MusicRecording", "name": song["title"],
        "duration": duration_schema, "isrcCode": song["isrc_code"],
        "inAlbum": {"@type": "MusicAlbum", "name": album["title"], "url": (site_url + album_path(album)) if site_url else None},
        "byArtist": [{"@type": "Person", "name": name} for name in credits],
        "lyricist": [{"@type": "Person", "name": name} for name in lyricist_names],
        "url": site_url + f"/song/{song['id']}/" if site_url else None,
    }
    ld = {key: value for key, value in ld.items() if value}
    return layout(cfg, site_url, title=f'{song["title"]} ({m["title"]}, {m["year"]})', desc=" ".join(desc_bits),
                  path=f"/song/{song['id']}/", body=body, og_type="music.song", og_image=art, jsonld=ld)


def album_page(cfg, site_url, album):
    movie = album["movie"]
    art = album_art(album, movie)
    total = album_total_plays(album)
    tracks = album["songs"]
    rows = "".join(song_row(song, rank=i + 1, show_plays=True) for i, song in enumerate(tracks))
    artists = ", ".join(movie["music_directors"])
    soundtrack_links = []
    if album.get("spotify_url"):
        soundtrack_links.append(f'<a class="btn provider-btn spotify-btn" href="{e(album["spotify_url"])}" rel="noopener noreferrer" target="_blank">{provider_icon("spotify")}<span>Open on Spotify</span></a>')
    if album.get("ytm_url"):
        soundtrack_links.append(f'<a class="btn provider-btn youtube-btn" href="{e(album["ytm_url"])}" rel="noopener noreferrer" target="_blank">{provider_icon("youtube")}<span>Open on YouTube Music</span></a>')
    actual_cover = bool(album.get("artwork") or album.get("artwork_small"))
    alt = f'Album artwork for {album["title"]}' if actual_cover else f'Movie poster for {movie["title"]}; album artwork unavailable'
    cover = img(art, alt, "album-detail-art", 640, 640, eager=True) if art else '<div class="album-detail-art album-cover-empty" aria-hidden="true">♪</div>'
    release = album.get("released")
    detail_rows = [
        ("Release date", e(fmt_date(release))),
        ("Record label", e(album.get("label") or "")),
        ("Copyright", e(" · ".join([x for x in (album.get("copyright_c"), album.get("copyright_p")) if x]))),
    ]
    details_markup = facts(detail_rows)
    genre_text = ", ".join(movie["genres"])
    body = f"""
<article class="album-detail-page">
  <section class="album-detail-hero">
    <div class="wrap album-detail-head">
      {cover}
      <div class="album-detail-copy">
        <p class="eyebrow">SOUNDTRACK ALBUM{f' · {e(movie["imdb_id"])}' if movie["imdb_id"] else ''}</p>
        <h1>{e(album["title"])}</h1>
        {f'<p class="album-telugu" lang="te">{e(movie["telugu"])}</p>' if movie["telugu"] else ''}
        <p class="album-byline">{e(movie["title"])} · {e(artists or "Telugu film soundtrack")} · {e(movie["year"])}</p>
        <p class="album-stats">{len(tracks)} {"song" if len(tracks) == 1 else "songs"} <span>·</span> {e(format_count(total))} combined plays{f' <span>·</span> Released {e(fmt_date(release))}' if release else ''}</p>
        <div class="actions">{"".join(soundtrack_links)}<a class="btn" href="{e(movie_path(movie))}">Movie details</a></div>
        {f'<p class="section-note">Movie genres: {e(genre_text)}</p>' if genre_text else ''}
      </div>
    </div>
  </section>
  {f'<section class="wrap album-release-details"><h2>Release details</h2>{details_markup}</section>' if any(value for _, value in detail_rows) else ''}
  <section class="wrap page-section album-track-section">
    <div class="section-heading"><div><p class="eyebrow">FULL TRACKLIST</p><h2>Songs in this album</h2></div><span class="sort-label">{len(tracks)} tracks</span></div>
    {f'<ol class="tracks chart-tracks">{rows}</ol>' if rows else '<p class="empty">No tracks are currently linked to this album in the database.</p>'}
    <p class="data-note">Play counts are provider snapshots, not live analytics.</p>
  </section>
</article>
"""
    desc = f'{album["title"]} soundtrack album for {movie["title"]} ({movie["year"]}) with {len(tracks)} songs, credits and listening links.'
    return layout(cfg, site_url, title=f'{album["title"]} · {movie["title"]} soundtrack album', desc=desc,
                  path=album_path(album), body=body, og_type="music.album", og_image=art)


def movie_page(cfg, site_url, m):
    rows = "".join(song_row(song, show_movie=False, show_plays=True) for song in m["songs"])
    songs_block = (f'<section><h2>Songs</h2><ol class="tracks">{rows}</ol></section>' if m["songs"]
                   else '<section><h2>Songs</h2><p class="section-note">No songs are currently linked to this movie.</p></section>')
    albums_block = ""
    if m["albums"]:
        cards = "".join(album_card(album, eager=i < 2) for i, album in enumerate(m["albums"]))
        albums_block = (
            '<section class="movie-albums-section"><div class="section-heading"><div><p class="eyebrow">SOUNDTRACKS</p>'
            f'<h2>Albums for {e(m["title"])}</h2></div></div><ul class="albums-grid">{cards}</ul></section>'
        )

    trailer = ""
    if m["trailer"] and re.fullmatch(r"[A-Za-z0-9_-]{6,20}", m["trailer"]):
        thumb = f'https://i.ytimg.com/vi/{e(m["trailer"])}/hqdefault.jpg'
        trailer = ('<section><h2>Trailer</h2>'
            f'<div class="trailer"><button type="button" data-embed="youtube" data-id="{e(m["trailer"])}" aria-label="Play the trailer for {e(m["title"])}">'
            f'<img src="{thumb}" alt="" width="480" height="360" loading="lazy" decoding="async" referrerpolicy="no-referrer">'
            '<span class="play">Play trailer</span></button></div></section>')

    details_rows = [
        ("Directed by", people(m["directors"])),
        ("Music by", people(m["music_directors"])),
        ("Starring", people(m["cast"][:8])),
        ("Cinematography", e(", ".join(m["cinematographers"]))),
        ("Production", e(", ".join(m["production_banners"]))),
        ("Genre", e(", ".join(m["genres"]))),
        ("Original language", e(m["original_language"] or "")),
        ("Cinematic universe", e(m["cinematic_universe"] or "")),
        ("Certification", e(m["certification"] or "")),
        ("Runtime", e(f'{m["runtime_minutes"]} minutes' if m["runtime_minutes"] else "")),
        ("Release year", e(m["year"])),
        ("IMDb rating", e(m["imdb_score"] or "")),
        ("IMDb votes", e(m["imdb_votes"] or "")),
    ]
    details_rows.extend((entry["label"], people(entry["names"])) for entry in m.get("additional_people", []))
    details = facts(details_rows)
    telugu = f'<p class="te" lang="te">{e(m["telugu"])}</p>' if m["telugu"] else ""
    primary_art = album_art(m.get("album"), m)
    theme_art = m["backdrop"] or m["poster"] or primary_art
    links_dropdown = movie_links_dropdown(m)
    ott = ott_buttons(m)
    body = f"""
<article class="wrap movie detail-art-theme" style="--artwork-url: url('{e(theme_art or "")}')">
  {img(m["backdrop"], "", "backdrop", 1280, 720, eager=True)}
  <div class="movie-head">
    {img(m["poster"], "Poster of " + m["title"], "poster", 500, 750, eager=True)}
    <div class="movie-main-copy">
      <p class="eyebrow movie-imdb-id">IMDb · {e(m["imdb_id"])}</p>
      {img(m["title_logo"], "Title logo for " + m["title"], "movie-title-logo", 600, 220, eager=True)}
      <h1>{e(m["title"])}</h1>
      {telugu}
      {f'<p class="plot">{e(m["plot"])}</p>' if m["plot"] else ''}
      <div class="actions">{f'<a class="btn" href="{e(album_path(m["albums"][0]))}">Explore soundtrack</a>' if m["albums"] else ''}{links_dropdown}</div>
    </div>
  </div>
  <section class="ott-section"><div class="section-heading"><div><p class="eyebrow">WHERE TO WATCH</p><h2>Streaming availability</h2></div></div>
    {f'<p class="section-note">Availability comes from the database snapshot. Provider buttons open a search on the corresponding service.</p><div class="ott-provider-grid">{ott}</div>' if m["ott_availability"] else ''}
  </section>
  {albums_block}
  {songs_block}
  <section><h2>Movie details</h2>{details}</section>
  {trailer}
</article>
"""
    names = ", ".join(m["music_directors"][:2])
    desc = f'{m["title"]} ({m["year"]}): {len(m["songs"])} songs across {len(m["albums"])} albums' + (f", music by {names}" if names else "") + ". Tracklist, film credits, streaming availability and soundtrack links."
    rating = None
    try:
        rating_value = float(m["imdb_score"]) if m["imdb_score"] else None
    except (TypeError, ValueError):
        rating_value = None
    if rating_value is not None and m.get("imdb_votes_numeric"):
        rating = {"@type": "AggregateRating", "ratingValue": rating_value, "ratingCount": int(m["imdb_votes_numeric"])}
    ld = {
        "@context": "https://schema.org", "@type": "Movie", "name": m["title"],
        "datePublished": str(m["year"]) if m["year"] != "Unknown" else None,
        "image": m["poster"], "genre": m["genres"],
        "director": [{"@type": "Person", "name": name} for name in m["directors"]],
        "musicBy": [{"@type": "Person", "name": name} for name in m["music_directors"]],
        "actor": [{"@type": "Person", "name": name} for name in m["cast"][:8]],
        "url": (m.get("urls") or {}).get("imdb"), "aggregateRating": rating,
    }
    ld = {key: value for key, value in ld.items() if value}
    return layout(cfg, site_url, title=f'{m["imdb_id"]} · {m["title"]} ({m["year"]})' if m["imdb_id"] else f'{m["title"]} ({m["year"]})', desc=desc, path=movie_path(m),
                  body=body, og_type="video.movie", og_image=m["backdrop"] or m["poster"])


def not_found_page(cfg, site_url):
    body = """
<section class="wrap">
  <h1>That page isn't here</h1>
  <p class="lede">The link may be old or mistyped. Search for the song or film instead.</p>
  <p><a class="btn primary" href="/">Search the database</a></p>
</section>
"""
    return layout(cfg, site_url, title="Page not found", desc="Page not found.", path="/404.html", body=body, noindex=True)


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------

def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_search_index(movies):
    songs = [song for movie in movies for song in movie["songs"]]
    albums = [album for movie in movies for album in movie["albums"]]
    return {
        "songs": [{
            "id": song["id"], "title": song["title"], "movieTitle": song["movie"]["title"],
            "movieSlug": song["movie"]["slug"], "moviePath": movie_path(song["movie"]),
            "albumPath": album_path(song["album"]), "albumTitle": song["album"]["title"],
            "year": song["movie"]["year"], "released": song["movie"]["released"],
            "artists": song["artists"], "lyricists": song["lyricists"],
            "musicDirectors": song["movie"]["music_directors"], "plays": song["plays"],
            "playsNum": song["plays_num"], "duration": song["duration"],
            "durationSec": song["duration_sec"], "number": song["number"],
            "discNumber": song["disc_number"], "songCount": len(song["album"]["songs"]),
            "artwork": album_art(song["album"], song["movie"]), "poster": song["movie"]["poster"],
            "genres": song["genres"], "movieGenres": song["movie"]["genres"],
            "songFlavor": song["song_flavor"], "imdbId": song["movie"]["imdb_id"],
            "release": song["movie"]["released"] or (song["movie"]["year"] + "-01-01"),
            "spotifyId": song["spotify_id"], "ytmId": song["ytm_id"],
            "spotifyUrl": song["spotify_url"], "ytmUrl": song["ytm_url"],
            "youtubeVideoUrl": song["youtube_url"], "youtubeVideoId": song["youtube_video_id"],
            "youtubeVideoTitle": song["youtube_video_title"], "youtubeVideoViews": song["youtube_video_views"],
        } for song in songs],
        "movies": [{
            "slug": movie["slug"], "path": movie_path(movie), "albumPath": album_path(movie),
            "imdbId": movie["imdb_id"], "title": movie["title"], "telugu": movie["telugu"],
            "year": movie["year"], "released": movie["released"], "genres": movie["genres"],
            "musicDirectors": movie["music_directors"], "directors": movie["directors"],
            "cast": movie["cast"], "plot": movie["plot"], "certification": movie["certification"],
            "originalLanguage": movie["original_language"], "runtimeMinutes": movie["runtime_minutes"],
            "ottProviders": [entry.get("provider") for entry in movie["ott_availability"]],
            "songs": len(movie["songs"]), "albums": len(movie["albums"]), "poster": movie["poster"],
            "artwork": album_art(movie.get("album"), movie), "playsNum": album_total_plays(movie),
            "albumReleased": movie["album"].get("released"),
        } for movie in movies],
        "albums": [{
            "slug": album["slug"], "path": album_path(album), "moviePath": movie_path(album["movie"]),
            "imdbId": album["movie"]["imdb_id"], "title": album["title"],
            "movieTitle": album["movie"]["title"], "year": album["movie"]["year"],
            "release": album["released"] or (album["movie"]["year"] + "-01-01"),
            "artist": "|".join(album["movie"]["music_directors"]),
            "musicDirectors": album["movie"]["music_directors"],
            "genres": album["movie"]["genres"], "artwork": album_art(album, album["movie"]),
            "plays": album_total_plays(album), "songs": len(album["songs"]),
        } for album in albums],
    }


def main():
    global ASSET_VERSION, SEARCH_INDEX_VERSION
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    site_url = (os.environ.get("SITE_URL") or cfg.get("url") or os.environ.get("CF_PAGES_URL") or "").rstrip("/")
    if not site_url:
        print("warning: no site URL (set SITE_URL or site.json url); canonical links and sitemap are skipped", file=sys.stderr)

    movies = load_movies()
    songs = [song for movie in movies for song in movie["songs"]]
    albums = [album for movie in movies for album in movie["albums"]]
    search_index_text = json.dumps(build_search_index(movies), ensure_ascii=False, separators=(",", ":"))
    SEARCH_INDEX_VERSION = hashlib.sha256(search_index_text.encode("utf-8")).hexdigest()[:12]
    app_source = (STATIC / "app.js").read_text(encoding="utf-8")
    app_built = app_source.replace("__SEARCH_INDEX_VERSION__", SEARCH_INDEX_VERSION)
    if "__SEARCH_INDEX_VERSION__" in app_built:
        raise SystemExit("unresolved search-index cache-version placeholder in static/app.js")
    css_source = (STATIC / "style.css").read_bytes()
    ASSET_VERSION = hashlib.sha256(app_built.encode("utf-8") + css_source).hexdigest()[:12]

    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()
    shutil.copytree(STATIC, DIST / "static")
    (DIST / "static" / "app.js").write_text(app_built, encoding="utf-8")
    for extra in ("_headers", "_redirects"):
        if (ROOT / extra).exists():
            shutil.copy2(ROOT / extra, DIST / extra)

    urls = ["/", "/songs/", "/albums/", "/movies/", "/charts/", "/advanced-search/"]
    write(DIST / "index.html", home_page(cfg, site_url, movies))
    write(DIST / "songs" / "index.html", songs_page(cfg, site_url, movies))
    write(DIST / "albums" / "index.html", albums_page(cfg, site_url, movies))
    write(DIST / "movies" / "index.html", movies_page(cfg, site_url, movies))
    write(DIST / "charts" / "index.html", charts_page(cfg, site_url, movies))
    write(DIST / "advanced-search" / "index.html", advanced_search_page(cfg, site_url))

    for movie in movies:
        movie_route = movie_path(movie)
        write(DIST / movie_route.strip("/") / "index.html", movie_page(cfg, site_url, movie))
        urls.append(movie_route)
    for album in albums:
        route = album_path(album)
        write(DIST / route.strip("/") / "index.html", album_page(cfg, site_url, album))
        urls.append(route)
    for song in songs:
        route = f'/song/{song["id"]}/'
        write(DIST / route.strip("/") / "index.html", song_page(cfg, site_url, song))
        urls.append(route)

    # Maintain legacy movie and album routes. Song aliases map only from the
    # provider ID previously chosen by the old builder; ambiguous IDs are omitted.
    redirect_rules: set[str] = set()
    for movie in movies:
        canonical_movie = movie_path(movie)
        canonical_album = album_path(movie)
        if canonical_movie.startswith("/tt"):
            legacy_movie = f'/movie/{movie["slug"]}/'
            if legacy_movie != canonical_movie:
                redirect_rules.add(f"{legacy_movie} {canonical_movie} 301")
            if movie["albums"]:
                for legacy_album in (f'{canonical_movie}album/', f'/album/{movie["slug"]}/'):
                    if legacy_album != canonical_album:
                        redirect_rules.add(f"{legacy_album} {canonical_album} 301")

    legacy_id_targets: dict[str, set[str]] = {}
    for song in songs:
        old_id = song.get("legacy_preferred_id")
        if old_id and re.fullmatch(r"[A-Za-z0-9_-]{1,160}", old_id):
            legacy_id_targets.setdefault(old_id, set()).add(song["id"])
    ambiguous_legacy_ids = [old_id for old_id, targets in legacy_id_targets.items() if len(targets) != 1]
    for old_id, targets in legacy_id_targets.items():
        if len(targets) != 1:
            continue
        target = next(iter(targets))
        if old_id != target:
            redirect_rules.add(f"/song/{old_id}/ /song/{target}/ 301")
    # Cloudflare Pages supports a limited number of static _redirects rules. Fail
    # loudly rather than silently ship an oversized redirect file if the catalogue
    # grows beyond that budget; a Worker-based mapping can replace it later.
    if len(redirect_rules) > 1900:
        raise SystemExit(
            f"Generated {len(redirect_rules)} redirect rules. This is near the Cloudflare Pages "
            "static _redirects limit; migrate legacy song route mapping to a Worker before publishing."
        )
    if redirect_rules:
        write(DIST / "_redirects", "\n".join(sorted(redirect_rules)) + "\n")
    elif (DIST / "_redirects").exists():
        (DIST / "_redirects").unlink()
    if ambiguous_legacy_ids:
        print(f"warning: skipped {len(ambiguous_legacy_ids)} ambiguous legacy song ID redirect(s)", file=sys.stderr)

    write(DIST / "search-index.json", search_index_text)
    write(DIST / "404.html", not_found_page(cfg, site_url))

    robots = "User-agent: *\nAllow: /\n"
    if site_url:
        sitemap = "".join(f"  <url><loc>{e(site_url + url)}</loc></url>\n" for url in urls)
        write(DIST / "sitemap.xml",
              '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
              + sitemap + "</urlset>\n")
        robots += f"Sitemap: {site_url}/sitemap.xml\n"
    write(DIST / "robots.txt", robots)

    # Build summary is also a quick signal that optional missing values did not
    # cause tracks to disappear from public output.
    with_media = sum(bool(song.get("spotify_url") or song.get("ytm_url") or song.get("youtube_url")) for song in songs)
    with_lyrics = sum(bool(song.get("lrc_lyrics") or song.get("plain_lyrics")) for song in songs)
    index_size = (DIST / "search-index.json").stat().st_size
    built_files = sum(1 for path in DIST.rglob("*") if path.is_file())
    print(
        f"built {len(movies)} movies, {len(albums)} albums, {len(songs)} songs; "
        f"{with_media} songs with media links, {with_lyrics} with lyrics; "
        f"search index {index_size:,} bytes; {built_files} output files; "
        f"{len(urls)} canonical URLs; asset version {ASSET_VERSION} into {DIST}"
    )


if __name__ == "__main__":
    main()
