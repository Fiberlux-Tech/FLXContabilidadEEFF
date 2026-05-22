# Concurrency & Scaling — Historical Postmortems

> **Status**: This document is a frozen record of two May 2026 incidents. The active scaling roadmap lives in [SCALING_ROADMAP.md](SCALING_ROADMAP.md) — start there for any new performance work. Tier 1 fixes described below shipped 2026-05-12; Tier 2/3 plans that previously lived here are **superseded** by SCALING_ROADMAP.md and have been removed.
>
> **Last updated**: 2026-05-14.

## Why this document exists

Two incidents within a week exposed concurrency limits in the original architecture. Both fixes shipped, but the failure modes and OOM analysis are worth keeping for future capacity planning.

---

## Incident 1 — 2026-05-05: Query timeout under concurrent load

On 2026-05-05 12:35 PE, a user (Cesar) hit the following error loading FIBERTECH/2026:

> `Failed to fetch data for FIBERTECH/2026: Execution failed on sql ... Query timeout expired (0)`

A second user-facing failure followed at 12:54 PE on the detail dialog. Both errors trace back to the same root cause: **the SQL Server query against `REPORTES.VISTA_ANALISIS_CECOS` exceeded `DB_QUERY_TIMEOUT=120s`** (configured in `.env`).

### What the investigation proved

1. **The query itself is fast under no load.** Re-running the exact failing SQL: 1.0s for the detail query, 1.8s for a P&L full year, ~5s for an 8-query worst case from a single client.
2. **Concurrent users multiply query time dramatically.**
   - 1 user (solo): ~2s per query
   - 2 users at once: ~41s per query (~20× slowdown)
   - 4+ users at once: extrapolates past 120s → **timeout**
3. **Server logs confirm the pattern.** During the failure window (`2026-05-05 17:35–19:37 UTC`), five separate `HYT00 Query timeout expired` errors landed within ~2 hours. Each was preceded by a cache miss that forced a fresh DB fetch.
4. **Multi-process Gunicorn deploys make it worse.** We run 3 sync workers, each with its own in-memory cache. When 3 users land on 3 different workers, each worker fires its own DB query — 3× the load for the same data.

### Architecture at the time

```
nginx (10.100.50.4:80)
   │
   ▼
Gunicorn (3 sync workers, port 5000)         <-- each worker has its OWN _caches dict
   │
   ▼
backend/services/data_service.py
  • In-memory LRU+TTL cache (per worker)
  • Disk cache: backend/services/.stmt_cache/*.pkl (shared across workers)
   │
   ▼
backend/data/fetcher.py
  • ThreadPoolExecutor(max_workers=5)         <-- per-request parallelism
  • Submits up to 4 queries per Resumen load
   │
   ▼
backend/data/db.py
  • pyodbc connection pool (size 8 per worker)
  • DB_QUERY_TIMEOUT=120s
   │
   ▼
SQL Server 192.168.30.118 — REPORTES.VISTA_ANALISIS_CECOS (~8.4M rows)
```

Key facts:

- A single `Resumen` load fires **2 parallel queries** (P&L full year + BS cumulative) when `need_pdf=False`. With prev-year data needed it's **4**.
- Each Gunicorn worker is a **separate Python process** with its own in-memory caches. The disk cache is the only shared layer.
- The detail endpoint forces a fresh fetch when the in-memory cache misses — so post-deploy, the first user to click a detail row hits the DB.
- We do **not** own the SQL Server. The view is shared with other consumers; index changes require DBA coordination.

### What shipped (2026-05-12)

Two fixes, summarized here. Implementation details live in the code (no separate doc page).

**Tier 1.1 — DB_QUERY_TIMEOUT 120s → 300s.** Legitimate (non-timed-out) queries can run 150–360s under DB load; 300s gives them headroom without leaving truly hung connections open forever. Change is a single line in `.env`.

**Tier 1.3 — Single-flight deduplication of concurrent fetches.** Two layers:
- *In-process* (per worker): a per-`(company, year, kind)` `threading.Lock` in `backend/services/data_service.py` ensures only one thread per worker triggers a DB fetch; siblings wait and read the freshly-populated cache.
- *Cross-process* (across the 3 workers): a `fcntl.flock` on `/tmp/flx_inflight_<company>_<year>_<kind>.lock` serializes across workers. The winning worker writes the disk cache; losing workers block on the flock and then read from disk.

### Outcome

Realistic concurrency capacity went from **"3 simultaneous cold-cache users will fail"** to **"~10 simultaneous cold-cache users serialize cleanly on a single DB query, no timeouts."** The DB is hit on `force_refresh=True` and on the very first call per `(company, year)` after a deploy — that first call is bounded by the new 300s pyodbc timeout and coalesces concurrent users via single-flight.

### How to reproduce the failure (for regression testing)

```bash
# From the FLXContabilidad directory, with venv activated
./venv/bin/python <<'PY'
import sys, os, time
sys.path.insert(0, 'backend'); sys.path.insert(0, 'backend/services')
from dotenv import load_dotenv
load_dotenv('.env')
from data.db import connect
from datetime import date
from concurrent.futures import ThreadPoolExecutor

def run(label, prefixes, start, end, cia='FIBERTECH'):
    sql = ("SELECT CIA, CUENTA_CONTABLE, DESCRIPCION, NIT, RAZON_SOCIAL, "
           "CENTRO_COSTO, DESC_CECO, FECHA, DEBITO_LOCAL, CREDITO_LOCAL, ASIENTO "
           "FROM REPORTES.VISTA_ANALISIS_CECOS "
           "WHERE CIA = ? AND FECHA >= ? AND FECHA < ? "
           "AND (" + " OR ".join("CUENTA_CONTABLE LIKE ?" for _ in prefixes) + ") "
           "AND FUENTE NOT LIKE 'CIERRE%'")
    params = [cia, start, end] + [f"{p}%" for p in prefixes]
    with connect() as c:
        cur = c.cursor()
        t0 = time.time()
        cur.execute(sql, params)
        n = sum(1 for _ in cur)
        return label, n, time.time() - t0

# Simulate 4 concurrent users on FIBERTECH (8 queries total)
jobs = []
for i in range(4):
    jobs.append((f"u{i} PNL", ('6','7','8'), date(2026,1,1), date(2027,1,1)))
    jobs.append((f"u{i} BS",  ('1','2','3','4','5'), date(2026,1,1), date(2026,5,1)))

with ThreadPoolExecutor(max_workers=8) as pool:
    for f in [pool.submit(run, *j) for j in jobs]:
        try:
            label, n, dt = f.result()
            mark = " ← OVER 120s" if dt > 120 else (" ← OVER 60s" if dt > 60 else "")
            print(f"{label}: {n:>7} rows in {dt:6.2f}s{mark}")
        except Exception as e:
            print("FAIL:", str(e)[:200])
PY
```

Expected behavior:
- **Pre-fix**: queries take 40–80s; some hit `Query timeout expired`.
- **Post-Tier 1.1 + 1.3**: only 2 unique queries actually run (single-flight absorbs the rest); test completes in ~5s.

---

## Incident 2 — 2026-05-12: Warmup OOM (Tier 1.2, reverted same-day)

**Outcome**: Implemented warmup as `backend/services/warmup.py` + gunicorn `post_worker_init` hook. Ran successfully on staging, then OOM-killed prod twice within an hour (16:05 and 16:07 PE). Reverted entirely the same day. **Do not re-attempt on this hardware.**

### Why it failed

The prod server is 5.8 GB RAM + 3.8 GB swap. Warmup loaded `df_stmt` for all 5 companies (FIBERLINE / FIBERLUX / FIBERTECH / NEXTNET / CONSOLIDADO) × current year, plus prev-year via the existing `_prefetch_prev_year_background` chain triggered by each `load_pl_data` call.

- CONSOLIDADO_2025 alone is 269 MB on disk → ~600 MB in memory
- CONSOLIDADO_2026 is 98 MB → ~200 MB
- 4 real companies × 2 years adds ~1.5 GB more

With 3 gunicorn workers (only 1 warms, but the other 2 still consume RAM), nginx, and the OS, peak memory hit 5.2 GB and the OOM killer terminated gunicorn mid-warmup. Systemd auto-restarted the service, the new worker started warmup again, and the cycle repeated.

> **Note**: CONSOLIDADO was retired as a company after this incident; current prod is the 4 real companies only. The `df_stmt_CONSOLIDADO_*.pkl` files on disk are residue. Memory math above is preserved as the historical record of *why* warmup OOM'd.

### Why the natural cache works fine without warmup

`load_pl_data` already triggers `_prefetch_bs_background`, `_prefetch_prev_year_background`, and `_prefetch_pl_sections_background` on the first request for any `(company, year)`. Combined with the Tier 1.3 single-flight, the first user pays a bounded wait (~10–30s for an uncached company under the 300s timeout) and every subsequent user gets the cache. The LRU+TTL also evicts entries users aren't touching, so memory tracks actual usage rather than theoretical worst case — exactly the property warmup deliberately fought.

### What to do if first-user latency ever becomes a real complaint

**Don't bring warmup back.** Add a tiny post-deploy cron that issues one HTTP request per company *serially* (e.g. `curl -s -X POST .../api/data/load-pl ...` once for each of the 4 companies). The cron user pays the cost, the existing background prefetch chain warms BS + prev-year + sections, and memory peaks at ~one-company-worth instead of all-at-once because the requests are sequential.

### Constraint that fell out of this incident

The 5.8 GB RAM ceiling is now a first-class design constraint. Any future change that loads multiple companies' DataFrames into memory simultaneously must be evaluated against it. See [SCALING_ROADMAP.md](SCALING_ROADMAP.md) for the active capacity plan that governs this.
