#!/usr/bin/env python3
"""Validate the current schema-v9 SQLite catalogue before site generation.

This validator intentionally follows the current Telugu Movie Pipeline schema.
In particular, ``songs.song_flavor`` is retired and must not be required.
"""
from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

# Keep the connection/path helpers shared with the website data layer, but do
# not import its older schema-version/column constants: this catalogue is now
# produced by movieinfo.py schema version 9.
from db_source import _read_only_connection, database_path

SUPPORTED_SCHEMA_VERSION = "9"

REQUIRED_TABLES = {
    "schema_metadata",
    "movies",
    "albums",
    "songs",
    "artists",
    "song_artists",
    "lyricists",
    "song_lyricists",
    "song_genres",
    "song_media",
    "movie_links",
    "movie_genres",
    "movie_people",
    "ott_availability",
    "source_album_matches",
}

# Required columns reflect final_release/schema.sql. Do not add song_flavor:
# the field, index, and historical JSON keys are removed by schema-v9 migration.
REQUIRED_COLUMNS = {
    "schema_metadata": {"key", "value"},
    "movies": {
        "imdb_id", "title", "title_telugu", "release_year", "original_language",
        "cinematic_universe", "imdb_score", "imdb_votes", "imdb_votes_numeric",
        "tmdb_url", "imdb_url", "wikipedia_url", "wikipedia_soundtrack_url",
        "tmdb_enriched", "wikipedia_movie_link_found", "source_metadata_json",
        "plot_summary", "genres_json", "certification", "runtime_minutes",
        "poster_url", "backdrop_url", "title_logo_url", "trailer_youtube_id",
        "total_songs", "processing_status", "source_status_json", "raw_json",
    },
    "albums": {
        "album_id", "movie_id", "title", "release_date", "label", "upc_barcode",
        "spotify_popularity", "artwork_hd_640", "artwork_300", "copyright_c", "copyright_p",
        "spotify_album_id", "youtube_album_id", "spotify_album_title", "youtube_album_title",
        "spotify_total_tracks", "spotify_images_json", "spotify_saved_to_library",
        "source_metadata_json", "spotify_url", "youtube_music_url", "total_tracks", "raw_json",
        "spotify", "ytm", "wikipedia_soundtrack_enriched",
    },
    "songs": {
        "song_id", "album_id", "movie_id", "track_number", "title", "lyricist",
        "lrc_lyrics", "plain_lyrics", "lrclib_id", "lyrics_status", "lyrics_type",
        "data_source", "is_bonus_track", "duration_formatted", "duration_ms", "duration_sec",
        "youtube_video_song_views", "spotify_uri", "track_number_original", "disc_number",
        "artist_ids_json", "spotify_artist_credits_json", "is_explicit", "isrc_code",
        "genres_json", "audio_features_json", "metadata_sources_json",
        "youtube_video_song_enriched", "spotify_track_details_enriched",
        "spotify_artist_details_enriched", "source_metadata_json", "raw_json",
    },
    "artists": {
        "artist_id", "artist_name", "normalized_name", "spotify_artist_id",
        "spotify_artist_metadata_json",
    },
    "song_artists": {"song_id", "artist_id", "credit_order", "credit_role"},
    "lyricists": {"lyricist_id", "lyricist_name", "normalized_name"},
    "song_lyricists": {"song_id", "lyricist_id", "credit_order"},
    "song_genres": {"song_id", "genre", "genre_order"},
    "song_media": {
        "song_id", "platform", "external_id", "url", "preview_url", "views_text",
        "popularity", "video_title", "extra_json",
    },
    "movie_links": {"movie_id", "link_type", "url"},
    "movie_genres": {"movie_id", "genre", "genre_order"},
    "movie_people": {"movie_id", "role", "person_name", "credit_order"},
    "ott_availability": {"movie_id", "provider", "availability_type"},
    "source_album_matches": {"movie_id", "platform", "album_id", "album_title", "url", "source_csv"},
}

BINARY_FLAGS = {
    "movies": ("tmdb_enriched", "wikipedia_movie_link_found"),
    "albums": ("spotify", "ytm", "wikipedia_soundtrack_enriched"),
    "songs": (
        "youtube_video_song_enriched",
        "spotify_track_details_enriched",
        "spotify_artist_details_enriched",
    ),
}


def fail(message: str) -> None:
    print(f"DATABASE VALIDATION FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row[1]).lower()
        for row in connection.execute(f'PRAGMA table_info("{table}")')
    }


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
            fail(
                f"SQLite foreign_key_check found {len(fk_issues)} violation(s); "
                f"first: {tuple(fk_issues[0])!r}"
            )

        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        missing_tables = sorted(REQUIRED_TABLES - tables)
        if missing_tables:
            fail("missing required normalized table(s): " + ", ".join(missing_tables))

        column_errors: list[str] = []
        actual_columns: dict[str, set[str]] = {}
        for table, expected in REQUIRED_COLUMNS.items():
            found = _columns(connection, table)
            actual_columns[table] = found
            absent = sorted(expected - found)
            if absent:
                column_errors.append(f"{table}: {', '.join(absent)}")
        if column_errors:
            fail(
                f"required schema-v{SUPPORTED_SCHEMA_VERSION} columns are missing: "
                + " | ".join(column_errors)
            )

        # song_flavor was deliberately retired in schema v9. Flag any database
        # that still exposes the old normalized column instead of silently
        # accepting a mixed/partially migrated schema.
        if "song_flavor" in actual_columns.get("songs", set()):
            fail(
                "songs.song_flavor is a retired column; migrate/rebuild the database "
                "with the current schema-v9 movieinfo.py before deployment."
            )

        version_row = connection.execute(
            "SELECT value FROM schema_metadata WHERE key='schema_version'"
        ).fetchone()
        version = str(version_row[0]) if version_row else ""
        if version != SUPPORTED_SCHEMA_VERSION:
            fail(
                f"unsupported schema_version {version or '(missing)'}; "
                f"expected {SUPPORTED_SCHEMA_VERSION}"
            )

        movie_count = connection.execute(
            "SELECT COUNT(*) FROM movies WHERE processing_status='processed'"
        ).fetchone()[0]
        album_count = connection.execute(
            """SELECT COUNT(*) FROM albums a
               JOIN movies m ON m.imdb_id=a.movie_id
               WHERE m.processing_status='processed'"""
        ).fetchone()[0]
        song_count = connection.execute(
            """SELECT COUNT(*) FROM songs s
               JOIN movies m ON m.imdb_id=s.movie_id
               WHERE m.processing_status='processed'"""
        ).fetchone()[0]

        if movie_count == 0:
            fail("there are no processed movies")
        if album_count == 0:
            fail("there are no albums associated with processed movies")
        if song_count == 0:
            fail("there are no songs associated with processed movies")

        errors: list[str] = []

        # Each processed movie must have exactly one album anchor.
        bad_album_counts = connection.execute(
            """SELECT m.imdb_id, COUNT(a.album_id) AS album_rows
               FROM movies m LEFT JOIN albums a ON a.movie_id=m.imdb_id
               WHERE m.processing_status='processed'
               GROUP BY m.imdb_id
               HAVING COUNT(a.album_id) <> 1
               LIMIT 20"""
        ).fetchall()
        for row in bad_album_counts:
            errors.append(
                f"movie {row[0]} has {row[1]} album rows; exactly one is required"
            )

        # Album display title must be the canonical movie title. Provider album
        # titles belong in spotify_album_title/youtube_album_title.
        title_mismatches = connection.execute(
            """SELECT m.imdb_id, m.title, a.title
               FROM movies m JOIN albums a ON a.movie_id=m.imdb_id
               WHERE m.processing_status='processed'
                 AND TRIM(COALESCE(a.title,'')) <> TRIM(COALESCE(m.title,''))
               LIMIT 20"""
        ).fetchall()
        for row in title_mismatches:
            errors.append(
                f"album title for movie {row[0]} differs from canonical movie title"
            )

        # All primary identifiers must be populated; song IDs must be URL-safe.
        for table, key in (
            ("movies", "imdb_id"),
            ("albums", "album_id"),
            ("songs", "song_id"),
        ):
            for index, row in enumerate(
                connection.execute(f'SELECT "{key}" FROM "{table}"'), start=1
            ):
                if not str(row[0] or "").strip():
                    errors.append(f"{table} row {index} has an empty {key}")

        for (song_id,) in connection.execute(
            """SELECT s.song_id FROM songs s
               JOIN movies m ON m.imdb_id=s.movie_id
               WHERE m.processing_status='processed'"""
        ):
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", str(song_id or "")):
                errors.append(f"song_id is not URL-safe: {str(song_id)[:80]!r}")

        empty_movie_titles = connection.execute(
            """SELECT COUNT(*) FROM movies
               WHERE processing_status='processed'
                 AND TRIM(COALESCE(title,''))=''"""
        ).fetchone()[0]
        if empty_movie_titles:
            errors.append(f"{empty_movie_titles} processed movie(s) have no title")

        empty_song_titles = connection.execute(
            """SELECT COUNT(*) FROM songs s
               JOIN movies m ON m.imdb_id=s.movie_id
               WHERE m.processing_status='processed'
                 AND TRIM(COALESCE(s.title,''))=''"""
        ).fetchone()[0]
        if empty_song_titles:
            errors.append(f"{empty_song_titles} song(s) have no title")

        orphan_song_rows = connection.execute(
            """SELECT s.song_id FROM songs s
               JOIN movies m ON m.imdb_id=s.movie_id
                    AND m.processing_status='processed'
               LEFT JOIN albums a ON a.album_id=s.album_id
                    AND a.movie_id=s.movie_id
               WHERE a.album_id IS NULL
               LIMIT 10"""
        ).fetchall()
        for row in orphan_song_rows:
            errors.append(f"song {row[0]} has no matching album for its movie")

        for table, key in (
            ("movies", "imdb_id"),
            ("albums", "album_id"),
            ("songs", "song_id"),
        ):
            duplicates = connection.execute(
                f'''SELECT "{key}", COUNT(*) AS n FROM "{table}"
                    GROUP BY "{key}" HAVING n > 1 LIMIT 10'''
            ).fetchall()
            if duplicates:
                errors.append(
                    f"duplicate {key} value(s): "
                    + ", ".join(str(row[0]) for row in duplicates)
                )

        # Every source-enrichment flag must remain binary (0 or 1).
        for table, columns in BINARY_FLAGS.items():
            for column in columns:
                bad = connection.execute(
                    f'''SELECT COUNT(*) FROM "{table}"
                        WHERE "{column}" IS NULL OR "{column}" NOT IN (0,1)'''
                ).fetchone()[0]
                if bad:
                    errors.append(
                        f"{table}.{column} contains {bad} non-binary value(s)"
                    )

        # Make sure the per-movie album uniqueness invariant exists in the
        # physical schema as well as in the data. This can be a UNIQUE constraint
        # or the explicit unique index created by the migration.
        unique_movie_index = False
        for index_row in connection.execute("PRAGMA index_list('albums')"):
            index_name, is_unique = index_row[1], index_row[2]
            if not is_unique:
                continue
            indexed_columns = [
                info[2]
                for info in connection.execute(
                    f'PRAGMA index_info("{index_name}")'
                )
            ]
            if indexed_columns == ["movie_id"]:
                unique_movie_index = True
                break
        if not unique_movie_index:
            errors.append("albums.movie_id is not protected by a UNIQUE constraint/index")

        if errors:
            fail(
                f"found {len(errors)} normalized catalogue issue(s): "
                + " | ".join(errors[:30])
            )

        media_song_count = connection.execute(
            """SELECT COUNT(DISTINCT s.song_id) FROM songs s
               JOIN movies m ON m.imdb_id=s.movie_id
               JOIN song_media sm ON sm.song_id=s.song_id
               WHERE m.processing_status='processed'"""
        ).fetchone()[0]
        lyricist_credit_count = connection.execute(
            """SELECT COUNT(*) FROM song_lyricists sl
               JOIN songs s ON s.song_id=sl.song_id
               JOIN movies m ON m.imdb_id=s.movie_id
               WHERE m.processing_status='processed'"""
        ).fetchone()[0]
        lrc_count = connection.execute(
            """SELECT COUNT(*) FROM songs s
               JOIN movies m ON m.imdb_id=s.movie_id
               WHERE m.processing_status='processed'
                 AND TRIM(COALESCE(s.lrc_lyrics,''))<>''"""
        ).fetchone()[0]
        plain_count = connection.execute(
            """SELECT COUNT(*) FROM songs s
               JOIN movies m ON m.imdb_id=s.movie_id
               WHERE m.processing_status='processed'
                 AND TRIM(COALESCE(s.plain_lyrics,''))<>''"""
        ).fetchone()[0]
        genre_count = connection.execute(
            """SELECT COUNT(*) FROM song_genres sg
               JOIN songs s ON s.song_id=sg.song_id
               JOIN movies m ON m.imdb_id=s.movie_id
               WHERE m.processing_status='processed'"""
        ).fetchone()[0]
        video_view_count = connection.execute(
            """SELECT COUNT(*) FROM songs s
               JOIN movies m ON m.imdb_id=s.movie_id
               WHERE m.processing_status='processed'
                 AND TRIM(COALESCE(s.youtube_video_song_views,''))<>''"""
        ).fetchone()[0]

        print(
            f"SQLite validation passed: schema {version}, {movie_count} movies, "
            f"{album_count} albums, {song_count} songs; integrity and FK checks ok "
            f"({Path(db).name})."
        )
        print(
            "Coverage notice: "
            f"{media_song_count}/{song_count} songs have media rows; "
            f"{video_view_count} have YouTube video-song views; "
            f"{lyricist_credit_count} lyricist relationships; "
            f"{lrc_count} LRC lyric records; {plain_count} plain lyric records; "
            f"{genre_count} normalized song-genre relationships. "
            "Missing media/lyrics/genres are not build errors."
        )
    finally:
        connection.close()


if __name__ == "__main__":
    main()
