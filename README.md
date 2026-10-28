# Vachika

Vachika is a static Telugu-film-music catalogue for discovering movies, soundtrack albums, songs and credits. The complete SQLite catalogue remains in a **private GitHub repository**; Cloudflare Pages downloads it during a build and publishes generated public pages. Visitors never download or query the private SQLite file.

## What the site provides

- Responsive, artwork-led movie, album and song pages with Vachika branding.
- Global search plus `/advanced-search/` across songs, albums and movies.
- `/songs/`, `/albums/`, `/movies/` and `/charts/` catalogues with filters and sorting.
- Responsive Docs-style header using the transparent Vachika wordmark at `static/vachika-wordmark.png` (a PNG logo asset, not a font file).
- Filter and sort controls stay expanded on desktop and collapse into accessible disclosure panels on mobile; advanced-search options follow the same mobile pattern.
- Album pages use a clean, unblurred artwork-led hero instead of duplicating a heavily blurred album cover in the page background.
- Movie pages using IMDb IDs where available, canonical album pages, and song pages keyed by the database's stable `song_id`.
- Song credits from normalized artist and lyricist relationship tables.
- Clean song metadata: only useful, populated values are shown; provider URLs/IDs are buttons or player links, not metadata rows.
- Optional LRC lyrics rendered as timestamped lines, or plain lyrics when no LRC is present. The section is omitted entirely when both lyric fields are empty. Timestamp display is implemented; synchronized highlighting against an external audio player is not.
- Click-to-load YouTube embeds and Spotify / YouTube Music buttons when valid media records exist.
- Movie credits, release details, source links and OTT availability from relational database tables.
- Canonical URLs, Open Graph metadata, structured data, `sitemap.xml` and `robots.txt` when `SITE_URL` is configured.

## Data and publishing architecture

```text
Private data repository (unchanged source of truth)
  └── vachikatelugu.db (normalized SQLite schema v5)
          │
          │ GitHub Actions validates DB commit
          ▼
Cloudflare Pages deploy hook
          │
          │ Cloudflare build fetches the private DB using a read-only token
          ▼
validate_database.py → build.py → check.py → check_public_output.py
          │
          ▼
Generated public dist/
  ├── static HTML pages (movie / album / every database song)
  ├── static JS/CSS and brand assets
  ├── search-index.json (small, reviewed browser-search projection generated from SQLite)
  └── sitemap.xml / robots.txt / redirects (when configured/needed)
          │
          ▼
Cloudflare CDN serves static files to visitors
```

**No Supabase or live database service is required for this architecture.** Database updates continue to follow the existing private-repo → GitHub Actions → Cloudflare Pages rebuild flow. The SQLite file is used during the build only and is not copied to `dist/`.

### Source-of-truth rules

- Public catalogue content is read from explicit scalar columns in the SQLite file and relational tables such as `movie_genres`, `movie_people`, `movie_links`, `ott_availability`, `song_artists`, `song_lyricists`, `song_media`, and `song_genres`.
- The website does **not** use `movies.raw_json`, `albums.raw_json`, `songs.raw_json`, serialized genre/artist ID arrays, source metadata/status blobs, or serialized provider payloads as content sources.
- The public `search-index.json` is an output generated from normalized SQLite data for browser search; it is not an input/source catalogue. It excludes full lyrics, source payloads, private ingestion fields, database rows and unused technical columns.
- Internal IDs provide stable page routes. A track does not need a Spotify, YouTube Music or YouTube ID to exist or receive a page.
- Missing optional information is omitted, not invented. Missing media, lyrics, artists or song genres are coverage gaps, not reasons to drop a track.
- `source_album_matches`, status/provenance data, timestamps used only for ingestion, raw snapshots, and provider-only IDs with no user-facing purpose stay internal.
- Album/movie aggregate counts are calculated from the actual relationships and songs table rather than trusting denormalized counters that may be stale.

## Build locally

Prerequisites: Python 3.10+ and access to the private database with a GitHub fine-grained read-only token, or a local database file. The project uses Python's standard library; the site needs no server-side Python runtime after deployment.

### Windows PowerShell

```powershell
$secureToken = Read-Host "Paste your read-only GitHub token" -AsSecureString
$env:GITHUB_TOKEN = [System.Net.NetworkCredential]::new("", $secureToken).Password
Remove-Variable secureToken
$env:DATABASE_REPO = "jampanirohith/telugumoviedb"
$env:DATABASE_BRANCH = "main"
$env:DATABASE_FILE = "vachikatelugu.db"
python fetch_database.py
python validate_database.py
python build.py
python check.py
python check_public_output.py
python -m http.server -d dist 8000
```

Open `http://localhost:8000`, then clear the token when finished:

```powershell
Remove-Item Env:GITHUB_TOKEN
```

You can also point the build at a local SQLite file without fetching it:

```powershell
$env:DATABASE_PATH = "C:\path\to\vachikatelugu.db"
python validate_database.py
python build.py
python check.py
python check_public_output.py
```

Do not commit that file to the website repository. `.gitignore` excludes the default downloaded database location and common SQLite sidecars.

## Cloudflare Pages settings

- **Framework preset:** None
- **Root directory:** directory containing `build.py` (normally repository root)
- **Build command:**

  ```sh
  python3 fetch_database.py && python3 validate_database.py && python3 build.py && python3 check.py && python3 check_public_output.py
  ```

- **Build output directory:** `dist`
- **Production branch:** `main`

Set regular variables `DATABASE_REPO=jampanirohith/telugumoviedb`, `DATABASE_BRANCH=main`, `DATABASE_FILE=vachikatelugu.db`, and `SITE_URL=https://your-final-domain.example`. Add `GITHUB_TOKEN` as an encrypted secret, using a fine-grained token restricted to the private data repository with **Contents: Read-only** permission.

See [`CLOUDFLARE_SETUP.md`](CLOUDFLARE_SETUP.md) for detailed setup and preview-build security guidance.

## Trigger a rebuild from the private database repository

The project includes a workflow template at `automation/private-data-repo/notify-vachikatelugu-pages.yml`. Install it in the private database repo at `.github/workflows/notify-vachikatelugu-pages.yml` and add `CLOUDFLARE_PAGES_DEPLOY_HOOK` as a GitHub Actions repository secret.

When `vachikatelugu.db` changes on `main`, the workflow checks SQLite integrity, schema version 5, required normalized tables/columns, non-empty titles, unique stable song IDs, and song/album/movie relationships. It intentionally does not reject songs with no external media IDs or lyrics. Only a validated commit triggers the Cloudflare Pages build, which fetches the database as before. Full steps: [`automation/private-data-repo/README.md`](automation/private-data-repo/README.md).

## Data model coverage

For the complete table-by-table and column-by-column display/visibility policy—including every column in the supplied schema snapshot—see [`DATABASE_FIELD_MAPPING.md`](DATABASE_FIELD_MAPPING.md).

The build reads the relevant values from these schema areas:

- `movies`: title, year, language, IMDb rating/votes, plot, certification/runtime, artwork, trailer and external URLs.
- `movie_genres`, `movie_people`, `movie_links`, `ott_availability`: film genres, credits, external links and streaming availability.
- `albums`: canonical album title, release/label/copyright fields, scalar album artwork, provider links and IDs. When album-specific artwork is not populated, artwork falls back to the linked movie poster and is described accessibly as a fallback.
- `songs`: stable `song_id`, title, track/disc number, duration, lyrics, song flavor, explicit/bonus flags and ISRC for structured metadata where available. Only a curated subset is displayed.
- `artists` + `song_artists` and `lyricists` + `song_lyricists`: normalized credits and their order.
- `song_media`: provider IDs, validated external URLs and play/view snapshots.
- `song_genres`: track-level genres. If this normalized table is empty, the track-genre filter is not shown; movie genres are not incorrectly treated as track genres.
- `schema_metadata`: the adapter explicitly requires schema version `5` so a breaking schema change fails visibly rather than silently dropping data.

Fields reserved for ingestion, provenance, raw source snapshots, internal matching, provider popularity/library flags and normalized-name matching are deliberately not shown on public pages unless a specific user-facing feature later justifies them.

## Validation and security

The production pipeline runs:

1. `validate_database.py` — read-only SQLite integrity, foreign-key, schema-version, required-table and relational checks.
2. `build.py` — uses only the private DB and generates all movie, album and song pages from the normalized relationships. Every valid `songs` row linked to a processed movie and album gets a canonical page, including tracks with no media.
3. `check.py` — checks generated routes/counts against the DB, the search index projection, internal links, metadata UI, lyric rendering and cache-version placeholders.
4. `check_public_output.py` — blocks accidental database copies, SQLite files, unexpected JSON artifacts, common credential patterns and unreviewed search-index fields.

Do not remove a failing check just to deploy. Fix the underlying data/schema or code issue. `fetch_database.py` writes to `.build-data/` and reads the DB in read-only mode; the folder is excluded from Git and never copied into `dist/`.

## Files

| File | Purpose |
|---|---|
| `fetch_database.py` | Fetches the SQLite file from the private GitHub repo using an environment secret. |
| `db_source.py` | Read-only adapter for normalized tables and relationship joins; no source JSON content dependency. |
| `validate_database.py` | Validates schema version, SQLite integrity and relational assumptions. |
| `build.py` | Generates static HTML, a public search projection, redirects and sitemap files. |
| `check.py` | Verifies generated site output against the current SQLite snapshot. |
| `check_public_output.py` | Checks the public build for database/secret leakage and limits search-index fields. |
| `static/app.js` | Search, catalogue filters, chart tabs, theme toggle, drawer and click-to-load media behavior. |
| `static/style.css` | Responsive styling, metadata layout and lyrics display. |
| `_headers` | Security headers, CSP and CDN cache policy. |
| `automation/private-data-repo/` | Workflow template and private-repo install instructions. |

## Security notes

Never commit the SQLite database, `.env` files, GitHub tokens, Cloudflare deploy-hook URLs or service credentials. Use a read-only GitHub fine-grained token limited to the private DB repository. Do not run trusted-secret builds for untrusted public pull requests. If any token or hook URL is exposed, revoke/rotate it and update the relevant secret.
