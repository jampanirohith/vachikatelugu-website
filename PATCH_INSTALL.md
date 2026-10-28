# Installing the Vachika website patch

## Do not delete files

**Do not delete any existing files or folders before applying this patch.** Unzip `vachikatelugu-complete-patch.zip` into the root of the existing website repository and allow the archive to overwrite files at matching paths. Commit the changed files, review the diff, then deploy through the existing Cloudflare Pages workflow.

The ZIP is a source overlay, not a database backup and not a replacement for the whole repository. It intentionally excludes `dist/`, `.git/`, secrets, `.env` files, the SQLite database, and any downloaded `.build-data/` content. Do not remove `.git`, `.gitignore`, Cloudflare settings, repository settings or unrelated assets. If you are copying files manually, preserve folder paths exactly as they appear in the archive.

## Files changed by this patch

Core code: `build.py`, `static/app.js`, `static/style.css`, `check.py`, `check_public_output.py`, `validate_database.py`.

Documentation/audit: `README.md`, `DATABASE_FIELD_MAPPING.md`, `CLOUDFLARE_SETUP.md`, `VALIDATION_REPORT.md`, `UI_CHANGELOG.md`, `automation/private-data-repo/README.md`, `DATABASE_AUDIT.md`, and this file.

## Database and Cloudflare

- Keep `vachikatelugu.db` in the existing **private** repository. It is not included in this patch ZIP and should not be copied into the public website repository.
- Keep the existing Cloudflare Pages variables/secrets and the private-repository deploy-hook secret in place.
- No database migration is required: the adapter and private workflow already target schema version 5.
- The expected Pages build command remains:

  ```sh
  python3 fetch_database.py && python3 validate_database.py && python3 build.py && python3 check.py && python3 check_public_output.py
  ```

- Set `SITE_URL` to your real production domain in Cloudflare Pages so canonical URLs and sitemap generation are enabled.

## Verification before deployment

Run locally from the website repository root with a copy of the SQLite database available through `DATABASE_PATH`:

```sh
DATABASE_PATH=/path/to/vachikatelugu.db python3 validate_database.py
DATABASE_PATH=/path/to/vachikatelugu.db python3 build.py
DATABASE_PATH=/path/to/vachikatelugu.db python3 check.py
DATABASE_PATH=/path/to/vachikatelugu.db python3 check_public_output.py
node --check static/app.js
python3 -m py_compile build.py db_source.py validate_database.py check.py check_public_output.py
```

Then review the Git diff and run the generated site in a normal browser at desktop and mobile widths, including opening and closing the song drawer. The current patch validation ran database/build/internal-link/privacy/syntax checks, but could not complete a reliable headless Chromium screenshot pass. See `VALIDATION_REPORT.md` for coverage details.


### Follow-up UI patch

This revision also overlays `check_public_output.py` and adds `static/vachika-logo-dark.png`, used as the high-contrast symbol beside the existing wordmark. Do not delete any existing files; allow these matching files to be overwritten.
