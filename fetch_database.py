#!/usr/bin/env python3
"""Fetch the private SQLite database from GitHub without embedding secrets."""
from __future__ import annotations

import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

OWNER_REPO = os.environ.get("DATABASE_REPO", "jampanirohith/telugumoviedb").strip()
BRANCH = os.environ.get("DATABASE_BRANCH", "main").strip()
DB_PATH = os.environ.get("DATABASE_FILE", "vachikatelugu.db").strip().lstrip("/")
DEST = Path(os.environ.get("DATABASE_DEST", ".build-data/vachikatelugu.db")).expanduser()
TOKEN = os.environ.get("GITHUB_TOKEN", "")

if not TOKEN:
    sys.exit("ERROR: GITHUB_TOKEN is required as a secret environment variable.")
if "/" not in OWNER_REPO or OWNER_REPO.count("/") != 1:
    sys.exit("ERROR: DATABASE_REPO must be owner/repository.")
if not DB_PATH or any(part == ".." for part in Path(DB_PATH).parts):
    sys.exit("ERROR: DATABASE_FILE must be a valid repository-relative path.")
if not BRANCH:
    sys.exit("ERROR: DATABASE_BRANCH must not be empty.")

encoded_path = urllib.parse.quote(DB_PATH, safe="/")
api_url = (
    f"https://api.github.com/repos/{OWNER_REPO}/contents/{encoded_path}"
    f"?ref={urllib.parse.quote(BRANCH, safe='')}"
)
request = urllib.request.Request(
    api_url,
    headers={
        "Authorization": "Bearer " + TOKEN,
        "Accept": "application/vnd.github.raw+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "vachikatelugu-pages-build",
    },
)

try:
    with urllib.request.urlopen(request, timeout=180) as response:
        content = response.read()
except urllib.error.HTTPError as exc:
    # Do not print the response body or request headers; keep logs secret-safe.
    sys.exit(
        f"ERROR: GitHub database download failed (HTTP {exc.code}). "
        "Check the repository, branch, file path and read-only token permissions."
    )
except Exception as exc:
    sys.exit(f"ERROR: unable to fetch the private database ({type(exc).__name__}).")

if not content.startswith(b"SQLite format 3\x00"):
    sys.exit(
        "ERROR: the downloaded file is not a SQLite database. Check whether "
        "Git LFS or a repository pointer file is being downloaded instead."
    )

# Resolve relative destinations against this project root, not the shell's cwd.
root = Path(__file__).resolve().parent
if not DEST.is_absolute():
    DEST = root / DEST
DEST.parent.mkdir(parents=True, exist_ok=True)
temporary = DEST.with_suffix(DEST.suffix + ".tmp")
try:
    temporary.write_bytes(content)
    temporary.replace(DEST)
except OSError as exc:
    temporary.unlink(missing_ok=True)
    sys.exit(f"ERROR: could not save database locally ({type(exc).__name__}).")

print(f"Fetched private SQLite database to {DEST} ({len(content):,} bytes).")
