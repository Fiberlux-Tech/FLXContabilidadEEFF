-- =============================================================================
-- REPORTES.VISTA_CLASIFICACION_GAPS
-- =============================================================================
-- Surfaces every row that neither pipeline could classify:
--   * P&L rows landing in PARTIDA_PL = 'POR CLASIFICAR'
--   * BS  rows landing in PARTIDA_BS LIKE 'POR DEFINIR%'
--
-- Purpose: give accounting a single place to look when they want to know
-- which accounts the reporting rules don't cover yet.  These rows are not
-- hidden by the dashboard — they appear under the "POR CLASIFICAR" /
-- "POR DEFINIR …" labels — but they're easy to miss because they often
-- carry near-zero SALDO (variance entries, rounding adjustments, etc.).
--
-- Columns:
--   SOURCE             'PNL' | 'BS'
--   BUCKET             the fallback label (e.g. 'POR CLASIFICAR',
--                      'POR DEFINIR ACTIVO', 'POR DEFINIR PASIVO', …)
--   CIA, CUENTA_CONTABLE, DESCRIPCION,
--   CENTRO_COSTO, DESC_CECO,
--   FECHA, MES, SALDO, ASIENTO, FUENTE
--
-- Filter recipe for callers (Excel / SSMS / dashboard):
--   SELECT * FROM REPORTES.VISTA_CLASIFICACION_GAPS
--   WHERE CIA = 'FIBERLINE' AND YEAR(FECHA) = 2026;
--
-- Pre-aggregated rollup query (paste into your reporting tool):
--   SELECT SOURCE, BUCKET, CIA, CUENTA_CONTABLE, DESCRIPCION,
--          COUNT(*) AS rows, SUM(SALDO) AS total_saldo,
--          MIN(FECHA) AS first_seen, MAX(FECHA) AS last_seen
--   FROM REPORTES.VISTA_CLASIFICACION_GAPS
--   GROUP BY SOURCE, BUCKET, CIA, CUENTA_CONTABLE, DESCRIPCION
--   ORDER BY rows DESC;
--
-- Deployment notes:
--   * Block 1 (P&L half) is safe to deploy NOW — VISTA_PNL_PREPARADO exists.
--   * Block 2 (BS half) requires REPORTES.VISTA_BS_PREPARADO. If you run
--     block 2 before BS_PREPARADO is deployed, SQL Server will reject it
--     with "Invalid object name".
--   * Block 3 (the umbrella) needs both halves. Run it last.
--   * Run all three in order once BS_PREPARADO is in place. CREATE OR ALTER
--     is idempotent.
-- =============================================================================


-- ─────────────────────────────────────────────────────────────────────────────
-- Block 1 — P&L gaps. Deployable today.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR ALTER VIEW [REPORTES].[VISTA_PNL_CLASIFICACION_GAPS] AS
SELECT
    CAST('PNL' AS VARCHAR(3))            AS SOURCE,
    CAST(PARTIDA_PL AS VARCHAR(40))      AS BUCKET,
    CIA,
    CUENTA_CONTABLE,
    DESCRIPCION,
    CENTRO_COSTO,
    DESC_CECO,
    FECHA,
    MES,
    SALDO,
    ASIENTO,
    FUENTE
FROM [REPORTES].[VISTA_PNL_PREPARADO]
WHERE PARTIDA_PL = 'POR CLASIFICAR';
GO


-- ─────────────────────────────────────────────────────────────────────────────
-- Block 2 — BS gaps. Requires REPORTES.VISTA_BS_PREPARADO.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR ALTER VIEW [REPORTES].[VISTA_BS_CLASIFICACION_GAPS] AS
SELECT
    CAST('BS' AS VARCHAR(3))             AS SOURCE,
    CAST(PARTIDA_BS AS VARCHAR(40))      AS BUCKET,
    CIA,
    CUENTA_CONTABLE,
    DESCRIPCION,
    CENTRO_COSTO,
    DESC_CECO,
    FECHA,
    MES,
    SALDO,
    ASIENTO,
    FUENTE
FROM [REPORTES].[VISTA_BS_PREPARADO]
WHERE PARTIDA_BS LIKE 'POR DEFINIR%';
GO


-- ─────────────────────────────────────────────────────────────────────────────
-- Block 3 — Unified umbrella. Run after both halves exist.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR ALTER VIEW [REPORTES].[VISTA_CLASIFICACION_GAPS] AS
SELECT * FROM [REPORTES].[VISTA_PNL_CLASIFICACION_GAPS]
UNION ALL
SELECT * FROM [REPORTES].[VISTA_BS_CLASIFICACION_GAPS];
GO
