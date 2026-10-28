# Vachika UI and responsive-layout changes

This change set refreshes the public site's branding and layout while preserving the SQLite-at-build-time architecture and private repository deployment trigger.

## Branding and header

- Changed the public site name and SEO title suffix to **Vachika**.
- Added `static/vachika-wordmark.png` using the provided transparent Vachika wordmark image.
- Added a small `MUSIC` label next to the wordmark, a dividing line, text-first navigation, a compact search control, an Advanced Search link and a theme button inspired by the Cloudflare Docs screenshot.
- Made the header adapt to desktop, tablet, phone and narrow-phone widths. On narrow screens the navigation is horizontally scrollable rather than forcing the page wider than the viewport.
- Set the default first-visit theme to dark, while retaining visitors' saved explicit theme choice.

## Layout and responsive behavior

- Normalized the content width and page gutters and applied defensive min-width/overflow handling to page grids, artwork, track rows and long metadata.
- Standardized button radius, spacing, line-height, hover/focus and disabled appearance.
- Made the song, album and movie catalogue filters collapsible below 800px. They stay expanded on larger screens. Their current result counts are mirrored into their summary labels.
- Made Advanced Search's type/date/sorting options a separate collapsible disclosure on narrower layouts, while keeping the query and submit action visible.
- Ensured collapsed native `<details>` content remains hidden, and kept the disclosures keyboard-operable.
- Redesigned album detail hero sections with a restrained tonal background, crisp artwork, constrained text and responsive action buttons. Removed the previous blurred enlarged-artwork background treatment.
- Tuned album track lists, cards, metadata wrapping and footer spacing for small screens down to 320px.

## Kept intact

- The private SQLite database remains fetched during the Cloudflare Pages build; it is not included in the project archive or public `dist` output.
- The existing private-repository GitHub Actions → Cloudflare Pages deploy-hook pattern remains in place.
- The normalized SQLite tables remain the website catalogue source; this UI pass does not restore `movies.raw_json` as a content dependency.
- Song pages, media buttons, clean metadata, lyricist credits and conditional LRC/plain-lyrics sections remain in place from the database-integration update.

## Asset clarification

The supplied asset is a transparent PNG wordmark, not an installable font file. It is used as the brand mark in the header. Existing website text fonts are retained.

## Verification

Using the supplied database snapshot and a clean build, checks passed for database schema/integrity, site generation, internal links, public-output privacy, Python syntax and JavaScript syntax. Browser layout and interaction checks ran at viewport widths 320, 360, 390, 430, 700, 760, 768, 800, 820, 1024, 1280, 1440 and 1920 pixels. No horizontal page overflow or browser-side JavaScript exceptions were observed. Mobile filter open/close behavior, Advanced Search option collapse and live result-count summaries were tested.

Browser-only visual fixtures use placeholder artwork to avoid reliance on third-party network images. Real artwork URLs in the production output are unaffected. Production domain/Cloudflare configuration and the workflow installed in the separate private repository are not changed by this source archive.


## 2026-10-28: catalogue search, IMDb ordering and glass drawer pass

- Defaulted the Movies page to descending numeric IMDb vote count and rendered the same order into static HTML for no-JavaScript and first-paint correctness. Added vote-count display to movie cards and vote fields to the reviewed public search projection.
- Added centered live homepage search covering songs, albums and movies, with the existing homepage sections restored when the query is cleared.
- Applied a coordinated Obsidian-black glass dark palette and clean paper light palette across common controls/cards; made header wordmark visibility explicit and neutralized legacy rotated nav links.
- Docked song detail drawer below the measured header on desktop, compacted the header while the drawer is open, preserved overlay mode on smaller screens, and moved provider actions toward the top of the drawer.
- Normalized displayed and indexed duration seconds/milliseconds from valid `duration_formatted` values without rewriting the DB.
- Added regression assertions for home search and static IMDb vote ordering. This patch's current environment did not permit a reliable headless Chromium visual run; refer to `VALIDATION_REPORT.md` for the exact checks run and remaining caveat.
