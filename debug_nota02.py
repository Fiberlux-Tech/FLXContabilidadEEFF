"""Debug script: export all raw registers that compose Nota 02 (Cuentas por Cobrar Comerciales) to Excel.

Usage:
    python debug_nota02.py [--company NEXTNET] [--year 2025]

Outputs: debug_nota02_<company>_<year>.xlsx
"""
import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

import pandas as pd

from data.db import connect
from data.queries import fetch_bs_data
from transforms.transforms import prepare_bs_stmt
from rules.account_rules import BS_CLASSIFICATION

# The PARTIDA_BS value that Nota 02 filters on
NOTA02_PARTIDA = "Cuentas por cobrar comerciales (neto)"

# Which 2-digit prefixes map to this partida (for reference)
NOTA02_PREFIXES = [k for k, v in BS_CLASSIFICATION.items() if v == NOTA02_PARTIDA]


def main():
    parser = argparse.ArgumentParser(description="Export Nota 02 raw registers to Excel")
    parser.add_argument("--company", type=str.upper, default="NEXTNET")
    parser.add_argument("--year", type=int, default=2025)
    args = parser.parse_args()

    print(f"Fetching BS data for {args.company} / {args.year}...")
    with connect() as conn:
        raw = fetch_bs_data(conn, args.company, args.year, month=None)

    if raw.empty:
        print("No data returned from query.")
        sys.exit(1)

    print(f"  Total raw BS rows: {len(raw):,}")

    # Apply transforms (SALDO calculation + PARTIDA_BS classification)
    df = prepare_bs_stmt(raw)

    # Filter to Nota 02 partida
    nota02 = df[df["PARTIDA_BS"] == NOTA02_PARTIDA].copy()
    print(f"  Rows classified as '{NOTA02_PARTIDA}': {nota02.shape[0]:,}")

    if nota02.empty:
        print("No rows found for Nota 02.")
        sys.exit(1)

    # Show summary of unique accounts
    summary = (
        nota02.groupby(["CUENTA_CONTABLE", "DESCRIPCION"], observed=True)
        .agg(ROWS=("SALDO", "size"), SALDO_TOTAL=("SALDO", "sum"))
        .sort_values("SALDO_TOTAL", ascending=False)
        .reset_index()
    )
    print(f"\n  Unique CUENTA_CONTABLE values: {summary.shape[0]}")
    print("\n  Account summary:")
    for _, row in summary.iterrows():
        print(f"    {row['CUENTA_CONTABLE']:20s}  {row['DESCRIPCION']:45s}  rows={row['ROWS']:>6,}  saldo={row['SALDO_TOTAL']:>15,.2f}")

    # Sort for the Excel output
    nota02 = nota02.sort_values(
        ["CUENTA_CONTABLE", "FECHA", "NIT"],
    ).reset_index(drop=True)

    # Select columns for output
    out_cols = [
        "CIA", "CUENTA_CONTABLE", "DESCRIPCION", "PARTIDA_BS", "SECCION_BS",
        "NIT", "RAZON_SOCIAL", "CENTRO_COSTO", "DESC_CECO",
        "FECHA", "MES", "DEBITO_LOCAL", "CREDITO_LOCAL", "SALDO",
    ]
    nota02_out = nota02[[c for c in out_cols if c in nota02.columns]]

    # Write to Excel
    outfile = Path(f"debug_nota02_{args.company}_{args.year}.xlsx")
    with pd.ExcelWriter(outfile, engine="openpyxl") as writer:
        # Sheet 1: all raw registers
        nota02_out.to_excel(writer, sheet_name="Registros", index=False)

        # Sheet 2: summary by account
        summary.to_excel(writer, sheet_name="Resumen por Cuenta", index=False)

        # Sheet 3: summary by NIT (top contributors)
        nit_summary = (
            nota02.groupby(["NIT", "RAZON_SOCIAL"], observed=True)
            .agg(ROWS=("SALDO", "size"), SALDO_TOTAL=("SALDO", "sum"))
            .sort_values("SALDO_TOTAL", ascending=False)
            .reset_index()
        )
        nit_summary.to_excel(writer, sheet_name="Resumen por NIT", index=False)

    print(f"\nExcel saved to: {outfile.resolve()}")


if __name__ == "__main__":
    main()
