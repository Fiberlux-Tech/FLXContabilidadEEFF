"""Validate that the fact-pickle aggregation produces bit-identical P&L
summaries vs the row-level df_stmt for every (company, year) pair.

For each company/year:
  - reads df_stmt_{company}_{year}.pkl and fact_{company}_{year}.pkl
    (or, for CONSOLIDADO, concat-s the 4 real-company fact pickles)
  - runs pl_summary on each over three subsets: all rows, ~IC, only IC
  - compares the resulting pivots element-wise

Tolerance is 1e-3 (one tenth of a Peruvian centavo). Float64 summation
order differs between the two paths so strict bit-equality fails by
~1e-9; dashboard numbers are rounded to 0.01 so any diff < 1e-3 is
invisible to users. If a diff exceeds the tolerance, the harness exits
non-zero and prints the offending (company, year, pivot, cell) so the
aggregation can be fixed before any USE_FACT_TABLE_<COMPANY> flag flips.

**Important: run after a full scheduler cycle.** The harness compares
df_stmt pickles (refreshed by the scheduler) against fact pickles (also
refreshed by the scheduler). If they were written at different times,
diffs are stale-snapshot artifacts, not aggregation bugs. The fix is to
let the scheduler complete one full cycle so all pickles are aligned,
then re-run.

Exit code 0 if zero diffs, 1 otherwise.

Usage (from the backend directory):
    ../venv/bin/python3 scripts/diff_fact_vs_view.py
    ../venv/bin/python3 scripts/diff_fact_vs_view.py --company FIBERLINE --year 2025
"""

import argparse
import logging
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
BACKEND = HERE.parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "services"))

import pandas as pd

from accounting.statements import pl_summary
from config.company import CONSOLIDADO, REAL_COMPANIES, COMPANY_META
from config.fields import IS_INTERCOMPANY

CACHE_DIR = BACKEND / "services" / ".stmt_cache"
TOLERANCE = 1e-3

logger = logging.getLogger("diff_fact_vs_view")


def _load_df_stmt(company: str, year: int) -> pd.DataFrame:
    return pd.read_pickle(CACHE_DIR / f"df_stmt_{company}_{year}.pkl")


def _load_fact(company: str, year: int) -> pd.DataFrame:
    """Read the fact pickle; CONSOLIDADO reconstructs from 4 real-company files."""
    if company == CONSOLIDADO:
        dfs = [pd.read_pickle(CACHE_DIR / f"fact_{c}_{year}.pkl")
               for c in REAL_COMPANIES]
        return pd.concat(dfs, ignore_index=True)
    return pd.read_pickle(CACHE_DIR / f"fact_{company}_{year}.pkl")


def _diff_pivots(a: pd.DataFrame, b: pd.DataFrame) -> pd.DataFrame:
    """Element-wise abs diff at the PARTIDA_PL row, MES column grain.

    Both pivots have PARTIDA_PL as a column and month columns ENE..DIC + TOTAL.
    Return rows where the max abs diff across month columns exceeds TOLERANCE.
    """
    # Align by PARTIDA_PL so row order doesn't matter
    a_sorted = a.sort_values("PARTIDA_PL").reset_index(drop=True)
    b_sorted = b.sort_values("PARTIDA_PL").reset_index(drop=True)
    if a_sorted.shape != b_sorted.shape:
        # Treat shape mismatch as a single sentinel diff row
        return pd.DataFrame({"reason": ["shape mismatch"],
                             "a_shape": [a_sorted.shape],
                             "b_shape": [b_sorted.shape]})
    num_cols = a_sorted.select_dtypes(include="number").columns
    a_num = a_sorted[num_cols]
    b_num = b_sorted[num_cols]
    abs_diff = (a_num - b_num).abs()
    max_per_row = abs_diff.max(axis=1)
    over = max_per_row > TOLERANCE
    if not over.any():
        return pd.DataFrame()
    return pd.DataFrame({
        "PARTIDA_PL": a_sorted.loc[over, "PARTIDA_PL"].values,
        "max_abs_diff": max_per_row[over].values,
    })


def diff_one(company: str, year: int) -> list[tuple[str, int, str, pd.DataFrame]]:
    """Compare pl_summary outputs for one (company, year). Returns one entry
    per non-empty diff."""
    df_stmt = _load_df_stmt(company, year)
    fact = _load_fact(company, year)

    results = []
    for name, mask in (
        ("pl_summary", None),
        ("pl_summary_ex_ic", "ex_ic"),
        ("pl_summary_only_ic", "only_ic"),
    ):
        if mask is None:
            d_pivot = pl_summary(df_stmt)
            f_pivot = pl_summary(fact)
        elif mask == "ex_ic":
            d_pivot = pl_summary(df_stmt[~df_stmt[IS_INTERCOMPANY]])
            f_pivot = pl_summary(fact[~fact[IS_INTERCOMPANY]])
        else:  # only_ic
            d_pivot = pl_summary(df_stmt[df_stmt[IS_INTERCOMPANY]])
            f_pivot = pl_summary(fact[fact[IS_INTERCOMPANY]])

        diff = _diff_pivots(d_pivot, f_pivot)
        if not diff.empty:
            results.append((company, year, name, diff))
    return results


def main(argv=None) -> int:
    global TOLERANCE
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--company", help="Restrict to one company (default: all)")
    parser.add_argument("--year", type=int, help="Restrict to one year (default: all)")
    parser.add_argument("--tolerance", type=float, default=TOLERANCE,
                        help=f"Max abs diff to treat as zero (default {TOLERANCE})")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    TOLERANCE = args.tolerance

    companies = [args.company] if args.company else list(COMPANY_META.keys())
    years = [args.year] if args.year else [2025, 2026]

    print(f"Diff harness | tolerance={TOLERANCE} | cache={CACHE_DIR}")
    print()

    all_diffs: list = []
    checked = 0
    skipped = []
    for company in companies:
        for year in years:
            try:
                diffs = diff_one(company, year)
                checked += 1
                if diffs:
                    all_diffs.extend(diffs)
                    for c, y, name, df in diffs:
                        print(f"DIFF  {c}/{y}  {name}:")
                        print(df.to_string(index=False))
                        print()
                else:
                    print(f"  ok  {company}/{year}")
            except FileNotFoundError as e:
                skipped.append(f"{company}/{year}: {e.filename}")
                print(f"  skip {company}/{year}: missing pickle")

    print()
    print(f"Checked: {checked} pairs")
    if skipped:
        print(f"Skipped: {len(skipped)} pairs (missing pickles)")
        for s in skipped:
            print(f"  - {s}")
    if all_diffs:
        print(f"FAILED: {len(all_diffs)} non-zero diff(s) above tolerance {TOLERANCE}")
        return 1
    print(f"PASS: all checked pairs are bit-identical within tolerance {TOLERANCE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
