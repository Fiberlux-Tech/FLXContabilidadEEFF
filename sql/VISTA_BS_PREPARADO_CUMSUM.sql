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
--   DESCRIPCION      VARCHAR         — MAX(DESCRIPCION) per cuenta-year
--   SALDO_MENSUAL    DECIMAL(28,8)   — SUM(SALDO) for that (cia, year, mes, cuenta)
--                                     (0 when no activity that month)
--   SALDO_CUMSUM     DECIMAL(28,8)   — running total Jan 1 through end of MES
--
-- =============================================================================
-- 2026-05-26 patch — calendar densification.
-- =============================================================================
-- Original DDL ran SUM() OVER directly on a `monthly` CTE that only had rows
-- for (cuenta, MES) pairs with activity. A cuenta booked once on Jan 1
-- produced exactly one row (MES=1), so downstream queries asking
-- "balance at end of MES=5?" got nothing back and treated it as zero.
-- VISTA_BS_SUMARIO TOTAL ACTIVO for FIBERLINE May 2025 came back ~S/. 4.6M
-- too low across multiple partidas (PATRIMONIO disappeared entirely; class
-- 33/3x ACTIVO cuentas booked only at year-open showed as zero from MES=2).
--
-- The patch introduces three CTEs:
--   * months(MES)    — calendar generator emitting 1..12
--   * cuenta_years   — one row per (CIA, YEAR, CUENTA) carrying attributes
--   * monthly        — GROUP BY (CIA, YEAR, MES, CUENTA) SUM(SALDO), unchanged
--   * dense          — cuenta_years CROSS JOIN months LEFT JOIN monthly,
--                      COALESCE(SALDO_MENSUAL, 0)
--
-- Window function then runs over the dense input — every cuenta has all 12
-- months, gap months contribute +0 to the running sum so the prior cumulative
-- balance carries forward correctly.
--
-- Row count: ~1,500 per (CIA, YEAR) on FIBERLINE (121 cuentas × 12 months);
-- ~3,000 on FIBERTECH (251 × 12).
--
-- Post-patch verification (2026-05-26):
--   * 50.1.1.1.01 Capital Emitido: 12 rows, all CUMSUM = S/. 10,180,068.00 ✓
--   * Row count = n_cuentas × 12 exactly for all 4 CIAs in 2025 ✓
--   * VISTA_BS_SUMARIO TOTAL ACTIVO FIBERLINE 2025/5 = S/. 16,126,321.00
--     (was 11,510,810.47; Python dashboard 16,086,457.31; residual
--     S/. 39,863.69 is the reclassification-timing semantic gap — see
--     "Open issue" in docs/SQL_VIEWS_ROADMAP.md Phase E).
-- =============================================================================


CREATE OR ALTER VIEW [FIBERLINE].[VISTA_BS_PREPARADO_CUMSUM] AS
WITH
months(MES) AS (
    SELECT 1  UNION ALL SELECT 2  UNION ALL SELECT 3  UNION ALL SELECT 4
    UNION ALL SELECT 5  UNION ALL SELECT 6  UNION ALL SELECT 7  UNION ALL SELECT 8
    UNION ALL SELECT 9  UNION ALL SELECT 10 UNION ALL SELECT 11 UNION ALL SELECT 12
),
cuenta_years AS (
    SELECT
        CIA,
        YEAR(FECHA)      AS YEAR,
        CUENTA_CONTABLE,
        MAX(PARTIDA_BS)  AS PARTIDA_BS,
        MAX(SECCION_BS)  AS SECCION_BS,
        MAX(DESCRIPCION) AS DESCRIPCION
    FROM [FIBERLINE].[VISTA_BS_PREPARADO]
    GROUP BY CIA, YEAR(FECHA), CUENTA_CONTABLE
),
monthly AS (
    SELECT
        CIA,
        YEAR(FECHA) AS YEAR,
        MES,
        CUENTA_CONTABLE,
        CAST(SUM(SALDO) AS DECIMAL(28, 8)) AS SALDO_MENSUAL
    FROM [FIBERLINE].[VISTA_BS_PREPARADO]
    GROUP BY CIA, YEAR(FECHA), MES, CUENTA_CONTABLE
),
dense AS (
    SELECT
        cy.CIA, cy.YEAR, m.MES,
        cy.CUENTA_CONTABLE, cy.PARTIDA_BS, cy.SECCION_BS, cy.DESCRIPCION,
        COALESCE(mo.SALDO_MENSUAL, 0) AS SALDO_MENSUAL
    FROM cuenta_years cy
    CROSS JOIN months m
    LEFT JOIN monthly mo
      ON  mo.CIA             = cy.CIA
      AND mo.YEAR            = cy.YEAR
      AND mo.CUENTA_CONTABLE = cy.CUENTA_CONTABLE
      AND mo.MES             = m.MES
)
SELECT
    CIA, YEAR, MES,
    PARTIDA_BS, SECCION_BS,
    CUENTA_CONTABLE, DESCRIPCION,
    CAST(SALDO_MENSUAL AS DECIMAL(28, 8)) AS SALDO_MENSUAL,
    CAST(
        SUM(SALDO_MENSUAL) OVER (
            PARTITION BY CIA, YEAR, CUENTA_CONTABLE
            ORDER BY MES
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        )
    AS DECIMAL(28, 8)) AS SALDO_CUMSUM
FROM dense;
GO


CREATE OR ALTER VIEW [FIBERTECH].[VISTA_BS_PREPARADO_CUMSUM] AS
WITH
months(MES) AS (
    SELECT 1  UNION ALL SELECT 2  UNION ALL SELECT 3  UNION ALL SELECT 4
    UNION ALL SELECT 5  UNION ALL SELECT 6  UNION ALL SELECT 7  UNION ALL SELECT 8
    UNION ALL SELECT 9  UNION ALL SELECT 10 UNION ALL SELECT 11 UNION ALL SELECT 12
),
cuenta_years AS (
    SELECT
        CIA,
        YEAR(FECHA)      AS YEAR,
        CUENTA_CONTABLE,
        MAX(PARTIDA_BS)  AS PARTIDA_BS,
        MAX(SECCION_BS)  AS SECCION_BS,
        MAX(DESCRIPCION) AS DESCRIPCION
    FROM [FIBERTECH].[VISTA_BS_PREPARADO]
    GROUP BY CIA, YEAR(FECHA), CUENTA_CONTABLE
),
monthly AS (
    SELECT
        CIA,
        YEAR(FECHA) AS YEAR,
        MES,
        CUENTA_CONTABLE,
        CAST(SUM(SALDO) AS DECIMAL(28, 8)) AS SALDO_MENSUAL
    FROM [FIBERTECH].[VISTA_BS_PREPARADO]
    GROUP BY CIA, YEAR(FECHA), MES, CUENTA_CONTABLE
),
dense AS (
    SELECT
        cy.CIA, cy.YEAR, m.MES,
        cy.CUENTA_CONTABLE, cy.PARTIDA_BS, cy.SECCION_BS, cy.DESCRIPCION,
        COALESCE(mo.SALDO_MENSUAL, 0) AS SALDO_MENSUAL
    FROM cuenta_years cy
    CROSS JOIN months m
    LEFT JOIN monthly mo
      ON  mo.CIA             = cy.CIA
      AND mo.YEAR            = cy.YEAR
      AND mo.CUENTA_CONTABLE = cy.CUENTA_CONTABLE
      AND mo.MES             = m.MES
)
SELECT
    CIA, YEAR, MES,
    PARTIDA_BS, SECCION_BS,
    CUENTA_CONTABLE, DESCRIPCION,
    CAST(SALDO_MENSUAL AS DECIMAL(28, 8)) AS SALDO_MENSUAL,
    CAST(
        SUM(SALDO_MENSUAL) OVER (
            PARTITION BY CIA, YEAR, CUENTA_CONTABLE
            ORDER BY MES
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        )
    AS DECIMAL(28, 8)) AS SALDO_CUMSUM
FROM dense;
GO


CREATE OR ALTER VIEW [NEXTNET].[VISTA_BS_PREPARADO_CUMSUM] AS
WITH
months(MES) AS (
    SELECT 1  UNION ALL SELECT 2  UNION ALL SELECT 3  UNION ALL SELECT 4
    UNION ALL SELECT 5  UNION ALL SELECT 6  UNION ALL SELECT 7  UNION ALL SELECT 8
    UNION ALL SELECT 9  UNION ALL SELECT 10 UNION ALL SELECT 11 UNION ALL SELECT 12
),
cuenta_years AS (
    SELECT
        CIA,
        YEAR(FECHA)      AS YEAR,
        CUENTA_CONTABLE,
        MAX(PARTIDA_BS)  AS PARTIDA_BS,
        MAX(SECCION_BS)  AS SECCION_BS,
        MAX(DESCRIPCION) AS DESCRIPCION
    FROM [NEXTNET].[VISTA_BS_PREPARADO]
    GROUP BY CIA, YEAR(FECHA), CUENTA_CONTABLE
),
monthly AS (
    SELECT
        CIA,
        YEAR(FECHA) AS YEAR,
        MES,
        CUENTA_CONTABLE,
        CAST(SUM(SALDO) AS DECIMAL(28, 8)) AS SALDO_MENSUAL
    FROM [NEXTNET].[VISTA_BS_PREPARADO]
    GROUP BY CIA, YEAR(FECHA), MES, CUENTA_CONTABLE
),
dense AS (
    SELECT
        cy.CIA, cy.YEAR, m.MES,
        cy.CUENTA_CONTABLE, cy.PARTIDA_BS, cy.SECCION_BS, cy.DESCRIPCION,
        COALESCE(mo.SALDO_MENSUAL, 0) AS SALDO_MENSUAL
    FROM cuenta_years cy
    CROSS JOIN months m
    LEFT JOIN monthly mo
      ON  mo.CIA             = cy.CIA
      AND mo.YEAR            = cy.YEAR
      AND mo.CUENTA_CONTABLE = cy.CUENTA_CONTABLE
      AND mo.MES             = m.MES
)
SELECT
    CIA, YEAR, MES,
    PARTIDA_BS, SECCION_BS,
    CUENTA_CONTABLE, DESCRIPCION,
    CAST(SALDO_MENSUAL AS DECIMAL(28, 8)) AS SALDO_MENSUAL,
    CAST(
        SUM(SALDO_MENSUAL) OVER (
            PARTITION BY CIA, YEAR, CUENTA_CONTABLE
            ORDER BY MES
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        )
    AS DECIMAL(28, 8)) AS SALDO_CUMSUM
FROM dense;
GO


CREATE OR ALTER VIEW [FIBERLUX].[VISTA_BS_PREPARADO_CUMSUM] AS
WITH
months(MES) AS (
    SELECT 1  UNION ALL SELECT 2  UNION ALL SELECT 3  UNION ALL SELECT 4
    UNION ALL SELECT 5  UNION ALL SELECT 6  UNION ALL SELECT 7  UNION ALL SELECT 8
    UNION ALL SELECT 9  UNION ALL SELECT 10 UNION ALL SELECT 11 UNION ALL SELECT 12
),
cuenta_years AS (
    SELECT
        CIA,
        YEAR(FECHA)      AS YEAR,
        CUENTA_CONTABLE,
        MAX(PARTIDA_BS)  AS PARTIDA_BS,
        MAX(SECCION_BS)  AS SECCION_BS,
        MAX(DESCRIPCION) AS DESCRIPCION
    FROM [FIBERLUX].[VISTA_BS_PREPARADO]
    GROUP BY CIA, YEAR(FECHA), CUENTA_CONTABLE
),
monthly AS (
    SELECT
        CIA,
        YEAR(FECHA) AS YEAR,
        MES,
        CUENTA_CONTABLE,
        CAST(SUM(SALDO) AS DECIMAL(28, 8)) AS SALDO_MENSUAL
    FROM [FIBERLUX].[VISTA_BS_PREPARADO]
    GROUP BY CIA, YEAR(FECHA), MES, CUENTA_CONTABLE
),
dense AS (
    SELECT
        cy.CIA, cy.YEAR, m.MES,
        cy.CUENTA_CONTABLE, cy.PARTIDA_BS, cy.SECCION_BS, cy.DESCRIPCION,
        COALESCE(mo.SALDO_MENSUAL, 0) AS SALDO_MENSUAL
    FROM cuenta_years cy
    CROSS JOIN months m
    LEFT JOIN monthly mo
      ON  mo.CIA             = cy.CIA
      AND mo.YEAR            = cy.YEAR
      AND mo.CUENTA_CONTABLE = cy.CUENTA_CONTABLE
      AND mo.MES             = m.MES
)
SELECT
    CIA, YEAR, MES,
    PARTIDA_BS, SECCION_BS,
    CUENTA_CONTABLE, DESCRIPCION,
    CAST(SALDO_MENSUAL AS DECIMAL(28, 8)) AS SALDO_MENSUAL,
    CAST(
        SUM(SALDO_MENSUAL) OVER (
            PARTITION BY CIA, YEAR, CUENTA_CONTABLE
            ORDER BY MES
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        )
    AS DECIMAL(28, 8)) AS SALDO_CUMSUM
FROM dense;
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
-- Expected query pattern from data_service.load_bs_data (post Phase C wiring):
--
--   SELECT MES, PARTIDA_BS, SECCION_BS, SALDO
--   FROM REPORTES.VISTA_BS_SUMARIO
--   WHERE CIA = ? AND YEAR = ?;
--
-- Python never queries VISTA_BS_PREPARADO_CUMSUM directly — VISTA_BS_SUMARIO
-- sits on top of it and is the only consumer.
--
-- Post-deploy verification:
--   SELECT MES, CAST(SALDO_CUMSUM AS DECIMAL(20,2)) AS CUMSUM
--   FROM REPORTES.VISTA_BS_PREPARADO_CUMSUM
--   WHERE CIA = 'FIBERLINE' AND YEAR = 2025 AND CUENTA_CONTABLE = '50.1.1.1.01'
--   ORDER BY MES;
--   -- Expected: 12 rows, all CUMSUM = 10180068.00
--
--   SELECT CIA, YEAR, COUNT(*) AS n_rows, COUNT(DISTINCT CUENTA_CONTABLE) AS n_cuentas
--   FROM REPORTES.VISTA_BS_PREPARADO_CUMSUM
--   WHERE YEAR = 2025
--   GROUP BY CIA, YEAR;
--   -- Expected: n_rows = n_cuentas * 12 exactly for every CIA
-- =============================================================================
