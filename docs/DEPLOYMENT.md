# Deployment Guide

Staging + production workflow for FLXContabilidad. Both environments run on the **same server** (`10.100.50.4`), distinguished by hostname.

## Environments

| Env     | Hostname                     | Code directory                                  | Branch | Service                            | Backend port |
|---------|------------------------------|-------------------------------------------------|--------|------------------------------------|--------------|
| Prod    | `flx.internal`               | `/home/administrator/FLXContabilidad/`          | `main` | `flxcontabilidad.service`          | 5000         |
| Staging | `flx-staging.internal`       | `/home/administrator/FLXContabilidad-staging/`  | `dev`  | `flxcontabilidad-staging.service`  | 5001         |

Both nginx vhosts listen on port 80; nginx routes by `server_name`. Both point at the **same database**.

Users must add both hostnames to `/etc/hosts` (or LAN DNS) pointing to `10.100.50.4`.

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

## One-time server setup (for reference, already done)

- Second working tree: `git clone <repo> /home/administrator/FLXContabilidad-staging && cd $_ && git checkout dev`
- Second systemd unit: `/etc/systemd/system/flxcontabilidad-staging.service` (copy of prod unit, port 5001, `WorkingDirectory` pointing at staging dir)
- Nginx: two `server` blocks on port 80, one per `server_name` (`flx.internal`, `flx-staging.internal`), each with its own `root` and `proxy_pass` to the matching backend port
- `/etc/hosts` on each user's machine:
  ```
  10.100.50.4  flx.internal
  10.100.50.4  flx-staging.internal
  ```
- `deploy.sh` in each working tree (identical — it just runs `git pull`, rebuilds, restarts the service matching that directory)
