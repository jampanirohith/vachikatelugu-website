# Install this workflow in the private data repository

This workflow belongs in **`jampanirohith/telugumoviedb`**, not in the public website repository. It validates the committed SQLite database and only then calls Cloudflare Pages' deploy hook.

1. In Cloudflare, open your Pages project → **Settings** → **Builds & deployments** → **Deploy hooks** and create a hook for the production branch (`main`). Copy the hook URL. Treat it like a password.
2. In `jampanirohith/telugumoviedb`, open **Settings → Secrets and variables → Actions → New repository secret**. Name it `CLOUDFLARE_PAGES_DEPLOY_HOOK` and set the value to the URL you copied.
3. Copy `notify-vachikatelugu-pages.yml` from this folder into the private repository at `.github/workflows/notify-vachikatelugu-pages.yml`.
4. Commit/push the workflow. The next push that changes `vachikatelugu.db` on `main` runs the validation and triggers a production deployment. You can also run it manually from that repository's **Actions** tab using **Run workflow**.

The workflow expects `vachikatelugu.db` in the root of the private repo, with `movies.imdb_id`, `movies.title`, `movies.processing_status`, and `movies.raw_json`. Each processed `raw_json` record must contain the complete movie object and its `songs` array. A failed check does not trigger a deployment.

This uses a Cloudflare deploy-hook secret instead of a GitHub token with write permission to the website repo. Keep the deploy-hook URL private. Rotate it in Cloudflare and update the Actions secret if it is exposed.
