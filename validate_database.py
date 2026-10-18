#!/usr/bin/env python3
"""Validate the normalized SQLite schema and relationships before site generation."""
from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

from db_source import REQUIRED_TABLES, SUPPORTED_SCHEMA_VERSION, _read_only_connection, database_path

REQUIRED_COLUMNS = {
    "schema_metadata": {"key", "value"},
    "movies": {
        "imdb_id", "title", "title_telugu", "release_year", "original_language",
        "cinematic_universe", "imdb_score", "imdb_votes", "imdb_votes_numeric",
        "tmdb_url", "imdb_url", "wikipedia_url", "wikipedia_soundtrack_url",
        "plot_summary", "certification", "runtime_minutes", "poster_url", "backdrop_url",
        "title_logo_url", "trailer_youtube_id", "total_songs", "processing_status",
    },
    "albums": {
        "album_id", "movie_id", "title", "release_date", "label", "upc_barcode",
        "spotify_popularity", "artwork_hd_640", "artwork_300", "copyright_c", "copyright_p",
        "spotify_album_id", "youtube_album_id", "spotify_album_title", "youtube_album_title",
        "spotify_total_tracks", "spotify_saved_to_library", "spotify_url", "youtube_music_url", "total_tracks",
    },
    "songs": {
        "song_id", "album_id", "movie_id", "track_number", "title", "lyricist", "song_flavor",
        "lrc_lyrics", "plain_lyrics", "lrclib_id", "lyrics_status", "lyrics_type", "data_source",
        "is_bonus_track", "duration_formatted", "duration_ms", "duration_sec", "spotify_uri",
        "track_number_original", "disc_number", "is_explicit", "isrc_code",
    },
    "artists": {"artist_id", "artist_name"},
    "lyricists": {"lyricist_id", "lyricist_name"},
    "song_artists": {"song_id", "artist_id", "credit_order", "credit_role"},
    "song_lyricists": {"song_id", "lyricist_id", "credit_order"},
    "song_media": {"song_id", "platform", "external_id", "url", "preview_url", "views_text", "popularity", "video_title"},
    "movie_people": {"movie_id", "role", "person_name", "credit_order"},
    "movie_genres": {"movie_id", "genre", "genre_order"},
    "song_genres": {"song_id", "genre", "genre_order"},
    "movie_links": {"movie_id", "link_type", "url"},
    "ott_availability": {"movie_id", "provider", "availability_type"},
    "source_album_matches": {"movie_id", "platform", "album_id", "album_title", "url", "source_csv"},
}


def fail(message: str) -> None:
    print(f"DATABASE VALIDATION FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    try:
        db = database_path()
    except RuntimeError as exc:
        fail(str(exc))
    if db is None:
        fail("No SQLite database is available. Run fetch_database.py first.")

    try:
        connection = _read_only_connection(db)
    except sqlite3.Error as exc:
        fail(f"Unable to open database read-only ({type(exc).__name__}).")

    try:
        integrity = connection.execute("PRAGMA quick_check").fetchone()
        if not integrity or integrity[0] != "ok":
            fail(f"SQLite quick_check returned {integrity!r}.")
        fk_issues = connection.execute("PRAGMA foreign_key_check").fetchall()
        if fk_issues:
            fail(f"SQLite foreign_key_check found {len(fk_issues)} violation(s); first: {tuple(fk_issues[0])!r}")

        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = sorted(REQUIRED_TABLES - tables)
        if missing:
            fail("missing required normalized table(s): " + ", ".join(missing))

        column_errors = []
        for table, expected_columns in REQUIRED_COLUMNS.items():
            actual_columns = {row[1].lower() for row in connection.execute(f'PRAGMA table_info("{table}")')}
            absent = sorted(expected_columns - actual_columns)
            if absent:
                column_errors.append(f"{table}: {', '.join(absent)}")
        if column_errors:
            fail("required schema-v4 columns are missing: " + " | ".join(column_errors))

        version_row = connection.execute(
            "SELECT value FROM schema_metadata WHERE key='schema_version'"
        ).fetchone()
        version = str(version_row[0]) if version_row else ""
        if version != SUPPORTED_SCHEMA_VERSION:
            fail(f"unsupported schema_version {version or '(missing)'}; expected {SUPPORTED_SCHEMA_VERSION}")

        movie_count = connection.execute(
            "SELECT COUNT(*) FROM movies WHERE processing_status='processed'"
        ).fetchone()[0]
        album_count = connection.execute("""
            SELECT COUNT(*) FROM albums a JOIN movies m ON m.imdb_id=a.movie_id
            WHERE m.processing_status='processed'
        """).fetchone()[0]
        song_count = connection.execute("""
            SELECT COUNT(*) FROM songs s JOIN movies m ON m.imdb_id=s.movie_id
            WHERE m.processing_status='processed'
        """).fetchone()[0]
        if movie_count == 0:
            fail("there are no processed movies")
        if album_count == 0:
            fail("there are no albums associated with processed movies")
        if song_count == 0:
            fail("there are no songs associated with processed movies")

        errors: list[str] = []
        # The internal identity, not a media-provider ID, determines whether a
        # track exists. Missing streaming URLs are permitted and expected.
        for table, key, label in (
            ("movies", "imdb_id", "movie"), ("albums", "album_id", "album"),
            ("songs", "song_id", "song"),
        ):
            rows = connection.execute(f"SELECT {key} FROM {table}").fetchall()
            for index, row in enumerate(rows, start=1):
                if not str(row[0] or "").strip():
                    errors.append(f"{table} row {index} has an empty {key}")
        unsafe_song_ids = connection.execute("""
            SELECT s.song_id FROM songs s JOIN movies m ON m.imdb_id=s.movie_id
            WHERE m.processing_status='processed'
        """).fetchall()
        for row in unsafe_song_ids:
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", str(row[0] or "")):
                errors.append(f"song_id is not URL-safe: {str(row[0])[:80]!r}")

        empty_titles = connection.execute("""
            SELECT COUNT(*) FROM movies
            WHERE processing_status='processed' AND TRIM(COALESCE(title,''))=''
        """).fetchone()[0]
        if empty_titles:
            errors.append(f"{empty_titles} processed movie(s) have no title")
        empty_song_titles = connection.execute("""
            SELECT COUNT(*) FROM songs s JOIN movies m ON m.imdb_id=s.movie_id
            WHERE m.processing_status='processed' AND TRIM(COALESCE(s.title,''))=''
        """).fetchone()[0]
        if empty_song_titles:
            errors.append(f"{empty_song_titles} song(s) have no title")

        orphan_song_rows = connection.execute("""
            SELECT s.song_id
            FROM songs s JOIN movies m ON m.imdb_id=s.movie_id AND m.processing_status='processed'
            LEFT JOIN albums a ON a.album_id=s.album_id AND a.movie_id=s.movie_id
            WHERE a.album_id IS NULL
            LIMIT 10
        """).fetchall()
        for row in orphan_song_rows:
            errors.append(f"song {row[0]} has no matching album for its movie")

        mismatch_rows = connection.execute("""
            SELECT s.song_id, s.movie_id, a.movie_id
            FROM songs s JOIN albums a ON a.album_id=s.album_id
            JOIN movies m ON m.imdb_id=s.movie_id
            WHERE m.processing_status='processed' AND s.movie_id <> a.movie_id
            LIMIT 10
        """).fetchall()
        for row in mismatch_rows:
            errors.append(f"song {row[0]} belongs to movie {row[1]} but its album belongs to {row[2]}")

        for table, key in (("movies", "imdb_id"), ("albums", "album_id"), ("songs", "song_id")):
            duplicates = connection.execute(
                f'SELECT "{key}", COUNT(*) n FROM "{table}" GROUP BY "{key}" HAVING n > 1 LIMIT 10'
            ).fetchall()
            if duplicates:
                errors.append(f"duplicate {key} value(s): " + ", ".join(str(row[0]) for row in duplicates))

        if errors:
            fail(f"found {len(errors)} normalized catalogue issue(s): " + " | ".join(errors[:30]))

        media_song_count = connection.execute("""
            SELECT COUNT(DISTINCT s.song_id) FROM songs s
            JOIN movies m ON m.imdb_id=s.movie_id
            JOIN song_media sm ON sm.song_id=s.song_id
            WHERE m.processing_status='processed'
        """).fetchone()[0]
        lyricist_credit_count = connection.execute("""
            SELECT COUNT(*) FROM song_lyricists sl JOIN songs s ON s.song_id=sl.song_id
            JOIN movies m ON m.imdb_id=s.movie_id WHERE m.processing_status='processed'
        """).fetchone()[0]
        lrc_count = connection.execute("""
            SELECT COUNT(*) FROM songs s JOIN movies m ON m.imdb_id=s.movie_id
            WHERE m.processing_status='processed' AND TRIM(COALESCE(s.lrc_lyrics,''))<>''
        """).fetchone()[0]
        plain_count = connection.execute("""
            SELECT COUNT(*) FROM songs s JOIN movies m ON m.imdb_id=s.movie_id
            WHERE m.processing_status='processed' AND TRIM(COALESCE(s.plain_lyrics,''))<>''
        """).fetchone()[0]
        genre_count = connection.execute("""
            SELECT COUNT(*) FROM song_genres sg JOIN songs s ON s.song_id=sg.song_id
            JOIN movies m ON m.imdb_id=s.movie_id WHERE m.processing_status='processed'
        """).fetchone()[0]
        print(
            f"SQLite validation passed: schema {version}, {movie_count} movies, "
            f"{album_count} albums, {song_count} songs; integrity and FK checks ok "
            f"({Path(db).name})."
        )
        print(
            "Coverage notice: "
            f"{media_song_count}/{song_count} songs have media rows; "
            f"{lyricist_credit_count} lyricist relationships; "
            f"{lrc_count} LRC lyric records; {plain_count} plain lyric records; "
            f"{genre_count} normalized song-genre relationships. Missing media/lyrics/genres are not build errors."
        )
    finally:
        connection.close()


if __name__ == "__main__":
    main()
