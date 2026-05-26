# SQL views — pushing Python transforms into the database

This directory holds DDL for views that replace work currently done in
`backend/services/accounting/transforms.py`. The intent: the website fetches
already-classified data and skips the Python preparation step entirely.

## Topology (mirrors the source)

Existing source pattern:

```
REPORTES.VISTA_ANALISIS_CECOS = UNION ALL of
    [FIBERLINE].VISTA_ANALISIS_CECOS
    [FIBERTECH].VISTA_ANALISIS_CECOS
    [NEXTNET].VISTA_ANALISIS_CECOS
    [FIBERLUX].VISTA_ANALISIS_CECOS
```

New views follow the same shape so SQL Server can push `CIA = ?` predicates
down into the matching per-company view:

```
REPORTES.VISTA_PNL_PREPARADO = UNION ALL of [CIA].VISTA_PNL_PREPARADO × 4
REPORTES.VISTA_BS_PREPARADO  = UNION ALL of [CIA].VISTA_BS_PREPARADO  × 4
```

Each `[CIA].VISTA_*_PREPARADO` reads from `[CIA].VISTA_ANALISIS_CECOS`,
applies the filters, computes `SALDO` / `MES`, and runs the classification
CASE.

## Files

| File | Purpose |
|---|---|
| `VISTA_PNL_PREPARADO.sql` | 4 per-CIA views + REPORTES umbrella. Replaces `prepare_pnl` + `filter_for_statements` + `assign_partida_pl`. Returns rows with `SALDO`, `YEAR`, `MES`, `PARTIDA_PL`, `IS_INTERCOMPANY`, `IS_STATEMENT_ELIGIBLE`. **The view enriches rows; it does not filter them** — callers add `WHERE IS_STATEMENT_ELIGIBLE = 1` to get the statement subset, or leave it off to also see inventory-side accounts like `60.x` for ad-hoc Excel-via-ODBC queries (and for debugging — keeping unfiltered rows visible is how we discover new ERP accounts falling outside the `>=619` rule). |
| `VISTA_BS_PREPARADO.sql` | 4 per-CIA views + REPORTES umbrella. Replaces `prepare_bs` + `assign_partida_bs`. Returns rows with `SALDO`, `YEAR`, `MES`, `PARTIDA_BS`, `SECCION_BS`. Does **not** do cumulative-sum or reclassification (those live in `VISTA_BS_PREPARADO_CUMSUM` and `VISTA_BS_SUMARIO`). |
| `VISTA_PNL_SUMARIO.sql` | Phase C — pre-aggregated P&L summary. `GROUP BY CIA, YEAR, MES, PARTIDA_PL` with three SALDO columns (total / ex_ic / only_ic) computed in one pass. ~100 rows per `(CIA, YEAR)`. Filters `IS_STATEMENT_ELIGIBLE = 1` internally since aggregated rows are always statement-eligible. |
| `VISTA_BS_PREPARADO_CUMSUM.sql` | Phase E — BS at cuenta-grain with monthly cumulative SALDO via `SUM() OVER (PARTITION BY CIA, YEAR, CUENTA ORDER BY MES)`. **Calendar-densified** (`cuenta_years CROSS JOIN months(1..12) LEFT JOIN monthly`) so cuentas with no activity in a month still emit a row carrying the prior cumulative balance forward. Patched 2026-05-26 to fix the gap-month bug. Stays at cuenta-grain because reclassification needs per-cuenta last-month balance. |
| `VISTA_BS_SUMARIO.sql` | Phase C — pre-aggregated BS summary on top of `VISTA_BS_PREPARADO_CUMSUM`. Applies the three `BS_RECLASSIFICATION_RULES` + native-section sign flip, then groups to partida-grain. ~30 rows × 12 months per `(CIA, YEAR)`. |
| `DROP_DETALLE_VIEWS.sql` | One-time drop of the redundant `VISTA_PNL_DETALLE` / `VISTA_BS_DETALLE` views the DBA deployed during Phase D exploration. The PREPARADO views (now with `YEAR`) cover the drill-down path directly. |
| `PARITY_CHECKS.sql` | SQL-only sanity checks (coverage, section consistency, row counts). |

## Deployment order

In SSMS, run each file end-to-end. Each `CREATE OR ALTER VIEW` is followed by
`GO`. **DDL is idempotent** — re-running replaces existing views without
dropping permissions. Cross-file ordering matters because later views read
from earlier ones.

1. `VISTA_PNL_PREPARADO.sql` (re-run to pick up the new `YEAR` column).
2. `VISTA_BS_PREPARADO.sql` (same).
3. `VISTA_PNL_SUMARIO.sql` — depends on #1.
4. `VISTA_BS_PREPARADO_CUMSUM.sql` — depends on #2.
5. `VISTA_BS_SUMARIO.sql` — depends on #4.
6. `DROP_DETALLE_VIEWS.sql` — one-time cleanup of the redundant DETALLE views.
7. Eyeball `PARITY_CHECKS.sql`: expect zero rows from check #1, near-zero
   from #2, and zero from #3.

After deploying a summary view (#3, #5), spot-check 3-5 partida totals for a
known-good month against the dashboard before wiring Python callers over.

## Editing the classification rules later

The PARTIDA_PL / PARTIDA_BS / SECCION_BS CASE blocks are **duplicated across
the four per-CIA views by design** — that's the trade-off for the per-CIA
topology. If you edit one of them, edit all four. The Python-side parity
harness that used to catch drift between Python and SQL was deleted in
Phase A Step 4 (the SQL view is now the single source of truth); the only
remaining safety net is the `POR CLASIFICAR` warning emitted by
`prepare_pnl_from_view` whenever an unrecognised CUENTA_CONTABLE flows
through. Watch `backend/logs/error.log` for spikes after editing rules.

## What stays in Python after Phase C/D/E

The five view files above cover row-level enrichment (A/B), pre-aggregation
(C), drill-down (D, no DDL), and cumsum (E). These bits stay in Python because
they're either presentation, cross-statement, or trivially small:

- **`build_pl_rows`** (statements.py) — the P&L display structure: UTILIDAD
  BRUTA / UTILIDAD OPERATIVA / UTILIDAD NETA subtotal rows. Presentation.
- **`_build_bs_rows`** + `BS_PARTIDA_ORDER` + CORRIENTE / NO CORRIENTE split.
  Pure display ordering.
- **UTILIDAD NETA injection into BS PATRIMONIO** (`extract_utilidad_neta`).
  Crosses the P&L/BS boundary; 5 lines in Python. Without it, the BS shows
  no `Resultados del Ejercicio` row (which is why `VISTA_BS_SUMARIO`
  TOTAL PASIVO+PATRIMONIO doesn't balance against TOTAL ACTIVO on its own).
- **BS-balance validation** (`_validate_bs_balance`). One assertion at the
  edge of the pipeline.
- **Detail pivots** (CECO / CUENTA / NOTA) — lazy, computed from already-cached
  prepared data, sub-100ms. Only worth a view if profiling shows them slow.
