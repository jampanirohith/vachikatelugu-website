#!/usr/bin/env python3
"""Fetch a private SQLite database from GitHub, including Git LFS objects."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
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
# Optional if the account holding the token differs from the repository owner.
GITHUB_USERNAME = os.environ.get("GITHUB_USERNAME", OWNER_REPO.split("/", 1)[0]).strip()
SQLITE_HEADER = b"SQLite format 3\x00"


def fail(message: str) -> None:
    sys.exit("ERROR: " + message)


def read_url(url: str, headers: dict[str, str], data: bytes | None = None, timeout: int = 240, allow_http_error: bool = False) -> bytes:
    req = urllib.request.Request(url, headers=headers, data=data, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        # Allow trying the alternate GitHub LFS endpoint without logging response data.
        if allow_http_error:
            raise
        fail(f"GitHub/LFS request failed (HTTP {exc.code}). Check token access and Git LFS object availability.")
    except Exception as exc:
        fail(f"Unable to download database ({type(exc).__name__}).")


if not TOKEN:
    fail("GITHUB_TOKEN is required as a Cloudflare Pages encrypted secret.")
if "/" not in OWNER_REPO or OWNER_REPO.count("/") != 1:
    fail("DATABASE_REPO must be owner/repository.")
if not DB_PATH or any(part == ".." for part in Path(DB_PATH).parts):
    fail("DATABASE_FILE must be a valid repository-relative path.")
if not BRANCH:
    fail("DATABASE_BRANCH must not be empty.")

encoded_path = urllib.parse.quote(DB_PATH, safe="/")
contents_url = (
    f"https://api.github.com/repos/{OWNER_REPO}/contents/{encoded_path}"
    f"?ref={urllib.parse.quote(BRANCH, safe='')}"
)
content = read_url(
    contents_url,
    {
        "Authorization": "Bearer " + TOKEN,
        "Accept": "application/vnd.github.raw+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "vachikatelugu-pages-build",
    },
)

# The GitHub Contents API may return the small Git LFS pointer instead of the
# real binary. Parse the pointer and ask GitHub's LFS Batch API for the object.
if not content.startswith(SQLITE_HEADER):
    pointer_text = content.decode("utf-8", errors="replace")
    oid_match = re.search(r"(?m)^oid sha256:([0-9a-f]{64})\s*$", pointer_text)
    size_match = re.search(r"(?m)^size ([0-9]+)\s*$", pointer_text)
    version_match = re.search(r"(?m)^version https://git-lfs\.github\.com/spec/v1\s*$", pointer_text)
    if not (oid_match and size_match and version_match):
        fail("GitHub did not return a SQLite database or a valid Git LFS pointer. Check DATABASE_FILE and the private repository file.")

    oid = oid_match.group(1)
    expected_size = int(size_match.group(1))
    username = GITHUB_USERNAME or OWNER_REPO.split("/", 1)[0]
    basic = base64.b64encode(f"{username}:{TOKEN}".encode("utf-8")).decode("ascii")
    lfs_url = f"https://github.com/{OWNER_REPO}.git/info/lfs/objects/batch"
    payload = json.dumps({
        "operation": "download",
        "transfers": ["basic"],
        "ref": {"name": f"refs/heads/{BRANCH}"},
        "objects": [{"oid": oid, "size": expected_size}],
        "hash_algo": "sha256",
    }).encode("utf-8")
    lfs_headers = {
        "Authorization": "Basic " + basic,
        "Accept": "application/vnd.git-lfs+json",
        "Content-Type": "application/vnd.git-lfs+json",
        "User-Agent": "vachikatelugu-pages-build",
    }
    # GitHub has served both the standard repository LFS endpoint and its
    # /_lfs/ endpoint; try the standard URL first, then the GitHub-specific one.
    batch_raw = None
    lfs_urls = [
        lfs_url,
        f"https://github.com/_lfs/{OWNER_REPO}.git/info/lfs/objects/batch",
    ]
    last_http_error = None
    for candidate_url in lfs_urls:
        try:
            batch_raw = read_url(candidate_url, lfs_headers, data=payload, allow_http_error=True)
            break
        except urllib.error.HTTPError as exc:
            last_http_error = exc
            if exc.code not in (404, 405):
                fail(f"GitHub LFS authorization/download request failed (HTTP {exc.code}). Check token access and Git LFS object availability.")
    if batch_raw is None:
        code = last_http_error.code if last_http_error else "unknown"
        fail(f"GitHub LFS endpoint was not available (HTTP {code}).")
    try:
        batch = json.loads(batch_raw)
        objects = batch["objects"]
        obj = next(item for item in objects if item.get("oid") == oid)
        if "error" in obj:
            fail(f"Git LFS reports object error {obj['error'].get('code', 'unknown')}. Check that the LFS object was uploaded to GitHub.")
        action = obj["actions"]["download"]
        download_headers = {str(k): str(v) for k, v in action.get("header", {}).items()}
        content = read_url(action["href"], download_headers, timeout=600)
    except SystemExit:
        raise
    except Exception:
        fail("Git LFS did not provide a valid download action. Check the token's read access and Git LFS object availability.")

    if len(content) != expected_size:
        fail(f"Git LFS download size mismatch (expected {expected_size:,} bytes, got {len(content):,}).")
    if hashlib.sha256(content).hexdigest() != oid:
        fail("Git LFS object SHA-256 verification failed; refusing to use the downloaded file.")

if not content.startswith(SQLITE_HEADER):
    fail("Downloaded content is not a SQLite database after Git LFS resolution.")

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
    fail(f"Could not save database locally ({type(exc).__name__}).")

print(f"Fetched private SQLite database to {DEST} ({len(content):,} bytes); SQLite header verified.")
