"""Cold-load timing measurement for the Phase 2 fact-table design.

Times the operations a gunicorn worker performs the first time it
serves a request for a (company, year) it doesn't have in memory:

    1. read_pickle(df_stmt)          row-level pickle deserialization
    2. read_pickle(preagg variants)  three small aggregated pickles
    3. preaggregate(df_stmt)         what runs if preagg pickles missing

Plus the cost of building the proposed Phase 2 fact aggregate from
df_stmt, which runs once per scheduler cycle (not on the cold-load path)
and replaces both (1) and (3) on the summary path.

Useful in three situations:

  - Before Phase 2 implementation: validate that the cold-load tax is
    dominated by (1) + (3), so shrinking df_stmt is worth doing.
  - During Phase 2 development: spot-check that the new fact pickle is
    much smaller than df_stmt and loads in well under 1 s.
  - After Phase 2 ships: re-run to confirm the predicted user-visible
    win (cold-worker first click <1 s for the big companies).

Read-only. Touches no shared state, does not write any file, does not
affect the running gunicorn service. Calls posix_fadvise(DONTNEED) to
drop the OS page cache for each pickle before timing, so the numbers
reflect a true cold read rather than warm OS cache.

Run from the backend directory of either the staging or prod tree:

    cd backend
    ../venv/bin/python3 scripts/phase2_cold_load_timing.py
"""

import gc
import os
import sys
import time
from pathlib import Path

# Resolve paths relative to this script so it works in any checkout.
HERE = Path(__file__).resolve()
BACKEND = HERE.parent.parent  # backend/scripts/foo.py -> backend/
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "services"))

import pandas as pd  # noqa: E402

CACHE_DIR = BACKEND / "services" / ".stmt_cache"

COMPANIES = ("FIBERLUX", "NEXTNET", "FIBERTECH", "FIBERLINE", "CONSOLIDADO")
YEARS = (2025, 2026)
PREAGG_KINDS = ("preagg", "preagg_ex_ic", "preagg_only_ic")


def _drop_page_cache(path: Path) -> None:
    """Hint the kernel to drop this file from page cache (best-effort)."""
    try:
        fd = os.open(str(path), os.O_RDONLY)
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
        os.close(fd)
    except (AttributeError, OSError):
        pass


def time_call(fn, *args, **kwargs):
    """Time a callable, return (elapsed_seconds, result)."""
    t0 = time.perf_counter()
    result = fn(*args, **kwargs)
    return time.perf_counter() - t0, result


def measure_one(company: str, year: int) -> dict:
    out = {"company": company, "year": year}

    df_path = CACHE_DIR / f"df_stmt_{company}_{year}.pkl"
    if not df_path.exists():
        out["error"] = "df_stmt pickle missing"
        return out
    out["df_stmt_size_mb"] = df_path.stat().st_size / (1024 * 1024)

    _drop_page_cache(df_path)
    gc.collect()
    elapsed, df_stmt = time_call(pd.read_pickle, df_path)
    out["t_read_df_stmt"] = elapsed
    out["df_stmt_rows"] = len(df_stmt)

    preagg_times = {}
    for kind in PREAGG_KINDS:
        p = CACHE_DIR / f"{kind}_{company}_{year}.pkl"
        if not p.exists():
            preagg_times[kind] = None
            continue
        _drop_page_cache(p)
        elapsed, _ = time_call(pd.read_pickle, p)
        preagg_times[kind] = elapsed
    out["t_read_preagg_total"] = sum(v for v in preagg_times.values() if v is not None)
    out["t_read_preagg_breakdown"] = preagg_times

    from accounting.aggregation import preaggregate
    from config.fields import IS_INTERCOMPANY

    elapsed, _ = time_call(preaggregate, df_stmt)
    out["t_recompute_preagg"] = elapsed
    elapsed, _ = time_call(preaggregate, df_stmt[~df_stmt[IS_INTERCOMPANY]])
    out["t_recompute_preagg_ex_ic"] = elapsed
    elapsed, _ = time_call(preaggregate, df_stmt[df_stmt[IS_INTERCOMPANY]])
    out["t_recompute_preagg_only_ic"] = elapsed
    out["t_recompute_total"] = (
        out["t_recompute_preagg"]
        + out["t_recompute_preagg_ex_ic"]
        + out["t_recompute_preagg_only_ic"]
    )

    # Cost of the proposed Phase 2 fact-aggregate build (runs on the
    # scheduler, not on the cold-load path).
    grain_cols = [c for c in ("CIA", "ANIO", "MES", "CUENTA_CONTABLE", "CENTRO_COSTO")
                  if c in df_stmt.columns]
    sum_cols = [c for c in ("DEBITO_LOCAL", "CREDITO_LOCAL") if c in df_stmt.columns]
    if grain_cols and sum_cols:
        elapsed, fact = time_call(
            lambda: df_stmt.groupby(grain_cols, observed=True, sort=False)[sum_cols].sum().reset_index()
        )
        out["t_build_fact_aggregate"] = elapsed
        out["fact_rows"] = len(fact)
    else:
        out["t_build_fact_aggregate"] = None
        out["fact_rows"] = None

    return out


def main():
    print(f"Cold-load timing  |  .stmt_cache/ at {CACHE_DIR}")
    print(f"pandas {pd.__version__}, python {sys.version_info.major}.{sys.version_info.minor}")
    print()

    rows = []
    for company in COMPANIES:
        for year in YEARS:
            print(f"  measuring {company}/{year}...", flush=True)
            rows.append(measure_one(company, year))

    print()
    fmt = "{:<14}{:>6}{:>10}{:>10}{:>10}{:>10}{:>10}{:>10}{:>10}"
    print(fmt.format(
        "company", "year",
        "size_MB", "rows_M",
        "read_s", "preagg_s", "recompS",
        "factRows", "factAgg_s",
    ))
    print("-" * 100)
    for r in rows:
        if "error" in r:
            print(f"{r['company']:<14}{r['year']:>6}  ({r['error']})")
            continue
        print(fmt.format(
            r["company"], r["year"],
            f"{r['df_stmt_size_mb']:.0f}",
            f"{r['df_stmt_rows']/1e6:.2f}",
            f"{r['t_read_df_stmt']:.2f}",
            f"{r['t_read_preagg_total']:.2f}",
            f"{r['t_recompute_total']:.2f}",
            f"{r.get('fact_rows', 0) or 0}",
            f"{r['t_build_fact_aggregate']:.2f}" if r.get("t_build_fact_aggregate") is not None else "n/a",
        ))

    print()
    print("Legend:")
    print("  size_MB    df_stmt pickle on disk (today's row-level)")
    print("  rows_M     millions of rows in df_stmt")
    print("  read_s     pd.read_pickle(df_stmt) cold-cache  <-- the user-visible tax today")
    print("  preagg_s   pd.read_pickle of the 3 preagg variants")
    print("  recompS    re-aggregate preaggs from df_stmt if those pickles are missing")
    print("  factRows   rows in the proposed Phase 2 fact aggregate (~75-300x smaller than df_stmt)")
    print("  factAgg_s  cost of building the fact aggregate (runs on the scheduler, not cold-load)")
    print()
    print("Today's cold-load tax = read_s + recompS (worst case, if preagg pickles missing).")
    print("After Phase 2, the summary path reads the small fact pickle instead of df_stmt,")
    print("so both terms collapse to a sub-second read.")


if __name__ == "__main__":
    main()
