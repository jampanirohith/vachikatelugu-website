# Production setup: VachikaTelugu + private SQLite database

## Architecture

- The private repository `jampanirohith/telugumoviedb` is the source of truth and holds `vachikatelugu.db`.
- The public repository `jampanirohith/vachikatelugu-website` contains the generator and front-end assets, not the database.
- Cloudflare Pages fetches the SQLite file during a build, validates it, generates the static site into `dist/`, runs link/catalogue checks, and checks that no database or unreviewed search-index fields were published.
- A GitHub Actions workflow in the private data repository validates a pushed DB and calls a Cloudflare deploy hook. This causes Pages to build the current website commit using the latest database.

## 1. Connect Cloudflare Pages to the website repo

1. Open the Cloudflare dashboard → **Workers & Pages** → create a Pages project by importing a Git repository.
2. Select `jampanirohith/vachikatelugu-website` and set the production branch to `main`.
3. Use these build settings:

   - **Framework preset:** None
   - **Root directory:** `/` if `build.py` is at the repository root. If you kept the outer `vachikatelugu/` folder as a directory inside the repository, set Root directory to `/vachikatelugu` instead.
   - **Build command:**

     ```sh
     python3 fetch_database.py && python3 validate_database.py && python3 build.py && python3 check.py && python3 check_public_output.py
     ```

   - **Build output directory:** `dist`

## 2. Add Pages environment variables

Set these ordinary variables on the Pages project:

| Variable | Value |
| --- | --- |
| `DATABASE_REPO` | `jampanirohith/telugumoviedb` |
| `DATABASE_BRANCH` | `main` |
| `DATABASE_FILE` | `vachikatelugu.db` |
| `SITE_URL` | Your real public HTTPS domain, e.g. `https://your-domain.example` |

Add `GITHUB_TOKEN` as an **encrypted secret**, not as a plain variable. Use a fresh GitHub fine-grained token limited to the private `telugumoviedb` repository, with **Contents: Read-only** permission. The token only lets the build fetch the private DB; it must not have write permissions.

Configure the database token for **Production** only where possible. Do not expose it to untrusted preview builds from public pull requests. Disable preview builds for untrusted branches, or ensure any previews using the token only run trusted, reviewed code. A modified build script could otherwise attempt to exfiltrate any secret injected into its environment.

## 3. Automate redeployment when the DB changes

1. In the Pages project, create a **Deploy hook** for the `main` production branch and copy its URL.
2. In the private database repo `jampanirohith/telugumoviedb`, create an Actions repository secret named `CLOUDFLARE_PAGES_DEPLOY_HOOK` and paste the URL into it.
3. Copy `automation/private-data-repo/notify-vachikatelugu-pages.yml` into the private data repo as `.github/workflows/notify-vachikatelugu-pages.yml`.
4. Commit and push this workflow to `main`.

A push that changes `vachikatelugu.db` on `main` will run the database validation. Only a passing validation triggers the Cloudflare Pages deploy hook. Cloudflare then fetches the latest database during the new build. A manual run is available in the private repository's Actions tab.

## 4. Test before publishing

A successful production build must show all of these:

- `Fetched private SQLite database ...`
- `SQLite validation passed ...` with schema version 4 and row counts
- `build.py` reports all processed movies, albums and songs, including songs without media
- `python3 check.py` ends with `ok`
- `Public-output check passed ...`
- Cloudflare reports the deployment as **Success**

If `validate_database.py` fails, do not remove the check to force a deploy. Review the error and confirm the committed database matches normalized schema version 4. The website reads explicit columns and relationship tables; it does not depend on `movies.raw_json`, `albums.raw_json`, `songs.raw_json`, or provider/source JSON blobs. Songs without media IDs or lyrics remain valid and still receive pages. The generated `search-index.json` is derived during the build from normalized DB values, not an external source of truth.

## 5. Security notes

- Never commit the SQLite database, GitHub token, Cloudflare deploy-hook URL, `.env` file, or credentials to the website repository.
- The builder reads SQLite in read-only mode. The downloaded file lives in `.build-data/`, which is ignored by Git and not copied to `dist/`.
- A private-database commit continues to trigger the existing GitHub Actions → Cloudflare Pages deploy-hook workflow. Supabase is not needed for this static publishing pipeline.
- `check_public_output.py` blocks database files, secret-looking files, common credential patterns, the configured `GITHUB_TOKEN` value, and unreviewed fields in `search-index.json`.
- The website intentionally publishes the catalogue metadata needed for the public-facing pages. Do not put genuinely private notes or credentials in the catalog fields used by the page generator.
- Revoke any token ever pasted into a chat or committed to a repository. Create a replacement and update the Cloudflare secret.
