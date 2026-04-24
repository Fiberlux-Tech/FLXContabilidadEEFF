# Deployment Guide

Staging + production workflow for FLXContabilidad. Both environments run on the **same server** (`10.100.50.4`), distinguished by hostname.

## Environments

| Env     | Hostname                     | Code directory                                  | Branch | Service                            | Backend port |
|---------|------------------------------|-------------------------------------------------|--------|------------------------------------|--------------|
| Prod    | `flx.internal`               | `/home/administrator/FLXContabilidad/`          | `main` | `flxcontabilidad.service`          | 5000         |
| Staging | `flx-staging.internal`       | `/home/administrator/FLXContabilidad-staging/`  | `dev`  | `flxcontabilidad-staging.service`  | 5001         |

Both nginx vhosts listen on port 80; nginx routes by `server_name`. Both read the **same read-only SQL Server** for financial data, but use **separate SQLite auth databases** so logins don't leak between environments:

- Prod auth DB: `/var/lib/flxcontabilidad/users.db`
- Staging auth DB: `/home/administrator/flxcontabilidad-staging-data/users.db`

Each environment has its own `SECRET_KEY`, so a session cookie signed by one is invalid on the other.

## Per-machine setup (one-time, per user)

The hostnames are resolved via `/etc/hosts` — there is no LAN DNS. Each machine that wants to use them needs these two lines:

```
10.100.50.4  flx.internal
10.100.50.4  flx-staging.internal
```

- **macOS / Linux:** `sudo sh -c 'echo "10.100.50.4  flx.internal" >> /etc/hosts && echo "10.100.50.4  flx-staging.internal" >> /etc/hosts'`
- **Windows:** edit `C:\Windows\System32\drivers\etc\hosts` as Administrator and add the two lines.

**If you don't add these**, `http://10.100.50.4` still works for prod (the IP is kept in the prod `server_name`). You only need the hosts entries to browse staging at `http://flx-staging.internal`.

## Golden rules

1. **Never edit code directly on the server.** Edit on laptop → push to GitHub → pull on server.
2. **Never push directly to `main`.** All changes land on `dev` first, get verified in staging, then merge to `main`.
3. **Prod (`main`) always reflects what's running live.** If `git log main` disagrees with the site, something is wrong — investigate, don't paper over it.
4. **Accounting logic changes need extra care.** Re-read [CODING_PATTERNS.md](CODING_PATTERNS.md) "SACRED" section before touching `backend/services/accounting/` or `backend/data/queries.py`.

## Daily workflow

### 1. Make changes on `dev`

On your laptop:
```bash
git checkout dev
git pull origin dev
# edit files, commit
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

Open `http://flx-staging.internal` in a browser. Exercise the changed feature. Check the golden path and at least one edge case. Compare numbers against prod if the change touches reports.

If broken: fix on laptop → push to `dev` → re-run `deploy.sh` on staging. Repeat until good.

### 4. Promote to prod

```bash
# on laptop
git checkout main
git pull origin main
git merge dev
git push origin main
```

(Preferred: open a PR `dev` → `main` on GitHub, review the diff, merge there.)

### 5. Deploy to prod

SSH to the server:
```bash
cd /home/administrator/FLXContabilidad
./deploy.sh
```

Verify `http://flx.internal` loads and the change is live.

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
4. **Never edit files under `/home/administrator/FLXContabilidad/` directly on the server.** Agents make changes on the user's laptop working copy (the one Claude Code is running in) and let the user handle the git push. The server directories exist only for `git pull` + build + restart.
5. **Never bypass staging.** If the user says "push this fix to prod", respond with: "I'll push to `dev` first so it lands in staging — verify at `flx-staging.internal`, then merge `dev` → `main` to release." Only skip staging if the user explicitly overrides with something like "hotfix straight to main, I've already verified".
6. **No `--no-verify`, no force-push to `main`, no `git reset --hard` on `main`.** Ever.
7. **Accounting-logic changes are gated by the SACRED rules** ([CODING_PATTERNS.md](CODING_PATTERNS.md)). Flag them explicitly before committing.
8. **After suggesting a deploy, remind the user of the verification step** ("open `flx-staging.internal` and check X"). Don't mark work complete until the user confirms staging looks right.

## Server-side layout (for reference, already set up)

- **Staging working tree:** `/home/administrator/FLXContabilidad-staging/` on branch `dev`, its own venv at `venv/`
- **Staging systemd unit:** `/etc/systemd/system/flxcontabilidad-staging.service` — same template as prod, pointed at the staging directory and `EnvironmentFile` at the staging `.env`
- **Staging env files:** `/home/administrator/FLXContabilidad-staging/.env` (inherits most keys from prod — distinct `SECRET_KEY`, `SQLITE_DB_PATH`, `APP_ENV=staging`, `GUNICORN_BIND=127.0.0.1:5001`) and `.env.staging` (staging-specific CORS origins)
- **Staging auth DB directory:** `/home/administrator/flxcontabilidad-staging-data/` — owned by `administrator:administrator`, mode `770`
- **Nginx:** `/etc/nginx/sites-available/flx-prod` and `/etc/nginx/sites-available/flx-staging`, both symlinked into `sites-enabled/`. Prod matches `flx.internal`, `10.100.50.4`, `10.100.23.164`; staging matches `flx-staging.internal`
- **`deploy.sh`:** identical script in both working tree roots — infers target service from its own directory name
