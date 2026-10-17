#!/usr/bin/env python3
"""Read canonical movie records from the private SQLite catalogue.

Production builds must fetch the database first. A JSON fallback is available
only when explicitly enabled for a developer's local preview; no JSON catalogue
is bundled in this public website repository.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / ".build-data" / "vachikatelugu.db"
LOCAL_DB = ROOT / "vachikatelugu.db"


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
    # as_uri() safely encodes spaces and other URI-sensitive path characters.
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def load_records(fallback_json: str | Path | None = None) -> list[dict]:
    """Return full movie objects stored in movies.raw_json.

    The expected SQLite schema comes from the companion data-collection
    pipeline. Only completed records are included when processing_status exists.
    """
    db = database_path()
    if db:
        connection = _read_only_connection(db)
        try:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if "movies" not in tables:
                raise RuntimeError(f"{db} has no 'movies' table")

            columns = {
                row[1].lower(): row[1]
                for row in connection.execute("PRAGMA table_info(movies)")
            }
            if "raw_json" not in columns:
                raise RuntimeError(
                    f"{db} movies table has no raw_json column; a schema adapter is required"
                )

            select_columns = [columns["raw_json"]]
            where_clause = ""
            parameters: tuple = ()
            if "processing_status" in columns:
                where_clause = f" WHERE {columns['processing_status']} = ?"
                parameters = ("processed",)

            order_columns = [
                columns[name]
                for name in ("release_year", "title")
                if name in columns
            ]
            order_clause = (
                " ORDER BY " + ", ".join(order_columns)
                if order_columns
                else " ORDER BY rowid"
            )
            sql = (
                f"SELECT {select_columns[0]} FROM movies"
                + where_clause
                + order_clause
            )
            rows = connection.execute(sql, parameters).fetchall()
            if not rows:
                raise RuntimeError(
                    f"{db} contains no completed movie records in movies.raw_json"
                )

            records: list[dict] = []
            for row_number, (raw_value,) in enumerate(rows, start=1):
                try:
                    value = json.loads(raw_value)
                except (TypeError, json.JSONDecodeError) as exc:
                    raise RuntimeError(
                        f"Invalid JSON in movies.raw_json at result row {row_number}"
                    ) from exc
                if not isinstance(value, dict):
                    raise RuntimeError(
                        f"movies.raw_json at result row {row_number} is not a JSON object"
                    )
                records.append(value)

            print(f"data source: SQLite ({db}); loaded {len(records)} completed movie records")
            return records
        finally:
            connection.close()

    # Explicit opt-in for an external local preview file. No fallback dataset
    # is bundled with the public site project and this mode must not be enabled
    # in Cloudflare Production.
    allow_fallback = os.environ.get("ALLOW_JSON_FALLBACK", "").lower() in {
        "1", "true", "yes"
    }
    if fallback_json and allow_fallback:
        fallback_path = Path(fallback_json)
        if not fallback_path.is_absolute():
            fallback_path = ROOT / fallback_path
        if fallback_path.is_file():
            print(
                f"WARNING: using explicitly enabled local JSON fallback: {fallback_path}",
                flush=True,
            )
            value = json.loads(fallback_path.read_text(encoding="utf-8"))
            if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
                raise RuntimeError("JSON fallback must be an array of movie objects")
            return value

    raise RuntimeError(
        "No SQLite database found. Run fetch_database.py, set DATABASE_PATH, or "
        "place the database at .build-data/vachikatelugu.db. A local JSON fallback "
        "is supported only when ALLOW_JSON_FALLBACK=1 and you provide the file yourself."
    )
