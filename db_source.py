#!/usr/bin/env python3
"""Read the normalized VachikaTelugu SQLite catalogue, read-only.

The website is built from relational tables and explicit scalar columns. No
source JSON blob or JSON-valued database column is used as catalogue content.
Raw snapshots, serialized arrays, provenance and source-status payloads are not
read by this module.
"""
from __future__ import annotations

import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / ".build-data" / "vachikatelugu.db"
LOCAL_DB = ROOT / "vachikatelugu.db"
SUPPORTED_SCHEMA_VERSION = "4"

REQUIRED_TABLES = {
    "schema_metadata", "movies", "albums", "songs", "artists", "lyricists",
    "song_artists", "song_lyricists", "song_media", "movie_people",
    "movie_genres", "song_genres", "movie_links", "ott_availability",
    "source_album_matches",
}


def database_path() -> Path | None:
    """Return the configured/local database path, without copying or modifying it."""
    configured = os.environ.get("DATABASE_PATH")
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            path = ROOT / path
        if not path.is_file():
            raise RuntimeError(f"DATABASE_PATH is set but the file does not exist: {path}")
        return path
    if DEFAULT_DB.is_file():
        return DEFAULT_DB
    if LOCAL_DB.is_file():
        return LOCAL_DB
    return None


def _read_only_connection(path: Path) -> sqlite3.Connection:
    # mode=ro prevents website build scripts from changing the source database.
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def _nonempty(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.casefold() in {"n/a", "na", "not available", "not provided", "not specified", "unknown", "null", "none", "undefined"}:
        return None
    return text


def _valid_external_id(value: Any) -> str | None:
    """Accept provider identifiers, never arbitrary URL/HTML fragments."""
    text = _nonempty(value)
    return text if text and re.fullmatch(r"[A-Za-z0-9_-]{1,160}", text) else None


def _valid_http_url(value: Any) -> str | None:
    """Accept only ordinary HTTP(S) URLs safe to place in links/image sources."""
    text = _nonempty(value)
    if not text or any(ch in text for ch in "\r\n\t\\\"'"):
        return None
    try:
        parsed = urlsplit(text)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return None
        # Do not allow embedded credentials in URLs that may be rendered publicly.
        if parsed.username is not None or parsed.password is not None:
            return None
        # Accessing .port catches malformed authority/port strings.
        _ = parsed.port
    except ValueError:
        return None
    return text


def load_database_catalogue() -> dict[str, Any]:
    """Load a normalized, relational catalogue from the SQLite database.

    Returns movies, albums and songs with relationship values attached. All
    source content comes from ordinary columns and normalized junction tables.
    No JSON-valued column, raw snapshot, provenance blob or status payload is
    used to construct public pages. The generated search-index.json is a
    separately reviewed derivative of this normalized catalogue.
    """
    db = database_path()
    if db is None:
        raise RuntimeError(
            "No SQLite database found. Run fetch_database.py or set DATABASE_PATH; "
            "the website requires the private SQLite catalogue and has no JSON fallback."
        )
    connection = _read_only_connection(db)
    try:
        connection.row_factory = sqlite3.Row
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        missing = sorted(REQUIRED_TABLES - tables)
        if missing:
            raise RuntimeError("SQLite database is missing required table(s): " + ", ".join(missing))

        schema_row = connection.execute(
            "SELECT value FROM schema_metadata WHERE key = 'schema_version'"
        ).fetchone()
        schema_version = str(schema_row[0]) if schema_row else ""
        if schema_version != SUPPORTED_SCHEMA_VERSION:
            raise RuntimeError(
                f"Unsupported database schema version {schema_version or '(missing)'}; "
                f"this website adapter supports version {SUPPORTED_SCHEMA_VERSION}."
            )

        # Movies: no raw_json, source_metadata_json or source_status_json selected.
        movie_rows = connection.execute("""
            SELECT imdb_id, title, title_telugu, release_year, original_language,
                   cinematic_universe, imdb_score, imdb_votes, imdb_votes_numeric,
                   tmdb_url, imdb_url, wikipedia_url, wikipedia_soundtrack_url,
                   plot_summary, certification, runtime_minutes, poster_url,
                   backdrop_url, title_logo_url, trailer_youtube_id, total_songs,
                   processing_status
            FROM movies
            WHERE processing_status = 'processed'
            ORDER BY release_year, title, imdb_id
        """).fetchall()
        if not movie_rows:
            raise RuntimeError("SQLite database contains no processed movie records")

        movies: list[dict[str, Any]] = []
        movie_by_id: dict[str, dict[str, Any]] = {}
        for row in movie_rows:
            item = dict(row)
            movie_id = _nonempty(item.get("imdb_id"))
            movie_title = _nonempty(item.get("title"))
            if not movie_id or not movie_title:
                raise RuntimeError("A processed movie row has an empty imdb_id or title")
            item["imdb_id"] = movie_id
            item["title"] = movie_title
            for image_field in ("poster_url", "backdrop_url", "title_logo_url"):
                item[image_field] = _valid_http_url(item.get(image_field))
            item["tmdb_url"] = _valid_http_url(item.get("tmdb_url"))
            item["imdb_url"] = _valid_http_url(item.get("imdb_url"))
            item["wikipedia_url"] = _valid_http_url(item.get("wikipedia_url"))
            item["wikipedia_soundtrack_url"] = _valid_http_url(item.get("wikipedia_soundtrack_url"))
            item["trailer_youtube_id"] = _valid_external_id(item.get("trailer_youtube_id"))
            item["genres"] = []
            # Preserve every normalized movie_people role, not only the roles
            # currently represented in the design. The renderer curates known
            # roles and can show additional public credit roles separately.
            item["people"] = {}
            item["links"] = {}
            item["ott_availability"] = []
            item["albums"] = []
            item["songs"] = []
            movie_by_id[item["imdb_id"]] = item
            movies.append(item)

        for row in connection.execute("""
            SELECT movie_id, genre FROM movie_genres
            ORDER BY movie_id, genre_order, genre COLLATE NOCASE
        """):
            if row[0] in movie_by_id and _nonempty(row[1]):
                movie_by_id[row[0]]["genres"].append(str(row[1]).strip())

        for row in connection.execute("""
            SELECT movie_id, role, person_name FROM movie_people
            ORDER BY movie_id, credit_order, person_name COLLATE NOCASE
        """):
            movie_id, role, name = row
            role_key = str(role or "").strip().lower().replace("-", "_").replace(" ", "_")
            person_name = _nonempty(name)
            if movie_id in movie_by_id and role_key and person_name:
                movie_by_id[movie_id]["people"].setdefault(role_key, []).append(person_name)

        for row in connection.execute("""
            SELECT movie_id, link_type, url FROM movie_links
            ORDER BY movie_id, link_type
        """):
            movie_id, link_type, url = row
            if movie_id not in movie_by_id:
                continue
            value = _valid_http_url(url)
            if value:
                movie_by_id[movie_id]["links"][str(link_type).strip().lower()] = value

        for row in connection.execute("""
            SELECT movie_id, provider, availability_type FROM ott_availability
            ORDER BY movie_id, provider COLLATE NOCASE, availability_type
        """):
            movie_id, provider, kind = row
            if movie_id in movie_by_id and _nonempty(provider) and _nonempty(kind):
                movie_by_id[movie_id]["ott_availability"].append({
                    "provider": str(provider).strip(), "type": str(kind).strip().lower()
                })

        # Album rows are first-class entities. One movie may own multiple albums.
        album_rows = connection.execute("""
            SELECT album_id, movie_id, title, release_date, label, upc_barcode,
                   spotify_popularity, artwork_hd_640, artwork_300, copyright_c,
                   copyright_p, spotify_album_id, youtube_album_id,
                   spotify_album_title, youtube_album_title, spotify_total_tracks,
                   spotify_saved_to_library, spotify_url,
                   youtube_music_url, total_tracks
            FROM albums
            ORDER BY movie_id, title COLLATE NOCASE, album_id
        """).fetchall()
        albums: list[dict[str, Any]] = []
        album_by_id: dict[str, dict[str, Any]] = {}
        for row in album_rows:
            source = dict(row)
            movie = movie_by_id.get(source["movie_id"])
            if movie is None:
                continue  # Album belongs to a movie excluded from the public processed catalogue.
            if not _nonempty(source.get("album_id")):
                raise RuntimeError(f"Album for movie {source['movie_id']} has no album_id")
            # Only the dedicated scalar artwork columns are used. If these are
            # absent, the site may show the movie poster with a clear fallback
            # alt text; it does not mine serialized provider JSON for artwork.
            item = {
                "album_id": _nonempty(source.get("album_id")),
                "movie_id": source["movie_id"], "title": _nonempty(source.get("title")),
                "release_date": _nonempty(source.get("release_date")),
                "label": _nonempty(source.get("label")),
                "upc_barcode": _nonempty(source.get("upc_barcode")),
                "spotify_popularity": source.get("spotify_popularity"),
                "artwork_hd_640": _valid_http_url(source.get("artwork_hd_640")),
                "artwork_300": _valid_http_url(source.get("artwork_300")),
                "copyright_c": _nonempty(source.get("copyright_c")),
                "copyright_p": _nonempty(source.get("copyright_p")),
                "spotify_album_id": _nonempty(source.get("spotify_album_id")),
                "youtube_album_id": _nonempty(source.get("youtube_album_id")),
                "spotify_album_title": _nonempty(source.get("spotify_album_title")),
                "youtube_album_title": _nonempty(source.get("youtube_album_title")),
                "spotify_total_tracks": source.get("spotify_total_tracks"),
                "spotify_saved_to_library": source.get("spotify_saved_to_library"),
                "spotify_url": _valid_http_url(source.get("spotify_url")),
                "youtube_music_url": _valid_http_url(source.get("youtube_music_url")),
                "declared_total_tracks": source.get("total_tracks") or 0,
                "songs": [],
            }
            item["spotify_url"] = item["spotify_url"] or (
                f"https://open.spotify.com/album/{item['spotify_album_id']}" if item["spotify_album_id"] else None
            )
            item["youtube_music_url"] = item["youtube_music_url"] or (
                f"https://music.youtube.com/browse/{item['youtube_album_id']}" if item["youtube_album_id"] else None
            )
            album_by_id[item["album_id"]] = item
            movie["albums"].append(item)
            albums.append(item)

        # Relationship tables are the authoritative song-credit source.
        artists_by_song: dict[str, list[dict[str, Any]]] = {}
        artist_rows = connection.execute("""
            SELECT sa.song_id, sa.credit_order, sa.credit_role, a.artist_id, a.artist_name
            FROM song_artists sa JOIN artists a ON a.artist_id = sa.artist_id
            ORDER BY sa.song_id, sa.credit_order, a.artist_name COLLATE NOCASE
        """).fetchall()
        for row in artist_rows:
            artist_name = _nonempty(row["artist_name"])
            if artist_name:
                artists_by_song.setdefault(row["song_id"], []).append({
                    "artist_id": row["artist_id"], "name": artist_name,
                    "role": _nonempty(row["credit_role"]) or "artist", "order": row["credit_order"],
                })

        lyricists_by_song: dict[str, list[dict[str, Any]]] = {}
        lyricist_rows = connection.execute("""
            SELECT sl.song_id, sl.credit_order, l.lyricist_id, l.lyricist_name
            FROM song_lyricists sl JOIN lyricists l ON l.lyricist_id = sl.lyricist_id
            ORDER BY sl.song_id, sl.credit_order, l.lyricist_name COLLATE NOCASE
        """).fetchall()
        for row in lyricist_rows:
            lyricist_name = _nonempty(row["lyricist_name"])
            if lyricist_name:
                lyricists_by_song.setdefault(row["song_id"], []).append({
                    "lyricist_id": row["lyricist_id"], "name": lyricist_name,
                    "order": row["credit_order"],
                })

        media_by_song: dict[str, dict[str, dict[str, Any]]] = {}
        media_rows = connection.execute("""
            SELECT song_id, platform, external_id, url, preview_url, views_text,
                   popularity, video_title
            FROM song_media ORDER BY song_id, platform
        """).fetchall()
        for row in media_rows:
            song_id = row["song_id"]
            platform = str(row["platform"] or "").strip().lower().replace("-", "_").replace(" ", "_")
            if not platform:
                continue
            media = {
                "platform": platform, "external_id": _valid_external_id(row["external_id"]),
                "url": _valid_http_url(row["url"]), "preview_url": _valid_http_url(row["preview_url"]),
                "views_text": _nonempty(row["views_text"]), "popularity": row["popularity"],
                "video_title": _nonempty(row["video_title"]),
            }
            media_by_song.setdefault(song_id, {})[platform] = media

        song_genres: dict[str, list[str]] = {}
        for row in connection.execute("""
            SELECT song_id, genre FROM song_genres
            ORDER BY song_id, genre_order, genre COLLATE NOCASE
        """):
            if _nonempty(row[1]):
                song_genres.setdefault(row[0], []).append(str(row[1]).strip())

        song_rows = connection.execute("""
            SELECT s.song_id, s.album_id, s.movie_id, s.track_number, s.title, s.lyricist,
                   s.song_flavor, s.lrc_lyrics, s.plain_lyrics, s.lrclib_id, s.lyrics_status,
                   s.lyrics_type, s.data_source, s.is_bonus_track, s.duration_formatted,
                   s.duration_ms, s.duration_sec, s.spotify_uri, s.track_number_original,
                   s.disc_number, s.is_explicit, s.isrc_code
            FROM songs s JOIN movies m ON m.imdb_id=s.movie_id
            WHERE m.processing_status='processed'
            ORDER BY s.movie_id, s.album_id, COALESCE(s.disc_number, 1),
                     COALESCE(s.track_number, 2147483647), s.title COLLATE NOCASE, s.song_id
        """).fetchall()
        songs: list[dict[str, Any]] = []
        for row in song_rows:
            song = dict(row)
            movie = movie_by_id.get(song["movie_id"])
            album = album_by_id.get(song["album_id"])
            # Never silently drop a processed song: bad relational links must fail
            # loudly before a partial catalogue can be published.
            if movie is None or album is None:
                raise RuntimeError(f"Song {song.get('song_id')!r} has no processed movie or album")
            if album.get("movie_id") != song.get("movie_id"):
                raise RuntimeError(f"Song {song.get('song_id')!r} and its album belong to different movies")
            if not _valid_external_id(song.get("song_id")):
                raise RuntimeError("A processed song has an empty or URL-unsafe song_id")
            if not _nonempty(song.get("title")):
                raise RuntimeError(f"Song {song.get('song_id')!r} has no title")
            item = {
                "song_id": _nonempty(song.get("song_id")),
                "album_id": song["album_id"], "movie_id": song["movie_id"],
                "track_number": song.get("track_number"), "title": _nonempty(song.get("title")),
                "lyricist_legacy": _nonempty(song.get("lyricist")),
                "song_flavor": _nonempty(song.get("song_flavor")),
                "lrc_lyrics": _nonempty(song.get("lrc_lyrics")),
                "plain_lyrics": _nonempty(song.get("plain_lyrics")),
                "lrclib_id": _nonempty(song.get("lrclib_id")),
                "lyrics_status": _nonempty(song.get("lyrics_status")),
                "lyrics_type": _nonempty(song.get("lyrics_type")),
                "data_source": _nonempty(song.get("data_source")),
                "is_bonus_track": song.get("is_bonus_track"),
                "duration_formatted": _nonempty(song.get("duration_formatted")),
                "duration_ms": song.get("duration_ms"), "duration_sec": song.get("duration_sec"),
                "spotify_uri": _nonempty(song.get("spotify_uri")),
                "track_number_original": song.get("track_number_original"),
                "disc_number": song.get("disc_number"), "is_explicit": song.get("is_explicit"),
                "isrc_code": _nonempty(song.get("isrc_code")),
                "genres": song_genres.get(song["song_id"], []),
                "artist_credits": artists_by_song.get(song["song_id"], []),
                "lyricist_credits": lyricists_by_song.get(song["song_id"], []),
                "media": media_by_song.get(song["song_id"], {}),
                "movie": movie, "album": album,
            }
            # Preserve a usable legacy lyricist column if the normalized junction
            # has not yet been populated for that song. It remains DB-column data.
            if not item["lyricist_credits"] and item["lyricist_legacy"]:
                item["lyricist_credits"] = [
                    {"lyricist_id": None, "name": part.strip(), "order": position}
                    for position, part in enumerate(item["lyricist_legacy"].split(","))
                    if part.strip()
                ]
            album["songs"].append(item)
            movie["songs"].append(item)
            songs.append(item)

        # Stable, predictable ordering, with every DB song retained regardless of media.
        for movie in movies:
            movie["songs"].sort(key=lambda s: (
                s.get("disc_number") or 1,
                s.get("track_number") if s.get("track_number") is not None else 2147483647,
                s["title"].casefold(), s["song_id"]
            ))
            movie["albums"].sort(key=lambda a: (
                -len(a["songs"]), (a.get("title") or "").casefold(), a["album_id"]
            ))
        for album in albums:
            album["songs"].sort(key=lambda s: (
                s.get("disc_number") or 1,
                s.get("track_number") if s.get("track_number") is not None else 2147483647,
                s["title"].casefold(), s["song_id"]
            ))

        # Report content counts only; never log row payloads or private metadata.
        print(
            f"data source: normalized SQLite ({db.name}); schema {schema_version}; "
            f"loaded {len(movies)} movies, {len(albums)} albums, {len(songs)} songs"
        )
        return {
            "schema_version": schema_version, "database_name": db.name,
            "movies": movies, "albums": albums, "songs": songs,
        }
    finally:
        connection.close()


# Backward-compatible function name for scripts within older deployments; this
# returns a normalized catalogue object, not decoded raw JSON records.
def load_records(_ignored_legacy_json_path: str | Path | None = None) -> dict[str, Any]:
    return load_database_catalogue()


if __name__ == "__main__":
    try:
        catalogue = load_database_catalogue()
    except RuntimeError as exc:
        print(f"DATABASE READ FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
    print(
        f"Loaded schema {catalogue['schema_version']}: "
        f"{len(catalogue['movies'])} movies, {len(catalogue['albums'])} albums, "
        f"{len(catalogue['songs'])} songs."
    )
