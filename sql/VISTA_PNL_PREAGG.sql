-- =============================================================================
-- VISTA_PNL_PREAGG  —  Phase F: pre-aggregated P&L detail grain
-- =============================================================================
-- Pushes the finest-grain GROUP BY used by every P&L *section detail* table
-- into SQL.  Replaces the in-Python `preaggregate(df_stmt)` frame (and the raw
-- df_stmt it was built from) so the section path stops pulling 8.4M raw rows
-- into a worker and grouping them in pandas.
--
-- This is to compute_pl_section what VISTA_PNL_SUMARIO is to pl_summary:
--   VISTA_PNL_SUMARIO   → GROUP BY (CIA, YEAR, MES, PARTIDA_PL)            ~100 rows
--   VISTA_PNL_PREAGG    → GROUP BY (… + CECO + CUENTA + NIT)              ~10²–10³ rows
-- Both collapse the 8.4M-row fetch to a small pre-summed result; the wider
-- grain here is the finest grain any of the 12 sections need (see
-- accounting.aggregation.preaggregate + detail_proveedores/proyectos which
-- also need NIT/RAZON_SOCIAL).
--
-- Replaces in Python: accounting.aggregation.preaggregate() and the raw
-- df_stmt scan that fed the seven detail aggregation functions
-- (sales_details, detail_by_ceco, detail_by_cuenta, detail_ceco_by_cuenta,
-- detail_planilla, proyectos_especiales, detail_proveedores_by_ceco).
-- Python keeps the cheap presentation work (pivot MES→columns, sort,
-- TOTAL row, the 77/77.6 prefix splits) — only the source frame changes.
--
-- Topology mirrors VISTA_PNL_SUMARIO / VISTA_PNL_PREPARADO — 4 per-CIA views +
-- REPORTES umbrella — so the optimizer can prune to one company on CIA = ?.
--
-- Output columns:
--   CIA              VARCHAR
--   YEAR             INT             -- YEAR(FECHA); cache key (company, year)
--                                       maps 1:1 to the WHERE clause.
--   MES              INT             -- MONTH(FECHA), 1..12.  Kept as a row (not
--                                       a column) so callers with a dynamic month
--                                       window (proyectos_especiales' trailing-12M
--                                       mes_cols) pivot client-side.
--   PARTIDA_PL       VARCHAR(40)     -- inherited from VISTA_PNL_PREPARADO
--   CENTRO_COSTO     VARCHAR
--   DESC_CECO        VARCHAR
--   CUENTA_CONTABLE  VARCHAR
--   DESCRIPCION      VARCHAR
--   NIT              VARCHAR         -- needed by proyectos_especiales +
--   RAZON_SOCIAL     VARCHAR            detail_proveedores_by_ceco (NIT-grain tables)
--   SALDO_TOTAL      DECIMAL(28,8)   -- SUM(SALDO) — all rows
--   SALDO_EX_IC      DECIMAL(28,8)   -- SUM(SALDO) excluding IS_INTERCOMPANY rows
--   SALDO_ONLY_IC    DECIMAL(28,8)   -- SUM(SALDO) of IS_INTERCOMPANY rows only
--
-- Why three SALDO columns instead of three views: the section path always
-- computes the "all" table plus its _ex_ic / _only_ic variants together
-- (data_service._add_ic_variants).  Returning all three SUMs in one row lets
-- one fetch feed all three variants — same rationale as VISTA_PNL_SUMARIO.
-- The _ex_ic / _only_ic variants are the SAME grain re-summed under the
-- IS_INTERCOMPANY filter, NOT a different grain — so no extra rows.
--
-- Filter baked in:
--   * IS_STATEMENT_ELIGIBLE = 1   — only statement-eligible rows feed the
--                                   section detail tables, matching the
--                                   df_stmt eligibility filter applied in
--                                   _run_pl_summary_only before preaggregate().
--
-- POR CLASIFICAR handling: rows with PARTIDA_PL = 'POR CLASIFICAR' are included
-- (same as VISTA_PNL_SUMARIO); filter at the Python layer if a given section
-- doesn't want them.  None of the section partida lists select POR CLASIFICAR,
-- so they are naturally excluded by the partida filter downstream.
-- =============================================================================


CREATE OR ALTER VIEW [FIBERLINE].[VISTA_PNL_PREAGG] AS
SELECT
    CIA,
    YEAR(FECHA) AS YEAR,
    MES,
    PARTIDA_PL,
    CENTRO_COSTO,
    DESC_CECO,
    CUENTA_CONTABLE,
    DESCRIPCION,
    NIT,
    RAZON_SOCIAL,
    CAST(SUM(SALDO)                                        AS DECIMAL(28, 8)) AS SALDO_TOTAL,
    CAST(SUM(CASE WHEN IS_INTERCOMPANY = 0 THEN SALDO END) AS DECIMAL(28, 8)) AS SALDO_EX_IC,
    CAST(SUM(CASE WHEN IS_INTERCOMPANY = 1 THEN SALDO END) AS DECIMAL(28, 8)) AS SALDO_ONLY_IC
FROM [FIBERLINE].[VISTA_PNL_PREPARADO]
WHERE IS_STATEMENT_ELIGIBLE = 1
GROUP BY CIA, YEAR(FECHA), MES, PARTIDA_PL,
         CENTRO_COSTO, DESC_CECO, CUENTA_CONTABLE, DESCRIPCION, NIT, RAZON_SOCIAL;
GO


CREATE OR ALTER VIEW [FIBERTECH].[VISTA_PNL_PREAGG] AS
SELECT
    CIA,
    YEAR(FECHA) AS YEAR,
    MES,
    PARTIDA_PL,
    CENTRO_COSTO,
    DESC_CECO,
    CUENTA_CONTABLE,
    DESCRIPCION,
    NIT,
    RAZON_SOCIAL,
    CAST(SUM(SALDO)                                        AS DECIMAL(28, 8)) AS SALDO_TOTAL,
    CAST(SUM(CASE WHEN IS_INTERCOMPANY = 0 THEN SALDO END) AS DECIMAL(28, 8)) AS SALDO_EX_IC,
    CAST(SUM(CASE WHEN IS_INTERCOMPANY = 1 THEN SALDO END) AS DECIMAL(28, 8)) AS SALDO_ONLY_IC
FROM [FIBERTECH].[VISTA_PNL_PREPARADO]
WHERE IS_STATEMENT_ELIGIBLE = 1
GROUP BY CIA, YEAR(FECHA), MES, PARTIDA_PL,
         CENTRO_COSTO, DESC_CECO, CUENTA_CONTABLE, DESCRIPCION, NIT, RAZON_SOCIAL;
GO


CREATE OR ALTER VIEW [NEXTNET].[VISTA_PNL_PREAGG] AS
SELECT
    CIA,
    YEAR(FECHA) AS YEAR,
    MES,
    PARTIDA_PL,
    CENTRO_COSTO,
    DESC_CECO,
    CUENTA_CONTABLE,
    DESCRIPCION,
    NIT,
    RAZON_SOCIAL,
    CAST(SUM(SALDO)                                        AS DECIMAL(28, 8)) AS SALDO_TOTAL,
    CAST(SUM(CASE WHEN IS_INTERCOMPANY = 0 THEN SALDO END) AS DECIMAL(28, 8)) AS SALDO_EX_IC,
    CAST(SUM(CASE WHEN IS_INTERCOMPANY = 1 THEN SALDO END) AS DECIMAL(28, 8)) AS SALDO_ONLY_IC
FROM [NEXTNET].[VISTA_PNL_PREPARADO]
WHERE IS_STATEMENT_ELIGIBLE = 1
GROUP BY CIA, YEAR(FECHA), MES, PARTIDA_PL,
         CENTRO_COSTO, DESC_CECO, CUENTA_CONTABLE, DESCRIPCION, NIT, RAZON_SOCIAL;
GO


CREATE OR ALTER VIEW [FIBERLUX].[VISTA_PNL_PREAGG] AS
SELECT
    CIA,
    YEAR(FECHA) AS YEAR,
    MES,
    PARTIDA_PL,
    CENTRO_COSTO,
    DESC_CECO,
    CUENTA_CONTABLE,
    DESCRIPCION,
    NIT,
    RAZON_SOCIAL,
    CAST(SUM(SALDO)                                        AS DECIMAL(28, 8)) AS SALDO_TOTAL,
    CAST(SUM(CASE WHEN IS_INTERCOMPANY = 0 THEN SALDO END) AS DECIMAL(28, 8)) AS SALDO_EX_IC,
    CAST(SUM(CASE WHEN IS_INTERCOMPANY = 1 THEN SALDO END) AS DECIMAL(28, 8)) AS SALDO_ONLY_IC
FROM [FIBERLUX].[VISTA_PNL_PREPARADO]
WHERE IS_STATEMENT_ELIGIBLE = 1
GROUP BY CIA, YEAR(FECHA), MES, PARTIDA_PL,
         CENTRO_COSTO, DESC_CECO, CUENTA_CONTABLE, DESCRIPCION, NIT, RAZON_SOCIAL;
GO


-- ─────────────────────────────────────────────────────────────────────────────
-- Umbrella view in REPORTES.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR ALTER VIEW [REPORTES].[VISTA_PNL_PREAGG] AS
SELECT * FROM [FIBERLINE].[VISTA_PNL_PREAGG]
UNION ALL
SELECT * FROM [FIBERTECH].[VISTA_PNL_PREAGG]
UNION ALL
SELECT * FROM [NEXTNET].[VISTA_PNL_PREAGG]
UNION ALL
SELECT * FROM [FIBERLUX].[VISTA_PNL_PREAGG];
GO


-- =============================================================================
-- Expected query pattern from data_service (Phase F section path):
--
--   SELECT MES, PARTIDA_PL, CENTRO_COSTO, DESC_CECO,
--          CUENTA_CONTABLE, DESCRIPCION, NIT, RAZON_SOCIAL,
--          SALDO_TOTAL, SALDO_EX_IC, SALDO_ONLY_IC
--   FROM REPORTES.VISTA_PNL_PREAGG
--   WHERE CIA = ? AND YEAR = ?;
--
-- Python rebuilds the (preagg, preagg_ex_ic, preagg_only_ic) triple by taking
-- the matching SALDO_* column as SALDO, then runs the existing aggregation
-- functions (pivot_by_month + sort + TOTAL row).  No GROUP BY left in pandas.
--
-- Parity (optional layer-isolation check — the end-to-end gate is the Python
-- diff script in Phase F step 6):  per (CIA, YEAR, MES, PARTIDA_PL), the SUM of
-- SALDO_TOTAL over this view must equal SALDO_TOTAL in VISTA_PNL_SUMARIO, since
-- this view only adds finer GROUP BY columns over the same filtered source:
--
--   SELECT s.CIA, s.YEAR, s.MES, s.PARTIDA_PL,
--          s.SALDO_TOTAL AS sumario, p.SALDO_TOTAL AS preagg_rolled
--   FROM REPORTES.VISTA_PNL_SUMARIO s
--   JOIN (
--       SELECT CIA, YEAR, MES, PARTIDA_PL,
--              SUM(SALDO_TOTAL) AS SALDO_TOTAL
--       FROM REPORTES.VISTA_PNL_PREAGG
--       GROUP BY CIA, YEAR, MES, PARTIDA_PL
--   ) p ON p.CIA = s.CIA AND p.YEAR = s.YEAR
--      AND p.MES = s.MES AND p.PARTIDA_PL = s.PARTIDA_PL
--   WHERE ABS(s.SALDO_TOTAL - p.SALDO_TOTAL) > 0.01;   -- expect zero rows
-- =============================================================================
