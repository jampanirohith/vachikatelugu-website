# vachikatelugu

VachikaTelugu is a static Telugu film-music catalogue for browsing movie soundtracks, albums and songs. The public website is generated from a **private SQLite database** and deployed to Cloudflare Pages. The site build uses Python's standard library; no application server or Python runtime is needed for visitors.

## Features

- Near-black glass styling, responsive layouts, artwork-led detail pages and Vachika branding assets.
- Global search and `/advanced-search/` for searching songs, albums and movies.
- `/songs/`, `/albums/`, `/movies/` and `/charts/` catalogues with filtering and sorting; chart tabs cover songs, albums and movies.
- IMDb-keyed movie pages (`/tt1234567/`) and soundtrack pages (`/tt1234567/album/`), plus stable song pages (`/song/<id>/`).
- Spotify-inspired song drawer on desktop and a sheet on smaller screens, with dedicated full song pages.
- Song metadata such as ISRC, duration, track number, explicit/bonus flags, source, media IDs/views, album release metadata and provider links when available.
- Optional YouTube song video embeds that are click-to-load.
- Movie link dropdowns and OTT-provider buttons based on source metadata. If a source record does not include a title-specific OTT deep link, the button opens a provider search page instead.
- Search-engine metadata and `sitemap.xml` when `SITE_URL` is configured.

## Architecture

```text
Private repo: jampanirohith/telugumoviedb
  └── vachikatelugu.db
          │ fetched in the build using a read-only GitHub token
          ▼
Public repo: jampanirohith/vachikatelugu-website
  ├── fetch_database.py
  ├── validate_database.py
  ├── build.py
  ├── check.py
  └── check_public_output.py
          │
          ▼
Cloudflare Pages publishes dist/
```

The website repository intentionally contains **no database copy and no bundled JSON catalogue**. The SQLite database stays in the private data repository; only the generated public-facing HTML, assets and reviewed search index are deployed. `build.py` is the static-site generator, not a web server.

## Build locally

Prerequisite: Python 3.10+ and access to the private DB through a GitHub fine-grained token, or a local database file.

PowerShell example (do not paste your token into the script or commit it):

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

Open `http://localhost:8000`. Clear the local token when done:

```powershell
Remove-Item Env:GITHUB_TOKEN
```

You can also use a local copy of the database, kept out of Git, by setting `DATABASE_PATH` to its path. Do not commit the DB to this repository.

## Cloudflare Pages deployment

- **Framework preset:** None
- **Root directory:** the directory containing `build.py` (normally the repository root)
- **Build command:**

  ```sh
  python3 fetch_database.py && python3 validate_database.py && python3 build.py && python3 check.py && python3 check_public_output.py
  ```

- **Build output directory:** `dist`
- **Production branch:** `main`

Set regular environment variables `DATABASE_REPO=jampanirohith/telugumoviedb`, `DATABASE_BRANCH=main`, `DATABASE_FILE=vachikatelugu.db` and `SITE_URL=https://your-final-domain.example`. Add `GITHUB_TOKEN` as an encrypted secret: use a fine-grained token restricted to the private data repository with **Contents: Read-only**.

For detailed click-by-click setup, preview-build security guidance and automation steps, see [`CLOUDFLARE_SETUP.md`](CLOUDFLARE_SETUP.md).

## Automatic redeployment after a database update

Cloudflare cannot automatically know that an external private database changed. This project includes a GitHub Actions workflow template at `automation/private-data-repo/notify-vachikatelugu-pages.yml`. Copy it into the private data repo as `.github/workflows/notify-vachikatelugu-pages.yml`, then add a repository Actions secret named `CLOUDFLARE_PAGES_DEPLOY_HOOK` using a Cloudflare Pages deploy-hook URL for the production branch.

On pushes to `main` that change `vachikatelugu.db`, the workflow validates SQLite integrity and the expected data shape. It only calls Cloudflare when validation passes. Cloudflare then rebuilds the website and fetches the latest DB. The workflow can also be run manually. Full instructions: [`automation/private-data-repo/README.md`](automation/private-data-repo/README.md).

## Validation and privacy checks

The production build runs three independent checks after fetching the DB:

1. `validate_database.py` checks SQLite integrity, expected schema, completed movie records and stable song media IDs.
2. `check.py` checks that generated pages, catalogue counts, navigation features and internal links are consistent.
3. `check_public_output.py` checks that the public build contains no database file, sensitive-looking file, common credential pattern, configured GitHub token value, or unreviewed field in `search-index.json`.

The source data must match the collector's expected schema: `movies.raw_json` holds a complete original movie object, including a `songs` list and media IDs for tracks. If a check fails, fix the underlying data/schema mismatch instead of bypassing the check.

## Public data and attribution notes

- Movie/song metadata, play counts, IMDb labels, media IDs and OTT availability are snapshots of the source DB, not live lookups performed by the visitor's browser.
- Missing metadata is omitted rather than invented.
- Album art, posters, backdrops, title logos and video thumbnails load from external providers recorded in the source. Update `_headers` / Content-Security-Policy when intentionally adding another media host.
- Public pages include the fields required to render and search the public catalogue. Do not store credentials, access tokens, private notes or other confidential values in source fields that the site generator uses.

## Key files

| File | Purpose |
| --- | --- |
| `fetch_database.py` | Downloads the DB from the private GitHub repo using an environment secret. |
| `db_source.py` | Opens the DB read-only and loads the canonical movie objects. |
| `validate_database.py` | Validates source DB integrity and the input shape. |
| `build.py` | Generates static HTML and search metadata into `dist/`. |
| `check.py` | Checks page counts, routes, required features and internal links. |
| `check_public_output.py` | Checks that public output does not contain the DB or unreviewed index fields. |
| `static/style.css` | Responsive black-glass styling. |
| `static/app.js` | Search, catalogue filters, charts, theme toggle and song drawer behavior. |
| `static/` and `assets/` | Logo variants, favicons, CSS/JS and source identity artwork. |
| `site.json` | Site name, tagline and optional canonical base URL. |
| `automation/private-data-repo/` | Workflow template and instructions for DB-triggered deployments. |

## Security

Never include API tokens, a `.env` file, `vachikatelugu.db` or Cloudflare deploy-hook URLs in this public repo. If a token was ever pasted into a chat or committed to Git, revoke it and create a replacement. The website's GitHub token must be read-only and limited to the private DB repository.
