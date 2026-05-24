-- =============================================================================
-- Parity checks for VISTA_PNL_PREPARADO / VISTA_BS_PREPARADO
-- =============================================================================
-- Run these after redeploying the views (DDL changes in VISTA_PNL_PREPARADO.sql
-- or VISTA_BS_PREPARADO.sql). Each query returns rows ONLY when there is a
-- discrepancy worth investigating. These are now the only post-deploy gate:
-- the Python-side parity harness (sql/parity_check.py) was deleted in Phase A
-- Step 4 once the SQL view became the single source of truth.
-- =============================================================================


-- -----------------------------------------------------------------------------
-- 1. PARTIDA_PL coverage — no rows should be 'POR CLASIFICAR'
-- -----------------------------------------------------------------------------
-- Python logs a warning when this happens (transforms.py:157-164). Ideally the
-- view returns zero rows. If any appear, the CUENTA sample tells us which
-- account isn't covered by the 15 rules.

SELECT TOP 50
    CIA,
    CUENTA_CONTABLE,
    CENTRO_COSTO,
    COUNT(*) AS n
FROM REPORTES.VISTA_PNL_PREPARADO
WHERE PARTIDA_PL = 'POR CLASIFICAR'
GROUP BY CIA, CUENTA_CONTABLE, CENTRO_COSTO
ORDER BY n DESC;


-- -----------------------------------------------------------------------------
-- 2. PARTIDA_BS coverage — POR DEFINIR rows are tolerated but flagged
-- -----------------------------------------------------------------------------
-- transforms.py:227 warns on these. Same expectation: minimal occurrences.

SELECT
    PARTIDA_BS,
    COUNT(*) AS n,
    COUNT(DISTINCT CUENTA_CONTABLE) AS distinct_cuentas
FROM REPORTES.VISTA_BS_PREPARADO
WHERE PARTIDA_BS LIKE 'POR DEFINIR%'
GROUP BY PARTIDA_BS;


-- -----------------------------------------------------------------------------
-- 3. PARTIDA_BS / SECCION_BS consistency
-- -----------------------------------------------------------------------------
-- Tributos por Pagar from 16.7.1.1.01 / 16.7.2.1.01 must be in PASIVO.
-- Tributos por acreditar from 16.7.* must stay in ACTIVO (first char = '1').
-- Patrimonio partidas must be in PATRIMONIO.

SELECT
    PARTIDA_BS,
    SECCION_BS,
    LEFT(CUENTA_CONTABLE, 1) AS first_char,
    COUNT(*) AS n,
    MIN(CUENTA_CONTABLE) AS cuenta_sample
FROM REPORTES.VISTA_BS_PREPARADO
WHERE
    -- Anomaly: PATRIMONIO partidas not in PATRIMONIO section
    (PARTIDA_BS IN ('Capital Emitido','Aportes','Excedente de revaluación','Reservas','Resultados Acumulados')
      AND SECCION_BS <> 'PATRIMONIO')
    -- Anomaly: PASIVO partidas in non-PASIVO section
    OR (PARTIDA_BS IN ('Cuentas por pagar comerciales','Otras cuentas por Pagar Relacionadas','Otras cuentas por pagar',
                       'Provisiones por beneficios a empleados','Obligaciones Financieras',
                       'Impuesto a la renta diferido','Participaciones de los trabajadores diferidas','Intereses diferidos')
        AND SECCION_BS <> 'PASIVO')
    -- Anomaly: ACTIVO native partidas in non-ACTIVO section, except known overrides
    OR (SECCION_BS = 'PASIVO' AND first_char = '1' AND PARTIDA_BS <> 'Tributos por Pagar')
GROUP BY PARTIDA_BS, SECCION_BS, LEFT(CUENTA_CONTABLE, 1)
ORDER BY n DESC;


-- -----------------------------------------------------------------------------
-- 4. SALDO sign sanity
-- -----------------------------------------------------------------------------
-- For the P&L view we'd EXPECT ingreso PARTIDA_PLs (INGRESOS *, RESULTADO
-- FINANCIERO net, etc.) to mostly have positive SUM(SALDO) and costo/gasto
-- partidas to mostly have negative SUM(SALDO).  Run it as a per-CIA snapshot
-- so the user can eyeball it against a known month.

SELECT
    CIA,
    YEAR(FECHA) AS YR,
    PARTIDA_PL,
    COUNT(*) AS n_rows,
    CAST(SUM(SALDO) AS DECIMAL(20, 2)) AS total_saldo
FROM REPORTES.VISTA_PNL_PREPARADO
WHERE FECHA >= '2026-01-01' AND FECHA < '2026-05-01'   -- adjust to a known month
GROUP BY CIA, YEAR(FECHA), PARTIDA_PL
ORDER BY CIA, PARTIDA_PL;


-- -----------------------------------------------------------------------------
-- 5. Row-count parity with the existing query path
-- -----------------------------------------------------------------------------
-- Compare a typical (company, date range) fetch against what queries.py would
-- pull (modulo the post-fetch Python filter). Numbers should match exactly.

DECLARE @cia varchar(9)   = 'FIBERLINE';
DECLARE @start date       = '2026-01-01';
DECLARE @end   date       = '2026-05-01';

-- Source path (mirrors fetch_pnl_data + filter_for_statements):
SELECT 'source_python_equiv' AS path, COUNT(*) AS n
FROM REPORTES.VISTA_ANALISIS_CECOS s
WHERE s.CIA = @cia
  AND s.FECHA >= @start AND s.FECHA < @end
  AND (s.CUENTA_CONTABLE LIKE '6%' OR s.CUENTA_CONTABLE LIKE '7%' OR s.CUENTA_CONTABLE LIKE '8%')
  AND s.FUENTE NOT LIKE 'CIERRE%'
  AND TRY_CAST(LEFT(REPLACE(s.CUENTA_CONTABLE, '.', ''), 3) AS INT) >= 619
  AND s.CUENTA_CONTABLE <> '79.1.1.1.01'

UNION ALL

-- View path:
SELECT 'view', COUNT(*) FROM REPORTES.VISTA_PNL_PREPARADO
WHERE CIA = @cia AND FECHA >= @start AND FECHA < @end;


-- -----------------------------------------------------------------------------
-- 6. Per-PARTIDA SUM(SALDO) parity — primary regression query
-- -----------------------------------------------------------------------------
-- This is the gold-standard check: the same totals you'd get from Python.
-- Once both columns match for every CIA/MES/PARTIDA_PL row, the view is good
-- to wire up.

SELECT
    CIA,
    MES,
    PARTIDA_PL,
    CAST(SUM(SALDO) AS DECIMAL(20, 2)) AS total_saldo
FROM REPORTES.VISTA_PNL_PREPARADO
WHERE FECHA >= '2026-01-01' AND FECHA < '2027-01-01'
GROUP BY CIA, MES, PARTIDA_PL
ORDER BY CIA, MES, PARTIDA_PL;
