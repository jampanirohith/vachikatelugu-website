#!/usr/bin/env python3
"""Read the normalized VachikaTelugu SQLite catalogue, read-only.

This adapter targets the current movie-pipeline schema v9. It deliberately
builds public catalogue data from normalized SQL columns and relationship
Tables; raw JSON/source payload blobs are not used to construct website pages.
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
SUPPORTED_SCHEMA_VERSION = "9"

REQUIRED_TABLES = {
    "schema_metadata", "movies", "albums", "songs", "artists", "lyricists",
    "song_artists", "song_lyricists", "song_media", "movie_people",
    "movie_genres", "song_genres", "movie_links", "ott_availability",
    "source_album_matches",
}

# Required columns are the normalized v9 contract used by the website.
# Deliberately do not list songs.song_flavor: it was retired from schema v9.
REQUIRED_COLUMNS = {
    "schema_metadata": {"key", "value"},
    "movies": {
        "imdb_id", "title", "title_telugu", "release_year", "original_language",
        "cinematic_universe", "imdb_score", "imdb_votes", "imdb_votes_numeric",
        "tmdb_url", "imdb_url", "wikipedia_url", "wikipedia_soundtrack_url",
        "plot_summary", "genres_json", "certification", "runtime_minutes",
        "poster_url", "backdrop_url", "title_logo_url", "trailer_youtube_id",
        "total_songs", "processing_status",
    },
    "albums": {
        "album_id", "movie_id", "title", "release_date", "label", "upc_barcode",
        "spotify_popularity", "artwork_hd_640", "artwork_300", "copyright_c", "copyright_p",
        "spotify_album_id", "youtube_album_id", "spotify_album_title", "youtube_album_title",
        "spotify_total_tracks", "spotify_saved_to_library", "spotify_url", "youtube_music_url",
        "total_tracks",
    },
    "songs": {
        "song_id", "album_id", "movie_id", "track_number", "title", "lyricist",
        "lrc_lyrics", "plain_lyrics", "lrclib_id", "lyrics_status", "lyrics_type",
        "data_source", "is_bonus_track", "duration_formatted", "duration_ms", "duration_sec",
        "youtube_video_song_views", "spotify_uri", "track_number_original", "disc_number",
        "is_explicit", "isrc_code",
    },
    "artists": {"artist_id", "artist_name", "normalized_name", "spotify_artist_id"},
    "lyricists": {"lyricist_id", "lyricist_name", "normalized_name"},
    "song_artists": {"song_id", "artist_id", "credit_order", "credit_role"},
    "song_lyricists": {"song_id", "lyricist_id", "credit_order"},
    "song_media": {
        "song_id", "platform", "external_id", "url", "preview_url", "views_text",
        "popularity", "video_title", "extra_json",
    },
    "movie_people": {"movie_id", "role", "person_name", "credit_order"},
    "movie_genres": {"movie_id", "genre", "genre_order"},
    "song_genres": {"song_id", "genre", "genre_order"},
    "movie_links": {"movie_id", "link_type", "url"},
    "ott_availability": {"movie_id", "provider", "availability_type"},
    "source_album_matches": {"movie_id", "platform", "album_id", "album_title", "url", "source_csv"},
}


def database_path() -> Path | None:
    """Return the configured/local database path without copying or modifying it."""
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
    """Open a SQLite database read-only so site builds cannot mutate source data."""
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def _nonempty(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.casefold() in {
        "n/a", "na", "not available", "not provided", "not specified",
        "unknown", "null", "none", "undefined",
    }:
        return None
    return text


def _valid_external_id(value: Any) -> str | None:
    """Accept provider identifiers, never arbitrary URL/HTML fragments."""
    text = _nonempty(value)
    return text if text and re.fullmatch(r"[A-Za-z0-9_-]{1,160}", text) else None


def _valid_http_url(value: Any) -> str | None:
    """Accept ordinary HTTP(S) URLs safe to place in links and image sources."""
    text = _nonempty(value)
    if not text or any(ch in text for ch in "\r\n\t\\\"'"):
        return None
    try:
        parsed = urlsplit(text)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return None
        if parsed.username is not None or parsed.password is not None:
            return None
        _ = parsed.port
    except ValueError:
        return None
    return text


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row[1]).lower()
        for row in connection.execute(f'PRAGMA table_info("{table}")')
    }


def load_database_catalogue() -> dict[str, Any]:
    """Load movies, albums and songs from normalized schema-v9 relations.

    Public page data is constructed from scalar columns and junction tables.
    Raw JSON snapshots, source metadata blobs, and status payloads are never
    decoded as a fallback for missing normalized values.
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
        missing_tables = sorted(REQUIRED_TABLES - tables)
        if missing_tables:
            raise RuntimeError(
                "SQLite database is missing required table(s): " + ", ".join(missing_tables)
            )

        missing_columns = []
        for table, expected in REQUIRED_COLUMNS.items():
            absent = sorted(expected - _table_columns(connection, table))
            if absent:
                missing_columns.append(f"{table}: {', '.join(absent)}")
        if missing_columns:
            raise RuntimeError(
                "SQLite database does not satisfy the schema-v9 website contract: "
                + " | ".join(missing_columns)
            )

        schema_row = connection.execute(
            "SELECT value FROM schema_metadata WHERE key='schema_version'"
        ).fetchone()
        schema_version = str(schema_row[0]) if schema_row else ""
        if schema_version != SUPPORTED_SCHEMA_VERSION:
            raise RuntimeError(
                f"Unsupported database schema version {schema_version or '(missing)'}; "
                f"this website adapter supports version {SUPPORTED_SCHEMA_VERSION}."
            )

        movie_rows = connection.execute("""
            SELECT imdb_id, title, title_telugu, release_year, original_language,
                   cinematic_universe, imdb_score, imdb_votes, imdb_votes_numeric,
                   tmdb_url, imdb_url, wikipedia_url, wikipedia_soundtrack_url,
                   plot_summary, certification, runtime_minutes, poster_url,
                   backdrop_url, title_logo_url, trailer_youtube_id, total_songs,
                   processing_status
            FROM movies
            WHERE processing_status='processed'
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
            for field in ("poster_url", "backdrop_url", "title_logo_url", "tmdb_url",
                          "imdb_url", "wikipedia_url", "wikipedia_soundtrack_url"):
                item[field] = _valid_http_url(item.get(field))
            item["trailer_youtube_id"] = _valid_external_id(item.get("trailer_youtube_id"))
            item["genres"] = []
            item["people"] = {}
            item["links"] = {}
            item["ott_availability"] = []
            item["albums"] = []
            item["songs"] = []
            movie_by_id[movie_id] = item
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
            valid_url = _valid_http_url(url)
            if valid_url:
                movie_by_id[movie_id]["links"][str(link_type).strip().lower()] = valid_url

        for row in connection.execute("""
            SELECT movie_id, provider, availability_type FROM ott_availability
            ORDER BY movie_id, provider COLLATE NOCASE, availability_type
        """):
            movie_id, provider, kind = row
            if movie_id in movie_by_id and _nonempty(provider) and _nonempty(kind):
                movie_by_id[movie_id]["ott_availability"].append({
                    "provider": str(provider).strip(), "type": str(kind).strip().lower()
                })

        album_rows = connection.execute("""
            SELECT album_id, movie_id, title, release_date, label, upc_barcode,
                   spotify_popularity, artwork_hd_640, artwork_300, copyright_c,
                   copyright_p, spotify_album_id, youtube_album_id,
                   spotify_album_title, youtube_album_title, spotify_total_tracks,
                   spotify_saved_to_library, spotify_url, youtube_music_url, total_tracks
            FROM albums
            ORDER BY movie_id, title COLLATE NOCASE, album_id
        """).fetchall()

        albums: list[dict[str, Any]] = []
        album_by_id: dict[str, dict[str, Any]] = {}
        album_counts: dict[str, int] = {}
        for row in album_rows:
            source = dict(row)
            movie = movie_by_id.get(source["movie_id"])
            if movie is None:
                continue
            album_id = _valid_external_id(source.get("album_id"))
            if not album_id:
                raise RuntimeError(f"Album for movie {source['movie_id']} has no valid album_id")
            item = {
                "album_id": album_id,
                "movie_id": source["movie_id"],
                "title": _nonempty(source.get("title")),
                "release_date": _nonempty(source.get("release_date")),
                "label": _nonempty(source.get("label")),
                "upc_barcode": _nonempty(source.get("upc_barcode")),
                "spotify_popularity": source.get("spotify_popularity"),
                "artwork_hd_640": _valid_http_url(source.get("artwork_hd_640")),
                "artwork_300": _valid_http_url(source.get("artwork_300")),
                "copyright_c": _nonempty(source.get("copyright_c")),
                "copyright_p": _nonempty(source.get("copyright_p")),
                "spotify_album_id": _valid_external_id(source.get("spotify_album_id")),
                "youtube_album_id": _valid_external_id(source.get("youtube_album_id")),
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
                f"https://open.spotify.com/album/{item['spotify_album_id']}"
                if item["spotify_album_id"] else None
            )
            item["youtube_music_url"] = item["youtube_music_url"] or (
                f"https://music.youtube.com/browse/{item['youtube_album_id']}"
                if item["youtube_album_id"] else None
            )
            album_by_id[album_id] = item
            movie["albums"].append(item)
            albums.append(item)
            album_counts[source["movie_id"]] = album_counts.get(source["movie_id"], 0) + 1

        # The current producer guarantees exactly one album anchor per movie.
        no_album_movies = [movie_id for movie_id in movie_by_id if album_counts.get(movie_id, 0) != 1]
        if no_album_movies:
            raise RuntimeError(
                "Schema-v9 catalogue must contain exactly one album row per processed movie; "
                f"found a mismatch for {len(no_album_movies)} movie(s), first: {no_album_movies[0]}"
            )

        artists_by_song: dict[str, list[dict[str, Any]]] = {}
        for row in connection.execute("""
            SELECT sa.song_id, sa.credit_order, sa.credit_role, a.artist_id, a.artist_name
            FROM song_artists sa JOIN artists a ON a.artist_id=sa.artist_id
            ORDER BY sa.song_id, sa.credit_order, a.artist_name COLLATE NOCASE
        """):
            name = _nonempty(row["artist_name"])
            if name:
                artists_by_song.setdefault(row["song_id"], []).append({
                    "artist_id": row["artist_id"], "name": name,
                    "role": _nonempty(row["credit_role"]) or "artist",
                    "order": row["credit_order"],
                })

        lyricists_by_song: dict[str, list[dict[str, Any]]] = {}
        for row in connection.execute("""
            SELECT sl.song_id, sl.credit_order, l.lyricist_id, l.lyricist_name
            FROM song_lyricists sl JOIN lyricists l ON l.lyricist_id=sl.lyricist_id
            ORDER BY sl.song_id, sl.credit_order, l.lyricist_name COLLATE NOCASE
        """):
            name = _nonempty(row["lyricist_name"])
            if name:
                lyricists_by_song.setdefault(row["song_id"], []).append({
                    "lyricist_id": row["lyricist_id"], "name": name,
                    "order": row["credit_order"],
                })

        media_by_song: dict[str, dict[str, dict[str, Any]]] = {}
        for row in connection.execute("""
            SELECT song_id, platform, external_id, url, preview_url, views_text,
                   popularity, video_title
            FROM song_media ORDER BY song_id, platform
        """):
            song_id = row["song_id"]
            platform = str(row["platform"] or "").strip().lower().replace("-", "_").replace(" ", "_")
            if not platform:
                continue
            media_by_song.setdefault(song_id, {})[platform] = {
                "platform": platform,
                "external_id": _valid_external_id(row["external_id"]),
                "url": _valid_http_url(row["url"]),
                "preview_url": _valid_http_url(row["preview_url"]),
                "views_text": _nonempty(row["views_text"]),
                "popularity": row["popularity"],
                "video_title": _nonempty(row["video_title"]),
            }

        genres_by_song: dict[str, list[str]] = {}
        for row in connection.execute("""
            SELECT song_id, genre FROM song_genres
            ORDER BY song_id, genre_order, genre COLLATE NOCASE
        """):
            genre = _nonempty(row["genre"])
            if genre:
                genres_by_song.setdefault(row["song_id"], []).append(genre)

        # song_flavor is intentionally absent from this SELECT. It was removed
        # from schema v9 and must not be reintroduced into website page data.
        song_rows = connection.execute("""
            SELECT s.song_id, s.album_id, s.movie_id, s.track_number, s.title, s.lyricist,
                   s.lrc_lyrics, s.plain_lyrics, s.lrclib_id, s.lyrics_status,
                   s.lyrics_type, s.data_source, s.is_bonus_track, s.duration_formatted,
                   s.duration_ms, s.duration_sec, s.youtube_video_song_views,
                   s.spotify_uri, s.track_number_original, s.disc_number,
                   s.is_explicit, s.isrc_code
            FROM songs s JOIN movies m ON m.imdb_id=s.movie_id
            WHERE m.processing_status='processed'
            ORDER BY s.movie_id, s.album_id, COALESCE(s.disc_number, 1),
                     COALESCE(s.track_number, 2147483647), s.title COLLATE NOCASE, s.song_id
        """).fetchall()

        songs: list[dict[str, Any]] = []
        for row in song_rows:
            source = dict(row)
            movie = movie_by_id.get(source["movie_id"])
            album = album_by_id.get(source["album_id"])
            if movie is None or album is None:
                raise RuntimeError(f"Song {source.get('song_id')!r} has no processed movie or album")
            if album.get("movie_id") != source.get("movie_id"):
                raise RuntimeError(
                    f"Song {source.get('song_id')!r} and its album belong to different movies"
                )
            song_id = _valid_external_id(source.get("song_id"))
            title = _nonempty(source.get("title"))
            if not song_id or not title:
                raise RuntimeError("A processed song has an empty/unsafe song_id or empty title")

            item = {
                "song_id": song_id,
                "album_id": source["album_id"],
                "movie_id": source["movie_id"],
                "track_number": source.get("track_number"),
                "title": title,
                "lyricist_legacy": _nonempty(source.get("lyricist")),
                "lrc_lyrics": _nonempty(source.get("lrc_lyrics")),
                "plain_lyrics": _nonempty(source.get("plain_lyrics")),
                "lrclib_id": _nonempty(source.get("lrclib_id")),
                "lyrics_status": _nonempty(source.get("lyrics_status")),
                "lyrics_type": _nonempty(source.get("lyrics_type")),
                "data_source": _nonempty(source.get("data_source")),
                "is_bonus_track": source.get("is_bonus_track"),
                "duration_formatted": _nonempty(source.get("duration_formatted")),
                "duration_ms": source.get("duration_ms"),
                "duration_sec": source.get("duration_sec"),
                "youtube_video_song_views": _nonempty(source.get("youtube_video_song_views")),
                "spotify_uri": _nonempty(source.get("spotify_uri")),
                "track_number_original": source.get("track_number_original"),
                "disc_number": source.get("disc_number"),
                "is_explicit": source.get("is_explicit"),
                "isrc_code": _nonempty(source.get("isrc_code")),
                "genres": genres_by_song.get(song_id, []),
                "artist_credits": artists_by_song.get(song_id, []),
                "lyricist_credits": lyricists_by_song.get(song_id, []),
                "media": media_by_song.get(song_id, {}),
                "movie": movie,
                "album": album,
            }
            # Retain compatibility with older rows whose lyricist relation has
            # not yet been backfilled; do not parse raw JSON to recover credits.
            if not item["lyricist_credits"] and item["lyricist_legacy"]:
                item["lyricist_credits"] = [
                    {"lyricist_id": None, "name": part.strip(), "order": index}
                    for index, part in enumerate(item["lyricist_legacy"].split(","))
                    if part.strip()
                ]
            album["songs"].append(item)
            movie["songs"].append(item)
            songs.append(item)

        for movie in movies:
            movie["songs"].sort(key=lambda song: (
                song.get("disc_number") or 1,
                song.get("track_number") if song.get("track_number") is not None else 2147483647,
                song["title"].casefold(), song["song_id"],
            ))
            movie["albums"].sort(key=lambda album: (
                -len(album["songs"]), (album.get("title") or "").casefold(), album["album_id"],
            ))
        for album in albums:
            album["songs"].sort(key=lambda song: (
                song.get("disc_number") or 1,
                song.get("track_number") if song.get("track_number") is not None else 2147483647,
                song["title"].casefold(), song["song_id"],
            ))

        print(
            f"data source: normalized SQLite ({db.name}); schema {schema_version}; "
            f"loaded {len(movies)} movies, {len(albums)} albums, {len(songs)} songs"
        )
        return {
            "schema_version": schema_version,
            "database_name": db.name,
            "movies": movies,
            "albums": albums,
            "songs": songs,
        }
    finally:
        connection.close()


def load_records(_ignored_legacy_json_path: str | Path | None = None) -> dict[str, Any]:
    """Backward-compatible alias; returns normalized catalogue, not raw JSON records."""
    return load_database_catalogue()


if __name__ == "__main__":
    try:
        catalogue = load_database_catalogue()
    except RuntimeError as exc:
        print(f"DATABASE READ FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
    print(
        f"Loaded schema {catalogue['schema_version']}: {len(catalogue['movies'])} movies, "
        f"{len(catalogue['albums'])} albums, {len(catalogue['songs'])} songs."
    )
