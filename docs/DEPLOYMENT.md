# Deployment Guide

Staging + production workflow for FLXContabilidad. Both environments run on the **same server** (`10.100.50.4`), distinguished by port.

## Environments

| Env     | URL                          | Code directory                                  | Branch | Service                            | Nginx port | Backend port |
|---------|------------------------------|-------------------------------------------------|--------|------------------------------------|------------|--------------|
| Prod    | `http://10.100.50.4`         | `/home/administrator/FLXContabilidad/`          | `main` | `flxcontabilidad.service`          | 80         | 5000         |
| Staging | `http://10.100.50.4:8081`    | `/home/administrator/FLXContabilidad-staging/`  | `dev`  | `flxcontabilidad-staging.service`  | 8081       | 5001         |

No per-machine setup is required — both URLs work directly for anyone on the LAN.

Both environments read the **same read-only SQL Server** for financial data, but use **separate SQLite auth databases** so logins don't leak between environments:

- Prod auth DB: `/var/lib/flxcontabilidad/users.db`
- Staging auth DB: `/home/administrator/flxcontabilidad-staging-data/users.db`

Each environment has its own `SECRET_KEY`, so a session cookie signed by one is invalid on the other.

**Staging auth is intentionally minimal — only the `admin` user exists there.** Finance team users live on prod only. Do **not** mirror prod users to staging: the point of the isolation is that staging is a developer sandbox, not a shadow production environment. If you ever need a non-admin account on staging for testing, create it explicitly with `backend/manage.py create-user` in the staging tree — do not copy `users.db` across.

## Golden rules

1. **Always commit before running `./deploy.sh`.** Both working trees may be edited (via SSH / VSCode Remote-SSH), but `git status` must say *"working tree clean"* before deploying. Otherwise the build will bake uncommitted work into the bundle and the running site will be code that doesn't exist in git — impossible to reproduce or roll back.
2. **Never push directly to `main`.** All changes land on `dev` first, get verified in staging, then merge to `main`.
3. **Prod (`main`) always reflects what's running live.** If `git log main` disagrees with the site, something is wrong — investigate, don't paper over it.
4. **Accounting logic changes need extra care.** Re-read [CODING_PATTERNS.md](CODING_PATTERNS.md) "SACRED" section before touching `backend/services/accounting/` or `backend/data/queries.py`.

## Daily workflow

### 1. Make changes on `dev`

Either on a local laptop clone or directly in the staging working tree on the server (via SSH / VSCode Remote-SSH). Either way:
```bash
git checkout dev
git pull origin dev
# edit files
git add -A && git commit -m "..."
git push origin dev
```

### 2. Deploy to staging

SSH to the server:
```bash
ssh administrator@10.100.50.4
cd /home/administrator/FLXContabilidad-staging
./deploy.sh
```

`deploy.sh` runs: `git pull` → `npm ci && npm run build` → `sudo systemctl restart flxcontabilidad-staging`.

### 3. Verify in staging

Open `http://10.100.50.4:8081` in a browser. Exercise the changed feature. Check the golden path and at least one edge case. Compare numbers against prod if the change touches reports.

If broken: fix on laptop → push to `dev` → re-run `deploy.sh` on staging. Repeat until good.

### 4. Promote to prod

Preferred (reviewable): open a PR `dev` → `main` on GitHub, review the diff, merge there.

Alternative (local, for trivial changes):
```bash
# on laptop
git checkout main
git pull origin main
git merge dev
git push origin main
```

### 5. Deploy to prod

SSH to the server:
```bash
cd /home/administrator/FLXContabilidad
./deploy.sh
```

Verify `http://10.100.50.4` loads and the change is live.

## Rollback

If prod breaks after a deploy:
```bash
cd /home/administrator/FLXContabilidad
git log --oneline -5                 # find the last good commit
git checkout <good-commit-sha>
cd frontend && npm run build && cd ..
sudo systemctl restart flxcontabilidad
```

Then fix the bug on `dev`, verify in staging, re-promote. Do **not** leave prod on a detached HEAD long-term — after the fix lands on `main`, `git checkout main && ./deploy.sh`.

## Rules for AI agents

When asked to "deploy", "push to staging", "release", "ship", etc., follow this exactly:

1. **Confirm the target environment.** Ask "staging or production?" if not specified. Default to staging if in doubt.
2. **Never `git push origin main` without explicit user approval in the current turn.** Pushing to `main` is a release action.
3. **Never run `./deploy.sh` in the prod directory without explicit user approval in the current turn.**
4. **Edit only in the staging working tree (`/home/administrator/FLXContabilidad-staging/`), never in the prod tree (`/home/administrator/FLXContabilidad/`).** The prod tree exists only for `git pull` + build + restart. Any code change goes through staging via `dev`. Before running `./deploy.sh` in either tree, always verify `git status` shows a clean tree — uncommitted changes must be committed or stashed first.
5. **Never bypass staging.** If the user says "push this fix to prod", respond with: "I'll push to `dev` first so it lands in staging — verify at `http://10.100.50.4:8081`, then merge `dev` → `main` to release." Only skip staging if the user explicitly overrides with something like "hotfix straight to main, I've already verified".
6. **No `--no-verify`, no force-push to `main`, no `git reset --hard` on `main`.** Ever.
7. **Accounting-logic changes are gated by the SACRED rules** ([CODING_PATTERNS.md](CODING_PATTERNS.md)). Flag them explicitly before committing.
8. **After suggesting a deploy, remind the user of the verification step** ("open `http://10.100.50.4:8081` and check X"). Don't mark work complete until the user confirms staging looks right.

## Server-side layout (for reference, already set up)

- **Staging working tree:** `/home/administrator/FLXContabilidad-staging/` on branch `dev`, its own venv at `venv/`
- **Staging systemd unit:** `/etc/systemd/system/flxcontabilidad-staging.service` — same template as prod, pointed at the staging directory and `EnvironmentFile` at the staging `.env`
- **Staging env files:** `/home/administrator/FLXContabilidad-staging/.env` (inherits most keys from prod — distinct `SECRET_KEY`, `SQLITE_DB_PATH`, `APP_ENV=staging`, `GUNICORN_BIND=127.0.0.1:5001`) and `.env.staging` (staging-specific CORS origins)
- **Staging auth DB directory:** `/home/administrator/flxcontabilidad-staging-data/` — owned by `administrator:administrator`, mode `770`
- **Nginx:** `/etc/nginx/sites-available/flx-prod` (listens on `:80`, serves prod dist, proxies `/api` + `/auth` to `:5000`) and `/etc/nginx/sites-available/flx-staging` (listens on `:8081`, serves staging dist, proxies to `:5001`). Both symlinked into `sites-enabled/`.
- **`deploy.sh`:** identical script in both working tree roots — infers target service and branch from the directory name.
- **Firewall (ufw):** allows incoming `80` (prod) and `8081` (staging). **Any new port exposed to the LAN needs `sudo ufw allow <port>/tcp`** or connections will time out silently.

## Visual distinction between staging and prod

The sidebar header on staging reads **"TEST WEB"** instead of "FLX Contabilidad" so you can tell at a glance which environment you're in. This is driven by `frontend/src/features/dashboard/Sidebar.tsx` reading `import.meta.env.VITE_APP_ENV` at **build time**.

The value comes from **`frontend/.env.local`** in the staging working tree:

```
VITE_APP_ENV=staging
```

This file is gitignored (`.env.*` in root `.gitignore`) so it cannot leak into prod via a merge. Prod's working tree has no `.env.local`, so its build leaves `VITE_APP_ENV` undefined and the sidebar shows "FLX Contabilidad".

If staging ever starts showing "FLX Contabilidad" instead of "TEST WEB", the first thing to check is that `frontend/.env.local` still exists in the staging tree and that `./deploy.sh` was re-run after creating it.

