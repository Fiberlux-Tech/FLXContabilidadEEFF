"""Compare SUM(SALDO) by (CIA, MES, PARTIDA_PL) from the new view vs Python.

Usage (from project root):
    venv/bin/python sql/parity_check.py --year 2026

Exits non-zero if any (CIA, MES, PARTIDA_PL) total differs by more than 0.01.
Run this BEFORE wiring queries.py to read from VISTA_PNL_PREPARADO.
"""
import argparse
import os
import sys

_P = "/home/administrator/FLXContabilidad"
sys.path.insert(0, os.path.join(_P, "backend"))
sys.path.insert(0, os.path.join(_P, "backend", "services"))

from config.env_loader import load_env_config  # noqa: E402
load_env_config(_P)

import pandas as pd  # noqa: E402

from data.db import connect  # noqa: E402
from data.queries import fetch_pnl_data, fetch_bs_data  # noqa: E402
from accounting.transforms import prepare_stmt, prepare_bs_stmt  # noqa: E402


def python_pnl_totals(cia: str, year: int) -> pd.DataFrame:
    with connect() as conn:
        raw = fetch_pnl_data(conn, cia, year, month=None)
    df = prepare_stmt(raw)
    g = (df.groupby(["MES", "PARTIDA_PL"], observed=True)["SALDO"]
           .sum().reset_index())
    g["CIA"] = cia
    return g[["CIA", "MES", "PARTIDA_PL", "SALDO"]].rename(columns={"SALDO": "py_total"})


def view_pnl_totals(cia: str, year: int) -> pd.DataFrame:
    # The view now enriches rather than filters. IS_STATEMENT_ELIGIBLE = 1
    # reproduces the Python-side filter_for_statements rule.
    with connect() as conn:
        q = """
            SELECT CIA, MES, PARTIDA_PL, SUM(SALDO) AS view_total
            FROM REPORTES.VISTA_PNL_PREPARADO
            WHERE CIA = ? AND FECHA >= ? AND FECHA < ?
              AND IS_STATEMENT_ELIGIBLE = 1
            GROUP BY CIA, MES, PARTIDA_PL
        """
        from datetime import date
        return pd.read_sql(q, conn, params=[cia, date(year, 1, 1), date(year + 1, 1, 1)])


def python_bs_totals(cia: str, year: int) -> pd.DataFrame:
    with connect() as conn:
        raw = fetch_bs_data(conn, cia, year, month=None)
    df = prepare_bs_stmt(raw)
    g = (df.groupby(["MES", "PARTIDA_BS", "SECCION_BS"], observed=True)["SALDO"]
           .sum().reset_index())
    g["CIA"] = cia
    return g.rename(columns={"SALDO": "py_total"})[
        ["CIA", "MES", "PARTIDA_BS", "SECCION_BS", "py_total"]]


def view_bs_totals(cia: str, year: int) -> pd.DataFrame:
    with connect() as conn:
        q = """
            SELECT CIA, MES, PARTIDA_BS, SECCION_BS, SUM(SALDO) AS view_total
            FROM REPORTES.VISTA_BS_PREPARADO
            WHERE CIA = ? AND FECHA >= ? AND FECHA < ?
            GROUP BY CIA, MES, PARTIDA_BS, SECCION_BS
        """
        from datetime import date
        return pd.read_sql(q, conn, params=[cia, date(year, 1, 1), date(year + 1, 1, 1)])


def compare(label: str, py: pd.DataFrame, sql: pd.DataFrame, keys: list[str]) -> bool:
    merged = py.merge(sql, on=keys, how="outer", indicator=True)
    merged["py_total"] = merged["py_total"].fillna(0)
    merged["view_total"] = merged["view_total"].fillna(0)
    merged["diff"] = (merged["py_total"] - merged["view_total"]).round(2)
    mismatched = merged[merged["diff"].abs() > 0.01]
    print(f"\n=== {label} ===")
    print(f"rows compared: {len(merged):,}   mismatches: {len(mismatched):,}")
    if not mismatched.empty:
        print(mismatched.head(20).to_string(index=False))
    return mismatched.empty


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--cias", nargs="+",
                    default=["FIBERLINE", "FIBERLUX", "FIBERTECH", "NEXTNET"])
    args = ap.parse_args()

    ok = True
    for cia in args.cias:
        py_pl  = python_pnl_totals(cia, args.year)
        sql_pl = view_pnl_totals(cia, args.year)
        ok &= compare(f"P&L  {cia} {args.year}", py_pl, sql_pl,
                      ["CIA", "MES", "PARTIDA_PL"])

        py_bs  = python_bs_totals(cia, args.year)
        sql_bs = view_bs_totals(cia, args.year)
        ok &= compare(f"BS   {cia} {args.year}", py_bs, sql_bs,
                      ["CIA", "MES", "PARTIDA_BS", "SECCION_BS"])

    print("\n" + ("PARITY OK ✓" if ok else "PARITY FAILED ✗"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
