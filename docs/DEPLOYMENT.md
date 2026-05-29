# Deployment Guide

Single-environment workflow for FLXContabilidad. Prod runs on `10.100.50.4` as the `flxcontabilidad.service` systemd unit (Gunicorn on `127.0.0.1:5000`, Nginx on `:80`). Pre-prod validation happens on a developer laptop clone against the same read-only SQL Server over VPN/LAN — there is no server-side staging tier (decommissioned 2026-05-29; see [SQL_VIEWS_ROADMAP.md Phase C+1](SQL_VIEWS_ROADMAP.md)).

## Environment

| Env  | URL                  | Code directory                         | Branch | Service                   | Nginx port | Backend port |
|------|----------------------|----------------------------------------|--------|---------------------------|------------|--------------|
| Prod | `http://10.100.50.4` | `/home/administrator/FLXContabilidad/` | `main` | `flxcontabilidad.service` | 80         | 5000         |

Auth DB: `/var/lib/flxcontabilidad/users.db` (SQLite).

## Golden rules

1. **Always commit before running `./deploy.sh`.** The prod tree is edited directly (via SSH / VSCode Remote-SSH), but `git status` must say *"working tree clean"* before deploying. Otherwise the build will bake uncommitted work into the bundle and the running site will be code that doesn't exist in git — impossible to reproduce or roll back.
2. **`main` always reflects what's running live.** If `git log main` disagrees with the site, something is wrong — investigate, don't paper over it.
3. **Accounting logic changes need extra care.** Re-read [CODING_PATTERNS.md](CODING_PATTERNS.md) "SACRED" section before touching `backend/services/accounting/` or `backend/data/queries.py`.

## Daily workflow

### 1. Make changes

Edit either on a local laptop clone or directly in the prod working tree on the server (via SSH / VSCode Remote-SSH). Either way, commit and push to `main` before deploying:

```bash
git checkout main
git pull --ff-only origin main
# edit files
git add <specific paths>
git commit -m "..."
git push origin main
```

### 2. Deploy

SSH to the server (or stay in the prod tree if you edited there):

```bash
cd /home/administrator/FLXContabilidad
./deploy.sh
```

`deploy.sh` runs: `git fetch + checkout main + pull --ff-only` → `npm ci && npm run build` → `sudo systemctl restart flxcontabilidad`. It also tails the error log if the service fails to come up.

### 3. Verify

Open `http://10.100.50.4` in a browser. Exercise the changed feature — golden path and at least one edge case. Compare numbers against a known-good baseline if the change touches reports.

If broken, see Rollback.

## Rollback

If prod breaks after a deploy:

```bash
cd /home/administrator/FLXContabilidad
git log --oneline -5                 # find the last good commit
git checkout <good-commit-sha>
cd frontend && npm run build && cd ..
sudo systemctl restart flxcontabilidad
```

Then fix the bug, push to `main`, and re-deploy. Do **not** leave prod on a detached HEAD long-term — after the fix lands on `main`, `git checkout main && ./deploy.sh`.

## Rules for AI agents

When asked to "deploy", "release", "ship", etc., follow this exactly:

1. **Never `git push origin main` or run `./deploy.sh` without explicit user approval in the current turn.** Both are release actions.
2. **Before running `./deploy.sh`, verify `git status` shows a clean tree.** Uncommitted changes must be committed (or stashed) first — see Golden rule 1.
3. **No `--no-verify`, no force-push to `main`, no `git reset --hard` on `main`.** Ever.
4. **Accounting-logic changes are gated by the SACRED rules** ([CODING_PATTERNS.md](CODING_PATTERNS.md)). Flag them explicitly before committing.
5. **After suggesting a deploy, remind the user of the verification step** ("open `http://10.100.50.4` and check X"). Don't mark work complete until the user confirms the site looks right.

## Server-side layout (for reference, already set up)

- **Working tree:** `/home/administrator/FLXContabilidad/` on branch `main`, venv at `venv/`
- **systemd unit:** `/etc/systemd/system/flxcontabilidad.service` — `EnvironmentFile` at the prod `.env`
- **Env files:** `/home/administrator/FLXContabilidad/.env` (shared defaults) + `.env.production` (prod-specific overrides — `GUNICORN_BIND=127.0.0.1:5000`, etc.)
- **Auth DB directory:** `/var/lib/flxcontabilidad/` — `users.db` lives here
- **Nginx:** `/etc/nginx/sites-available/flx-prod` (listens on `:80`, serves `frontend/dist/`, proxies `/api` + `/auth` to `127.0.0.1:5000`). Symlinked into `sites-enabled/`.
- **`deploy.sh`:** prod-tree script — pulls `main`, builds the frontend, restarts the service. Errors out if invoked from any other directory name.
- **Firewall (ufw):** allows incoming `80`. Any new port exposed to the LAN needs `sudo ufw allow <port>/tcp` or connections will time out silently.
