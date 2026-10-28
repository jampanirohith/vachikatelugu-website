# Build, UI and validation report

## Uploaded SQLite database audit

The supplied `vachikatelugu.db` snapshot is normalized SQLite schema version 5. The database was opened read-only for validation and the original file was not modified or included in the patch ZIP.

- SQLite `PRAGMA quick_check`: `ok`.
- SQLite `PRAGMA foreign_key_check`: no violations.
- Catalogue: 45 processed movies, 45 albums and 243 songs.
- All 45 movies have poster/backdrop, IMDb score, display vote count, numeric IMDb vote count and plot summary.
- All 243 songs have at least one media relationship and receive a canonical page; 240 have normalized artist credits, 97 have normalized lyricist relationships.
- Lyrics coverage is 0/243 for both LRC and plain lyrics; `song_genres` has 0 rows.
- Seven albums have a declared `total_tracks` value that differs from connected song rows; 17 movies have a declared `total_songs` value that differs from connected songs. The site calculates displayed track counts from normalized relationships instead of trusting these stale values.
- 94 rows have a `duration_formatted` value that disagrees with `duration_sec`. The generated public model now consistently prefers a valid `duration_formatted` value and derives seconds/milliseconds from it for the UI/search projection. No DB values were written back.

## Build and regression checks

These checks were run with `DATABASE_PATH` set to the uploaded database:

- `python validate_database.py`: passed schema-v5, SQLite integrity, foreign-key, required-column and relationship checks.
- `python build.py`: generated 45 movie pages, 45 album pages, 243 song pages and a generated search index; no database file is copied into public output.
- `python check.py`: passed route/page coverage, internal-link, lyric-fixture, source-JSON-independence, homepage-search and default IMDb-vote-sort regression checks.
- `python check_public_output.py`: passed checks for private database leakage and unreviewed public search fields.
- `node --check static/app.js` and `python -m py_compile build.py db_source.py validate_database.py check.py check_public_output.py`: passed.

The build warns that `SITE_URL` is not set in the local validation environment, so canonical URLs and the sitemap are skipped here. Set `SITE_URL` to the real production domain in Cloudflare Pages. One ambiguous legacy song-ID redirect is skipped intentionally; the canonical song page still builds.

## UI changes included in this patch

- Obsidian-style black/glass dark theme plus a coordinated light/paper theme.
- Dedicated centered homepage catalogue search with live song, album and movie results, followed by the existing catalogue content when the search is empty.
- Restored/explicitly visible Vachika wordmark in the global header and corrected the legacy rotated nav-link styling.
- Default Movies sort is highest numeric IMDb vote count first, including before JavaScript loads; dropdown sort remains functional.
- Song click-to-open details drawer is docked to the right on desktop, measured below the live header height, and causes the header to compact. On smaller screens it remains an overlay drawer. Provider links/actions are placed near the top of the drawer rather than at its bottom.
- Movie cards display rating and vote-count context. Search index includes only the reviewed IMDb score/vote fields needed for UI search/sorting.

A real browser screenshot/viewport interaction pass was not completed for this patch in the current environment because the available headless Chromium process did not start reliably. The assertions above are reproducible build/static/syntax checks, not a claim that the live Cloudflare deployment or third-party media providers were browser-tested. Recheck responsive drawer behavior once deployed or in a normal local browser.

## Deployment architecture retained

The private GitHub SQLite repository remains the source of truth. Cloudflare Pages fetches it during the build; the public site receives generated static pages and reviewed search JSON, never the SQLite file. This patch changes the website repository source and documentation only. It does not change the deployed Cloudflare project, its secrets, or the workflow already installed in the separate private DB repository.
