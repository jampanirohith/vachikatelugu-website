#!/usr/bin/env python3
"""Fail a site build early if the fetched SQLite source is incomplete or invalid."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from db_source import _read_only_connection, database_path


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
        check_result = connection.execute("PRAGMA quick_check").fetchone()
        if not check_result or check_result[0] != "ok":
            fail(f"SQLite quick_check returned {check_result!r}.")

        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "movies" not in tables:
            fail("the database does not contain a movies table")

        columns = {
            row[1].lower(): row[1]
            for row in connection.execute("PRAGMA table_info(movies)")
        }
        required = {"raw_json", "imdb_id", "title"}
        missing = sorted(required - set(columns))
        if missing:
            fail("movies table is missing required column(s): " + ", ".join(missing))

        where_clause = ""
        if "processing_status" in columns:
            where_clause = f" WHERE {columns['processing_status']} = 'processed'"
        query = (
            f"SELECT {columns['imdb_id']}, {columns['raw_json']} FROM movies"
            + where_clause
        )
        rows = connection.execute(query).fetchall()
        if not rows:
            fail("there are no completed movie records to build")

        movie_ids: set[str] = set()
        total_songs = 0
        errors: list[str] = []
        for index, (database_id, raw_json) in enumerate(rows, start=1):
            label = str(database_id or f"row {index}")
            try:
                movie = json.loads(raw_json)
            except (TypeError, json.JSONDecodeError):
                errors.append(f"{label}: raw_json is not valid JSON")
                continue
            if not isinstance(movie, dict):
                errors.append(f"{label}: raw_json is not a JSON object")
                continue
            if movie.get("error_flag"):
                errors.append(f"{label}: record is marked with error_flag")
            if not str(movie.get("title") or "").strip():
                errors.append(f"{label}: source record has no title")
            source_id = str(movie.get("movie_id") or movie.get("imdb_id") or database_id or "").strip()
            if not source_id:
                errors.append(f"{label}: source record has no movie identifier")
            elif source_id in movie_ids:
                errors.append(f"{label}: duplicate source movie identifier {source_id}")
            else:
                movie_ids.add(source_id)

            songs = movie.get("songs")
            if not isinstance(songs, list):
                errors.append(f"{label}: songs is missing or is not a list")
                continue
            total_songs += len(songs)
            for song_index, song in enumerate(songs, start=1):
                song_label = f"{label}, song #{song_index}"
                if not isinstance(song, dict):
                    errors.append(f"{song_label}: song is not an object")
                    continue
                if not str(song.get("title") or "").strip():
                    errors.append(f"{song_label}: song has no title")
                media = song.get("media") if isinstance(song.get("media"), dict) else {}
                spotify = media.get("spotify") if isinstance(media.get("spotify"), dict) else {}
                ytm = media.get("youtube_music") if isinstance(media.get("youtube_music"), dict) else {}
                youtube = media.get("youtube_video_song") if isinstance(media.get("youtube_video_song"), dict) else {}
                media_id = (
                    spotify.get("track_id")
                    or ytm.get("video_id")
                    or youtube.get("video_id")
                )
                if not media_id:
                    errors.append(f"{song_label}: no Spotify, YouTube Music or YouTube video ID for a stable song page")

        if total_songs == 0:
            errors.append("no songs were found in the completed movie records")
        if errors:
            preview = errors[:30]
            fail(
                f"found {len(errors)} catalogue issue(s) in {len(rows)} movie records; "
                + " | ".join(preview)
                + (" | ...more issues omitted" if len(errors) > len(preview) else "")
            )

        print(
            f"SQLite validation passed: {len(rows)} completed movies, "
            f"{total_songs} songs, database integrity ok ({Path(db).name})."
        )
    finally:
        connection.close()


if __name__ == "__main__":
    main()
