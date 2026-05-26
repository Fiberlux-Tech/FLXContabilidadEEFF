-- =============================================================================
-- VISTA_BS_SUMARIO  —  Phase C: pre-aggregated BS summary (post-reclassification)
-- =============================================================================
-- Sits on top of VISTA_BS_PREPARADO_CUMSUM.  Applies the three
-- BS_RECLASSIFICATION_RULES from rules.py:67-71 (per-cuenta, based on the
-- last-month cumulative balance) and then groups to partida-grain.  The
-- dashboard fetches ~30 rows per (CIA, YEAR) instead of pulling ~6K
-- cuenta-rows and reclassifying in pandas.
--
-- Replaces in Python: statements._reclassify_bs_cuentas (statements.py:257-290)
-- plus the partida aggregation loop that follows it (statements.py:377-394).
--
-- What still stays in Python AFTER this view ships:
--   * UTILIDAD NETA injection — crosses P&L/BS boundary; 5 lines, easier in
--     Python once both summaries are loaded.
--   * CORRIENTE / NO CORRIENTE display split (rules.py:88-96).
--   * BS-balance validation (_validate_bs_balance) and the _build_bs_rows
--     display structure (TOTAL ACTIVO / TOTAL PASIVO / TOTAL PASIVO Y PATRIMONIO).
--   * Display sort order (BS_PARTIDA_ORDER, BS_SECTION_ORDER).
--
-- The three reclassification rules (in evaluation order, first match wins):
--   1. CUENTA_CONTABLE = '12.2.1.1.01' AND last-month cumsum < 0
--        → PARTIDA_BS = 'Anticipos Recibidos', SECCION_BS = 'PASIVO', sign flipped
--   2. CUENTA_CONTABLE starts with '14'   AND last-month cumsum < 0
--        → PARTIDA_BS = 'Provisiones por beneficios a empleados', SECCION_BS = 'PASIVO', sign flipped
--   3. CUENTA_CONTABLE starts with '42.2' AND last-month cumsum < 0
--        → PARTIDA_BS = 'Anticipos Otorgados', SECCION_BS = 'ACTIVO', sign flipped
--
-- "Last-month cumsum" = SALDO_CUMSUM where MES = 12 (or MAX(MES) for the
-- current year, since rows for future months don't exist yet).
--
-- Native-section sign flip (statements.py:283-287):
--   When an account's native section (1/2/3=ACTIVO, 4=PASIVO, 5=PATRIMONIO)
--   differs from its assigned section, the sign flips.  Apply BEFORE
--   reclassification in the cumsum view's output.  Since
--   VISTA_BS_PREPARADO.SALDO is already (DEBITO-CREDITO) for classes 1/2/3
--   and (CREDITO-DEBITO) for 4/5, the native-section flip only kicks in for
--   the static cross-section overrides — VISTA_BS_PREPARADO maps a handful
--   of '16.7.1.1.01%' / '16.7.2.1.01%' accounts to 'PASIVO' but they have
--   FIRST_CHAR='1' (native ACTIVO), so their sign should flip.
--
-- Output columns:
--   CIA          VARCHAR
--   YEAR         INT
--   MES          INT             — 1..12 (each month is the cumulative-as-of-end-of-month)
--   PARTIDA_BS   VARCHAR(60)     — post-reclassification
--   SECCION_BS   VARCHAR(12)     — post-reclassification
--   SALDO        DECIMAL(28,8)   — sum of SALDO_CUMSUM (sign-corrected) across cuentas
-- =============================================================================


-- Per-CIA pattern: a CTE computes the last-month cumulative balance per cuenta,
-- a second CTE picks the reclassified PARTIDA/SECCION/sign, and the outer
-- SELECT groups to partida-grain.

CREATE OR ALTER VIEW [FIBERLINE].[VISTA_BS_SUMARIO] AS
WITH
last_month_balance AS (
    -- Last available month per (cia, year, cuenta).  In the current year the
    -- max MES with rows is what we use; in closed years it's 12.
    SELECT CIA, YEAR, CUENTA_CONTABLE,
           MAX(SALDO_CUMSUM_FOR_MAX_MES) AS LAST_BAL
    FROM (
        SELECT CIA, YEAR, CUENTA_CONTABLE,
               FIRST_VALUE(SALDO_CUMSUM) OVER (
                   PARTITION BY CIA, YEAR, CUENTA_CONTABLE
                   ORDER BY MES DESC
               ) AS SALDO_CUMSUM_FOR_MAX_MES
        FROM [FIBERLINE].[VISTA_BS_PREPARADO_CUMSUM]
    ) x
    GROUP BY CIA, YEAR, CUENTA_CONTABLE
),
reclassified AS (
    SELECT
        c.CIA, c.YEAR, c.MES,
        c.CUENTA_CONTABLE,

        -- PARTIDA_BS after reclassification (first matching rule wins)
        CASE
            WHEN c.CUENTA_CONTABLE = '12.2.1.1.01' AND lmb.LAST_BAL < 0
                THEN 'Anticipos Recibidos'
            WHEN LEFT(c.CUENTA_CONTABLE, 2) = '14' AND lmb.LAST_BAL < 0
                THEN 'Provisiones por beneficios a empleados'
            WHEN LEFT(c.CUENTA_CONTABLE, 4) = '42.2' AND lmb.LAST_BAL < 0
                THEN 'Anticipos Otorgados'
            ELSE c.PARTIDA_BS
        END AS PARTIDA_BS_FINAL,

        -- SECCION_BS after reclassification
        CASE
            WHEN c.CUENTA_CONTABLE = '12.2.1.1.01' AND lmb.LAST_BAL < 0
                THEN 'PASIVO'
            WHEN LEFT(c.CUENTA_CONTABLE, 2) = '14' AND lmb.LAST_BAL < 0
                THEN 'PASIVO'
            WHEN LEFT(c.CUENTA_CONTABLE, 4) = '42.2' AND lmb.LAST_BAL < 0
                THEN 'ACTIVO'
            ELSE c.SECCION_BS
        END AS SECCION_BS_FINAL,

        -- Sign-corrected SALDO_CUMSUM:
        --   * Reclassified rows: flip sign (statements.py:276 vals = -vals)
        --   * Static cross-section override (native != assigned): flip sign
        --   * Otherwise: keep sign
        -- Native section = ACTIVO when FIRST_CHAR in 1/2/3, PASIVO when 4, PATRIMONIO when 5.
        CAST(
            CASE
                -- Reclassified → flip
                WHEN c.CUENTA_CONTABLE = '12.2.1.1.01' AND lmb.LAST_BAL < 0
                    THEN -c.SALDO_CUMSUM
                WHEN LEFT(c.CUENTA_CONTABLE, 2) = '14' AND lmb.LAST_BAL < 0
                    THEN -c.SALDO_CUMSUM
                WHEN LEFT(c.CUENTA_CONTABLE, 4) = '42.2' AND lmb.LAST_BAL < 0
                    THEN -c.SALDO_CUMSUM
                -- Static override (native section ≠ assigned section) → flip
                WHEN LEFT(c.CUENTA_CONTABLE, 1) IN ('1','2','3') AND c.SECCION_BS <> 'ACTIVO'
                    THEN -c.SALDO_CUMSUM
                WHEN LEFT(c.CUENTA_CONTABLE, 1) = '4'           AND c.SECCION_BS <> 'PASIVO'
                    THEN -c.SALDO_CUMSUM
                WHEN LEFT(c.CUENTA_CONTABLE, 1) = '5'           AND c.SECCION_BS <> 'PATRIMONIO'
                    THEN -c.SALDO_CUMSUM
                ELSE c.SALDO_CUMSUM
            END
        AS DECIMAL(28, 8)) AS SALDO_SIGNED
    FROM [FIBERLINE].[VISTA_BS_PREPARADO_CUMSUM] c
    JOIN last_month_balance lmb
      ON lmb.CIA = c.CIA
     AND lmb.YEAR = c.YEAR
     AND lmb.CUENTA_CONTABLE = c.CUENTA_CONTABLE
)
SELECT
    CIA, YEAR, MES, PARTIDA_BS_FINAL AS PARTIDA_BS, SECCION_BS_FINAL AS SECCION_BS,
    CAST(SUM(SALDO_SIGNED) AS DECIMAL(28, 8)) AS SALDO
FROM reclassified
GROUP BY CIA, YEAR, MES, PARTIDA_BS_FINAL, SECCION_BS_FINAL;
GO


CREATE OR ALTER VIEW [FIBERTECH].[VISTA_BS_SUMARIO] AS
WITH
last_month_balance AS (
    SELECT CIA, YEAR, CUENTA_CONTABLE,
           MAX(SALDO_CUMSUM_FOR_MAX_MES) AS LAST_BAL
    FROM (
        SELECT CIA, YEAR, CUENTA_CONTABLE,
               FIRST_VALUE(SALDO_CUMSUM) OVER (
                   PARTITION BY CIA, YEAR, CUENTA_CONTABLE
                   ORDER BY MES DESC
               ) AS SALDO_CUMSUM_FOR_MAX_MES
        FROM [FIBERTECH].[VISTA_BS_PREPARADO_CUMSUM]
    ) x
    GROUP BY CIA, YEAR, CUENTA_CONTABLE
),
reclassified AS (
    SELECT
        c.CIA, c.YEAR, c.MES, c.CUENTA_CONTABLE,
        CASE
            WHEN c.CUENTA_CONTABLE = '12.2.1.1.01' AND lmb.LAST_BAL < 0 THEN 'Anticipos Recibidos'
            WHEN LEFT(c.CUENTA_CONTABLE, 2) = '14' AND lmb.LAST_BAL < 0 THEN 'Provisiones por beneficios a empleados'
            WHEN LEFT(c.CUENTA_CONTABLE, 4) = '42.2' AND lmb.LAST_BAL < 0 THEN 'Anticipos Otorgados'
            ELSE c.PARTIDA_BS
        END AS PARTIDA_BS_FINAL,
        CASE
            WHEN c.CUENTA_CONTABLE = '12.2.1.1.01' AND lmb.LAST_BAL < 0 THEN 'PASIVO'
            WHEN LEFT(c.CUENTA_CONTABLE, 2) = '14' AND lmb.LAST_BAL < 0 THEN 'PASIVO'
            WHEN LEFT(c.CUENTA_CONTABLE, 4) = '42.2' AND lmb.LAST_BAL < 0 THEN 'ACTIVO'
            ELSE c.SECCION_BS
        END AS SECCION_BS_FINAL,
        CAST(
            CASE
                WHEN c.CUENTA_CONTABLE = '12.2.1.1.01' AND lmb.LAST_BAL < 0 THEN -c.SALDO_CUMSUM
                WHEN LEFT(c.CUENTA_CONTABLE, 2) = '14' AND lmb.LAST_BAL < 0 THEN -c.SALDO_CUMSUM
                WHEN LEFT(c.CUENTA_CONTABLE, 4) = '42.2' AND lmb.LAST_BAL < 0 THEN -c.SALDO_CUMSUM
                WHEN LEFT(c.CUENTA_CONTABLE, 1) IN ('1','2','3') AND c.SECCION_BS <> 'ACTIVO'     THEN -c.SALDO_CUMSUM
                WHEN LEFT(c.CUENTA_CONTABLE, 1) = '4'           AND c.SECCION_BS <> 'PASIVO'     THEN -c.SALDO_CUMSUM
                WHEN LEFT(c.CUENTA_CONTABLE, 1) = '5'           AND c.SECCION_BS <> 'PATRIMONIO' THEN -c.SALDO_CUMSUM
                ELSE c.SALDO_CUMSUM
            END
        AS DECIMAL(28, 8)) AS SALDO_SIGNED
    FROM [FIBERTECH].[VISTA_BS_PREPARADO_CUMSUM] c
    JOIN last_month_balance lmb
      ON lmb.CIA = c.CIA AND lmb.YEAR = c.YEAR AND lmb.CUENTA_CONTABLE = c.CUENTA_CONTABLE
)
SELECT
    CIA, YEAR, MES, PARTIDA_BS_FINAL AS PARTIDA_BS, SECCION_BS_FINAL AS SECCION_BS,
    CAST(SUM(SALDO_SIGNED) AS DECIMAL(28, 8)) AS SALDO
FROM reclassified
GROUP BY CIA, YEAR, MES, PARTIDA_BS_FINAL, SECCION_BS_FINAL;
GO


CREATE OR ALTER VIEW [NEXTNET].[VISTA_BS_SUMARIO] AS
WITH
last_month_balance AS (
    SELECT CIA, YEAR, CUENTA_CONTABLE,
           MAX(SALDO_CUMSUM_FOR_MAX_MES) AS LAST_BAL
    FROM (
        SELECT CIA, YEAR, CUENTA_CONTABLE,
               FIRST_VALUE(SALDO_CUMSUM) OVER (
                   PARTITION BY CIA, YEAR, CUENTA_CONTABLE
                   ORDER BY MES DESC
               ) AS SALDO_CUMSUM_FOR_MAX_MES
        FROM [NEXTNET].[VISTA_BS_PREPARADO_CUMSUM]
    ) x
    GROUP BY CIA, YEAR, CUENTA_CONTABLE
),
reclassified AS (
    SELECT
        c.CIA, c.YEAR, c.MES, c.CUENTA_CONTABLE,
        CASE
            WHEN c.CUENTA_CONTABLE = '12.2.1.1.01' AND lmb.LAST_BAL < 0 THEN 'Anticipos Recibidos'
            WHEN LEFT(c.CUENTA_CONTABLE, 2) = '14' AND lmb.LAST_BAL < 0 THEN 'Provisiones por beneficios a empleados'
            WHEN LEFT(c.CUENTA_CONTABLE, 4) = '42.2' AND lmb.LAST_BAL < 0 THEN 'Anticipos Otorgados'
            ELSE c.PARTIDA_BS
        END AS PARTIDA_BS_FINAL,
        CASE
            WHEN c.CUENTA_CONTABLE = '12.2.1.1.01' AND lmb.LAST_BAL < 0 THEN 'PASIVO'
            WHEN LEFT(c.CUENTA_CONTABLE, 2) = '14' AND lmb.LAST_BAL < 0 THEN 'PASIVO'
            WHEN LEFT(c.CUENTA_CONTABLE, 4) = '42.2' AND lmb.LAST_BAL < 0 THEN 'ACTIVO'
            ELSE c.SECCION_BS
        END AS SECCION_BS_FINAL,
        CAST(
            CASE
                WHEN c.CUENTA_CONTABLE = '12.2.1.1.01' AND lmb.LAST_BAL < 0 THEN -c.SALDO_CUMSUM
                WHEN LEFT(c.CUENTA_CONTABLE, 2) = '14' AND lmb.LAST_BAL < 0 THEN -c.SALDO_CUMSUM
                WHEN LEFT(c.CUENTA_CONTABLE, 4) = '42.2' AND lmb.LAST_BAL < 0 THEN -c.SALDO_CUMSUM
                WHEN LEFT(c.CUENTA_CONTABLE, 1) IN ('1','2','3') AND c.SECCION_BS <> 'ACTIVO'     THEN -c.SALDO_CUMSUM
                WHEN LEFT(c.CUENTA_CONTABLE, 1) = '4'           AND c.SECCION_BS <> 'PASIVO'     THEN -c.SALDO_CUMSUM
                WHEN LEFT(c.CUENTA_CONTABLE, 1) = '5'           AND c.SECCION_BS <> 'PATRIMONIO' THEN -c.SALDO_CUMSUM
                ELSE c.SALDO_CUMSUM
            END
        AS DECIMAL(28, 8)) AS SALDO_SIGNED
    FROM [NEXTNET].[VISTA_BS_PREPARADO_CUMSUM] c
    JOIN last_month_balance lmb
      ON lmb.CIA = c.CIA AND lmb.YEAR = c.YEAR AND lmb.CUENTA_CONTABLE = c.CUENTA_CONTABLE
)
SELECT
    CIA, YEAR, MES, PARTIDA_BS_FINAL AS PARTIDA_BS, SECCION_BS_FINAL AS SECCION_BS,
    CAST(SUM(SALDO_SIGNED) AS DECIMAL(28, 8)) AS SALDO
FROM reclassified
GROUP BY CIA, YEAR, MES, PARTIDA_BS_FINAL, SECCION_BS_FINAL;
GO


CREATE OR ALTER VIEW [FIBERLUX].[VISTA_BS_SUMARIO] AS
WITH
last_month_balance AS (
    SELECT CIA, YEAR, CUENTA_CONTABLE,
           MAX(SALDO_CUMSUM_FOR_MAX_MES) AS LAST_BAL
    FROM (
        SELECT CIA, YEAR, CUENTA_CONTABLE,
               FIRST_VALUE(SALDO_CUMSUM) OVER (
                   PARTITION BY CIA, YEAR, CUENTA_CONTABLE
                   ORDER BY MES DESC
               ) AS SALDO_CUMSUM_FOR_MAX_MES
        FROM [FIBERLUX].[VISTA_BS_PREPARADO_CUMSUM]
    ) x
    GROUP BY CIA, YEAR, CUENTA_CONTABLE
),
reclassified AS (
    SELECT
        c.CIA, c.YEAR, c.MES, c.CUENTA_CONTABLE,
        CASE
            WHEN c.CUENTA_CONTABLE = '12.2.1.1.01' AND lmb.LAST_BAL < 0 THEN 'Anticipos Recibidos'
            WHEN LEFT(c.CUENTA_CONTABLE, 2) = '14' AND lmb.LAST_BAL < 0 THEN 'Provisiones por beneficios a empleados'
            WHEN LEFT(c.CUENTA_CONTABLE, 4) = '42.2' AND lmb.LAST_BAL < 0 THEN 'Anticipos Otorgados'
            ELSE c.PARTIDA_BS
        END AS PARTIDA_BS_FINAL,
        CASE
            WHEN c.CUENTA_CONTABLE = '12.2.1.1.01' AND lmb.LAST_BAL < 0 THEN 'PASIVO'
            WHEN LEFT(c.CUENTA_CONTABLE, 2) = '14' AND lmb.LAST_BAL < 0 THEN 'PASIVO'
            WHEN LEFT(c.CUENTA_CONTABLE, 4) = '42.2' AND lmb.LAST_BAL < 0 THEN 'ACTIVO'
            ELSE c.SECCION_BS
        END AS SECCION_BS_FINAL,
        CAST(
            CASE
                WHEN c.CUENTA_CONTABLE = '12.2.1.1.01' AND lmb.LAST_BAL < 0 THEN -c.SALDO_CUMSUM
                WHEN LEFT(c.CUENTA_CONTABLE, 2) = '14' AND lmb.LAST_BAL < 0 THEN -c.SALDO_CUMSUM
                WHEN LEFT(c.CUENTA_CONTABLE, 4) = '42.2' AND lmb.LAST_BAL < 0 THEN -c.SALDO_CUMSUM
                WHEN LEFT(c.CUENTA_CONTABLE, 1) IN ('1','2','3') AND c.SECCION_BS <> 'ACTIVO'     THEN -c.SALDO_CUMSUM
                WHEN LEFT(c.CUENTA_CONTABLE, 1) = '4'           AND c.SECCION_BS <> 'PASIVO'     THEN -c.SALDO_CUMSUM
                WHEN LEFT(c.CUENTA_CONTABLE, 1) = '5'           AND c.SECCION_BS <> 'PATRIMONIO' THEN -c.SALDO_CUMSUM
                ELSE c.SALDO_CUMSUM
            END
        AS DECIMAL(28, 8)) AS SALDO_SIGNED
    FROM [FIBERLUX].[VISTA_BS_PREPARADO_CUMSUM] c
    JOIN last_month_balance lmb
      ON lmb.CIA = c.CIA AND lmb.YEAR = c.YEAR AND lmb.CUENTA_CONTABLE = c.CUENTA_CONTABLE
)
SELECT
    CIA, YEAR, MES, PARTIDA_BS_FINAL AS PARTIDA_BS, SECCION_BS_FINAL AS SECCION_BS,
    CAST(SUM(SALDO_SIGNED) AS DECIMAL(28, 8)) AS SALDO
FROM reclassified
GROUP BY CIA, YEAR, MES, PARTIDA_BS_FINAL, SECCION_BS_FINAL;
GO


-- ─────────────────────────────────────────────────────────────────────────────
-- Umbrella view in REPORTES.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR ALTER VIEW [REPORTES].[VISTA_BS_SUMARIO] AS
SELECT * FROM [FIBERLINE].[VISTA_BS_SUMARIO]
UNION ALL
SELECT * FROM [FIBERTECH].[VISTA_BS_SUMARIO]
UNION ALL
SELECT * FROM [NEXTNET].[VISTA_BS_SUMARIO]
UNION ALL
SELECT * FROM [FIBERLUX].[VISTA_BS_SUMARIO];
GO


-- =============================================================================
-- Expected query pattern from data_service.load_bs_data:
--
--   SELECT MES, PARTIDA_BS, SECCION_BS, SALDO
--   FROM REPORTES.VISTA_BS_SUMARIO
--   WHERE CIA = ? AND YEAR = ?;
--
-- Returns ~30 rows × 12 months = ~360 rows per (company, year).  Python
-- pivots MES → columns, injects "Resultados del Ejercicio" from the P&L
-- summary, and emits the display structure via _build_bs_rows.
--
-- Validation: after deploy, compare TOTAL ACTIVO / TOTAL PASIVO+PATRIMONIO
-- per (CIA, YEAR, MES=12) against the dashboard's existing DEC column for
-- a known-good month.  If they balance to within 0.01 PEN, the view matches
-- _build_bs_rows semantics.
-- =============================================================================
