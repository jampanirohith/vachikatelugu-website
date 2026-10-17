#!/usr/bin/env python3
"""Check that dist/ contains public site assets, not database/source secrets."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"

# Explicit allow-lists make the public client-side index a reviewed projection
# of catalogue fields, not a dump of raw database rows.
ALLOWED_INDEX_KEYS = {
    "songs": {
        "id", "title", "movieTitle", "movieSlug", "moviePath", "albumPath",
        "year", "released", "artists", "musicDirectors", "plays", "playsNum",
        "duration", "number", "songCount", "artwork", "poster", "genres", "imdbId",
        "release", "spotifyId", "ytmId", "spotifyUrl", "ytmUrl", "youtubeVideoUrl",
        "youtubeVideoId", "youtubeVideoTitle", "youtubeVideoViews", "isrc", "durationMs",
    },
    "movies": {
        "slug", "path", "albumPath", "imdbId", "title", "telugu", "year", "released",
        "genres", "musicDirectors", "directors", "cast", "plot", "certification",
        "originalLanguage", "runtimeMinutes", "ottProviders", "songs", "poster", "artwork",
        "playsNum", "albumReleased",
    },
    "albums": {
        "slug", "path", "moviePath", "imdbId", "title", "year", "release", "artist",
        "musicDirectors", "genres", "artwork", "plays", "songs",
    },
}

FORBIDDEN_NAMES = {
    ".env", ".env.production", ".env.local", "vachikatelugu.db", "database.sqlite",
    "id_rsa", "id_ed25519",
}
FORBIDDEN_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".pem", ".p12", ".pfx", ".key"}
SENSITIVE_JSON_KEY_PATTERN = re.compile(
    rb"[\"\'](?:raw_json|processing_status|created_at|updated_at|api_key|access_token|refresh_token|password|secret|private_notes|internal_notes)[\"\']\s*:",
    re.IGNORECASE,
)
SECRET_PATTERNS = [
    re.compile(rb"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(rb"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(rb"AKIA[0-9A-Z]{16}"),
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]


def fail(message: str, problems: list[str]) -> None:
    problems.append(message)


def main() -> None:
    problems: list[str] = []
    if not DIST.is_dir():
        print("PUBLIC OUTPUT CHECK FAILED: dist/ does not exist. Run build.py first.", file=sys.stderr)
        raise SystemExit(1)

    files = [path for path in DIST.rglob("*") if path.is_file()]
    if not files:
        fail("dist/ is empty", problems)
    if not (DIST / "index.html").is_file():
        fail("dist/index.html is missing", problems)
    if not (DIST / "search-index.json").is_file():
        fail("dist/search-index.json is missing", problems)

    github_token = os.environ.get("GITHUB_TOKEN", "").encode("utf-8")
    for path in files:
        relative = path.relative_to(DIST)
        lower_parts = {part.lower() for part in relative.parts}
        if any(part in {".build-data", ".git", "data-private", "private-data"} for part in lower_parts):
            fail(f"private/source directory was copied into dist/: {relative}", problems)
        if path.name.lower() in FORBIDDEN_NAMES or path.suffix.lower() in FORBIDDEN_SUFFIXES:
            fail(f"sensitive-looking file was copied into dist/: {relative}", problems)
        if path.suffix.lower() == ".json" and relative.as_posix() != "search-index.json":
            fail(f"unreviewed JSON file was copied into dist/: {relative}", problems)
        try:
            contents = path.read_bytes()
        except OSError as exc:
            fail(f"could not read generated file {relative} ({type(exc).__name__})", problems)
            continue
        if contents.startswith(b"SQLite format 3\x00"):
            fail(f"SQLite database found in public output: {relative}", problems)
        if github_token and len(github_token) >= 8 and github_token in contents:
            fail(f"GITHUB_TOKEN value appears in public output: {relative}", problems)
        if SENSITIVE_JSON_KEY_PATTERN.search(contents):
            fail(f"sensitive/raw database field name appears in public output: {relative}", problems)
        for pattern in SECRET_PATTERNS:
            if pattern.search(contents):
                fail(f"possible credential/private-key material found in public output: {relative}", problems)
                break

    index_path = DIST / "search-index.json"
    if index_path.is_file():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            fail("search-index.json is not valid UTF-8 JSON", problems)
        else:
            if not isinstance(index, dict):
                fail("search-index.json root is not an object", problems)
            else:
                for group, allowed in ALLOWED_INDEX_KEYS.items():
                    records = index.get(group)
                    if not isinstance(records, list):
                        fail(f"search-index.json is missing list '{group}'", problems)
                        continue
                    for row_number, record in enumerate(records, start=1):
                        if not isinstance(record, dict):
                            fail(f"search-index.json {group}[{row_number}] is not an object", problems)
                            continue
                        unexpected = sorted(set(record) - allowed)
                        if unexpected:
                            fail(
                                f"search-index.json {group}[{row_number}] contains unreviewed field(s): "
                                + ", ".join(unexpected),
                                problems,
                            )
                            break
                unexpected_groups = sorted(set(index) - set(ALLOWED_INDEX_KEYS))
                if unexpected_groups:
                    fail("search-index.json contains unreviewed top-level section(s): " + ", ".join(unexpected_groups), problems)

    if problems:
        print("PUBLIC OUTPUT CHECK FAILED:")
        for message in problems[:50]:
            print(f"- {message}")
        if len(problems) > 50:
            print(f"- ... {len(problems) - 50} more issue(s) omitted")
        raise SystemExit(1)

    print(f"Public-output check passed: {len(files)} generated files; no database file or unreviewed search-index fields found.")


if __name__ == "__main__":
    main()
