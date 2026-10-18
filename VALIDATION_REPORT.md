# Build, UI and validation report

## Database and catalogue verification

The website was rebuilt using the supplied SQLite snapshot `vachikatelugu(2).db`, schema version 4. The DB was opened read-only and was not included in the project ZIP.

- SQLite `PRAGMA quick_check`: `ok`.
- `PRAGMA foreign_key_check`: no violations.
- Processed catalogue: 4 movies, 4 albums, 25 songs.
- Song credits: 45 normalized artist relationships and 20 normalized lyricist relationships.
- Media coverage: 14 of 25 songs have media records; the other 11 still receive pages.
- Lyrics coverage: this snapshot has no populated LRC/plain lyrics; fixture tests cover LRC, plain and empty lyrics rendering.
- `song_genres` has no rows in this snapshot, so track-level genres and that filter are not fabricated from movie genres.

## Build and safety checks

- `validate_database.py`: passed.
- `build.py`: generated 4 movie pages, 4 album pages and all 25 song pages from normalized tables, plus shared static output.
- `check.py`: passed page/index coverage, internal-link checks, media-independent song page coverage, metadata and lyrics fixture checks, plus source-JSON independence.
- The source-JSON independence test emptied raw/serialized JSON blob columns in a temporary database copy and verified that the normalized catalogue model stayed identical. The original DB was untouched.
- `check_public_output.py`: passed; the private SQLite database and internal source payloads are not published.
- `python -m py_compile ...` and `node --check static/app.js`: passed.
- A build with `SITE_URL=https://vachika.example` verified canonical URL, sitemap and robots output generation. Use the real production domain in Cloudflare settings.

## UI changes and browser checks

- Replaced the old header mark/name with the uploaded transparent Vachika wordmark, added the small MUSIC badge and redesigned navigation/search to follow the supplied Cloudflare Docs header reference.
- Public branding and page-title suffix now use **Vachika**, while repository, SQLite filename and existing deploy-hook pipeline identifiers remain unchanged.
- Default theme is dark for new visitors; an explicit saved light/dark preference is retained and the theme toggle still works.
- Removed the strongly blurred album-cover background from album pages. The hero uses a subtle tonal background and clear, properly constrained cover artwork.
- Filters on songs, albums and movies collapse behind a disclosure summary on mobile and remain open on desktop. Advanced-search options use the same mobile disclosure pattern.
- Unified button shapes and tightened image, grid and long-text constraints to avoid horizontal overflow on narrow screens.
- Browser-rendered layout checks ran at widths 320, 360, 390, 430, 700, 760, 768, 800, 820, 1024, 1280, 1440 and 1920 px. No horizontal overflow or browser-side JavaScript exceptions were found. Mobile filter open/close behavior and live result-count summary updates were tested.
- For deterministic layout checks, remote artwork URLs were replaced in the isolated visual-test fixture with a local placeholder; the actual website code still uses the database's validated artwork URLs. Live third-party image availability was not tested.

## Asset note

The supplied `wordmark.png` is a transparent PNG wordmark rather than an installable font file. It is shipped as `static/vachika-wordmark.png` and used for the website branding. Body text continues to use the existing Anek Telugu web-font stylesheet.

## Deployment architecture retained

The private GitHub SQLite repository remains the source of truth. Its GitHub Action still validates a DB commit and triggers the existing Cloudflare Pages deploy hook. Cloudflare fetches the current private database during the build; visitors are served generated static pages and reviewed search JSON, never the SQLite file. The workflow already installed in the separate private repository cannot be edited from this ZIP, so compare it with the updated template if it still contains older validation rules.
