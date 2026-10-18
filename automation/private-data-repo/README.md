# Install this workflow in the private data repository

This workflow belongs in **`jampanirohith/telugumoviedb`**, not in the website repository. It validates the private SQLite database's normalized schema before calling the Cloudflare Pages deploy hook.

1. In Cloudflare, open your Pages project → **Settings** → **Builds & deployments** → **Deploy hooks**, and create a hook for the production branch (`main`). Copy the hook URL and treat it like a password.
2. In `jampanirohith/telugumoviedb`, open **Settings → Secrets and variables → Actions → New repository secret**. Name it `CLOUDFLARE_PAGES_DEPLOY_HOOK` and set its value to the URL you copied.
3. Copy `notify-vachikatelugu-pages.yml` from this folder into the private repository at `.github/workflows/notify-vachikatelugu-pages.yml`.
4. Commit/push the workflow. A push to `main` that changes `vachikatelugu.db` validates the DB and triggers production deployment only after validation passes. You can also run the workflow manually from the repository's **Actions** tab.

## What the workflow validates

- SQLite `quick_check` and `foreign_key_check`.
- Schema version 4 and the normalized tables/columns the website reads.
- Non-empty processed catalogue, stable unique song IDs, non-empty titles, and song-to-album/movie relationship consistency.
- It deliberately **does not** require Spotify/YouTube IDs, lyrics, or song genres. A song remains a valid catalogue entry even if it cannot currently be played on an external platform.

The website build reads explicit columns and relationships from `movies`, `albums`, `songs`, `artists`, `lyricists`, the junction tables, `song_media`, `movie_genres`, `movie_people`, `movie_links`, and `ott_availability`. It does not depend on `movies.raw_json`, `albums.raw_json`, or `songs.raw_json`.

This uses a Cloudflare deploy-hook secret instead of a GitHub token with write permission to the website repo. Keep the deploy-hook URL private. Rotate it in Cloudflare and update the Actions secret if it is exposed.
