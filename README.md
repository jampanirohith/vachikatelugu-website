# Vāchika

A static site for Telugu film music: movies, soundtrack albums, songs, credits, lyrics and where to listen. The SQLite catalogue lives in a private GitHub repository. Cloudflare Pages downloads it at build time and publishes plain HTML. Visitors never see the database.

## Pipeline

1. A change to `vachikatelugu.db` lands on `main` of the private data repo (`jampanirohith/telugumoviedb`).
2. The workflow in that repo (`automation/private-data-repo/notify-vachikatelugu-pages.yml`) checks SQLite integrity, schema version 9 and the relational rules. Only a valid commit calls the Cloudflare Pages deploy hook.
3. Cloudflare runs the build command:
   ```sh
   python3 fetch_database.py && python3 validate_database.py && python3 build.py && python3 check.py && python3 check_public_output.py
   ```
   - `fetch_database.py` downloads the DB into `.build-data/` with a read-only token.
   - `validate_database.py` runs read-only integrity, foreign-key, schema and relationship checks, and reports data problems such as album "total length" rows stored as songs.
   - `build.py` reads the DB through `db_source.py` and writes `dist/`: one page per movie, album and song, the list pages, `search-index.json`, `_redirects`, `sitemap.xml`, `robots.txt`.
   - `check.py` compares the output with the DB: page and song counts, index contents, internal links, one `<h1>` per page, song metadata, lyrics and the movies default sort.
   - `check_public_output.py` fails the build if `dist/` contains a database file, a credential pattern, an unexpected JSON file or an index field that is not on its allow-list.
4. Cloudflare serves `dist/` from its CDN.

`.build-data/` and the database are never copied into `dist/`.

## Build locally

Python 3.10 or newer, standard library only.

```sh
export DATABASE_PATH=/path/to/vachikatelugu.db      # or set GITHUB_TOKEN, DATABASE_REPO, DATABASE_BRANCH, DATABASE_FILE and run fetch_database.py
python3 validate_database.py
python3 build.py
python3 check.py
python3 check_public_output.py
python3 -m http.server -d dist 8000
```

On PowerShell use `$env:DATABASE_PATH = "C:\path\to\vachikatelugu.db"` and `python`.

Cloudflare Pages settings: framework preset none, output directory `dist`, production branch `main`. Variables: `DATABASE_REPO`, `DATABASE_BRANCH`, `DATABASE_FILE`, `SITE_URL`, and `GITHUB_TOKEN` (encrypted; fine-grained, Contents read-only on the data repo). Details and preview-build guidance are in [`CLOUDFLARE_SETUP.md`](CLOUDFLARE_SETUP.md).

## What the site does

- **Theme.** Neutral obsidian-black glass in dark mode and a matching warm-white light mode, one orange accent, no blue. The saved choice is applied by `static/theme.js` before first paint.
- **Header.** Logo mark plus the Vāchika wordmark (`static/vachika-*-dark.png` / `-light.png`, swapped with the theme). The search bar carries the type chips and the advanced filters (year range, language, genre, sort) in a popover; Enter or "See all results" opens `/advanced-search/` with the same state in the URL.
- **Song drawer (desktop only, 1100 px and up with a pointer).** Clicking a song opens a panel on the right and the whole page, header included, narrows to make room. Escape or the close button dismisses it. On phones and tablets a song link opens the song page.
- **Home.** Hero with a pointer-tilted album stack and inline search. Trending songs, popular albums and the popular-movies rail reveal as you scroll.
- **Songs, albums, movies.** Filterable and sortable lists. Movies default to the number of IMDb ratings; "Best rated" uses the IMDb weighted-rating formula so a high score from few votes does not rank first.
- **Charts.** Songs and albums by combined YouTube views and YouTube Music plays; movies by rating count or by weighted rating.
- **Song page.** Listen links (Spotify, YouTube Music, YouTube video, each with its own count), lyrics column with hide/show and optional timestamps (choices are remembered), a details card, the film card and the rest of the album.
- **Search index.** `search-index.json` is a reviewed projection of the DB for browser search. It carries no lyrics and no source payloads.

## Which DB content the site uses

| Table | Used for |
|---|---|
| `movies`, `movie_genres`, `movie_people`, `movie_links`, `ott_availability` | Movie pages: poster, backdrop, title logo, trailer, plot, credits, IMDb score and rating count, franchise, links, streaming. |
| `albums` | Album pages and artwork (falls back to the movie poster), release date, label, copyright, UPC, provider links. |
| `songs`, `song_artists`, `song_lyricists`, `artists`, `lyricists` | Song pages: singers, lyricists, track and disc number, duration, ISRC, explicit and instrumental flags, lyrics. |
| `song_media` | Spotify, YouTube Music and YouTube video links and IDs, play and view counts. |
| `song_genres` | Track genre filter; hidden while the table is empty. |
| `schema_metadata` | The build stops if the version is not 9. |

Not published: `raw_json`, `*_source_metadata_json`, `source_status_json`, `audio_features_json`, `spotify_*_json`, `source_album_matches`, enrichment flags, timestamps, and empty columns (`label`, `lrclib_id`, `lyrics_status`, `lyrics_type`, `preview_url`, `popularity`, Spotify library flags).

### Data rules applied at build time

- Rows whose title is a duration (for example `27:08`) are album "total length" lines, not songs, and are skipped.
- Combined play count is YouTube video views plus YouTube Music plays; a missing count adds zero.
- Singers are taken from performer-role credits. Composers and lyricists are not shown as singers.
- `name_aliases.json` maps spelling variants of a person to one display name (for example `Keeravani`, `Chandrabose`). The build warns when two names differ only in spacing or punctuation, so add them to the file.
- OTT duplicates are merged and "X Amazon Channel" entries are shown as the channel they belong to.

## Files

| File | Purpose |
|---|---|
| `fetch_database.py`, `db_source.py`, `validate_database.py` | Download, read and validate the DB. |
| `build.py` | Generates every page and the search index. |
| `check.py`, `check_public_output.py` | Post-build checks described above. |
| `name_aliases.json` | Display-name aliases. |
| `static/theme.js` | Applies the saved theme before paint. |
| `static/style.css`, `static/app.js` | Styling and all behaviour (search, filters, charts, drawer, lyrics, reveal). |
| `static/vachika-*.png`, `favicon.png` | Logo mark, wordmark (dark and light) and favicon. |
| `_headers`, `site.json` | CSP and cache headers; site name, tagline and URL. |
| `automation/private-data-repo/` | Workflow for the private data repo. |
| `assets/vachika-logo-source.png` | Original logo artwork. |

The CSP allows scripts only from the site itself, so there are no inline scripts; that is why the theme script is a separate file. Fonts load from Google Fonts (Fraunces, Manrope, Anek Telugu).

## Security

Never commit the database, `.env` files, tokens or the deploy-hook URL. Use a read-only fine-grained token limited to the data repo, and do not run secret-bearing builds for untrusted pull requests. Rotate anything that leaks.
