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
from urllib.parse import quote as url_quote

ROOT = Path(__file__).resolve().parent
from db_source import load_database_catalogue
CONFIG = ROOT / "site.json"
ALIASES = ROOT / "name_aliases.json"
STATIC = ROOT / "static"
DIST = ROOT / "dist"

ASSET_VERSION = "dev"
SEARCH_INDEX_VERSION = "dev"
# Filled in by main() once the catalogue is loaded; used by the search controls
# that every page carries in its header.
SEARCH_FACETS = {"languages": [], "genres": []}

FONT_URL = (
    "https://fonts.googleapis.com/css2?"
    "family=Anek+Telugu:wdth,wght@75..125,300..800"
    "&family=Fraunces:opsz,wght@9..144,500..700"
    "&family=Manrope:wght@400..800&display=swap"
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


def quote(text: str) -> str:
    return url_quote(text, safe="")


def alnum_key(text: str) -> str:
    """Accent-, case- and punctuation-insensitive comparison key."""
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "", text)


def _load_aliases() -> dict:
    """Map a spelling key to the display spelling listed in name_aliases.json."""
    lookup = {}
    if not ALIASES.is_file():
        return lookup
    try:
        data = json.loads(ALIASES.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"warning: could not read {ALIASES.name}: {exc}", file=sys.stderr)
        return lookup
    for canonical, variants in data.items():
        if canonical.startswith("_") or not isinstance(variants, list):
            continue
        for spelling in [canonical, *variants]:
            lookup[alnum_key(spelling)] = canonical
    return lookup


NAME_ALIASES = _load_aliases()
_SEEN_NAME_SPELLINGS = {}


def _phonetic_key(name: str) -> str:
    key = alnum_key(re.sub(r"\([^)]*\)", "", name)).replace("h", "").replace("w", "v")
    return re.sub(r"(.)\1+", r"\1", key)


def canon_name(name: str) -> str:
    """Drop bracketed notes and merge known alternate spellings of one person."""
    cleaned = re.sub(r"\s*\([^)]*\)", "", str(name or "")).strip() or str(name or "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    canonical = NAME_ALIASES.get(alnum_key(cleaned), cleaned)
    _SEEN_NAME_SPELLINGS.setdefault(_phonetic_key(canonical), set()).add(canonical)
    return canonical


def unique_names(names) -> list:
    out, seen = [], set()
    for name in names:
        cleaned = canon_name(name)
        key = alnum_key(cleaned)
        if cleaned and key not in seen:
            seen.add(key)
            out.append(cleaned)
    return out


_QUOTE = "\"“”"
_TITLE_RULES = [
    re.compile(rf"\s*[\(\[]\s*From\s+[{_QUOTE}][^{_QUOTE}]*[{_QUOTE}]\s*[\)\]]", re.I),
    re.compile(rf"\s+-\s+From\s+[{_QUOTE}][^{_QUOTE}]*[{_QUOTE}]\s*$", re.I),
    re.compile(r"\s*[\(\[]\s*Telugu\s*[\)\]]", re.I),
    re.compile(r"\s+-\s+Telugu(\s+Version)?\s*$", re.I),
]


def clean_title(title: str, movie_title: str = "") -> str:
    """Tidy a track title the way a listener would expect to read it."""
    out = str(title or "").strip()
    for rule in _TITLE_RULES:
        out = rule.sub("", out)
    out = re.sub(r"\s+-\s*$", "", out).strip()
    # A lone straight quote is what is left of '"Name" (Version)' after the
    # opening quote was dropped upstream: 'Theme of Kalki" (Krishna Song)'.
    if out.count('"') % 2 == 1:
        out = out.replace('"', "")
    # "You’Re" -> "You’re" (contraction suffixes that arrive capitalised)
    out = re.sub(r"(?<=[A-Za-z])([’'])(Re|S|Ll|Ve|D|T|M)\b", lambda m: m.group(1) + m.group(2).lower(), out)
    # "Dhurandhar The Revenge - Aari Aari" -> "Aari Aari" (film name repeated as prefix)
    prefix = re.match(r"^(.+?)\s+[-–]\s+(.+)$", out)
    if prefix and movie_title and alnum_key(prefix.group(1)) == alnum_key(movie_title):
        out = prefix.group(2)
    out = re.sub(r"\s{2,}", " ", out)
    out = re.sub(r"\s+([\)\]])", r"\1", out).strip()
    return out or str(title or "").strip()


_NOT_A_NAME = {"-", "–", "—", "n/a", "na", "none", "unknown", "tba"}


def split_credit(text: str) -> list:
    """'A, B & C' -> ['A', 'B', 'C']; placeholder dashes are dropped."""
    parts = re.split(r"\s*(?:,|&|;|\band\b|\+)\s*", str(text or ""))
    return [p.strip() for p in parts if p.strip() and p.strip().casefold() not in _NOT_A_NAME]


def parse_count(text):
    """'729M' -> 729000000, '1.2M plays' -> 1200000, '4,312' -> 4312."""
    if not text:
        return 0
    m = re.match(r"\s*([\d][\d,]*(?:\.\d+)?)\s*([KMB]?)", str(text).replace(" ", " "), re.I)
    if not m:
        return 0
    value = float(m.group(1).replace(",", ""))
    return value * {"": 1, "K": 1e3, "M": 1e6, "B": 1e9}[m.group(2).upper()]


def format_count(value) -> str:
    """Compactly format counts: 1234 -> 1.2K, 729000000 -> 729M."""
    value = max(0, float(value or 0))
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}".rstrip("0").rstrip(".") + "B"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}".rstrip("0").rstrip(".") + "M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}".rstrip("0").rstrip(".") + "K"
    return f"{int(value):,}"


def fmt_date(text):
    if not text:
        return ""
    try:
        d = datetime.strptime(text[:10], "%Y-%m-%d")
    except ValueError:
        return text
    return f"{d.day} {d:%B %Y}"


def fmt_runtime(minutes):
    try:
        total = int(minutes)
    except (TypeError, ValueError):
        return ""
    if total <= 0:
        return ""
    return f"{total // 60}h {total % 60:02d}m" if total >= 60 else f"{total}m"


def people(names) -> str:
    """Comma-separated links that run a site search for each name."""
    return ", ".join(f'<a href="/advanced-search/?q={e(quote(n))}">{e(n)}</a>' for n in names)


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


# --------------------------------------------------------------------------
# data
# --------------------------------------------------------------------------

_LANGUAGE_NAMES = {
    "te": "Telugu", "hi": "Hindi", "ta": "Tamil", "ml": "Malayalam",
    "kn": "Kannada", "en": "English", "bn": "Bengali", "mr": "Marathi",
    "ur": "Urdu", "sa": "Sanskrit", "pa": "Punjabi", "gu": "Gujarati",
}


def clean_ott(entries):
    """Trim provider names and fold obvious duplicates (e.g. 'X with Ads')."""
    cleaned, seen = [], set()
    for entry in entries or []:
        provider = re.sub(r"\s+", " ", str(entry.get("provider") or "")).strip()
        kind = str(entry.get("type") or "flatrate").strip().lower()
        if not provider:
            continue
        key = (provider.casefold(), kind)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append({"provider": provider, "type": kind})
    providers = {(c["provider"].casefold(), c["type"]) for c in cleaned}
    result = []
    for entry in cleaned:
        base = re.sub(r"\s+with ads$", "", entry["provider"], flags=re.I)
        if base != entry["provider"] and (base.casefold(), entry["type"]) in providers:
            continue
        result.append(entry)
    return result


def weighted_rating(rating, votes, mean_rating, min_votes):
    """IMDb's Bayesian rating: WR = v/(v+m)*R + m/(v+m)*C."""
    return (votes / (votes + min_votes)) * rating + (min_votes / (votes + min_votes)) * mean_rating


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

    def display_language(value):
        text = text_or_none(value)
        return _LANGUAGE_NAMES.get(text.casefold(), text) if text else None

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
        return unique_names(str(person).strip() for person in movie["people"].get(role, []) if text_or_none(person))

    for row in catalogue["movies"]:
        title = str(row.get("title") or "Untitled film").strip()
        year = str(row.get("release_year") or "Unknown")
        slug = unique_slug(f"{title}-{year}", used_movie_slugs)
        urls = dict(row.get("links") or {})
        for key, field in (("imdb", "imdb_url"), ("tmdb", "tmdb_url"), ("wikipedia", "wikipedia_url"),
                           ("wikipedia_soundtrack", "wikipedia_soundtrack_url")):
            urls.setdefault(key, row.get(field))
        try:
            votes_numeric = max(0, int(row.get("imdb_votes_numeric") or 0))
        except (TypeError, ValueError):
            votes_numeric = 0
        try:
            rating_numeric = float(row.get("imdb_score")) if text_or_none(row.get("imdb_score")) else None
        except (TypeError, ValueError):
            rating_numeric = None
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
            "production_banners": unique_names(
                str(p).strip() for p in (row.get("people") or {}).get("production_banner", []) if text_or_none(p)),
            "additional_people": [],
            "trailer": text_or_none(row.get("trailer_youtube_id")),
            "imdb_score": text_or_none(row.get("imdb_score")),
            "imdb_rating_numeric": rating_numeric,
            "imdb_votes": text_or_none(row.get("imdb_votes")),
            "imdb_votes_numeric": votes_numeric,
            "imdb_weighted": None,
            "urls": urls, "ott_availability": clean_ott(row.get("ott_availability")),
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
            extra_names = unique_names(str(n).strip() for n in raw_names)
            if extra_names:
                label = role_labels.get(role, role.replace("_", " ").strip().title())
                movie["additional_people"].append({"label": label, "names": extra_names})
        movie_by_id[movie["imdb_id"]] = movie
        movies.append(movie)

    # Weighted rating so a 9.0 from 300 voters does not outrank an 8.0 from 150,000.
    rated = [m for m in movies if m["imdb_rating_numeric"] is not None and m["imdb_votes_numeric"] > 0]
    if rated:
        mean_rating = sum(m["imdb_rating_numeric"] for m in rated) / len(rated)
        vote_counts = sorted(m["imdb_votes_numeric"] for m in rated)
        min_votes = vote_counts[len(vote_counts) // 2]
        for m in rated:
            m["imdb_weighted"] = round(weighted_rating(
                m["imdb_rating_numeric"], m["imdb_votes_numeric"], mean_rating, min_votes), 3)

    # Schema v9 maintains exactly one canonical soundtrack album anchor per movie.
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
        title = clean_title(str(raw["title"]).strip(), movie["title"])
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

        raw_sec = raw.get("duration_sec")
        raw_ms = raw.get("duration_ms")
        try:
            sec = int(raw_sec) if raw_sec is not None else (int(raw_ms) // 1000 if raw_ms is not None else None)
        except (TypeError, ValueError):
            sec = None
        try:
            ms = int(raw_ms) if raw_ms is not None else (sec * 1000 if sec is not None else None)
        except (TypeError, ValueError):
            ms = sec * 1000 if sec is not None else None

        # The formatted duration is the human-reviewed value; a subset of imported
        # rows has stale duration_sec/duration_ms, so prefer the formatted string.
        duration = text_or_none(raw.get("duration_formatted")) or ""
        if duration and re.fullmatch(r"\d{1,4}:\d{2}", duration):
            minutes, seconds = duration.split(":", 1)
            if int(seconds) < 60:
                sec = int(minutes) * 60 + int(seconds)
                ms = sec * 1000
            else:
                duration = ""
        else:
            duration = ""
        if not duration and sec is not None and sec >= 0:
            duration = f"{sec // 60}:{sec % 60:02d}"
        duration = duration or ""

        # Singers: the database's 'singer' credits only. spotify_performer and
        # ytm_performer rows are provider-side contributor lists (often the
        # composer, lyricist or a differently spelled copy of the same singer),
        # so they are not shown as people.
        singer_credits = [c for c in (raw.get("artist_credits") or []) if str(c.get("role") or "singer").lower() == "singer"]
        lyricist_names, seen_lyricists, instrumental = [], set(), False
        for credit in raw.get("lyricist_credits") or []:
            for piece in re.split(r"\s*(?:,|&|;)\s*", str(credit.get("name") or "")):
                piece = piece.strip()
                if not piece or piece.casefold() in _NOT_A_NAME:
                    continue
                if piece.casefold() == "instrumental":
                    instrumental = True
                    continue
                name = canon_name(piece)
                if alnum_key(name) not in seen_lyricists:
                    seen_lyricists.add(alnum_key(name))
                    lyricist_names.append(name)
        singer_names = unique_names(str(c.get("name") or "") for c in singer_credits)
        # The source table sometimes lists the composer or lyricist in the singer
        # column. Drop them when other singers remain; keep them if they sang alone.
        contributors = {alnum_key(n) for n in lyricist_names} | {alnum_key(n) for n in movie["music_directors"]}
        performers = [n for n in singer_names if alnum_key(n) not in contributors]
        if performers:
            singer_names = performers

        ytm_plays_text = text_or_none(ytm.get("views_text"))
        youtube_views = (text_or_none(raw.get("youtube_video_song_views"))
                         or text_or_none(youtube.get("views_text")))
        yt_views_num = parse_count(youtube_views)
        ytm_plays_num = parse_count(ytm_plays_text)
        plays_num = yt_views_num + ytm_plays_num
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
            "disc_number": raw.get("disc_number"), "artists": singer_names,
            "artist_credits": raw.get("artist_credits") or [], "lyricists": lyricist_names,
            "instrumental": instrumental,
            "genres": list(raw.get("genres") or []),
            "duration": duration, "duration_sec": sec, "duration_ms": ms,
            "explicit": tri_bool(explicit_value),
            "bonus_track": tri_bool(bonus_value),
            "isrc_code": text_or_none(raw.get("isrc_code")),
            "data_source": text_or_none(raw.get("data_source")),
            "spotify_id": spotify_id, "spotify_url": spotify_url,
            "spotify_preview_url": text_or_none(spotify.get("preview_url")),
            "spotify_popularity": spotify.get("popularity"),
            "ytm_id": ytm_id, "ytm_url": ytm_url, "ytm_views": ytm_plays_text,
            # "Plays" combines every captured count: YouTube video views + YouTube Music plays.
            "plays": format_count(plays_num) if plays_num else "", "plays_num": plays_num,
            "ytm_plays_num": ytm_plays_num, "yt_views_num": yt_views_num,
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
    def song_order(song):
        return (song.get("disc_number") or 1,
                song.get("number") if song.get("number") is not None else 2147483647,
                song["title"].casefold(), song["id"])

    for movie in movies:
        movie["songs"].sort(key=song_order)
        movie["albums"].sort(key=lambda album: (-len(album["songs"]), album["title"].casefold(), album["album_id"] or ""))
        movie["album"] = movie["albums"][0] if movie["albums"] else {}
        for album in movie["albums"]:
            album["songs"].sort(key=song_order)
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

    # Surface likely duplicate spellings so name_aliases.json can be extended.
    duplicates = [sorted(v) for v in _SEEN_NAME_SPELLINGS.values() if len(v) > 1]
    if duplicates:
        print("warning: possible duplicate spellings (add to name_aliases.json if they are one person): "
              + "; ".join(" / ".join(group) for group in duplicates[:12]), file=sys.stderr)

    return movies


# --------------------------------------------------------------------------
# icons and small components
# --------------------------------------------------------------------------

_ICONS = {
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20.5 20.5-4.2-4.2"/>',
    "sliders": '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M18.7 5.3l-1.6 1.6M6.9 17.1l-1.6 1.6"/>',
    "moon": '<path d="M20.5 14.2A8.5 8.5 0 0 1 9.8 3.5a8.5 8.5 0 1 0 10.7 10.7Z"/>',
    "arrow": '<path d="M7 17 17 7M8.5 7H17v8.5"/>',
    "close": '<path d="m6 6 12 12M18 6 6 18"/>',
    "chevron": '<path d="m6 9 6 6 6-6"/>',
    "play": '<path d="M8 5.5v13l11-6.5z" fill="currentColor" stroke="none"/>',
    "star": '<path d="m12 3.2 2.7 5.6 6.1.8-4.5 4.3 1.1 6.1L12 17.1l-5.4 2.9 1.1-6.1-4.5-4.3 6.1-.8z" fill="currentColor" stroke="none"/>',
    "link": '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3A4 4 0 0 0 11 18.7l1-1"/>',
    "note": '<path d="M9 18V5l11-2v13"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="17.5" cy="16" r="2.5"/>',
}


def icon(name: str, cls: str = "") -> str:
    body = _ICONS[name]
    return (f'<svg class="icon{(" " + cls) if cls else ""}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">{body}</svg>')


def provider_icon(provider: str) -> str:
    """Small inline provider marks; these accompany text labels for accessibility."""
    if provider == "spotify":
        return ('<svg class="provider-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
                '<circle cx="12" cy="12" r="11" fill="currentColor"/><path d="M5.3 9.2c4.3-1.2 9.4-.7 13.2 1.5M6.2 12.4c3.6-1 7.7-.5 10.8 1.3M7.1 15.3c2.8-.7 5.9-.3 8.2 1" '
                'fill="none" stroke="#0a0a0a" stroke-width="1.5" stroke-linecap="round"/></svg>')
    if provider == "youtube":
        return ('<svg class="provider-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
                '<rect x="1" y="4.5" width="22" height="15" rx="4.5" fill="currentColor"/><path d="M10 9v6l5.2-3z" fill="#fff"/></svg>')
    return ('<svg class="provider-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
            '<circle cx="12" cy="12" r="11" fill="currentColor"/><circle cx="12" cy="12" r="6.2" fill="none" stroke="#fff" stroke-width="1.4"/>'
            '<path d="M10.2 9v6l5-3z" fill="#fff"/></svg>')


def img(src, alt, cls, w, h, eager=False):
    if not src:
        return ""
    loading = "eager" if eager else "lazy"
    return (f'<img class="{cls}" src="{e(src)}" alt="{e(alt)}" width="{w}" height="{h}" '
            f'loading="{loading}" decoding="async" referrerpolicy="no-referrer">')


def cover_img(src, cls="track-artwork", size=48, eager=False):
    if not src:
        return f'<span class="{cls} {cls}-empty" aria-hidden="true">{icon("note")}</span>'
    return img(src, "", cls, size, size, eager)


def facts(rows):
    items = "".join(f"<dt>{e(k)}</dt><dd>{v}</dd>" for k, v in rows if v)
    return f'<dl class="facts">{items}</dl>' if items else ""


def song_sub(song, show_movie):
    if show_movie:
        bits = [f'{song["movie"]["title"]} · {song["movie"]["year"]}']
        if song["artists"]:
            bits.append(", ".join(song["artists"][:2]))
        return " · ".join(bits)
    return ", ".join(song["artists"][:3])


def plays_title(song):
    bits = []
    if song.get("youtube_video_views"):
        bits.append(f'YouTube {song["youtube_video_views"]} views')
    if song.get("ytm_views"):
        bits.append(f'YouTube Music {song["ytm_views"]}')
    return " · ".join(bits)


def song_row(song, *, rank=None, current=False, show_movie=True, show_plays=False, filterable=False):
    number = rank if rank is not None else song.get("number")
    number_markup = f'<span class="n">{e(number)}</span>' if number not in (None, "") else ""
    sub = song_sub(song, show_movie)
    plays = ""
    if show_plays and song["plays"]:
        plays = f'<span class="plays" title="{e(plays_title(song))}">{e(song["plays"])}</span>'
    cur = ' aria-current="true"' if current else ""
    movie = song["movie"]
    cover = cover_img(album_art(song.get("album"), movie))
    duration = f'<span class="dur">{e(song["duration"])}</span>' if song.get("duration") else ""
    if filterable:
        filter_attrs = (
            f' class="track song-catalog-item" data-title="{e(song["title"].lower())}" '
            f'data-artists="{e("|".join(song["artists"]).lower())}" data-lyricists="{e("|".join(song["lyricists"]).lower())}" '
            f'data-music="{e("|".join(movie["music_directors"]).lower())}" data-album="{e(song["album"]["title"].lower())}" '
            f'data-movie="{e(movie["title"].lower())}" data-lang="{e((movie["original_language"] or "").lower())}" '
            f'data-genre="{e("|".join(song["genres"]).lower())}" data-release="{e(movie["released"] or (movie["year"] + "-01-01"))}" '
            f'data-year="{e(movie["year"])}" data-plays="{int(song["plays_num"])}" data-songid="{e(song["id"])}"')
    else:
        filter_attrs = ' class="track"'
    return (
        f'<li{filter_attrs}><a href="/song/{e(song["id"])}/"{cur}>'
        f'{number_markup}{cover}'
        f'<span class="main"><span class="name">{e(song["title"])}</span>'
        f'<span class="sub">{e(sub)}</span></span>'
        f'<span class="meta">{duration}{plays}</span>'
        f"</a></li>"
    )


def listen_links(song):
    """Provider rows: label, what the count means, and an arrow."""
    out = []
    if song.get("spotify_url"):
        out.append(
            f'<a class="listen-link spotify" href="{e(song["spotify_url"])}" rel="noopener noreferrer" target="_blank">'
            f'{provider_icon("spotify")}<span class="ll-copy"><strong>Spotify</strong><small>Open the track</small></span>'
            f'{icon("arrow", "ll-arrow")}</a>')
    if song.get("ytm_url"):
        small = f'{song["ytm_views"]}' if song.get("ytm_views") else "Open the track"
        out.append(
            f'<a class="listen-link ytmusic" href="{e(song["ytm_url"])}" rel="noopener noreferrer" target="_blank">'
            f'{provider_icon("ytmusic")}<span class="ll-copy"><strong>YouTube Music</strong><small>{e(small)}</small></span>'
            f'{icon("arrow", "ll-arrow")}</a>')
    if song.get("youtube_url"):
        small = f'{song["youtube_video_views"]} views' if song.get("youtube_video_views") else "Watch the video"
        out.append(
            f'<a class="listen-link youtube" href="{e(song["youtube_url"])}" rel="noopener noreferrer" target="_blank">'
            f'{provider_icon("youtube")}<span class="ll-copy"><strong>YouTube</strong><small>{e(small)}</small></span>'
            f'{icon("arrow", "ll-arrow")}</a>')
    return f'<div class="listen-links">{"".join(out)}</div>' if out else ""


def player(song):
    if song.get("spotify_id"):
        kind, ident, label = "spotify", song["spotify_id"], "Play here"
    elif song.get("ytm_id"):
        kind, ident, label = "youtube", song["ytm_id"], "Play here"
    else:
        return ""
    return (f'<button type="button" class="btn" data-embed="{kind}" data-id="{e(ident)}">'
            f'{icon("play")}<span>{label}</span></button>')


def youtube_video_block(song):
    video_id = song.get("youtube_video_id")
    if not video_id:
        return ""
    thumb = f'https://i.ytimg.com/vi/{e(video_id)}/hqdefault.jpg'
    title = song.get("youtube_video_title") or song["title"]
    views = f'<span class="chip">{e(song["youtube_video_views"])} views</span>' if song.get("youtube_video_views") else ""
    return (
        f'<section class="card song-video-section"><div class="section-heading"><div><p class="eyebrow">YOUTUBE</p><h2>Song video</h2></div>{views}</div>'
        f'<p class="song-video-title">{e(title)}</p>'
        f'<div class="trailer song-video-embed"><button type="button" data-embed="youtube" data-id="{e(video_id)}" aria-label="Play YouTube video for {e(song["title"])}"><img src="{thumb}" alt="" width="480" height="360" loading="lazy" decoding="async" referrerpolicy="no-referrer"><span class="play">{icon("play")}<span>Play video</span></span></button></div></section>'
    )


def provider_search_url(provider, title):
    q = url_quote(title, safe="")
    key = str(provider or "").strip().lower()
    if "netflix" in key:
        return f"https://www.netflix.com/search?q={q}"
    if "sony liv" in key or "sonyliv" in key:
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
    elif "sony" in p:
        label, cls = "SONY", "ott-logo-sonyliv"
    elif "hotstar" in p:
        label, cls = "Jio", "ott-logo-hotstar"
    elif "sun nxt" in p:
        label, cls = "SUN", "ott-logo-sunnxt"
    elif p.startswith("vi"):
        label, cls = "Vi", "ott-logo-vi"
    else:
        label, cls = (str(provider or "?").strip()[:3].upper(), "ott-logo-generic")
    return f'<span class="ott-logo {cls}" aria-hidden="true">{e(label)}</span>'


def ott_label(provider):
    """'Sonyliv Amazon Channel' -> ('Sonyliv', 'via Prime Video channel')."""
    text = str(provider or "").strip()
    match = re.match(r"^(.*?)\s+Amazon Channel$", text, re.I)
    if match:
        return match.group(1).strip(), "Prime Video channel"
    return text, ""


def ott_buttons(movie):
    entries = movie.get("ott_availability") or []
    if not entries:
        return ""
    out = []
    for entry in entries:
        provider = str(entry.get("provider") or "Streaming provider")
        mode = str(entry.get("type") or "flatrate").lower()
        if mode in ("rent", "rent/buy"):
            verb, kind = "Rent on", "Rent"
        elif mode == "buy":
            verb, kind = "Buy on", "Buy"
        elif mode in ("free", "ads", "free with ads"):
            verb, kind = "Watch on", "Free"
        else:
            verb, kind = "Stream on", "Subscription"
        name, via = ott_label(provider)
        sub = f"{kind} · {via}" if via else kind
        out.append(
            f'<a class="ott-provider-btn" href="{e(provider_search_url(provider, movie["title"]))}" target="_blank" rel="noopener noreferrer">'
            f'{ott_provider_icon(provider)}<span class="ott-provider-copy"><strong>{e(verb)} {e(name)}</strong><small>{e(sub)}</small></span>'
            f'{icon("arrow", "ott-arrow")}</a>')
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
            links.append(f'<a href="{e(url)}" target="_blank" rel="noopener noreferrer">{e(label)} {icon("arrow")}</a>')
    if not links:
        return ""
    return ('<details class="movie-links-dropdown"><summary class="btn">More links ' + icon("chevron")
            + '</summary><div class="movie-links-menu">' + "".join(links) + "</div></details>")


# --------------------------------------------------------------------------
# page chrome
# --------------------------------------------------------------------------

NAV = (("home", "/", "Home"), ("songs", "/songs/", "Songs"), ("albums", "/albums/", "Albums"),
       ("movies", "/movies/", "Movies"), ("charts", "/charts/", "Charts"))


def search_controls(*, options_open=False):
    """Type chips and filters shared by the header, home and search page."""
    types = "".join(
        f'<button type="button" class="sp-type{" is-active" if value == "all" else ""}" data-type="{value}" '
        f'aria-pressed="{"true" if value == "all" else "false"}">{label}</button>'
        for value, label in (("all", "All"), ("song", "Songs"), ("album", "Albums"), ("movie", "Movies")))
    languages = "".join(f'<option value="{e(v.lower())}">{e(v)}</option>' for v in SEARCH_FACETS["languages"])
    genres = "".join(f'<option value="{e(v.lower())}">{e(v)}</option>' for v in SEARCH_FACETS["genres"])
    hidden = "" if options_open else " hidden"
    return (
        f'<div class="sp-types" role="group" aria-label="Search in">{types}</div>'
        f'<div class="sp-options" data-search-options{hidden}>'
        '<label>From year<input type="number" inputmode="numeric" min="1900" max="2100" placeholder="Any" data-filter="from"></label>'
        '<label>To year<input type="number" inputmode="numeric" min="1900" max="2100" placeholder="Any" data-filter="to"></label>'
        f'<label>Language<select data-filter="lang"><option value="">Any</option>{languages}</select></label>'
        f'<label>Genre<select data-filter="genre"><option value="">Any</option>{genres}</select></label>'
        '<label>Sort by<select data-filter="sort"><option value="relevance">Best match</option>'
        '<option value="popular">Most popular</option><option value="newest">Newest first</option>'
        '<option value="oldest">Oldest first</option><option value="title">Title A–Z</option></select></label>'
        '<button type="button" class="sp-reset" data-search-reset>Reset</button>'
        '</div>'
    )


def layout(cfg, site_url, *, title, desc, path, body, section="", page="", og_type="website", og_image=None,
           jsonld=None, noindex=False):
    full_title = title if title == cfg["name"] else f"{title} | {cfg['name']}"
    head = [
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">',
        f"<title>{e(full_title)}</title>",
        f'<meta name="description" content="{e(desc)}">',
        '<meta name="color-scheme" content="dark light">',
        '<meta name="theme-color" content="#050505">',
        '<link rel="icon" href="/static/favicon.png" type="image/png">',
        '<link rel="apple-touch-icon" href="/static/favicon.png">',
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
        # Applies the saved theme before first paint so there is no light/dark flash.
        f'<script src="/static/theme.js?v={e(ASSET_VERSION)}"></script>',
        f'<link rel="stylesheet" href="/static/style.css?v={e(ASSET_VERSION)}">',
        f'<script src="/static/app.js?v={e(ASSET_VERSION)}" defer></script>',
    ]
    if jsonld:
        blob = json.dumps(jsonld, ensure_ascii=False).replace("<", "\\u003c")
        head.append(f'<script type="application/ld+json">{blob}</script>')

    nav_items = []
    for key, href, label in NAV:
        active = key == section
        nav_items.append(
            '<a class="nav-link' + (" active" if active else "") + '" href="' + href + '"'
            + (' aria-current="page"' if active else "") + '><span>' + label + "</span></a>")
    nav = "".join(nav_items)
    brand = (
        '<a class="brand" href="/" aria-label="Vāchika home">'
        '<span class="brand-mark"><img class="logo-on-dark" src="/static/vachika-mark-dark.png" alt="" width="20" height="38">'
        '<img class="logo-on-light" src="/static/vachika-mark-light.png" alt="" width="20" height="38"></span>'
        '<span class="brand-word"><img class="logo-on-dark" src="/static/vachika-wordmark-dark.png" alt="Vāchika" width="112" height="25">'
        '<img class="logo-on-light" src="/static/vachika-wordmark-light.png" alt="" width="112" height="25"></span></a>')
    header = f"""<header class="site-header" id="site-header">
  <div class="header-inner">
    {brand}
    <nav class="site-nav" aria-label="Main navigation">{nav}</nav>
    <form role="search" action="/advanced-search/" method="get" class="search header-search" id="global-search-form" data-search-root="popover">
      <label class="sr" for="q">Search songs, movies, albums, singers and music directors</label>
      <div class="search-shell">
        {icon("search", "search-glyph")}
        <input id="q" name="q" type="search" placeholder="Search songs, movies, singers…" autocomplete="off" enterkeyhint="search" aria-controls="search-popover" aria-expanded="false" data-search-input>
        <button type="button" class="search-filter-toggle" data-filter-toggle aria-label="Show search filters" aria-expanded="false" title="Filters">{icon("sliders")}</button>
      </div>
      <div id="search-popover" class="search-popover" hidden>
        <div class="sp-controls">{search_controls()}</div>
        <div class="sp-body" data-search-body role="listbox" aria-label="Search results"></div>
      </div>
    </form>
    <button type="button" class="theme-toggle" id="theme-toggle" aria-label="Switch theme" title="Switch theme">{icon("sun", "i-sun")}{icon("moon", "i-moon")}</button>
  </div>
</header>"""

    return f"""<!doctype html>
<html lang="en" data-theme="dark">
<head>
{chr(10).join(head)}
</head>
<body data-page="{e(page or section)}">
<div class="page-shell" id="page-shell">
{header}
<main id="main">
{body}
</main>
<footer class="site-footer">
  <p>Song audio, artwork and film details belong to their owners. Play links go to Spotify and YouTube.</p>
  <p>Film data and images from TMDB. This site uses the TMDB API but is not endorsed or certified by TMDB.</p>
</footer>
</div>
<aside id="song-drawer" class="song-drawer" aria-hidden="true" aria-label="Song details" role="complementary" inert>
  <div class="drawer-scroll">
    <div class="drawer-topline"><span class="eyebrow">Song details</span><button type="button" class="drawer-close" id="drawer-close" aria-label="Close song details">{icon("close")}</button></div>
    <div id="drawer-body" class="drawer-body"></div>
  </div>
</aside>
</body>
</html>
"""


# --------------------------------------------------------------------------
# cards and lists
# --------------------------------------------------------------------------

def album_total_plays(entity) -> float:
    """Sum captured YouTube views and YouTube Music plays over a soundtrack's songs."""
    return sum(song["plays_num"] for song in entity["songs"])


def album_year(album) -> str:
    return str(album.get("released") or album["movie"]["year"] or "")[:4]


def rating_label(movie) -> str:
    return f'{movie["imdb_score"]}' if movie.get("imdb_score") else ""


def votes_label(movie) -> str:
    votes = int(movie.get("imdb_votes_numeric") or 0)
    return format_count(votes) if votes else ""


def album_card(album, *, eager=False, filterable=False):
    movie = album["movie"]
    artwork = album_art(album, movie)
    count = len(album["songs"])
    total = album_total_plays(album)
    loading = "eager" if eager else "lazy"
    actual_cover = bool(album.get("artwork") or album.get("artwork_small"))
    alt = f'Album artwork for {album["title"]}' if actual_cover else f'Movie poster for {movie["title"]}; album artwork unavailable'
    if artwork:
        fallback = "" if actual_cover else " album-cover-fallback"
        cover = (f'<img class="album-cover{fallback}" src="{e(artwork)}" alt="{e(alt)}" '
                 f'width="640" height="640" loading="{loading}" decoding="async" referrerpolicy="no-referrer">')
    else:
        cover = f'<span class="album-cover album-cover-empty" aria-hidden="true">{icon("note")}</span>'
    released = album["released"] or (movie["year"] + "-01-01")
    attrs = (f' class="album-item" data-title="{e((album["title"] + " " + movie["title"]).lower())}" data-year="{e(album_year(album))}" '
             f'data-release="{e(released)}" data-artist="{e("|".join(movie["music_directors"]).lower())}" data-plays="{int(total)}" '
             f'data-songs="{count}" data-genre="{e("|".join(movie["genres"]).lower())}" data-lang="{e((movie["original_language"] or "").lower())}"')
    plays = f'<span class="album-plays">{e(format_count(total))} plays</span>' if total else ""
    return (
        f'<li{attrs}><a class="album-card" href="{e(album_path(album))}">'
        f'<span class="album-cover-wrap">{cover}</span><span class="album-card-title">{e(album["title"])}</span>'
        f'<span class="sub">{e(movie["title"])} · {e(movie["year"])} · {count} {"song" if count == 1 else "songs"}</span>'
        f'{plays}</a></li>'
    )


def rating_pill(movie) -> str:
    if not movie.get("imdb_score"):
        return ""
    return f'<span class="rating-pill">{icon("star")}{e(movie["imdb_score"])}</span>'


def movie_card(movie, *, eager=False, rank=None):
    artwork = movie["poster"] or album_art(movie.get("album"), movie)
    count = len(movie["songs"])
    release = movie["released"] or (movie["year"] + "-01-01")
    loading = "eager" if eager else "lazy"
    if artwork:
        cover = (f'<img class="movie-cover" src="{e(artwork)}" alt="Poster for {e(movie["title"])}" width="500" height="750" '
                 f'loading="{loading}" decoding="async" referrerpolicy="no-referrer">')
    else:
        cover = f'<span class="movie-cover movie-cover-empty" aria-hidden="true">{icon("note")}</span>'
    votes = votes_label(movie)
    votes_html = f'<span class="movie-card-votes"><strong>{e(votes)}</strong> IMDb ratings</span>' if votes else ""
    language = f' · {e(movie["original_language"])}' if movie["original_language"] else ""
    rank_html = f'<span class="rank-badge" data-rank>{rank}</span>' if rank else '<span class="rank-badge" data-rank></span>'
    weighted = movie.get("imdb_weighted") or 0
    return (
        f'<li class="movie-item" data-title="{e(movie["title"].lower())}" data-release="{e(release)}" '
        f'data-year="{e(movie["year"])}" data-genre="{e("|".join(movie["genres"]).lower())}" '
        f'data-music="{e("|".join(movie["music_directors"]).lower())}" data-director="{e("|".join(movie["directors"]).lower())}" '
        f'data-lang="{e((movie["original_language"] or "").lower())}" data-universe="{e((movie["cinematic_universe"] or "").lower())}" '
        f'data-songs="{count}" data-imdb-votes="{int(movie.get("imdb_votes_numeric") or 0)}" '
        f'data-rating="{e(movie.get("imdb_rating_numeric") or 0)}" data-weighted="{weighted}">'
        f'<a class="movie-card" href="{e(movie_path(movie))}"><span class="poster-wrap">{cover}{rank_html}{rating_pill(movie)}</span>'
        f'<span class="movie-card-title">{e(movie["title"])}</span>'
        f'<span class="sub">{e(movie["year"])}{language} · {count} {"song" if count == 1 else "songs"}</span>'
        f'{votes_html}</a></li>'
    )


def votes_ranked(movies):
    return sorted(movies, key=lambda m: (-int(m.get("imdb_votes_numeric") or 0), m["title"].casefold()))


def weighted_ranked(movies):
    return sorted(movies, key=lambda m: (-(m.get("imdb_weighted") or 0), m["title"].casefold()))


def movie_rail_item(movie, rank):
    artwork = movie["poster"] or album_art(movie.get("album"), movie)
    cover = (img(artwork, f'Poster for {movie["title"]}', "rail-poster", 500, 750) if artwork
             else f'<span class="rail-poster movie-cover-empty">{icon("note")}</span>')
    bits = []
    if movie.get("imdb_score"):
        bits.append(f'{icon("star")}{e(movie["imdb_score"])}')
    if votes_label(movie):
        bits.append(f'{e(votes_label(movie))} ratings')
    return (f'<li class="rail-item" style="--i:{rank - 1}"><a href="{e(movie_path(movie))}">'
            f'<span class="rail-rank" aria-hidden="true">{rank}</span><span class="rail-art">{cover}</span>'
            f'<span class="rail-title">{e(movie["title"])}</span>'
            f'<span class="rail-meta">{" <i>·</i> ".join(bits)}</span></a></li>')


def chart_entity_row(entity, rank, kind, view="votes"):
    if kind == "album":
        album = entity
        movie = album["movie"]
        artwork = album_art(album, movie)
        path = album_path(album)
        count = len(album["songs"])
        total = album_total_plays(album)
        title = album["title"]
        subtitle = f'{movie["title"]} · {movie["year"]} · {count} {"song" if count == 1 else "songs"}'
        metric = f'{format_count(total)} plays'
    else:
        movie = entity
        artwork = movie["poster"] or album_art(movie.get("album"), movie)
        path = movie_path(movie)
        title = movie["title"]
        votes = int(movie.get("imdb_votes_numeric") or 0)
        bits = [str(movie["year"])]
        if movie.get("imdb_score"):
            bits.append(f'★ {movie["imdb_score"]}')
        if votes:
            bits.append(f'{votes:,} IMDb ratings')
        subtitle = " · ".join(bits)
        if view == "weighted":
            metric = f'{movie.get("imdb_weighted") or 0:.2f} weighted'
        else:
            metric = f'{format_count(votes)} ratings'
    return (f'<li class="track entity-chart-row"><a href="{e(path)}"><span class="n">{rank}</span>{cover_img(artwork)}'
            f'<span class="main"><span class="name">{e(title)}</span><span class="sub">{e(subtitle)}</span></span>'
            f'<span class="meta"><span class="plays">{e(metric)}</span></span></a></li>')


def section_heading(eyebrow, title, link_href="", link_text=""):
    link = f'<a class="text-link" href="{e(link_href)}">{e(link_text)} {icon("arrow")}</a>' if link_href else ""
    return f'<div class="section-heading"><div><p class="eyebrow">{e(eyebrow)}</p><h2>{e(title)}</h2></div>{link}</div>'


def year_inputs(prefix, label):
    return (f'<label>{label} from<input type="number" inputmode="numeric" min="1900" max="2100" placeholder="Any" id="{prefix}-from"></label>'
            f'<label>{label} to<input type="number" inputmode="numeric" min="1900" max="2100" placeholder="Any" id="{prefix}-to"></label>')


def options_html(values, lower=True):
    return "".join(f'<option value="{e(v.lower() if lower else v)}">{e(v)}</option>' for v in values)


def filter_panel(panel_id, summary_id, count_text, inner):
    return (f'<details class="filter-panel glass" id="{panel_id}" open>'
            f'<summary class="filter-panel-summary"><span class="filter-summary-label">Filters and sorting</span>'
            f'<span class="filter-summary-count" id="{summary_id}">{e(count_text)}</span>{icon("chevron", "filter-summary-chevron")}</summary>'
            f'{inner}</details>')


# --------------------------------------------------------------------------
# pages
# --------------------------------------------------------------------------

def home_page(cfg, site_url, movies):
    all_songs = [s for m in movies for s in m["songs"]]
    all_albums = [album for movie in movies for album in movie["albums"]]
    top_songs = sorted(all_songs, key=lambda s: s["plays_num"], reverse=True)[:6]
    popular_albums = sorted(all_albums, key=album_total_plays, reverse=True)[:6]
    top_rows = "".join(song_row(song, rank=i + 1, show_plays=True) for i, song in enumerate(top_songs))
    rail = "".join(movie_rail_item(m, i + 1) for i, m in enumerate(votes_ranked(movies)[:10]))
    album_items = "".join(album_card(a, eager=False) for a in popular_albums)
    stage_albums = [a for a in sorted(all_albums, key=album_total_plays, reverse=True) if a.get("artwork")][:5]
    stage = "".join(
        f'<a class="stage-card" style="--i:{i}" href="{e(album_path(a))}" tabindex="-1">'
        f'{img(a["artwork"], "", "stage-art", 640, 640, eager=True)}</a>' for i, a in enumerate(stage_albums))
    languages = ", ".join(SEARCH_FACETS["languages"])

    body = f"""
<section class="hero" id="hero">
  <div class="hero-copy">
    <p class="eyebrow">TELUGU SOUNDTRACK ARCHIVE</p>
    <h1>Every song <span class="hero-accent">has a story.</span></h1>
    <p class="lede">Songs, soundtrack albums and the films behind them: singers, lyricists, lyrics and where to listen.</p>
    <form role="search" action="/advanced-search/" method="get" class="home-search" id="home-search-form" data-search-root="inline" data-search-target="results">
      <label class="sr" for="home-q">Search songs, movies, albums, singers and music directors</label>
      <div class="search-shell search-shell-lg">
        {icon("search", "search-glyph")}
        <input id="home-q" name="q" type="search" placeholder="Search songs, movies, albums, singers…" autocomplete="off" enterkeyhint="search" data-search-input>
        <button type="button" class="search-filter-toggle" data-filter-toggle aria-label="Show search filters" aria-expanded="false" title="Filters">{icon("sliders")}<span>Filters</span></button>
        <button type="submit" class="btn primary search-go">Search</button>
      </div>
      <div class="sp-controls">{search_controls()}</div>
    </form>
    <div class="home-stats"><span><strong>{len(all_songs)}</strong> songs</span><span><strong>{len(all_albums)}</strong> albums</span><span><strong>{len(movies)}</strong> movies</span></div>
  </div>
  <div class="hero-stage" aria-hidden="true"><div class="stage" id="stage">{stage}</div></div>
  <a class="scroll-cue" href="#browse" aria-label="Scroll to charts"><span>Scroll</span>{icon("chevron")}</a>
</section>

<div id="results" class="wrap search-results" data-search-body hidden></div>
<p id="status" class="sr" role="status" aria-live="polite"></p>

<div id="browse" class="home-flow">
  <section class="wrap home-section reveal" data-reveal>
    {section_heading("MOST PLAYED", "Trending songs", "/charts/", "Full charts")}
    <p class="section-note">Ranked by captured YouTube views and YouTube Music plays added together.</p>
    <ol class="tracks chart-tracks">{top_rows}</ol>
  </section>
  <section class="wrap home-section reveal" data-reveal>
    {section_heading("SOUNDTRACKS", "Popular albums", "/albums/", "All albums")}
    <p class="section-note">Ranked by the combined plays of each soundtrack's songs.</p>
    <ul class="albums-grid">{album_items}</ul>
  </section>
  <section class="home-section home-rail-section reveal" data-reveal>
    <div class="wrap">
      {section_heading("MOST RATED", "Popular movies", "/movies/", "All movies")}
      <p class="section-note">Ranked by the number of IMDb ratings each film has received.</p>
    </div>
    <ol class="poster-rail" id="poster-rail">{rail}</ol>
  </section>
  <section class="wrap home-cta reveal" data-reveal>
    <p class="eyebrow">KEEP DIGGING</p>
    <h2>Pick a film and follow the music.</h2>
    <p class="lede">Every movie page lists its tracklist, credits and streaming availability.{(" Languages covered: " + e(languages) + ".") if languages else ""}</p>
    <div class="actions"><a class="btn primary" href="/movies/">Browse movies</a><a class="btn" href="/songs/">Browse songs</a><a class="btn" href="/charts/">See charts</a></div>
  </section>
</div>
"""
    return layout(cfg, site_url, title=cfg["name"], section="home", page="home",
                  desc=f'{cfg["tagline"]}. Explore {len(all_songs)} songs, {len(all_albums)} albums and {len(movies)} movies.',
                  path="/", body=body)


def page_intro(eyebrow, title, lede, meta=""):
    meta_html = f'<p class="intro-meta">{meta}</p>' if meta else ""
    return (f'<section class="page-intro wrap"><p class="eyebrow">{e(eyebrow)}</p><h1>{e(title)}</h1>'
            f'<p class="lede">{lede}</p>{meta_html}</section>')


def albums_page(cfg, site_url, movies):
    albums = sorted((album for movie in movies for album in movie["albums"]), key=album_total_plays, reverse=True)
    items = "".join(album_card(album, eager=i < 4, filterable=True) for i, album in enumerate(albums))
    total_plays = sum(album_total_plays(album) for album in albums)
    artists = sorted({artist for album in albums for artist in album["movie"]["music_directors"] if artist}, key=str.casefold)
    genres = sorted({genre for album in albums for genre in album["movie"]["genres"] if genre}, key=str.casefold)
    inner = f"""<div class="filter-bar" id="album-filters" aria-label="Filter albums">
    <label class="filter-search">Find an album<input id="album-query" type="search" placeholder="Album or film title" autocomplete="off"></label>
    <label>Sort by<select id="album-sort"><option value="plays">Most played</option><option value="release-new">Newest release</option><option value="release-old">Oldest release</option><option value="title-az">Title A–Z</option><option value="title-za">Title Z–A</option><option value="songs">Most songs</option></select></label>
    <label>Music director<select id="album-artist"><option value="">All music directors</option>{options_html(artists)}</select></label>
    <label>Movie genre<select id="album-genre"><option value="">All genres</option>{options_html(genres)}</select></label>
    <label>Film language<select id="album-lang"><option value="">All languages</option>{options_html(SEARCH_FACETS["languages"])}</select></label>
    {year_inputs("album", "Year")}
    <p class="filter-count" id="album-count" aria-live="polite">{len(albums)} albums</p>
  </div>"""
    body = f"""
{page_intro("SOUNDTRACK LIBRARY", "Albums", f"{len(albums)} soundtrack albums with full tracklists, credits and listening links.", f'{len(albums)} albums <span aria-hidden="true">·</span> {e(format_count(total_plays))} combined plays')}
<section class="wrap page-section">
  {filter_panel("album-filter-panel", "album-filter-summary-count", f"{len(albums)} albums", inner)}
  <ul class="albums-grid albums-grid-large" id="album-grid">{items}</ul>
  <p class="empty" id="album-empty" hidden>No albums match those filters. Try a different title, music director or year range.</p>
  <p class="data-note">Plays add each song's YouTube views and YouTube Music plays at the time of the last data capture. Release sorting uses the album release date and falls back to the film's release year.</p>
</section>
"""
    return layout(cfg, site_url, title="Telugu soundtrack albums", section="albums", page="albums",
                  desc="Browse Telugu soundtrack albums by plays, release date, title and music director.",
                  path="/albums/", body=body)


def movies_page(cfg, site_url, movies):
    # The default vote-count order is rendered into the HTML so it is right before JS loads.
    ordered = votes_ranked(movies)
    items = "".join(movie_card(movie, eager=i < 4, rank=i + 1) for i, movie in enumerate(ordered))
    genres = sorted({genre for movie in movies for genre in movie["genres"] if genre}, key=str.casefold)
    artists = sorted({a for movie in movies for a in movie["music_directors"] if a}, key=str.casefold)
    directors = sorted({a for movie in movies for a in movie["directors"] if a}, key=str.casefold)
    universes = sorted({m["cinematic_universe"] for m in movies if m["cinematic_universe"]}, key=str.casefold)
    total_votes = sum(int(m.get("imdb_votes_numeric") or 0) for m in movies)
    top = ordered[0] if ordered else None
    backdrop = img(top["backdrop"], "", "movies-hero-art", 1280, 720, eager=True) if top and top.get("backdrop") else ""
    spotlight = ""
    if top:
        spotlight = (f'<a class="spotlight" href="{e(movie_path(top))}"><span class="eyebrow">MOST RATED</span>'
                     f'<strong>{e(top["title"])}</strong><span>{e(format_count(top["imdb_votes_numeric"]))} IMDb ratings'
                     f'{(" · ★ " + e(top["imdb_score"])) if top.get("imdb_score") else ""}</span></a>')
    language_options = options_html(SEARCH_FACETS["languages"])
    inner = f"""<div class="filter-bar movie-filter-bar" id="movie-filters" aria-label="Filter movies">
    <label class="filter-search">Find a movie<input id="movie-query" type="search" placeholder="Title, actor or director" autocomplete="off"></label>
    <label>Sort by<select id="movie-sort"><option value="imdb-votes" selected>Most IMDb ratings</option><option value="rating">Highest IMDb score</option><option value="weighted">Best rated (score + ratings)</option><option value="release-new">Newest release</option><option value="release-old">Oldest release</option><option value="title-az">Title A–Z</option><option value="title-za">Title Z–A</option><option value="songs">Most songs</option></select></label>
    <label>Language<select id="movie-lang"><option value="">All languages</option>{language_options}</select></label>
    <label>Genre<select id="movie-genre"><option value="">All genres</option>{options_html(genres)}</select></label>
    <label>Music director<select id="movie-music"><option value="">All music directors</option>{options_html(artists)}</select></label>
    <label>Director<select id="movie-director"><option value="">All directors</option>{options_html(directors)}</select></label>
    {('<label>Franchise<select id="movie-universe"><option value="">Any</option>' + options_html(universes) + '</select></label>') if universes else ''}
    {year_inputs("movie", "Year")}
    <p class="filter-count" id="movie-count" aria-live="polite">{len(movies)} movies</p>
  </div>"""
    body = f"""
<section class="movies-hero">
  {backdrop}
  <div class="wrap movies-hero-inner">
    <div class="movies-hero-copy">
      <p class="eyebrow">FILMOGRAPHY</p>
      <h1>Movies</h1>
      <p class="lede">Every film with its soundtrack, credits and where to watch it. Sorted by the number of IMDb ratings by default.</p>
      <p class="intro-meta"><strong>{len(movies)}</strong> movies <span aria-hidden="true">·</span> <strong>{e(format_count(total_votes))}</strong> IMDb ratings in total</p>
    </div>
    {spotlight}
  </div>
</section>
<section class="wrap page-section">
  {filter_panel("movie-filter-panel", "movie-filter-summary-count", f"{len(movies)} movies", inner)}
  <ul class="movies-grid" id="movie-grid">{items}</ul>
  <p class="empty" id="movie-empty" hidden>No movies match those filters. Try changing the title, language, genre or year range.</p>
  <p class="data-note">"Best rated" uses the IMDb weighted-rating formula: it balances a film's score against how many people rated it, so a high score from very few votes does not jump the queue.</p>
</section>
"""
    return layout(cfg, site_url, title="Telugu movies", section="movies", page="movies",
                  desc="Browse Telugu films by IMDb ratings, language, genre, director and music director, and explore each movie soundtrack.",
                  path="/movies/", body=body)


def songs_page(cfg, site_url, movies):
    songs = [song for movie in movies for song in movie["songs"]]
    songs.sort(key=lambda song: song["plays_num"], reverse=True)
    artists = sorted({artist for song in songs for artist in song["artists"] if artist}, key=str.casefold)
    genres = sorted({genre for song in songs for genre in song["genres"] if genre}, key=str.casefold)
    lyricists = sorted({lyricist for song in songs for lyricist in song["lyricists"] if lyricist}, key=str.casefold)
    music_directors = sorted({artist for movie in movies for artist in movie["music_directors"] if artist}, key=str.casefold)
    genre_filter_markup = (f'<label>Track genre<select id="song-genre"><option value="">All track genres</option>{options_html(genres)}</select></label>' if genres else "")
    rows = "".join(song_row(song, rank=i + 1, show_movie=True, show_plays=True, filterable=True) for i, song in enumerate(songs))
    inner = f"""<div class="filter-bar song-filter-bar" id="song-filters" aria-label="Filter songs">
    <label class="filter-search">Search songs<input id="song-query" type="search" placeholder="Song, film, singer or lyricist" autocomplete="off"></label>
    <label>Sort by<select id="song-sort"><option value="plays">Most played</option><option value="release-new">Newest movie</option><option value="release-old">Oldest movie</option><option value="title-az">Title A–Z</option><option value="title-za">Title Z–A</option></select></label>
    <label>Singer<select id="song-artist"><option value="">All singers</option>{options_html(artists)}</select></label>
    <label>Lyricist<select id="song-lyricist"><option value="">All lyricists</option>{options_html(lyricists)}</select></label>
    <label>Music director<select id="song-music"><option value="">All music directors</option>{options_html(music_directors)}</select></label>
    <label>Film language<select id="song-lang"><option value="">All languages</option>{options_html(SEARCH_FACETS["languages"])}</select></label>
    {genre_filter_markup}
    {year_inputs("song", "Film year")}
    <p class="filter-count" id="song-count" aria-live="polite">{len(songs)} songs</p>
  </div>"""
    body = f"""
{page_intro("THE FULL TRACK LIBRARY", "Songs", "Every song in the archive. Open one to see its singers, lyricists, lyrics and listening links without leaving the list.", f"{len(songs)} songs across {len(movies)} movies")}
<section class="wrap page-section">
  {filter_panel("song-filter-panel", "song-filter-summary-count", f"{len(songs)} songs", inner)}
  <ol class="tracks chart-tracks" id="song-grid">{rows}</ol>
  <p class="empty" id="song-empty" hidden>No songs match those filters. Try a different singer, language or year range.</p>
</section>
"""
    return layout(cfg, site_url, title="Telugu songs library", section="songs", page="songs",
                  desc=f"Search and filter all {len(songs)} Telugu movie songs by singer, lyricist, music director, plays and film year.",
                  path="/songs/", body=body)


def advanced_search_page(cfg, site_url):
    body = f"""
{page_intro("SEARCH", "Search the archive", "Songs, albums and movies in one place. Narrow by type, year, language or genre.")}
<section class="wrap page-section advanced-search-page">
  <form id="advanced-search-form" class="advanced-search glass" role="search" action="/advanced-search/" method="get" data-search-root="page" data-search-target="advanced-results">
    <label class="sr" for="advanced-query">Search term</label>
    <div class="search-shell search-shell-lg">
      {icon("search", "search-glyph")}
      <input id="advanced-query" name="q" type="search" placeholder="Title, singer, director, genre or IMDb ID" autocomplete="off" autofocus data-search-input>
      <button type="submit" class="btn primary search-go">Search</button>
    </div>
    <div class="sp-controls">{search_controls(options_open=True)}</div>
  </form>
  <div class="advanced-results-head"><h2>Results</h2><p id="advanced-count" class="filter-count" aria-live="polite" data-search-count>Enter a term to search the archive.</p></div>
  <div id="advanced-results" class="advanced-results-grid" aria-live="polite" data-search-body></div>
  <p id="advanced-empty" class="empty" hidden>No matching records. Try a broader term, another type, or widen the year range.</p>
</section>
"""
    return layout(cfg, site_url, title="Search", section="", page="search",
                  desc="Search Telugu songs, albums and movies in Vāchika by type, year, language and genre.",
                  path="/advanced-search/", body=body)


def charts_page(cfg, site_url, movies):
    songs = sorted((s for movie in movies for s in movie["songs"]), key=lambda s: s["plays_num"], reverse=True)
    albums = sorted((album for movie in movies for album in movie["albums"]), key=album_total_plays, reverse=True)
    song_rows = "".join(song_row(song, rank=i + 1, show_plays=True) for i, song in enumerate(songs[:30]))
    album_rows = "".join(chart_entity_row(album, i + 1, "album") for i, album in enumerate(albums[:30]))
    movie_rows = "".join(chart_entity_row(movie, i + 1, "movie", "votes") for i, movie in enumerate(votes_ranked(movies)[:30]))
    weighted_rows = "".join(chart_entity_row(movie, i + 1, "movie", "weighted") for i, movie in enumerate(weighted_ranked(movies)[:30]))
    body = f"""
{page_intro("DATABASE RANKINGS", "Charts", "The most played songs and soundtrack albums, and the most rated films.", f'{len(songs)} songs · {len(albums)} albums · {len(movies)} movies <span>·</span> Snapshot-based, not live')}
<section class="wrap page-section charts-section">
  <div class="chart-tabs" role="tablist" aria-label="Chart type">
    <button class="chart-tab is-active" type="button" role="tab" aria-selected="true" data-chart-tab="songs">Songs</button>
    <button class="chart-tab" type="button" role="tab" aria-selected="false" data-chart-tab="albums">Albums</button>
    <button class="chart-tab" type="button" role="tab" aria-selected="false" data-chart-tab="movies">Movies</button>
  </div>
  <section class="chart-panel is-active" data-chart-panel="songs" role="tabpanel">
    {section_heading("TRACK LEADERS", "Most-played songs", "/songs/", "Browse all songs")}
    <ol class="tracks chart-tracks">{song_rows}</ol>
  </section>
  <section class="chart-panel" data-chart-panel="albums" role="tabpanel" hidden>
    {section_heading("SOUNDTRACK LEADERS", "Popular albums", "/albums/", "Browse all albums")}
    <ol class="tracks entity-chart-list">{album_rows}</ol>
  </section>
  <section class="chart-panel" data-chart-panel="movies" role="tabpanel" hidden>
    {section_heading("FILM LEADERS", "Popular movies", "/movies/", "Browse all movies")}
    <div class="chart-views" role="group" aria-label="Movie ranking">
      <button type="button" class="chip-button is-active" data-chart-view="votes" aria-pressed="true">Most IMDb ratings</button>
      <button type="button" class="chip-button" data-chart-view="weighted" aria-pressed="false">Best rated (score + ratings)</button>
    </div>
    <ol class="tracks entity-chart-list" data-chart-list="votes">{movie_rows}</ol>
    <ol class="tracks entity-chart-list" data-chart-list="weighted" hidden>{weighted_rows}</ol>
  </section>
  <p class="data-note">Songs and albums are ranked by YouTube views plus YouTube Music plays at the time the data was captured; a missing count adds zero. "Most IMDb ratings" ranks films by how many people rated them. "Best rated" weighs the IMDb score against that number, so one enthusiastic rating cannot beat a film with a hundred thousand.</p>
</section>
"""
    return layout(cfg, site_url, title="Telugu music charts", section="charts", page="charts",
                  desc="Charts for Telugu songs, soundtrack albums and the most-rated movies in the current database.",
                  path="/charts/", body=body)


def render_lyrics_section(song):
    """Render lyric text only when populated; keep LRC timestamp data per line."""
    lrc = song.get("lrc_lyrics")
    plain = song.get("plain_lyrics")
    if not lrc and not plain:
        return ""
    has_times = False
    line_count = 0
    if lrc:
        rendered = []
        timestamp_re = re.compile(r"\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\]")
        pending_gap = False
        for raw_line in lrc.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            timestamps = list(timestamp_re.finditer(line))
            text = timestamp_re.sub("", line).strip()
            # LRC metadata tags such as [ar:], [ti:], [by:] are parser directives, not lyrics.
            if re.fullmatch(r"\[[A-Za-z]+:.*\]", line) and not timestamps:
                continue
            if not text:
                # A timed empty line marks an instrumental gap between verses.
                pending_gap = bool(rendered)
                continue
            gap = " lyrics-gap" if pending_gap else ""
            pending_gap = False
            if timestamps:
                for match in timestamps:
                    minutes, seconds = int(match.group(1)), int(match.group(2))
                    fraction = (match.group(3) or "0")
                    centiseconds = int((fraction + "00")[:2])
                    total_seconds = minutes * 60 + seconds + centiseconds / 100
                    visible_time = f"{minutes}:{seconds:02d}"
                    rendered.append(
                        f'<li class="lyrics-line{gap}" data-time="{total_seconds:.2f}"><time class="lyrics-timestamp">{visible_time}</time><span class="lyrics-text">{e(text)}</span></li>'
                    )
                    line_count += 1
                    gap = ""
                has_times = True
            else:
                rendered.append(f'<li class="lyrics-line lyrics-line-untimed{gap}"><span class="lyrics-text">{e(text)}</span></li>')
                line_count += 1
        if not rendered:
            # Malformed LRC should still degrade to readable text without raw timestamps.
            cleaned = timestamp_re.sub("", lrc).strip()
            source = cleaned or plain or ""
            content = "".join(f'<p>{e(line)}</p>' for line in source.splitlines() if line.strip())
            if not content:
                return ""
            lyrics_markup = f'<div class="lyrics-plain">{content}</div>'
        else:
            lyrics_markup = '<ol class="lyrics-lines">' + "".join(rendered) + "</ol>"
    else:
        stanzas = [block for block in re.split(r"\n\s*\n", (plain or "").strip()) if block.strip()]
        content = ""
        for block in stanzas:
            lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
            line_count += len(lines)
            content += '<p class="stanza">' + "<br>".join(e(ln) for ln in lines) + "</p>"
        if not content:
            return ""
        lyrics_markup = f'<div class="lyrics-plain">{content}</div>'
    times_button = ('<button type="button" class="chip-button" data-lyrics-times aria-pressed="false">Timestamps</button>'
                    if has_times else "")
    count_html = f'<span class="lyrics-count">{line_count} lines</span>' if line_count else ""
    return (
        '<section class="card song-lyrics-section" aria-labelledby="song-lyrics-heading" data-lyrics>'
        '<div class="section-heading"><div><p class="eyebrow">LYRICS</p><h2 id="song-lyrics-heading">Lyrics</h2></div>'
        f'<div class="lyrics-tools">{count_html}{times_button}'
        f'<button type="button" class="chip-button" data-lyrics-toggle aria-expanded="true" aria-controls="lyrics-panel"><span data-label>Hide lyrics</span>{icon("chevron")}</button></div></div>'
        f'<div class="lyrics-panel" id="lyrics-panel">{lyrics_markup}</div>'
        '</section>'
    )


def song_page(cfg, site_url, song):
    m = song["movie"]
    album = song["album"]
    art = album_art(album, m)
    singers = song["artists"]
    lyricist_names = song["lyricists"]
    desc_bits = [f'{song["title"]} from {m["title"]} ({m["year"]}).']
    if singers:
        desc_bits.append("Sung by " + ", ".join(singers[:4]) + ".")
    if m["music_directors"]:
        desc_bits.append("Music by " + ", ".join(m["music_directors"][:3]) + ".")
    if lyricist_names:
        desc_bits.append("Lyrics by " + ", ".join(lyricist_names[:3]) + ".")
    if song.get("duration"):
        desc_bits.append(f'Duration {song["duration"]}.')

    others = "".join(song_row(other, current=(other["id"] == song["id"]), show_movie=False, show_plays=True)
                     for other in album["songs"] if other["id"] != song["id"])
    track_of = ""
    if song.get("number") is not None:
        track_of = f'{song["number"]} of {len(album["songs"])}'
    metadata_rows = [
        ("Singers" if len(singers) != 1 else "Singer", people(singers)),
        ("Lyricists" if len(lyricist_names) != 1 else "Lyricist", people(lyricist_names)),
        ("Music", people(m["music_directors"])),
        ("Film", f'<a href="{e(movie_path(m))}">{e(m["title"])}</a> ({e(m["year"])})'),
        ("Album", f'<a href="{e(album_path(album))}">{e(album["title"])}</a>' if album.get("album_id") else ""),
        ("Album release", e(fmt_date(album.get("released")))),
        ("Film language", e(m["original_language"] or "")),
        ("Duration", e(song["duration"])),
        ("Track", e(track_of)),
        ("Disc", e(song["disc_number"] if song.get("disc_number") not in (None, 1) else "")),
        ("Genre" if len(song["genres"]) == 1 else "Genres", e(", ".join(song["genres"]))),
        ("ISRC", e(song["isrc_code"] or "")),
    ]
    metadata_markup = facts(metadata_rows)
    flags = ""
    if song["explicit"] is True:
        flags += '<span class="flag">Explicit</span>'
    if song.get("instrumental"):
        flags += '<span class="flag">Instrumental</span>'
    if song.get("bonus_track") is True:
        flags += '<span class="flag">Bonus track</span>'

    about_rows = [
        ("Director", people(m["directors"])),
        ("Starring", people(m["cast"][:5])),
        ("Genres", e(", ".join(m["genres"]))),
        ("Runtime", e(fmt_runtime(m["runtime_minutes"]))),
        ("IMDb", (f'★ {e(m["imdb_score"])} · {e(votes_label(m))} ratings' if m.get("imdb_score") and votes_label(m) else e(m["imdb_score"] or ""))),
    ]
    poster = img(m["poster"], f'Poster of {m["title"]}', "film-card-poster", 500, 750)
    film_card = (
        '<section class="card song-film-context"><div class="film-card-head">' + poster +
        f'<div><p class="eyebrow">THE FILM</p><h2><a href="{e(movie_path(m))}">{e(m["title"])}</a></h2><p class="sub">{e(m["year"])}'
        + (f' · {e(m["original_language"])}' if m["original_language"] else "") + "</p></div></div>"
        + (f'<p class="plot">{e(m["plot"])}</p>' if m["plot"] else "")
        + facts(about_rows)
        + f'<p class="card-link"><a href="{e(movie_path(m))}">All songs and details {icon("arrow")}</a></p></section>')

    video_block = youtube_video_block(song)
    theme_art = art or m["backdrop"] or m["poster"]
    lyrics_block = render_lyrics_section(song)
    more_albums = "".join(
        f'<li><a href="{e(album_path(other_album))}">{e(other_album["title"])}</a></li>'
        for other_album in m["albums"] if other_album.get("album_id") != album.get("album_id"))
    other_albums_block = (f'<section class="card song-other-albums"><h2>Other albums from {e(m["title"])}</h2><ul>{more_albums}</ul></section>'
                          if more_albums else "")
    singer_line = f'<p class="song-singers">{people(singers)}</p>' if singers else ""
    body = f"""
<article class="song-page detail-art-theme" style="--artwork-url: url('{e(theme_art or "")}')">
  <div class="wrap">
    <section class="song-hero glass">
      {img(art, ("Artwork for " + album["title"]) if album.get("artwork") or album.get("artwork_small") else ("Movie poster for " + m["title"]), "art", 640, 640, eager=True)}
      <div class="song-main">
        <p class="eyebrow">SONG</p>
        <h1>{e(song["title"])}</h1>
        <p class="from">From <a href="{e(movie_path(m))}">{e(m["title"])}</a> · {e(m["year"])}{flags}</p>
        {singer_line}
        {listen_links(song)}
        <div class="actions">{player(song)}<button type="button" class="btn" data-copy-link>{icon("link")}<span>Copy link</span></button><a class="btn" href="{e(album_path(album))}">{icon("note")}<span>Album</span></a></div>
      </div>
    </section>
    <div class="song-layout">
      <div class="song-col-main">
        {lyrics_block}
        {video_block}
        <section class="card song-tracklist">
          {section_heading("ALBUM TRACKLIST", "More from " + album["title"], album_path(album), "Album page")}
          {f'<ol class="tracks">{others}</ol>' if others else '<p class="section-note">This is the only track currently listed for this album.</p>'}
        </section>
      </div>
      <aside class="song-col-side">
        <section class="card song-metadata-section">
          <div class="section-heading"><div><p class="eyebrow">TRACK INFORMATION</p><h2>Details</h2></div></div>
          {metadata_markup}
        </section>
        {film_card}
        {other_albums_block}
      </aside>
    </div>
  </div>
</article>
"""
    duration_schema = None
    if song.get("duration_sec") is not None and song["duration_sec"] >= 0:
        duration_schema = f'PT{song["duration_sec"] // 60}M{song["duration_sec"] % 60}S'
    ld = {
        "@context": "https://schema.org", "@type": "MusicRecording", "name": song["title"],
        "duration": duration_schema, "isrcCode": song["isrc_code"],
        "inAlbum": {"@type": "MusicAlbum", "name": album["title"], "url": (site_url + album_path(album)) if site_url else None},
        "byArtist": [{"@type": "Person", "name": name} for name in singers],
        "lyricist": [{"@type": "Person", "name": name} for name in lyricist_names],
        "url": site_url + f"/song/{song['id']}/" if site_url else None,
    }
    ld = {key: value for key, value in ld.items() if value}
    return layout(cfg, site_url, title=f'{song["title"]} ({m["title"]}, {m["year"]})', desc=" ".join(desc_bits),
                  path=f"/song/{song['id']}/", body=body, og_type="music.song", og_image=art, jsonld=ld,
                  section="songs", page="song")


def album_page(cfg, site_url, album):
    movie = album["movie"]
    art = album_art(album, movie)
    total = album_total_plays(album)
    tracks = album["songs"]
    rows = "".join(song_row(song, rank=i + 1, show_plays=True, show_movie=False) for i, song in enumerate(tracks))
    artists = ", ".join(movie["music_directors"])
    links = []
    if album.get("spotify_url"):
        links.append(f'<a class="btn provider-btn spotify-btn" href="{e(album["spotify_url"])}" rel="noopener noreferrer" target="_blank">{provider_icon("spotify")}<span>Spotify</span></a>')
    if album.get("ytm_url"):
        links.append(f'<a class="btn provider-btn youtube-btn" href="{e(album["ytm_url"])}" rel="noopener noreferrer" target="_blank">{provider_icon("ytmusic")}<span>YouTube Music</span></a>')
    actual_cover = bool(album.get("artwork") or album.get("artwork_small"))
    alt = f'Album artwork for {album["title"]}' if actual_cover else f'Movie poster for {movie["title"]}; album artwork unavailable'
    cover = img(art, alt, "album-detail-art", 640, 640, eager=True) if art else f'<div class="album-detail-art album-cover-empty" aria-hidden="true">{icon("note")}</div>'
    release = album.get("released")
    detail_rows = [
        ("Release date", e(fmt_date(release))),
        ("Film", f'<a href="{e(movie_path(movie))}">{e(movie["title"])}</a> ({e(movie["year"])})'),
        ("Music", people(movie["music_directors"])),
        ("Record label", e(album.get("label") or "")),
        ("Copyright", e(" · ".join([x for x in (album.get("copyright_c"), album.get("copyright_p")) if x]))),
        ("Barcode (UPC)", e(album.get("upc") or "")),
    ]
    details_markup = facts(detail_rows)
    stats = [f'{len(tracks)} {"song" if len(tracks) == 1 else "songs"}']
    if total:
        stats.append(f'{format_count(total)} plays')
    if release:
        stats.append(f'Released {fmt_date(release)}')
    body = f"""
<article class="album-detail-page detail-art-theme" style="--artwork-url: url('{e(art or "")}')">
  <div class="wrap">
    <section class="album-detail-hero glass">
      {cover}
      <div class="album-detail-copy">
        <p class="eyebrow">SOUNDTRACK ALBUM</p>
        <h1>{e(album["title"])}</h1>
        {f'<p class="album-telugu" lang="te">{e(movie["telugu"])}</p>' if movie["telugu"] else ''}
        <p class="album-byline"><a href="{e(movie_path(movie))}">{e(movie["title"])}</a> · {e(artists or "Telugu film soundtrack")} · {e(movie["year"])}</p>
        <p class="album-stats">{" <span>·</span> ".join(e(s) for s in stats)}</p>
        <div class="actions">{"".join(links)}<a class="btn" href="{e(movie_path(movie))}">Movie details</a></div>
      </div>
    </section>
    <div class="album-layout">
      <section class="card album-track-section">
        {section_heading("FULL TRACKLIST", "Songs in this album")}
        {f'<ol class="tracks chart-tracks">{rows}</ol>' if rows else '<p class="empty">No tracks are currently linked to this album in the database.</p>'}
        <p class="data-note">Plays add YouTube views and YouTube Music plays from the last data capture.</p>
      </section>
      {f'<aside class="card album-release-details"><h2>Release details</h2>{details_markup}</aside>' if details_markup else ''}
    </div>
  </div>
</article>
"""
    desc = f'{album["title"]} soundtrack album for {movie["title"]} ({movie["year"]}) with {len(tracks)} songs, credits and listening links.'
    return layout(cfg, site_url, title=f'{album["title"]} · {movie["title"]} soundtrack album', desc=desc,
                  path=album_path(album), body=body, og_type="music.album", og_image=art, section="albums", page="album")


def movie_page(cfg, site_url, m):
    rows = "".join(song_row(song, show_movie=False, show_plays=True) for song in m["songs"])
    songs_block = (f'<section class="card"><h2>Songs</h2><ol class="tracks">{rows}</ol></section>' if m["songs"]
                   else '<section class="card"><h2>Songs</h2><p class="section-note">No songs are currently linked to this movie.</p></section>')
    albums_block = ""
    if m["albums"]:
        cards = "".join(album_card(album, eager=i < 2) for i, album in enumerate(m["albums"]))
        albums_block = (f'<section class="movie-albums-section">{section_heading("SOUNDTRACKS", "Albums for " + m["title"])}'
                        f'<ul class="albums-grid">{cards}</ul></section>')

    trailer = ""
    if m["trailer"] and re.fullmatch(r"[A-Za-z0-9_-]{6,20}", m["trailer"]):
        thumb = f'https://i.ytimg.com/vi/{e(m["trailer"])}/hqdefault.jpg'
        trailer = ('<section class="card"><h2>Trailer</h2>'
            f'<div class="trailer"><button type="button" data-embed="youtube" data-id="{e(m["trailer"])}" aria-label="Play the trailer for {e(m["title"])}">'
            f'<img src="{thumb}" alt="" width="480" height="360" loading="lazy" decoding="async" referrerpolicy="no-referrer">'
            f'<span class="play">{icon("play")}<span>Play trailer</span></span></button></div></section>')

    details_rows = [
        ("Directed by", people(m["directors"])),
        ("Music by", people(m["music_directors"])),
        ("Starring", people(m["cast"][:8])),
        ("Cinematography", people(m["cinematographers"])),
        ("Production", e(", ".join(m["production_banners"]))),
        ("Genres", e(", ".join(m["genres"]))),
        ("Original language", e(m["original_language"] or "")),
        ("Franchise", e(m["cinematic_universe"] or "")),
        ("Certification", e(m["certification"] or "")),
        ("Runtime", e(fmt_runtime(m["runtime_minutes"]))),
        ("Release year", e(m["year"])),
        ("IMDb rating", e(m["imdb_score"] or "")),
        ("IMDb ratings", e(f'{int(m["imdb_votes_numeric"]):,}' if m.get("imdb_votes_numeric") else "")),
    ]
    details_rows.extend((entry["label"], people(entry["names"])) for entry in m.get("additional_people", []))
    details = facts(details_rows)
    telugu = f'<p class="te" lang="te">{e(m["telugu"])}</p>' if m["telugu"] else ""
    primary_art = album_art(m.get("album"), m)
    theme_art = m["backdrop"] or m["poster"] or primary_art
    ott = ott_buttons(m)
    chips = []
    if m.get("imdb_score"):
        votes = f' <small>{e(votes_label(m))} ratings</small>' if votes_label(m) else ""
        chips.append(f'<span class="chip chip-rating">{icon("star")}<strong>{e(m["imdb_score"])}</strong>{votes}</span>')
    for value in (m["year"], m["certification"], fmt_runtime(m["runtime_minutes"]), m["original_language"]):
        if value:
            chips.append(f'<span class="chip">{e(value)}</span>')
    genre_chips = "".join(f'<span class="chip chip-soft">{e(g)}</span>' for g in m["genres"])
    if m["cinematic_universe"]:
        genre_chips += f'<span class="chip chip-soft">{e(m["cinematic_universe"])}</span>'
    title_block = (f'<h1 class="movie-title"><span class="sr">{e(m["title"])}</span>'
                   f'{img(m["title_logo"], m["title"], "movie-title-logo", 600, 220, eager=True)}</h1>'
                   if m["title_logo"] else f'<h1 class="movie-title">{e(m["title"])}</h1>')
    body = f"""
<article class="movie-page detail-art-theme" style="--artwork-url: url('{e(theme_art or "")}')">
  <section class="movie-hero">
    {img(m["backdrop"], "", "backdrop", 1280, 720, eager=True)}
    <div class="wrap movie-head">
      {img(m["poster"], "Poster of " + m["title"], "poster", 500, 750, eager=True)}
      <div class="movie-main-copy">
        <p class="eyebrow movie-imdb-id">IMDb · {e(m["imdb_id"])}</p>
        {title_block}
        {f'<p class="movie-title-text">{e(m["title"])}</p>' if m["title_logo"] else ''}
        {telugu}
        <div class="chip-row">{"".join(chips)}</div>
        <div class="chip-row">{genre_chips}</div>
        {f'<p class="plot">{e(m["plot"])}</p>' if m["plot"] else ''}
        <div class="actions">{f'<a class="btn primary" href="{e(album_path(m["albums"][0]))}">Explore soundtrack</a>' if m["albums"] else ''}{movie_links_dropdown(m)}</div>
      </div>
    </div>
  </section>
  <div class="wrap movie-body">
    {f'<section class="ott-section"><div class="section-heading"><div><p class="eyebrow">WHERE TO WATCH</p><h2>Streaming availability</h2></div></div><p class="section-note">From the database snapshot. Each button opens a search on that service.</p><div class="ott-provider-grid">{ott}</div></section>' if ott else ''}
    {albums_block}
    <div class="movie-columns">
      <div>{songs_block}</div>
      <div><section class="card"><h2>Movie details</h2>{details}</section>{trailer}</div>
    </div>
  </div>
</article>
"""
    names = ", ".join(m["music_directors"][:2])
    desc = f'{m["title"]} ({m["year"]}): {len(m["songs"])} songs across {len(m["albums"])} albums' + (f", music by {names}" if names else "") + ". Tracklist, film credits, streaming availability and soundtrack links."
    rating = None
    rating_value = m.get("imdb_rating_numeric")
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
                  body=body, og_type="video.movie", og_image=m["backdrop"] or m["poster"], jsonld=ld,
                  section="movies", page="movie")


def not_found_page(cfg, site_url):
    body = """
<section class="wrap page-intro">
  <p class="eyebrow">404</p>
  <h1>That page isn't here</h1>
  <p class="lede">The link may be old or mistyped. Search for the song or film instead.</p>
  <p><a class="btn primary" href="/">Back to the archive</a></p>
</section>
"""
    return layout(cfg, site_url, title="Page not found", desc="Page not found.", path="/404.html", body=body, noindex=True, page="404")


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
            "albumRelease": song["album"].get("released"),
            "artists": song["artists"], "lyricists": song["lyricists"],
            "musicDirectors": song["movie"]["music_directors"], "plays": song["plays"],
            "playsNum": song["plays_num"], "duration": song["duration"],
            "durationSec": song["duration_sec"], "number": song["number"],
            "discNumber": song["disc_number"], "songCount": len(song["album"]["songs"]),
            "artwork": album_art(song["album"], song["movie"]), "poster": song["movie"]["poster"],
            "genres": song["genres"], "movieGenres": song["movie"]["genres"],
            "language": song["movie"]["original_language"],
            "imdbId": song["movie"]["imdb_id"],
            "release": song["movie"]["released"] or (song["movie"]["year"] + "-01-01"),
            "spotifyId": song["spotify_id"], "ytmId": song["ytm_id"],
            "spotifyUrl": song["spotify_url"], "ytmUrl": song["ytm_url"],
            "ytmPlays": song["ytm_views"],
            "youtubeVideoUrl": song["youtube_url"], "youtubeVideoId": song["youtube_video_id"],
            "youtubeVideoTitle": song["youtube_video_title"], "youtubeVideoViews": song["youtube_video_views"],
            "isrc": song["isrc_code"], "explicit": song["explicit"] is True,
            "instrumental": bool(song.get("instrumental")),
            "hasLyrics": bool(song.get("lrc_lyrics") or song.get("plain_lyrics")),
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
            "imdbScore": movie["imdb_score"], "imdbVotes": movie["imdb_votes"],
            "imdbVotesNumeric": int(movie.get("imdb_votes_numeric") or 0),
            "imdbWeighted": movie.get("imdb_weighted"),
            "universe": movie["cinematic_universe"],
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
            "language": album["movie"]["original_language"],
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
    SEARCH_FACETS["languages"] = sorted({m["original_language"] for m in movies if m["original_language"]}, key=str.casefold)
    SEARCH_FACETS["genres"] = sorted({g for m in movies for g in m["genres"] if g}, key=str.casefold)
    songs = [song for movie in movies for song in movie["songs"]]
    albums = [album for movie in movies for album in movie["albums"]]
    search_index_text = json.dumps(build_search_index(movies), ensure_ascii=False, separators=(",", ":"))
    SEARCH_INDEX_VERSION = hashlib.sha256(search_index_text.encode("utf-8")).hexdigest()[:12]
    app_source = (STATIC / "app.js").read_text(encoding="utf-8")
    app_built = app_source.replace("__SEARCH_INDEX_VERSION__", SEARCH_INDEX_VERSION)
    if "__SEARCH_INDEX_VERSION__" in app_built:
        raise SystemExit("unresolved search-index cache-version placeholder in static/app.js")
    css_source = (STATIC / "style.css").read_bytes()
    theme_source = (STATIC / "theme.js").read_bytes()
    ASSET_VERSION = hashlib.sha256(app_built.encode("utf-8") + css_source + theme_source).hexdigest()[:12]

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

    # Maintain the most useful legacy routes within Cloudflare Pages' static
    # redirect budget (2,000 rules). The IMDb-nested album aliases are retired.
    redirect_rules: set = set()
    for movie in movies:
        canonical_movie = movie_path(movie)
        canonical_album = album_path(movie)
        if canonical_movie.startswith("/tt"):
            legacy_movie = f'/movie/{movie["slug"]}/'
            if legacy_movie != canonical_movie:
                redirect_rules.add(f"{legacy_movie} {canonical_movie} 301")
            if movie["albums"]:
                legacy_album = f'/album/{movie["slug"]}/'
                if legacy_album != canonical_album:
                    redirect_rules.add(f"{legacy_album} {canonical_album} 301")

    legacy_id_targets: dict = {}
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

    redirect_budget = 1950
    if len(redirect_rules) > redirect_budget:
        raise SystemExit(
            f"Generated {len(redirect_rules)} required legacy redirect rules, above the safe "
            f"budget of {redirect_budget}. Cloudflare Pages allows 2,000 static _redirects rules; "
            "move the overflow to Cloudflare Bulk Redirects or a Pages Function before publishing."
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
