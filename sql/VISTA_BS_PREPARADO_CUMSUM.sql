-- =============================================================================
-- VISTA_BS_PREPARADO_CUMSUM  —  Phase E: BS at cuenta-grain with monthly cumsum
-- =============================================================================
-- Pushes the BS cumulative-sum across months into SQL.  Stays at cuenta-grain
-- (PARTIDA_BS, SECCION_BS, CUENTA_CONTABLE, DESCRIPCION) — NOT partida-grain —
-- because BS_RECLASSIFICATION_RULES in rules.py operate per-cuenta based on the
-- last-month balance, and partida-grain would lose the data needed to apply
-- them.  Partida-grain aggregation lives in VISTA_BS_SUMARIO, which sits on
-- top of THIS view after Python applies the reclassification.
--
-- Replaces in Python: the cumsum portion of statements.bs_summary
-- (`_apply_bs_cumsum` over the cuenta_pivot at statements.py:353-359).
--
-- What stays in Python (does NOT move into SQL):
--   * BS_RECLASSIFICATION_RULES — order-sensitive, must apply AFTER cumsum
--     because the decision depends on the last-month cumulative balance.
--     Three rules total (rules.py:67-71); easier as a 10-line pandas pass
--     than a CASE+JOIN chain in SQL.
--   * UTILIDAD NETA injection from P&L into PATRIMONIO — crosses statement
--     boundary; trivial in Python once both summaries are in memory.
--   * CORRIENTE / NO CORRIENTE display split — pure presentation (rules.py:88-96).
--
-- Topology mirrors the other views — 4 per-CIA + REPORTES umbrella.
--
-- Output columns:
--   CIA              VARCHAR
--   YEAR             INT             — YEAR(FECHA)
--   MES              INT             — MONTH(FECHA), 1..12
--   PARTIDA_BS       VARCHAR(60)     — inherited
--   SECCION_BS       VARCHAR(12)     — inherited
--   CUENTA_CONTABLE  VARCHAR
--   DESCRIPCION      VARCHAR         — latest non-null description for this cuenta
--   SALDO_MENSUAL    DECIMAL(28,8)   — SUM(SALDO) for that (cia, year, mes, cuenta)
--   SALDO_CUMSUM     DECIMAL(28,8)   — running total Jan 1 through end of MES
--
-- Window function semantics:
--   SUM(SALDO_MENSUAL) OVER (
--       PARTITION BY CIA, YEAR, CUENTA_CONTABLE
--       ORDER BY MES
--       ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
--   )
-- This is the cumsum the BS shows: each month's column = "balance as of end of
-- that month".  PARTITION BY YEAR means cumsum resets at Jan 1 of each year —
-- matches the Python behavior (fetch_bs_data always starts at year start).
--
-- Why the inner aggregation step (CTE `monthly`):
--   The source view emits one row per journal entry; we need one row per
--   (cia, year, mes, cuenta) before the cumsum so the window function adds up
--   one number per month, not millions.  PARTIDA_BS / SECCION_BS / DESCRIPCION
--   are functionally dependent on CUENTA_CONTABLE so we carry them via MAX().
-- =============================================================================


CREATE OR ALTER VIEW [FIBERLINE].[VISTA_BS_PREPARADO_CUMSUM] AS
WITH monthly AS (
    SELECT
        CIA,
        YEAR(FECHA)                     AS YEAR,
        MES,
        CUENTA_CONTABLE,
        MAX(PARTIDA_BS)                 AS PARTIDA_BS,
        MAX(SECCION_BS)                 AS SECCION_BS,
        MAX(DESCRIPCION)                AS DESCRIPCION,
        CAST(SUM(SALDO) AS DECIMAL(28, 8)) AS SALDO_MENSUAL
    FROM [FIBERLINE].[VISTA_BS_PREPARADO]
    GROUP BY CIA, YEAR(FECHA), MES, CUENTA_CONTABLE
)
SELECT
    CIA, YEAR, MES, PARTIDA_BS, SECCION_BS,
    CUENTA_CONTABLE, DESCRIPCION,
    SALDO_MENSUAL,
    CAST(
        SUM(SALDO_MENSUAL) OVER (
            PARTITION BY CIA, YEAR, CUENTA_CONTABLE
            ORDER BY MES
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        )
    AS DECIMAL(28, 8)) AS SALDO_CUMSUM
FROM monthly;
GO


CREATE OR ALTER VIEW [FIBERTECH].[VISTA_BS_PREPARADO_CUMSUM] AS
WITH monthly AS (
    SELECT
        CIA, YEAR(FECHA) AS YEAR, MES, CUENTA_CONTABLE,
        MAX(PARTIDA_BS)  AS PARTIDA_BS,
        MAX(SECCION_BS)  AS SECCION_BS,
        MAX(DESCRIPCION) AS DESCRIPCION,
        CAST(SUM(SALDO) AS DECIMAL(28, 8)) AS SALDO_MENSUAL
    FROM [FIBERTECH].[VISTA_BS_PREPARADO]
    GROUP BY CIA, YEAR(FECHA), MES, CUENTA_CONTABLE
)
SELECT
    CIA, YEAR, MES, PARTIDA_BS, SECCION_BS,
    CUENTA_CONTABLE, DESCRIPCION, SALDO_MENSUAL,
    CAST(
        SUM(SALDO_MENSUAL) OVER (
            PARTITION BY CIA, YEAR, CUENTA_CONTABLE
            ORDER BY MES
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        )
    AS DECIMAL(28, 8)) AS SALDO_CUMSUM
FROM monthly;
GO


CREATE OR ALTER VIEW [NEXTNET].[VISTA_BS_PREPARADO_CUMSUM] AS
WITH monthly AS (
    SELECT
        CIA, YEAR(FECHA) AS YEAR, MES, CUENTA_CONTABLE,
        MAX(PARTIDA_BS)  AS PARTIDA_BS,
        MAX(SECCION_BS)  AS SECCION_BS,
        MAX(DESCRIPCION) AS DESCRIPCION,
        CAST(SUM(SALDO) AS DECIMAL(28, 8)) AS SALDO_MENSUAL
    FROM [NEXTNET].[VISTA_BS_PREPARADO]
    GROUP BY CIA, YEAR(FECHA), MES, CUENTA_CONTABLE
)
SELECT
    CIA, YEAR, MES, PARTIDA_BS, SECCION_BS,
    CUENTA_CONTABLE, DESCRIPCION, SALDO_MENSUAL,
    CAST(
        SUM(SALDO_MENSUAL) OVER (
            PARTITION BY CIA, YEAR, CUENTA_CONTABLE
            ORDER BY MES
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        )
    AS DECIMAL(28, 8)) AS SALDO_CUMSUM
FROM monthly;
GO


CREATE OR ALTER VIEW [FIBERLUX].[VISTA_BS_PREPARADO_CUMSUM] AS
WITH monthly AS (
    SELECT
        CIA, YEAR(FECHA) AS YEAR, MES, CUENTA_CONTABLE,
        MAX(PARTIDA_BS)  AS PARTIDA_BS,
        MAX(SECCION_BS)  AS SECCION_BS,
        MAX(DESCRIPCION) AS DESCRIPCION,
        CAST(SUM(SALDO) AS DECIMAL(28, 8)) AS SALDO_MENSUAL
    FROM [FIBERLUX].[VISTA_BS_PREPARADO]
    GROUP BY CIA, YEAR(FECHA), MES, CUENTA_CONTABLE
)
SELECT
    CIA, YEAR, MES, PARTIDA_BS, SECCION_BS,
    CUENTA_CONTABLE, DESCRIPCION, SALDO_MENSUAL,
    CAST(
        SUM(SALDO_MENSUAL) OVER (
            PARTITION BY CIA, YEAR, CUENTA_CONTABLE
            ORDER BY MES
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        )
    AS DECIMAL(28, 8)) AS SALDO_CUMSUM
FROM monthly;
GO


-- ─────────────────────────────────────────────────────────────────────────────
-- Umbrella view in REPORTES.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR ALTER VIEW [REPORTES].[VISTA_BS_PREPARADO_CUMSUM] AS
SELECT * FROM [FIBERLINE].[VISTA_BS_PREPARADO_CUMSUM]
UNION ALL
SELECT * FROM [FIBERTECH].[VISTA_BS_PREPARADO_CUMSUM]
UNION ALL
SELECT * FROM [NEXTNET].[VISTA_BS_PREPARADO_CUMSUM]
UNION ALL
SELECT * FROM [FIBERLUX].[VISTA_BS_PREPARADO_CUMSUM];
GO


-- =============================================================================
-- Expected query pattern from data_service.load_bs_data:
--
--   SELECT MES, PARTIDA_BS, SECCION_BS, CUENTA_CONTABLE, DESCRIPCION,
--          SALDO_CUMSUM
--   FROM REPORTES.VISTA_BS_PREPARADO_CUMSUM
--   WHERE CIA = ? AND YEAR = ?;
--
-- Returns one row per (mes, cuenta) — roughly 12 × ~500 cuentas = ~6000 rows
-- per (company, year).  Python applies BS_RECLASSIFICATION_RULES (per-cuenta
-- on the last-month SALDO_CUMSUM), aggregates to partida-grain, injects
-- UTILIDAD NETA, and emits the display structure via _build_bs_rows.
--
-- Validation expectation (run after deploy):
--   SELECT TOP 20 *
--   FROM REPORTES.VISTA_BS_PREPARADO_CUMSUM
--   WHERE CIA = 'FIBERLINE' AND YEAR = 2025 AND MES = 12
--   ORDER BY ABS(SALDO_CUMSUM) DESC;
--
-- Each SALDO_CUMSUM at MES=12 should equal the SUM of SALDO_MENSUAL across
-- MES 1..12 for the same cuenta.  Spot-check 3-5 high-balance accounts
-- against the dashboard BS column for DEC.
-- =============================================================================
