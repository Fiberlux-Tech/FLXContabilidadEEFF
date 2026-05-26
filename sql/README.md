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
| `VISTA_PNL_PREPARADO.sql` | 4 per-CIA views + REPORTES umbrella. Replaces `prepare_pnl` + `filter_for_statements` + `assign_partida_pl`. Returns rows with `SALDO`, `MES`, `PARTIDA_PL`, `IS_INTERCOMPANY`, `IS_STATEMENT_ELIGIBLE`. **The view enriches rows; it does not filter them** — callers add `WHERE IS_STATEMENT_ELIGIBLE = 1` to get the statement subset, or leave it off to also see inventory-side accounts like `60.x` for ad-hoc Excel-via-ODBC queries. |
| `VISTA_BS_PREPARADO.sql` | 4 per-CIA views + REPORTES umbrella. Replaces `prepare_bs` + `assign_partida_bs`. Returns rows with `SALDO`, `MES`, `PARTIDA_BS`, `SECCION_BS`. Does **not** do cumulative-sum or reclassification (Phase B). |
| `PARITY_CHECKS.sql` | SQL-only sanity checks (coverage, section consistency, row counts). |

## Deployment order

1. In SSMS, run `VISTA_PNL_PREPARADO.sql` end-to-end. It deploys 4 per-CIA
   views (one per schema) and then the REPORTES umbrella. Each `CREATE OR
   ALTER VIEW` is followed by `GO`. **The DDL is idempotent** — re-running
   replaces existing views without dropping permissions.
2. Run `VISTA_BS_PREPARADO.sql` the same way.
3. Eyeball `PARITY_CHECKS.sql`: expect zero rows from check #1, near-zero
   from #2, and zero from #3.

## Editing the classification rules later

The PARTIDA_PL / PARTIDA_BS / SECCION_BS CASE blocks are **duplicated across
the four per-CIA views by design** — that's the trade-off for the per-CIA
topology. If you edit one of them, edit all four. The Python-side parity
harness that used to catch drift between Python and SQL was deleted in
Phase A Step 4 (the SQL view is now the single source of truth); the only
remaining safety net is the `POR CLASIFICAR` warning emitted by
`prepare_pnl_from_view` whenever an unrecognised CUENTA_CONTABLE flows
through. Watch `backend/logs/error.log` for spikes after editing rules.

## Out of scope here (Phase B candidates)

- P&L summary pivot (`pl_summary`) — easy SQL once views land.
- BS cumulative sum across months — needs window functions.
- BS reclassification rules (negative balance → move section) — order-sensitive
  with the cumsum; stays in Python for now.
- UTILIDAD NETA injection into BS — depends on P&L summary; do after the
  PL_SUMARIO view exists.
- Detail pivots (CECO/CUENTA/NOTA) — lazy; only worth it if profiling shows
  these are slow.
