#!/usr/bin/env python3
"""Build the static site into dist/. Standard library only.

    python3 build.py

Site URL (used for canonical links, Open Graph and sitemap.xml) is read from,
in order: the SITE_URL environment variable, "url" in site.json, CF_PAGES_URL.
"""
from __future__ import annotations

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
DATA = ROOT / "data" / "telugu_movies_master.json"
from db_source import load_records as load_database_records
CONFIG = ROOT / "site.json"
STATIC = ROOT / "static"
DIST = ROOT / "dist"

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


def album_path(movie) -> str:
    """Give soundtrack albums a dedicated IMDb-ID child route."""
    base = movie_path(movie)
    if base.startswith("/tt"):
        return base + "album/"
    return f"/album/{movie['slug']}/"


# --------------------------------------------------------------------------
# data
# --------------------------------------------------------------------------

def load_movies():
    """Normalize the final master JSON schema for the static website.

    The source keeps movie visuals/crew/URLs at the top level and song media
    under song.media.{spotify,youtube_music,youtube_video_song}. Missing
    metadata is preserved as absent UI data rather than inferred.
    """
    raw = load_database_records(DATA)
    if not isinstance(raw, list):
        raise SystemExit(f"{DATA} must contain a JSON array of movies")

    movies, used_slugs, used_ids = [], set(), set()

    def as_dict(value):
        return value if isinstance(value, dict) else {}

    def as_list(value):
        return [item for item in value if item is not None and str(item).strip()] if isinstance(value, list) else []

    def text_or_none(value):
        return str(value).strip() if value is not None and str(value).strip() else None

    for source in raw:
        if not isinstance(source, dict):
            print("warning: skipped a non-object movie record", file=sys.stderr)
            continue

        cd = as_dict(source.get("cinematic_data"))
        visuals = as_dict(source.get("visuals"))
        crew = as_dict(source.get("crew"))
        rating = as_dict(source.get("ratings"))
        urls = {str(k): str(v) for k, v in as_dict(source.get("urls")).items() if v and isinstance(v, str)}
        album_source = as_dict(source.get("album_metadata"))
        released = text_or_none(cd.get("release_date") or source.get("release_date"))
        year_value = source.get("release_year") or (released[:4] if released else "Unknown")
        year = str(year_value)
        title = str(source.get("title") or "Untitled film")
        base = f"{slugify(title) or 'untitled-film'}-{year}"
        slug, n = base, 2
        while slug in used_slugs:
            slug, n = f"{base}-{n}", n + 1
        used_slugs.add(slug)

        music_directors = [str(x).strip() for x in as_list(crew.get("music_directors"))]
        directors = [str(x).strip() for x in as_list(crew.get("directors"))]
        cast = [str(x).strip() for x in as_list(crew.get("lead_cast"))]
        genres = [str(x).strip() for x in as_list(cd.get("genres"))]
        album_spotify_id = album_source.get("spotify_album_id")
        album_ytm_id = album_source.get("youtube_album_id")
        if not urls.get("spotify_album") and album_spotify_id:
            urls["spotify_album"] = f"https://open.spotify.com/album/{album_spotify_id}"
        if not urls.get("youtube_music_album") and album_ytm_id:
            urls["youtube_music_album"] = f"https://music.youtube.com/browse/{album_ytm_id}"

        movie = {
            "imdb_id": source.get("movie_id") or "",
            "slug": slug,
            "title": title,
            "telugu": source.get("title_telugu") or "",
            "year": year,
            "released": released,
            "original_language": text_or_none(source.get("original_language")),
            "cinematic_universe": text_or_none(source.get("cinematic_universe")),
            "genres": genres,
            "certification": cd.get("certification") or "",
            "plot": cd.get("plot_summary") or "",
            "runtime_minutes": cd.get("runtime_minutes"),
            "poster": visuals.get("poster_w500"),
            "backdrop": visuals.get("backdrop_w1280"),
            "title_logo": visuals.get("title_logo_png"),
            "music_directors": music_directors,
            "directors": directors,
            "cast": cast,
            "cinematographers": [str(x).strip() for x in as_list(crew.get("cinematographers"))],
            "production_banners": [str(x).strip() for x in as_list(crew.get("production_banners"))],
            "trailer": source.get("trailer_youtube_id"),
            "imdb_score": rating.get("imdb_score"),
            "imdb_votes": rating.get("imdb_votes"),
            "urls": urls,
            "ott_availability": [as_dict(x) for x in as_list(source.get("ott_availability")) if isinstance(x, dict)],
            "album": {
                "spotify_id": album_spotify_id,
                "ytm_id": album_ytm_id,
                "released": album_source.get("release_date"),
                "label": album_source.get("label"),
                "upc": album_source.get("upc_barcode"),
                "spotify_popularity": album_source.get("spotify_popularity"),
                "copyright_c": album_source.get("copyright_c"),
                "copyright_p": album_source.get("copyright_p"),
                "artwork": album_source.get("artwork_hd_640"),
                "artwork_small": album_source.get("artwork_300"),
            },
            "songs": [],
        }

        songs = source.get("songs")
        if not isinstance(songs, list):
            songs = []
        for position, item in enumerate(songs, start=1):
            if not isinstance(item, dict):
                print(f"warning: skipped a malformed track in '{title}'", file=sys.stderr)
                continue
            media = as_dict(item.get("media"))
            sp = as_dict(media.get("spotify"))
            ytm = as_dict(media.get("youtube_music"))
            youtube = as_dict(media.get("youtube_video_song"))
            sid = sp.get("track_id") or ytm.get("video_id") or youtube.get("video_id")
            song_title = str(item.get("title") or "Untitled track")
            if not sid:
                print(f"warning: skipped '{song_title}' ({title}): no usable media ID", file=sys.stderr)
                continue
            sid = str(sid)
            if sid in used_ids:
                alternatives = [ytm.get("video_id"), youtube.get("video_id"), sp.get("track_id")]
                sid = next((str(x) for x in alternatives if x and str(x) not in used_ids), "")
                if not sid:
                    raise SystemExit(f"duplicate media IDs for '{song_title}' ({title})")
            used_ids.add(sid)
            raw_number = item.get("track_number")
            try:
                number = int(raw_number) if raw_number is not None else position
            except (TypeError, ValueError):
                number = position
            duration = str(item.get("duration_formatted") or item.get("duration") or "0:00")
            try:
                duration_ms = int(item.get("duration_ms")) if item.get("duration_ms") is not None else None
            except (TypeError, ValueError):
                duration_ms = None
            song_genres = [str(x).strip() for x in as_list(item.get("genres"))]
            spotify_url = sp.get("url") or (f"https://open.spotify.com/track/{sp['track_id']}" if sp.get("track_id") else None)
            ytm_url = ytm.get("url") or (f"https://music.youtube.com/watch?v={ytm['video_id']}" if ytm.get("video_id") else None)
            youtube_url = youtube.get("url") or (f"https://www.youtube.com/watch?v={youtube['video_id']}" if youtube.get("video_id") else None)
            song = {
                "id": sid,
                "title": clean_title(song_title),
                "raw_title": song_title,
                "number": number,
                "artists": [clean_artist(str(a)) for a in as_list(item.get("singers"))],
                "genres": song_genres,
                "duration": duration,
                "duration_ms": duration_ms,
                "explicit": bool(item.get("is_explicit")),
                "isrc_code": text_or_none(item.get("isrc_code")),
                "data_source": text_or_none(item.get("data_source")),
                "bonus_track": item.get("is_bonus_track") if "is_bonus_track" in item else None,
                "spotify_audio_features": item.get("spotify_audio_features") if isinstance(item.get("spotify_audio_features"), dict) else None,
                "spotify_id": sp.get("track_id"),
                "spotify_url": spotify_url,
                "spotify_preview_url": sp.get("preview_url_30s"),
                "spotify_popularity": sp.get("popularity"),
                "ytm_id": ytm.get("video_id"),
                "ytm_url": ytm_url,
                "ytm_views": ytm.get("views"),
                "plays": ytm.get("views"),
                "plays_num": parse_plays(ytm.get("views")),
                "youtube_video_id": youtube.get("video_id"),
                "youtube_url": youtube_url,
                "youtube_video_title": youtube.get("video_title"),
                "youtube_video_views": youtube.get("views"),
                "movie": movie,
            }
            movie["songs"].append(song)
        movie["songs"].sort(key=lambda x: x["number"])
        movies.append(movie)
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
        '<link rel="stylesheet" href="/static/style.css?v=20261016-jsonmeta3">',
        '<script src="/static/app.js?v=20261016-jsonmeta3" defer></script>',
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
    <a class="brand" href="/" aria-label="vachikatelugu home"><span class="brand-mark"><img class="brand-logo logo-for-light" src="/static/vachika-logo-light.png" alt="" width="24" height="45"><img class="brand-logo logo-for-dark" src="/static/vachika-logo-dark.png" alt="" width="24" height="45"></span><span class="brand-name">{e(cfg["name"])}</span></a>
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
    number = rank if rank is not None else song["number"]
    sub = f'{e(song["movie"]["title"])}, {e(song["movie"]["year"])}' if show_movie else ""
    if not show_movie and song["artists"]:
        sub = e(", ".join(song["artists"][:3]))
    plays = f'<span class="plays">{e(song["plays"])}</span>' if show_plays and song["plays"] else ""
    cur = ' aria-current="true"' if current else ""
    movie = song["movie"]
    artwork = movie["album"]["artwork"] or movie["album"]["artwork_small"] or movie["poster"]
    cover = (f'<img class="track-artwork" src="{e(artwork)}" alt="" width="48" height="48" loading="lazy" decoding="async" referrerpolicy="no-referrer">'
             if artwork else '<span class="track-artwork track-artwork-empty" aria-hidden="true">♪</span>')
    filter_attrs = ""
    if filterable:
        filter_attrs = (f' class="track song-catalog-item" data-title="{e(song["title"].lower())}" '
            f'data-artists="{e("|".join(song["artists"]).lower())}" data-music="{e("|".join(movie["music_directors"]).lower())}" '
            f'data-genre="{e("|".join(movie["genres"]).lower())}" data-release="{e(movie["released"] or (movie["year"] + "-01-01"))}" '
            f'data-year="{e(movie["year"])}" data-plays="{song["plays_num"]}" data-songid="{e(song["id"])}"')
    else:
        filter_attrs = ' class="track"'
    return (
        f'<li{filter_attrs}><a href="/song/{e(song["id"])}/"{cur}>'
        f'<span class="n">{number}</span>{cover}'
        f'<span class="main"><span class="name">{e(song["title"])}</span>'
        f'<span class="sub">{sub}</span></span>'
        f'<span class="meta"><span class="dur">{e(song["duration"])}</span>{plays}</span>'
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
              ("spotify_album", "Spotify soundtrack"), ("youtube_music_album", "YouTube Music soundtrack")]
    links = []
    for key, label in labels:
        url = urls.get(key)
        if url:
            links.append(f'<a href="{e(url)}" target="_blank" rel="noopener noreferrer">{e(label)} <span aria-hidden="true">↗</span></a>')
    if not links:
        return ""
    return '<details class="movie-links-dropdown"><summary class="btn">More links <span aria-hidden="true">⌄</span></summary><div class="movie-links-menu">' + "".join(links) + '</div></details>'


def audio_features_text(features):
    if not isinstance(features, dict) or not features:
        return ""
    return ", ".join(f'{str(k).replace("_", " ").title()}: {v}' for k, v in features.items() if v is not None)


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


def album_card(movie, *, eager=False, filterable=False) -> str:
    album = movie["album"]
    artwork = album["artwork"] or album["artwork_small"] or movie["poster"]
    count = len(movie["songs"])
    total = album_total_plays(movie)
    loading = "eager" if eager else "lazy"
    cover = (f'<img class="album-cover" src="{e(artwork)}" alt="Album artwork for {e(movie["title"])} soundtrack" '
             f'width="640" height="640" loading="{loading}" decoding="async" referrerpolicy="no-referrer">'
             if artwork else '<span class="album-cover album-cover-empty" aria-hidden="true">♪</span>')
    released = album["released"] or movie["released"] or (movie["year"] + "-01-01")
    artists = "|".join(movie["music_directors"])
    genres = "|".join(movie["genres"])
    wrapper_class = ' class="album-item"' if filterable else ' class="album-item"'
    attrs = (f'{wrapper_class} data-title="{e(movie["title"].lower())}" data-year="{e(movie["year"])}" '
             f'data-release="{e(released)}" data-artist="{e(artists.lower())}" data-plays="{total}" '
             f'data-songs="{count}" data-genre="{e(genres.lower())}"')
    return (
        f'<li{attrs}><a class="album-card" href="{e(album_path(movie))}">'
        f'{cover}<span class="album-card-title">{e(movie["title"])}</span>'
        f'<span class="sub">{e(movie["year"])} · {count} {"song" if count == 1 else "songs"}</span>'
        f'<span class="album-plays">{e(format_count(total))} combined plays</span>'
        f'</a></li>'
    )


def movie_card(movie, *, eager=False):
    artwork = movie["poster"] or movie["album"]["artwork"] or movie["album"]["artwork_small"]
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
    with_songs = [m for m in movies if m["songs"]]
    top_songs = sorted(all_songs, key=lambda s: s["plays_num"], reverse=True)[:5]
    popular_albums = sorted(with_songs, key=album_total_plays, reverse=True)[:6]
    top_rows = "".join(song_row(song, rank=i + 1, show_plays=True) for i, song in enumerate(top_songs))
    album_items = "".join(album_card(movie, eager=i < 3) for i, movie in enumerate(popular_albums))

    body = f"""
<section class="home-intro wrap">
  <p class="eyebrow">TELUGU SOUNDTRACK ARCHIVE</p>
  <h1>Every song has a story.</h1>
  <p class="lede">Discover songs, albums and the films behind them.</p>
  <div class="home-stats"><span>{len(all_songs)} songs</span><span>{len(with_songs)} soundtracks</span></div>
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
                  desc=f'{cfg["tagline"]}. Explore {len(all_songs)} songs, {len(with_songs)} soundtracks and song charts.',
                  path="/", body=body)


def albums_page(cfg, site_url, movies):
    albums = sorted((m for m in movies if m["songs"]), key=album_total_plays, reverse=True)
    items = "".join(album_card(movie, eager=i < 4, filterable=True) for i, movie in enumerate(albums))
    total_plays = sum(album_total_plays(movie) for movie in albums)
    artists = sorted({artist for movie in albums for artist in movie["music_directors"] if artist}, key=str.casefold)
    artist_options = "".join(f'<option value="{e(a.lower())}">{e(a)}</option>' for a in artists)
    body = f"""
<section class="page-intro wrap">
  <p class="eyebrow">SOUNDTRACK LIBRARY</p>
  <h1>Albums</h1>
  <p class="lede">Explore {len(albums)} Telugu film soundtracks with original soundtrack artwork and complete tracklists.</p>
  <p class="intro-meta">{len(albums)} albums <span aria-hidden="true">·</span> {e(format_count(total_plays))} combined track plays in the current data</p>
</section>
<section class="wrap page-section">
  <div class="filter-bar" id="album-filters" aria-label="Filter albums">
    <label class="filter-search">Find an album<input id="album-query" type="search" placeholder="Album or film title" autocomplete="off"></label>
    <label>Sort by<select id="album-sort"><option value="plays">Most played</option><option value="release-new">Newest release</option><option value="release-old">Oldest release</option><option value="title-az">Title A–Z</option><option value="title-za">Title Z–A</option><option value="songs">Most songs</option></select></label>
    <label>Music director<select id="album-artist"><option value="">All artists</option>{artist_options}</select></label>
    <label>Genre<select id="album-genre"><option value="">All genres</option>{"".join(f'<option value="{e(g.lower())}">{e(g)}</option>' for g in sorted({genre for movie in albums for genre in movie["genres"] if genre}, key=str.casefold))}</select></label>
    <label>Released from<input type="date" id="album-from" aria-label="Album release from date"></label>
    <label>Released to<input type="date" id="album-to" aria-label="Album release to date"></label>
    <p class="filter-count" id="album-count" aria-live="polite">{len(albums)} albums</p>
  </div>
  <ul class="albums-grid albums-grid-large" id="album-grid">{items}</ul>
  <p class="empty" id="album-empty" hidden>No albums match those filters. Try a different title, artist or sort option.</p>
  <p class="data-note">Play counts are captured in the source JSON and are not live analytics. Album totals add the listed plays for each song; missing counts contribute zero. Release sorting uses the soundtrack date where available and falls back to the film release date.</p>
</section>
"""
    return layout(cfg, site_url, title="Telugu soundtrack albums", desc="Browse Telugu movie soundtrack albums by combined song plays, release date, title and music director.", path="/albums/", body=body)


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
  <ul class="movies-grid" id="movie-grid">{items}</ul>
  <p class="empty" id="movie-empty" hidden>No movies match those filters. Try changing the title, genre or director.</p>
</section>
"""
    return layout(cfg, site_url, title="Telugu movies", desc="Browse Telugu films by release date, genre, director and music director, and explore each movie soundtrack.", path="/movies/", body=body)


def songs_page(cfg, site_url, movies):
    songs = [song for movie in movies for song in movie["songs"]]
    songs.sort(key=lambda song: song["plays_num"], reverse=True)
    artists = sorted({artist for song in songs for artist in song["artists"] if artist}, key=str.casefold)
    genres = sorted({genre for movie in movies for genre in movie["genres"] if genre}, key=str.casefold)
    music_directors = sorted({artist for movie in movies for artist in movie["music_directors"] if artist}, key=str.casefold)
    artist_options = "".join(f'<option value="{e(a.lower())}">{e(a)}</option>' for a in artists)
    genre_options = "".join(f'<option value="{e(g.lower())}">{e(g)}</option>' for g in genres)
    music_options = "".join(f'<option value="{e(a.lower())}">{e(a)}</option>' for a in music_directors)
    rows = "".join(song_row(song, rank=i + 1, show_movie=True, show_plays=True, filterable=True) for i, song in enumerate(songs))
    body = f"""
<section class="page-intro wrap">
  <p class="eyebrow">THE FULL TRACK LIBRARY</p>
  <h1>Songs</h1>
  <p class="lede">Search every song in the database, browse by artist or music director, and narrow the list by release date.</p>
  <p class="intro-meta">{len(songs)} songs across {len(movies)} movies</p>
</section>
<section class="wrap page-section">
  <div class="filter-bar song-filter-bar" id="song-filters" aria-label="Filter songs">
    <label class="filter-search">Search songs<input id="song-query" type="search" placeholder="Song, film or singer" autocomplete="off"></label>
    <label>Sort by<select id="song-sort"><option value="plays">Most played</option><option value="release-new">Newest movie</option><option value="release-old">Oldest movie</option><option value="title-az">Title A–Z</option><option value="title-za">Title Z–A</option></select></label>
    <label>Singer / artist<select id="song-artist"><option value="">All singers</option>{artist_options}</select></label>
    <label>Music director<select id="song-music"><option value="">All music directors</option>{music_options}</select></label>
    <label>Genre<select id="song-genre"><option value="">All genres</option>{genre_options}</select></label>
    <label>Movie released from<input id="song-from" type="date" aria-label="Movie release from date"></label>
    <label>Movie released to<input id="song-to" type="date" aria-label="Movie release to date"></label>
    <p class="filter-count" id="song-count" aria-live="polite">{len(songs)} songs</p>
  </div>
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
    <label>Search type<select id="advanced-type"><option value="all">Everything</option><option value="song">Songs</option><option value="album">Albums</option><option value="movie">Movies</option></select></label>
    <label>Release from<input id="advanced-from" type="date"></label>
    <label>Release to<input id="advanced-to" type="date"></label>
    <label>Sort results<select id="advanced-sort"><option value="relevance">Best match</option><option value="popular">Most played</option><option value="newest">Newest first</option><option value="oldest">Oldest first</option><option value="title-az">Title A–Z</option><option value="title-za">Title Z–A</option></select></label>
    <button type="submit" class="btn primary advanced-submit">Search database</button>
  </form>
  <div class="advanced-results-head"><h2>Results</h2><p id="advanced-count" class="filter-count" aria-live="polite">Enter a term to search the database.</p></div>
  <div id="advanced-results" class="advanced-results-grid" aria-live="polite"></div>
  <p id="advanced-empty" class="empty" hidden>No matching records. Try a broader term, another type, or adjust the release-date range.</p>
</section>
"""
    return layout(cfg, site_url, title="Advanced database search", desc="Search all Vachika Telugu songs, albums and movies with type, release-date and sorting filters.", path="/advanced-search/", body=body)


def chart_entity_row(movie, rank, kind):
    album = movie["album"]
    artwork = (album["artwork"] or album["artwork_small"] or movie["poster"]) if kind == "album" else (movie["poster"] or album["artwork"] or album["artwork_small"])
    path = album_path(movie) if kind == "album" else movie_path(movie)
    count = len(movie["songs"])
    total = album_total_plays(movie)
    cover = (f'<img class="track-artwork" src="{e(artwork)}" alt="" width="48" height="48" loading="lazy" decoding="async" referrerpolicy="no-referrer">' if artwork else '<span class="track-artwork track-artwork-empty">♪</span>')
    subtitle = f'{movie["year"]} · {count} {"song" if count == 1 else "songs"}'
    return f'<li class="track entity-chart-row"><a href="{e(path)}"><span class="n">{rank}</span>{cover}<span class="main"><span class="name">{e(movie["title"])}</span><span class="sub">{e(subtitle)}</span></span><span class="meta"><span class="plays">{e(format_count(total))} plays</span></span></a></li>'


def charts_page(cfg, site_url, movies):
    songs = sorted((s for movie in movies for s in movie["songs"]), key=lambda s: s["plays_num"], reverse=True)
    albums = sorted((m for m in movies if m["songs"]), key=album_total_plays, reverse=True)
    movies_ranked = sorted(movies, key=album_total_plays, reverse=True)
    song_rows = "".join(song_row(song, rank=i + 1, show_plays=True) for i, song in enumerate(songs[:30]))
    album_rows = "".join(chart_entity_row(movie, i+1, "album") for i, movie in enumerate(albums[:30]))
    movie_rows = "".join(chart_entity_row(movie, i+1, "movie") for i, movie in enumerate(movies_ranked[:30]))
    body = f"""
<section class="page-intro wrap">
  <p class="eyebrow">DATABASE RANKINGS</p>
  <h1>Charts</h1>
  <p class="lede">Explore the most-played songs, most popular soundtracks and movies with the strongest combined song plays in the current dataset.</p>
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
  <p class="data-note">Songs are ranked by captured YouTube Music plays. Album and movie charts rank the sum of their listed soundtrack song plays; missing counts contribute zero. Counts are source-data snapshots, not live streaming analytics.</p>
</section>
"""
    return layout(cfg, site_url, title="Telugu music charts", desc="Charts for Telugu songs, soundtrack albums and movies ranked using play counts in the current database.", path="/charts/", body=body)


def song_page(cfg, site_url, song):
    m = song["movie"]
    art = m["album"]["artwork"] or m["album"]["artwork_small"] or m["poster"]
    credits = song["artists"]
    song_no = f'{song["number"]} of {len(m["songs"])} on the {m["title"]} soundtrack'
    desc_bits = [f'{song["title"]} from {m["title"]} ({m["year"]}).']
    if m["music_directors"]:
        desc_bits.append("Music by " + ", ".join(m["music_directors"][:3]) + ".")
    if credits:
        desc_bits.append("Artists: " + ", ".join(credits[:4]) + ".")
    desc_bits.append(f'Duration {song["duration"]}. Play on Spotify, YouTube Music and YouTube.')

    others = "".join(song_row(other, current=(other["id"] == song["id"]), show_movie=False, show_plays=True) for other in m["songs"])
    about_rows = [
        ("Director", people(m["directors"])),
        ("Starring", people(m["cast"][:6])),
        ("Movie genres", e(", ".join(m["genres"]))),
        ("Release year", e(m["year"])),
        ("Language", e(m["original_language"])),
        ("IMDb rating", e(m["imdb_score"])),
    ]
    about = facts(about_rows)
    explicit = '<span class="flag">Explicit</span>' if song["explicit"] else ""

    metadata = [
        ("ISRC", e(song["isrc_code"] or "Not provided in source data")),
        ("Duration", e(song["duration"])),
        ("Duration (milliseconds)", e(f'{song["duration_ms"]:,}' if song["duration_ms"] is not None else "")),
        ("Track number", e(song["number"])),
        ("Source title", e(song["raw_title"] if song["raw_title"] != song["title"] else "")),
        ("Song genres", e(", ".join(song["genres"]) or "Not specified in source data")),
        ("Explicit content", "Yes" if song["explicit"] else "No"),
        ("Bonus track", "Yes" if song["bonus_track"] is True else ("No" if song["bonus_track"] is False else "Not specified in source data")),
        ("Source", e(song["data_source"] or "Not provided in source data")),
        ("Spotify track ID", e(song["spotify_id"] or "")),
        ("Spotify popularity", e(song["spotify_popularity"] if song["spotify_popularity"] is not None else "")),
        ("Spotify preview", f'<a href="{e(song["spotify_preview_url"])}" target="_blank" rel="noopener noreferrer">Open preview ↗</a>' if song["spotify_preview_url"] else ""),
        ("YouTube Music video ID", e(song["ytm_id"] or "")),
        ("YouTube Music plays", e(song["ytm_views"] or "")),
        ("YouTube video ID", e(song["youtube_video_id"] or "")),
        ("YouTube video title", e(song["youtube_video_title"] or "")),
        ("YouTube video views", e(song["youtube_video_views"] or "")),
        ("Spotify audio features", e(audio_features_text(song["spotify_audio_features"]))),
        ("Album release date", e(fmt_date(m["album"]["released"]))),
        ("Album label", e(m["album"]["label"] or "")),
        ("Album UPC / barcode", e(m["album"]["upc"] or "")),
        ("Album copyright (C)", e(m["album"]["copyright_c"] or "")),
        ("Album copyright (P)", e(m["album"]["copyright_p"] or "")),
    ]
    video_block = youtube_video_block(song)
    theme_art = art or m["backdrop"] or m["poster"]
    body = f"""
<article class="wrap song detail-art-theme" style="--artwork-url: url('{e(theme_art or "")}')">
  <div class="song-head" style="--artwork-url: url('{e(art or "")}')">
    {img(art, "Artwork for the " + m["title"] + " soundtrack", "art", 640, 640, eager=True)}
    <div class="song-main">
      <p class="eyebrow">SONG · {e(m["imdb_id"])}</p>
      <h1>{e(song["title"])}</h1>
      <p class="from">From <a href="{e(movie_path(m))}">{e(m["title"])}</a>, {e(m["year"])} {explicit}</p>
      <div class="actions">{listen_links(song)}<button type="button" class="btn" data-copy-link>Copy song link</button></div>
      {player(song)}
      <p><a class="text-link" href="{e(album_path(m))}">Open full soundtrack album ↗</a></p>
    </div>
  </div>

  <section class="song-metadata-section">
    <div class="section-heading"><div><p class="eyebrow">TRACK INFORMATION</p><h2>Song metadata</h2></div></div>
    {facts([( "Artists", people(credits)), ("Music director", people(m["music_directors"])), ("Track", e(song_no))])}
    <details class="metadata-details" open><summary>All available track and release metadata</summary>{facts(metadata)}</details>
  </section>

  {video_block}

  <section class="song-film-context">
    <h2>About the film</h2>
    <p class="plot">{e(m["plot"])}</p>
    {about}
    <p><a href="{e(movie_path(m))}">All songs and details for {e(m["title"])}</a></p>
  </section>

  <section>
    <div class="section-heading"><div><p class="eyebrow">SOUNDTRACK</p><h2>More from {e(m["title"])}</h2></div><a class="text-link" href="{e(album_path(m))}">Album page ↗</a></div>
    <ol class="tracks">{others}</ol>
  </section>
</article>
"""
    ld = {
        "@context": "https://schema.org",
        "@type": "MusicRecording",
        "name": song["title"],
        "duration": iso_duration(song["duration"]),
        "isrcCode": song["isrc_code"],
        "inAlbum": {"@type": "MusicAlbum", "name": m["title"] + " (Original Motion Picture Soundtrack)"},
        "byArtist": [{"@type": "Person", "name": name} for name in credits],
        "url": site_url + f"/song/{song['id']}/" if site_url else None,
    }
    ld = {key: value for key, value in ld.items() if value}
    return layout(cfg, site_url, title=f'{song["title"]} ({m["title"]}, {m["year"]})', desc=" ".join(desc_bits),
                  path=f"/song/{song['id']}/", body=body, og_type="music.song", og_image=art, jsonld=ld)


def album_page(cfg, site_url, m):
    album = m["album"]
    art = album["artwork"] or album["artwork_small"] or m["poster"]
    total = album_total_plays(m)
    rows = "".join(song_row(song, rank=i + 1, show_plays=True) for i, song in enumerate(m["songs"]))
    artists = ", ".join(m["music_directors"])
    soundtrack_links = []
    if album["spotify_id"]:
        soundtrack_links.append(f'<a class="btn provider-btn spotify-btn" href="https://open.spotify.com/album/{e(album["spotify_id"])}" rel="noopener noreferrer" target="_blank">{provider_icon("spotify")}<span>Open on Spotify</span></a>')
    if album["ytm_id"]:
        soundtrack_links.append(f'<a class="btn provider-btn youtube-btn" href="https://music.youtube.com/browse/{e(album["ytm_id"])}" rel="noopener noreferrer" target="_blank">{provider_icon("youtube")}<span>Open on YouTube Music</span></a>')
    cover = img(art, "Album artwork for " + m["title"], "album-detail-art", 640, 640, eager=True) if art else '<div class="album-detail-art album-cover-empty">♪</div>'
    release = album["released"] or m["released"]
    body = f"""
<article class="album-detail-page detail-art-theme" style="--artwork-url: url('{e(art or "")}')">
  <section class="album-detail-hero" style="--artwork-url: url('{e(art or "")}')">
    <div class="wrap album-detail-head">
      {cover}
      <div class="album-detail-copy">
        <p class="eyebrow">TELUGU SOUNDTRACK ALBUM{f' · {e(m["imdb_id"])}' if m["imdb_id"] else ''}</p>
        <h1>{e(m["title"])}</h1>
        {f'<p class="album-telugu" lang="te">{e(m["telugu"])}</p>' if m["telugu"] else ''}
        <p class="album-byline">{e(artists or "Telugu film soundtrack")} · {e(m["year"])}</p>
        <p class="album-stats">{len(m["songs"])} songs <span>·</span> {e(format_count(total))} combined plays{f' <span>·</span> Released {e(fmt_date(release))}' if release else ''}</p>
        <div class="actions">{"".join(soundtrack_links)}<a class="btn" href="{e(movie_path(m))}">Movie details</a></div>
      </div>
    </div>
  </section>
  <section class="wrap page-section album-track-section">
    <div class="section-heading"><div><p class="eyebrow">FULL TRACKLIST</p><h2>Songs in this album</h2></div><span class="sort-label">{len(m["songs"])} tracks</span></div>
    <ol class="tracks chart-tracks">{rows}</ol>
    <p class="data-note">Play counts are captured from the source dataset and are not live analytics.</p>
  </section>
</article>
"""
    desc = f'{m["title"]} soundtrack album ({m["year"]}) with {len(m["songs"])} songs, music credits and listening links.'
    return layout(cfg, site_url, title=f'{m["imdb_id"]} · {m["title"]} soundtrack album' if m["imdb_id"] else f'{m["title"]} soundtrack album', desc=desc,
                  path=album_path(m), body=body, og_type="music.album", og_image=art)


def movie_page(cfg, site_url, m):
    rows = "".join(song_row(song, show_movie=False, show_plays=True) for song in m["songs"])
    songs_block = (f'<section><h2>Songs</h2><ol class="tracks">{rows}</ol></section>' if m["songs"]
                   else '<section><h2>Songs</h2><p class="empty">No songs are listed for this movie in the current database.</p></section>')

    album = m["album"]
    soundtrack_links = []
    spotify_album_url = (m.get("urls") or {}).get("spotify_album")
    ytm_album_url = (m.get("urls") or {}).get("youtube_music_album")
    if spotify_album_url:
        soundtrack_links.append(f'<a class="btn provider-btn spotify-btn" href="{e(spotify_album_url)}" rel="noopener noreferrer" target="_blank">{provider_icon("spotify")}<span>Soundtrack on Spotify</span></a>')
    if ytm_album_url:
        soundtrack_links.append(f'<a class="btn provider-btn youtube-btn" href="{e(ytm_album_url)}" rel="noopener noreferrer" target="_blank">{provider_icon("youtube")}<span>Soundtrack on YouTube Music</span></a>')

    trailer = ""
    if m["trailer"]:
        thumb = f'https://i.ytimg.com/vi/{e(m["trailer"])}/hqdefault.jpg'
        trailer = ('<section><h2>Trailer</h2>'
            f'<div class="trailer"><button type="button" data-embed="youtube" data-id="{e(m["trailer"])}" aria-label="Play the trailer for {e(m["title"])}">'
            f'<img src="{thumb}" alt="" width="480" height="360" loading="lazy" decoding="async" referrerpolicy="no-referrer">'
            '<span class="play">Play trailer</span></button></div></section>')

    details_rows = [
        ("IMDb ID", e(m["imdb_id"])),
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
        ("Soundtrack released", e(fmt_date(album["released"]))),
        ("Soundtrack label", e(album["label"] or "")),
        ("Album UPC / barcode", e(album["upc"] or "")),
        ("Copyright (C)", e(album["copyright_c"] or "")),
        ("Copyright (P)", e(album["copyright_p"] or "")),
    ]
    details = facts(details_rows)
    telugu = f'<p class="te" lang="te">{e(m["telugu"])}</p>' if m["telugu"] else ""
    theme_art = m["backdrop"] or m["poster"] or album["artwork"] or album["artwork_small"]
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
      <p class="plot">{e(m["plot"])}</p>
      <div class="actions">{"".join(soundtrack_links)}{f'<a class="btn" href="{e(album_path(m))}">View album page</a>' if m["songs"] else ''}{links_dropdown}</div>
    </div>
  </div>
  <section class="ott-section"><div class="section-heading"><div><p class="eyebrow">WHERE TO WATCH</p><h2>Streaming availability</h2></div></div>
    <p class="section-note">Availability is based on the supplied dataset. Buttons open each provider's search so you can find the movie on that service.</p>
    <div class="ott-provider-grid">{ott}</div>
  </section>
  {songs_block}
  <section><h2>Movie details</h2>{details}</section>
  {trailer}
</article>
"""
    names = ", ".join(m["music_directors"][:2])
    desc = f'{m["title"]} ({m["year"]}): {len(m["songs"])} songs' + (f", music by {names}" if names else "") + ". Tracklist, film credits, streaming availability and soundtrack links."
    ld = {
        "@context": "https://schema.org", "@type": "Movie", "name": m["title"],
        "datePublished": str(m["year"]) if m["year"] != "Unknown" else None,
        "image": m["poster"], "genre": m["genres"],
        "director": [{"@type": "Person", "name": name} for name in m["directors"]],
        "musicBy": [{"@type": "Person", "name": name} for name in m["music_directors"]],
        "actor": [{"@type": "Person", "name": name} for name in m["cast"][:8]],
        "url": (m.get("urls") or {}).get("imdb"),
        "aggregateRating": ({"@type": "AggregateRating", "ratingValue": m["imdb_score"], "ratingCount": m["imdb_votes"]} if m["imdb_score"] and m["imdb_votes"] else None),
    }
    ld = {key: value for key, value in ld.items() if value}
    return layout(cfg, site_url, title=f'{m["imdb_id"]} · {m["title"]} ({m["year"]})' if m["imdb_id"] else f'{m["title"]} ({m["year"]})', desc=desc, path=movie_path(m),
                  body=body, og_type="video.movie", og_image=m["backdrop"] or m["poster"], jsonld=ld)


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


def main():
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    site_url = (os.environ.get("SITE_URL") or cfg.get("url") or os.environ.get("CF_PAGES_URL") or "").rstrip("/")
    if not site_url:
        print("warning: no site URL (set SITE_URL or site.json url); canonical links and sitemap are skipped", file=sys.stderr)

    movies = load_movies()
    songs = [s for m in movies for s in m["songs"]]

    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()
    shutil.copytree(STATIC, DIST / "static")
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
    for m in movies:
        mv_path = movie_path(m)
        mv_rel = mv_path.strip("/")
        write(DIST / mv_rel / "index.html", movie_page(cfg, site_url, m))
        urls.append(mv_path)
        if m["songs"]:
            ab_path = album_path(m)
            ab_rel = ab_path.strip("/")
            write(DIST / ab_rel / "index.html", album_page(cfg, site_url, m))
            urls.append(ab_path)
    for s in songs:
        write(DIST / "song" / s["id"] / "index.html", song_page(cfg, site_url, s))
        urls.append(f"/song/{s['id']}/")
    # Keep previous slug routes working on Cloudflare Pages, while all generated
    # internal links and canonical URLs use IMDb ID routes.
    redirect_rules = []
    for m in movies:
        canonical_movie = movie_path(m)
        canonical_album = album_path(m)
        if canonical_movie.startswith("/tt"):
            legacy_movie = f"/movie/{m['slug']}/"
            legacy_album = f"/album/{m['slug']}/"
            if legacy_movie != canonical_movie:
                redirect_rules.append(f"{legacy_movie} {canonical_movie} 301")
            if m["songs"] and legacy_album != canonical_album:
                redirect_rules.append(f"{legacy_album} {canonical_album} 301")
    if redirect_rules:
        write(DIST / "_redirects", "\n".join(redirect_rules) + "\n")
    write(DIST / "404.html", not_found_page(cfg, site_url))

    # A single small JSON index powers site-wide search, filters and the song details drawer.
    index = {
        "songs": [{
            "id": s["id"], "title": s["title"], "movieTitle": s["movie"]["title"],
            "movieSlug": s["movie"]["slug"], "moviePath": movie_path(s["movie"]),
            "albumPath": album_path(s["movie"]), "year": s["movie"]["year"],
            "released": s["movie"]["released"], "artists": s["artists"],
            "musicDirectors": s["movie"]["music_directors"], "plays": s["plays"],
            "playsNum": s["plays_num"], "duration": s["duration"], "number": s["number"],
            "songCount": len(s["movie"]["songs"]), "artwork": s["movie"]["album"]["artwork"] or s["movie"]["album"]["artwork_small"] or s["movie"]["poster"],
            "poster": s["movie"]["poster"], "genres": s["movie"]["genres"],
            "imdbId": s["movie"]["imdb_id"], "release": s["movie"]["released"] or (s["movie"]["year"] + "-01-01"),
            "spotifyId": s["spotify_id"], "ytmId": s["ytm_id"],
            "spotifyUrl": s["spotify_url"], "ytmUrl": s["ytm_url"], "youtubeVideoUrl": s["youtube_url"], "youtubeVideoId": s["youtube_video_id"], "youtubeVideoTitle": s["youtube_video_title"], "youtubeVideoViews": s["youtube_video_views"], "isrc": s["isrc_code"], "durationMs": s["duration_ms"],
        } for s in songs],
        "movies": [{
            "slug": m["slug"], "path": movie_path(m), "albumPath": album_path(m),
            "imdbId": m["imdb_id"], "title": m["title"], "telugu": m["telugu"],
            "year": m["year"], "released": m["released"], "genres": m["genres"],
            "musicDirectors": m["music_directors"], "directors": m["directors"],
            "cast": m["cast"], "plot": m["plot"], "certification": m["certification"], "originalLanguage": m["original_language"], "runtimeMinutes": m["runtime_minutes"], "ottProviders": [x.get("provider") for x in m["ott_availability"]],
            "songs": len(m["songs"]), "poster": m["poster"],
            "artwork": m["album"]["artwork"] or m["album"]["artwork_small"] or m["poster"],
            "playsNum": album_total_plays(m), "albumReleased": m["album"]["released"],
        } for m in movies],
        "albums": [{
            "slug": m["slug"], "path": album_path(m), "moviePath": movie_path(m),
            "imdbId": m["imdb_id"], "title": m["title"], "year": m["year"],
            "release": m["album"]["released"] or m["released"],
            "artist": "|".join(m["music_directors"]), "musicDirectors": m["music_directors"],
            "genres": m["genres"], "artwork": m["album"]["artwork"] or m["album"]["artwork_small"] or m["poster"],
            "plays": album_total_plays(m), "songs": len(m["songs"]), "release": m["album"]["released"] or m["released"],
            "year": m["year"],
        } for m in movies if m["songs"]],
    }
    write(DIST / "search-index.json", json.dumps(index, ensure_ascii=False, separators=(",", ":")))

    robots = "User-agent: *\nAllow: /\n"
    if site_url:
        sitemap = "".join(f"  <url><loc>{e(site_url + u)}</loc></url>\n" for u in urls)
        write(DIST / "sitemap.xml",
              '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
              + sitemap + "</urlset>\n")
        robots += f"Sitemap: {site_url}/sitemap.xml\n"
    write(DIST / "robots.txt", robots)

    print(f"built {len(movies)} films, {len(songs)} songs, {len(urls) + 1} pages into {DIST}")


if __name__ == "__main__":
    main()
