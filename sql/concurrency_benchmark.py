"""Concurrent-user benchmark for P&L data loading.

Measures the SQL+pandas path under simulated concurrency. Used to capture
BEFORE/AFTER numbers for the VISTA_PNL_PREPARADO migration (see
docs/SQL_VIEWS_ROADMAP.md Phase A).

Two orthogonal axes:
  --mode {direct,http}
    direct: calls load_pl_data() in N threads via ThreadPoolExecutor.
            Bypasses Flask/gunicorn/auth. Isolates SQL+pandas time.
            force_refresh=True so each call bypasses cache.
    http:   POSTs /api/data/load-pl from N threads against --base-url.
            Picks up gunicorn dispatch + orjson + auth. Caveat:
            force_refresh is silently dropped at the HTTP layer
            (routes.py:133), so "cold" HTTP runs are only really cold
            on the FIRST run after a backend restart or cache TTL expiry.

  --variant {same,cold}
    same: all N workers target (FIBERLUX, 2026). Measures
          single-flight/cache coalescing — should be ~1 actual fetch.
    cold: N workers target N distinct (CIA, year) tuples from a pool of 12.
          Stresses real concurrent DB fetches.

Usage:
  # Before the wiring change:
  venv/bin/python sql/concurrency_benchmark.py --mode direct --variant cold --n 5 \\
      --out bench_before_direct_cold.json

  # After:
  venv/bin/python sql/concurrency_benchmark.py --mode direct --variant cold --n 5 \\
      --out bench_after_direct_cold.json

  # Compare:
  venv/bin/python sql/concurrency_benchmark.py \\
      --compare bench_before_direct_cold.json bench_after_direct_cold.json
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import statistics
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path


# ── Setup paths for `direct` mode ────────────────────────────────────────────
# We do this at import so direct-mode imports work; http-mode tolerates the
# imports failing (e.g. when the benchmark host can't talk to the DB).

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "backend"))
sys.path.insert(0, str(_PROJECT_ROOT / "backend" / "services"))


COMPANIES = ("FIBERLINE", "FIBERLUX", "FIBERTECH", "NEXTNET")
YEARS = (2024, 2025, 2026)
COLD_POOL = [(c, y) for c in COMPANIES for y in YEARS]   # 12 tuples
SAME_TUPLE = ("FIBERLUX", 2026)


# ── Worker functions ─────────────────────────────────────────────────────────

def _direct_worker(barrier: threading.Barrier, company: str, year: int) -> dict:
    """Direct call to load_pl_data, force_refresh=True."""
    # Late import so http-mode users don't pay for DB module load
    from config.env_loader import load_env_config
    load_env_config(str(_PROJECT_ROOT))
    from data_service import load_pl_data, invalidate_cache  # noqa: E402

    # Wipe in-process cache for this tuple so we always exercise the fetch
    # path. force_refresh=True at the data_service layer also does this, but
    # belt-and-suspenders.
    invalidate_cache(company, year)

    barrier.wait()                 # all workers start simultaneously
    t0 = time.perf_counter()
    try:
        result = load_pl_data(company, year, force_refresh=True)
        elapsed = time.perf_counter() - t0
        return {
            "company": company, "year": year, "ok": True,
            "elapsed_ms": round(elapsed * 1000, 1),
            "row_counts": {k: (len(v) if hasattr(v, "__len__") else None)
                            for k, v in result.items() if not k.startswith("_")},
        }
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        return {
            "company": company, "year": year, "ok": False,
            "elapsed_ms": round(elapsed * 1000, 1),
            "error": f"{type(exc).__name__}: {exc}",
        }


def _http_login(session, base_url: str, username: str, password: str) -> None:
    """Acquire a session cookie via /auth/login."""
    r = session.post(
        f"{base_url}/auth/login",
        json={"username": username, "password": password},
        timeout=10,
    )
    r.raise_for_status()


def _http_worker(barrier: threading.Barrier, base_url: str, session,
                 company: str, year: int) -> dict:
    """POST /api/data/load-pl with the shared session cookie."""
    barrier.wait()
    t0 = time.perf_counter()
    try:
        r = session.post(
            f"{base_url}/api/data/load-pl",
            json={"company": company, "year": year},
            timeout=120,
        )
        elapsed = time.perf_counter() - t0
        ok_ = r.ok
        backend_timing = None
        try:
            body = r.json()
            if isinstance(body, dict) and "data" in body and isinstance(body["data"], dict):
                backend_timing = body["data"].get("_timing_ms")
        except Exception:
            pass
        return {
            "company": company, "year": year, "ok": ok_,
            "elapsed_ms": round(elapsed * 1000, 1),
            "status_code": r.status_code,
            "backend_timing_ms": backend_timing,
        }
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        return {
            "company": company, "year": year, "ok": False,
            "elapsed_ms": round(elapsed * 1000, 1),
            "error": f"{type(exc).__name__}: {exc}",
        }


# ── Stats ────────────────────────────────────────────────────────────────────

def _pct(values, q: float) -> float:
    """Return the q-th percentile (0 <= q <= 100) using linear interpolation."""
    if not values:
        return float("nan")
    s = sorted(values)
    k = (len(s) - 1) * (q / 100.0)
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    if lo == hi:
        return s[lo]
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _summary(per_worker: list[dict]) -> dict:
    elapsed = [w["elapsed_ms"] for w in per_worker if w.get("ok")]
    n_ok = len(elapsed)
    n_total = len(per_worker)
    return {
        "n_total": n_total,
        "n_ok": n_ok,
        "n_failed": n_total - n_ok,
        "p50_ms": round(_pct(elapsed, 50), 1) if elapsed else None,
        "p95_ms": round(_pct(elapsed, 95), 1) if elapsed else None,
        "p99_ms": round(_pct(elapsed, 99), 1) if elapsed else None,
        "min_ms": round(min(elapsed), 1) if elapsed else None,
        "max_ms": round(max(elapsed), 1) if elapsed else None,
        "mean_ms": round(statistics.mean(elapsed), 1) if elapsed else None,
        "stdev_ms": round(statistics.stdev(elapsed), 1) if len(elapsed) > 1 else None,
    }


# ── Runner ───────────────────────────────────────────────────────────────────

def _git_sha() -> str:
    try:
        out = subprocess.check_output(["git", "rev-parse", "HEAD"],
                                       cwd=str(_PROJECT_ROOT), text=True).strip()
        return out
    except Exception:
        return "unknown"


def run_benchmark(mode: str, variant: str, n: int,
                  base_url: str | None,
                  username: str | None, password: str | None) -> dict:
    # Pick tuples
    if variant == "same":
        tuples = [SAME_TUPLE] * n
    else:
        tuples = list(itertools.islice(itertools.cycle(COLD_POOL), n))

    print(f"\n=== {mode}/{variant} | n={n} | tuples={tuples} ===")

    # Set up shared resources
    barrier = threading.Barrier(n)

    if mode == "http":
        import requests
        session = requests.Session()
        if not (base_url and username and password):
            raise SystemExit("http mode needs --base-url, --username, --password")
        _http_login(session, base_url, username, password)
        worker_fn = lambda c, y: _http_worker(barrier, base_url, session, c, y)
    else:
        worker_fn = lambda c, y: _direct_worker(barrier, c, y)

    # Fire
    wall_t0 = time.perf_counter()
    results = []
    with ThreadPoolExecutor(max_workers=n) as pool:
        futs = [pool.submit(worker_fn, c, y) for c, y in tuples]
        for fut in as_completed(futs):
            results.append(fut.result())
    wall_elapsed = round((time.perf_counter() - wall_t0) * 1000, 1)

    summary = _summary(results)
    summary["wall_ms"] = wall_elapsed

    return {
        "mode": mode,
        "variant": variant,
        "n": n,
        "tuples": tuples,
        "git_sha": _git_sha(),
        "timestamp": datetime.now().isoformat(),
        "summary": summary,
        "per_worker": results,
    }


# ── Reporting ────────────────────────────────────────────────────────────────

def _print_summary(report: dict) -> None:
    s = report["summary"]
    print()
    print(f"  mode={report['mode']}  variant={report['variant']}  n={report['n']}  "
          f"sha={report['git_sha'][:10]}")
    print(f"  wall_clock: {s['wall_ms']:.1f} ms")
    print(f"  per-worker latency:")
    print(f"    p50 = {s['p50_ms']} ms")
    print(f"    p95 = {s['p95_ms']} ms")
    print(f"    p99 = {s['p99_ms']} ms")
    print(f"    min = {s['min_ms']} ms")
    print(f"    max = {s['max_ms']} ms")
    print(f"    mean = {s['mean_ms']} ms  (stdev = {s['stdev_ms']})")
    print(f"  ok={s['n_ok']}/{s['n_total']}, failed={s['n_failed']}")
    failed = [w for w in report["per_worker"] if not w.get("ok")]
    for f in failed:
        print(f"    !! {f['company']}/{f['year']}: {f.get('error')}")


def _compare(a_path: str, b_path: str) -> None:
    a = json.loads(Path(a_path).read_text())
    b = json.loads(Path(b_path).read_text())
    print()
    print(f"BEFORE: {a_path}  (sha {a['git_sha'][:10]}, mode={a['mode']}, variant={a['variant']})")
    print(f"AFTER:  {b_path}  (sha {b['git_sha'][:10]}, mode={b['mode']}, variant={b['variant']})")
    if a["mode"] != b["mode"] or a["variant"] != b["variant"]:
        print("  WARNING: mode/variant mismatch")

    metrics = ["wall_ms", "p50_ms", "p95_ms", "p99_ms", "min_ms", "max_ms", "mean_ms"]
    print()
    print(f"  {'metric':<12} {'BEFORE':>12} {'AFTER':>12} {'speedup':>10}")
    print(f"  {'-'*12} {'-'*12} {'-'*12} {'-'*10}")
    for m in metrics:
        bef = a["summary"].get(m)
        aft = b["summary"].get(m)
        if bef is None or aft is None or aft == 0:
            speed = "n/a"
        else:
            speed = f"{bef / aft:.2f}x"
        print(f"  {m:<12} {str(bef):>12} {str(aft):>12} {speed:>10}")


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["direct", "http"])
    ap.add_argument("--variant", choices=["same", "cold"])
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--out", type=str, help="write JSON report to this path")
    ap.add_argument("--base-url", default=os.environ.get("BENCH_BASE_URL", "http://10.100.50.4"))
    ap.add_argument("--username", default=os.environ.get("BENCH_USER"))
    ap.add_argument("--password", default=os.environ.get("BENCH_PASS"))
    ap.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"),
                    help="compare two JSON outputs side by side")
    args = ap.parse_args()

    if args.compare:
        _compare(args.compare[0], args.compare[1])
        return 0

    if not args.mode or not args.variant:
        ap.error("--mode and --variant required (unless --compare)")

    report = run_benchmark(args.mode, args.variant, args.n,
                           args.base_url, args.username, args.password)
    _print_summary(report)

    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2, default=str))
        print(f"\n  → wrote {args.out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
