-- =============================================================================
-- VISTA_PNL_SUMARIO  —  Phase C: pre-aggregated P&L summary
-- =============================================================================
-- Pushes the pl_summary() GROUP BY into SQL.  The dashboard fetches ~100 rows
-- per (CIA, YEAR) instead of pulling 8.4M raw rows and grouping in pandas.
--
-- Replaces in Python: pl_summary() pivot in statements.py:98-103, run three
-- times (all / ex_ic / only_ic) inside data_service._run_pl_summary_only.
-- After this view ships, those three pivots collapse into a single SELECT.
--
-- Topology mirrors VISTA_PNL_PREPARADO — 4 per-CIA views + REPORTES umbrella —
-- so the optimizer can prune to one company when CIA = ? is filtered.
--
-- Output columns:
--   CIA              VARCHAR
--   YEAR             INT             -- YEAR(FECHA), included so a single query
--                                       can slice any year and the cache key
--                                       (company, year) maps 1:1 to a WHERE clause.
--   MES              INT             -- MONTH(FECHA), 1..12
--   PARTIDA_PL       VARCHAR(40)     -- inherited from VISTA_PNL_PREPARADO
--   SALDO_TOTAL      DECIMAL(28,8)   -- SUM(SALDO) — all rows
--   SALDO_EX_IC      DECIMAL(28,8)   -- SUM(SALDO) excluding IS_INTERCOMPANY rows
--   SALDO_ONLY_IC    DECIMAL(28,8)   -- SUM(SALDO) of IS_INTERCOMPANY rows only
--
-- Why three SALDO columns instead of three separate views: the dashboard always
-- computes pl_summary, pl_summary_ex_ic, and pl_summary_only_ic together (see
-- _run_pl_summary_only in data_service.py:719-721). Returning all three in one
-- row collapses three SQL round-trips into one.  Storage cost is trivial — the
-- view materializes nothing; SQL Server computes the three SUMs in one pass
-- over the source.
--
-- Filter baked in:
--   * IS_STATEMENT_ELIGIBLE = 1   — only statement-eligible rows feed the summary.
--                                   Raw pivots (Excel) keep using VISTA_PNL_PREPARADO
--                                   with eligible_only=False; this summary view is
--                                   for the statement path only.
--
-- POR CLASIFICAR handling: rows with PARTIDA_PL = 'POR CLASIFICAR' are included
-- so the dashboard's POR CLASIFICAR canary row keeps working.  Filter them out
-- at the Python layer if needed.
-- =============================================================================


CREATE OR ALTER VIEW [FIBERLINE].[VISTA_PNL_SUMARIO] AS
SELECT
    CIA,
    YEAR(FECHA) AS YEAR,
    MES,
    PARTIDA_PL,
    CAST(SUM(SALDO)                                        AS DECIMAL(28, 8)) AS SALDO_TOTAL,
    CAST(SUM(CASE WHEN IS_INTERCOMPANY = 0 THEN SALDO END) AS DECIMAL(28, 8)) AS SALDO_EX_IC,
    CAST(SUM(CASE WHEN IS_INTERCOMPANY = 1 THEN SALDO END) AS DECIMAL(28, 8)) AS SALDO_ONLY_IC
FROM [FIBERLINE].[VISTA_PNL_PREPARADO]
WHERE IS_STATEMENT_ELIGIBLE = 1
GROUP BY CIA, YEAR(FECHA), MES, PARTIDA_PL;
GO


CREATE OR ALTER VIEW [FIBERTECH].[VISTA_PNL_SUMARIO] AS
SELECT
    CIA,
    YEAR(FECHA) AS YEAR,
    MES,
    PARTIDA_PL,
    CAST(SUM(SALDO)                                        AS DECIMAL(28, 8)) AS SALDO_TOTAL,
    CAST(SUM(CASE WHEN IS_INTERCOMPANY = 0 THEN SALDO END) AS DECIMAL(28, 8)) AS SALDO_EX_IC,
    CAST(SUM(CASE WHEN IS_INTERCOMPANY = 1 THEN SALDO END) AS DECIMAL(28, 8)) AS SALDO_ONLY_IC
FROM [FIBERTECH].[VISTA_PNL_PREPARADO]
WHERE IS_STATEMENT_ELIGIBLE = 1
GROUP BY CIA, YEAR(FECHA), MES, PARTIDA_PL;
GO


CREATE OR ALTER VIEW [NEXTNET].[VISTA_PNL_SUMARIO] AS
SELECT
    CIA,
    YEAR(FECHA) AS YEAR,
    MES,
    PARTIDA_PL,
    CAST(SUM(SALDO)                                        AS DECIMAL(28, 8)) AS SALDO_TOTAL,
    CAST(SUM(CASE WHEN IS_INTERCOMPANY = 0 THEN SALDO END) AS DECIMAL(28, 8)) AS SALDO_EX_IC,
    CAST(SUM(CASE WHEN IS_INTERCOMPANY = 1 THEN SALDO END) AS DECIMAL(28, 8)) AS SALDO_ONLY_IC
FROM [NEXTNET].[VISTA_PNL_PREPARADO]
WHERE IS_STATEMENT_ELIGIBLE = 1
GROUP BY CIA, YEAR(FECHA), MES, PARTIDA_PL;
GO


CREATE OR ALTER VIEW [FIBERLUX].[VISTA_PNL_SUMARIO] AS
SELECT
    CIA,
    YEAR(FECHA) AS YEAR,
    MES,
    PARTIDA_PL,
    CAST(SUM(SALDO)                                        AS DECIMAL(28, 8)) AS SALDO_TOTAL,
    CAST(SUM(CASE WHEN IS_INTERCOMPANY = 0 THEN SALDO END) AS DECIMAL(28, 8)) AS SALDO_EX_IC,
    CAST(SUM(CASE WHEN IS_INTERCOMPANY = 1 THEN SALDO END) AS DECIMAL(28, 8)) AS SALDO_ONLY_IC
FROM [FIBERLUX].[VISTA_PNL_PREPARADO]
WHERE IS_STATEMENT_ELIGIBLE = 1
GROUP BY CIA, YEAR(FECHA), MES, PARTIDA_PL;
GO


-- ─────────────────────────────────────────────────────────────────────────────
-- Umbrella view in REPORTES.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR ALTER VIEW [REPORTES].[VISTA_PNL_SUMARIO] AS
SELECT * FROM [FIBERLINE].[VISTA_PNL_SUMARIO]
UNION ALL
SELECT * FROM [FIBERTECH].[VISTA_PNL_SUMARIO]
UNION ALL
SELECT * FROM [NEXTNET].[VISTA_PNL_SUMARIO]
UNION ALL
SELECT * FROM [FIBERLUX].[VISTA_PNL_SUMARIO];
GO


-- =============================================================================
-- Expected query pattern from data_service.load_pl_data:
--
--   SELECT MES, PARTIDA_PL, SALDO_TOTAL, SALDO_EX_IC, SALDO_ONLY_IC
--   FROM REPORTES.VISTA_PNL_SUMARIO
--   WHERE CIA = ? AND YEAR = ?;
--
-- Returns ~100 rows.  Python builds the three pl_summary DataFrames by
-- pivoting MES → columns and joining with PL_SUBTOTAL_LABELS / build_pl_rows
-- (kept in statements.py for the display structure — UTILIDAD BRUTA, UTILIDAD
-- OPERATIVA, etc. — which is presentation, not aggregation).
-- =============================================================================
