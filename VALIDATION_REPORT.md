# Build and validation report

## Verified against the supplied SQLite snapshot

The website was rebuilt from the uploaded `vachikatelugu(2).db` using the normalized schema-v4 adapter. The original database file was opened read-only and was not modified. It is not included in this website package.

Database checks:

- SQLite `PRAGMA quick_check`: `ok`.
- `PRAGMA foreign_key_check`: no violations.
- Schema version: `4`.
- Processed catalogue: 4 movies, 4 albums, 25 songs.
- Song credits: 45 normalized artist relationships and 20 normalized lyricist relationships.
- Media coverage: 14 of 25 songs have media records; 11 songs do not have a track-level media link and are still valid pages.
- Lyrics coverage: no songs in this snapshot currently have `lrc_lyrics` or `plain_lyrics` populated. The display path is covered by fixture tests.
- Track genres: `song_genres` is currently empty; the track-level genre filter is hidden rather than pretending movie genres are track genres.

Build and public-output checks:

- `python -m py_compile db_source.py build.py validate_database.py check.py check_public_output.py`: passed.
- `validate_database.py`: passed.
- `build.py`: generated all 4 movie pages, 4 album pages and all 25 song pages; emitted 51 files including static assets and the derived search index.
- `check.py`: validates exact page/index coverage, legacy redirects and internal links; verifies metadata is clean and missing song media does not remove pages; exercises LRC/plain/empty-lyrics fixtures; copies the supplied database to a temporary file, replaces raw and serialized JSON source columns with empty JSON values, and verifies that the normalized website model remains unchanged.
- `check_public_output.py`: passed. No SQLite database or other private database file was copied to `dist/`; the public search index contains only allow-listed fields.
- `node --check static/app.js`: passed where Node.js is available.
- Private-repository workflow: checked for normalized schema validation and continued deploy-hook behaviour. The workflow still triggers the existing Cloudflare Pages build only after the database commit validates.

## Important notes

- The website generator reads catalogue content from scalar database columns and normalized relationship tables. It does **not** consume `movies.raw_json`, `albums.raw_json`, `songs.raw_json`, or JSON-valued provider/source blobs.
- `search-index.json` is still produced as a **derived public build artifact** from normalized database data, because the static browser search needs a client-side index. It is not an input/source of truth and is not fetched from your database repository.
- The private DB fetch mechanism and GitHub Actions → Cloudflare Pages deploy-hook pipeline are retained.
- This workspace cannot inspect the live private repository settings, GitHub secrets, Cloudflare project configuration or production deployment. Those must remain configured in the user's accounts as described in `CLOUDFLARE_SETUP.md`.
- The build was tested against the uploaded database snapshot. On deployment, the validators must pass against the exact latest DB fetched from the private repository.
