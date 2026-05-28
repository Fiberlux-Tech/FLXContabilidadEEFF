-- =============================================================================
-- VISTA_BS_DETALLE_NIT_CUMSUM  —  Phase F: BS NIT-grain with monthly cumsum
-- =============================================================================
-- NIT-grain sibling of VISTA_BS_PREPARADO_CUMSUM (Phase E).  Feeds the BS note
-- "top-20 by NIT" ranking tables (bs_cxc_*/bs_cxp_* _nit_top20) so the
-- bs_top20_by_nit() builder stops scanning the cached row-level df_bs.
--
-- Replaces in Python: the cumsum + densify portion of bs_top20_by_nit
-- (`_apply_bs_cumsum` over an NIT pivot, aggregation.py).  The TOP-20 ranking,
-- the SIN NIT / SIN RAZON SOCIAL null-fill, the future-month zeroing, and the
-- TOTAL row STAY in Python — they are presentation/ranking, not aggregation.
--
-- Grain: (CIA, YEAR, MES, PARTIDA_BS, NIT, RAZON_SOCIAL).  PARTIDA_BS is in the
-- grain because the note builder filters by a PARTIDA_BS list and a single NIT
-- can appear under more than one partida; keeping it in the partition makes the
-- running balance per (NIT, partida) — matching the Python path, which filters
-- to the partida list BEFORE pivoting by NIT.
--
-- SECCION_BS is intentionally NOT carried: the NIT ranking tables never use it
-- (they display NIT + RAZON_SOCIAL + month columns), and excluding it keeps the
-- grain from splitting a NIT across sections.
--
-- Topology mirrors VISTA_BS_PREPARADO_CUMSUM — 4 per-CIA + REPORTES umbrella —
-- and uses the same calendar-densification CTE chain (months / nit_years /
-- monthly / dense) so gap months carry the prior cumulative balance forward.
--
-- Null handling: NIT / RAZON_SOCIAL can be NULL in the source.  They are NOT
-- coalesced here — the Python builder fills 'SIN NIT' / 'SIN RAZON SOCIAL'
-- (aggregation.bs_top20_by_nit) so the fill stays in one place.  NULLs group
-- together naturally in SQL GROUP BY, so the densified partition is stable.
--
-- Output columns:
--   CIA              VARCHAR
--   YEAR             INT             — YEAR(FECHA)
--   MES              INT             — 1..12 (densified: every (partida, NIT) has all 12)
--   PARTIDA_BS       VARCHAR(60)     — inherited
--   NIT              VARCHAR         — may be NULL (filled in Python)
--   RAZON_SOCIAL     VARCHAR         — may be NULL (filled in Python)
--   SALDO_MENSUAL    DECIMAL(28,8)   — SUM(SALDO) for that (cia, year, mes, partida, nit)
--   SALDO_CUMSUM     DECIMAL(28,8)   — running total Jan 1 through end of MES
--
-- Row count: bounded by (distinct partida×NIT pairs) × 12.  The note builder
-- only queries 4 partidas (cxc comerciales/otras, cxp comerciales/otras), so
-- the per-(CIA,YEAR) fetch with a PARTIDA_BS IN (...) filter is small.
-- =============================================================================


CREATE OR ALTER VIEW [FIBERLINE].[VISTA_BS_DETALLE_NIT_CUMSUM] AS
WITH
months(MES) AS (
    SELECT 1  UNION ALL SELECT 2  UNION ALL SELECT 3  UNION ALL SELECT 4
    UNION ALL SELECT 5  UNION ALL SELECT 6  UNION ALL SELECT 7  UNION ALL SELECT 8
    UNION ALL SELECT 9  UNION ALL SELECT 10 UNION ALL SELECT 11 UNION ALL SELECT 12
),
nit_years AS (
    SELECT
        CIA,
        YEAR(FECHA) AS YEAR,
        PARTIDA_BS,
        NIT,
        MAX(RAZON_SOCIAL) AS RAZON_SOCIAL
    FROM [FIBERLINE].[VISTA_BS_PREPARADO]
    GROUP BY CIA, YEAR(FECHA), PARTIDA_BS, NIT
),
monthly AS (
    SELECT
        CIA,
        YEAR(FECHA) AS YEAR,
        MES,
        PARTIDA_BS,
        NIT,
        CAST(SUM(SALDO) AS DECIMAL(28, 8)) AS SALDO_MENSUAL
    FROM [FIBERLINE].[VISTA_BS_PREPARADO]
    GROUP BY CIA, YEAR(FECHA), MES, PARTIDA_BS, NIT
),
dense AS (
    SELECT
        ny.CIA, ny.YEAR, m.MES,
        ny.PARTIDA_BS, ny.NIT, ny.RAZON_SOCIAL,
        COALESCE(mo.SALDO_MENSUAL, 0) AS SALDO_MENSUAL
    FROM nit_years ny
    CROSS JOIN months m
    LEFT JOIN monthly mo
      ON  mo.CIA        = ny.CIA
      AND mo.YEAR       = ny.YEAR
      AND mo.PARTIDA_BS = ny.PARTIDA_BS
      AND mo.MES        = m.MES
      AND (mo.NIT = ny.NIT OR (mo.NIT IS NULL AND ny.NIT IS NULL))
)
SELECT
    CIA, YEAR, MES,
    PARTIDA_BS, NIT, RAZON_SOCIAL,
    CAST(SALDO_MENSUAL AS DECIMAL(28, 8)) AS SALDO_MENSUAL,
    CAST(
        SUM(SALDO_MENSUAL) OVER (
            PARTITION BY CIA, YEAR, PARTIDA_BS, NIT
            ORDER BY MES
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        )
    AS DECIMAL(28, 8)) AS SALDO_CUMSUM
FROM dense;
GO


CREATE OR ALTER VIEW [FIBERTECH].[VISTA_BS_DETALLE_NIT_CUMSUM] AS
WITH
months(MES) AS (
    SELECT 1  UNION ALL SELECT 2  UNION ALL SELECT 3  UNION ALL SELECT 4
    UNION ALL SELECT 5  UNION ALL SELECT 6  UNION ALL SELECT 7  UNION ALL SELECT 8
    UNION ALL SELECT 9  UNION ALL SELECT 10 UNION ALL SELECT 11 UNION ALL SELECT 12
),
nit_years AS (
    SELECT
        CIA,
        YEAR(FECHA) AS YEAR,
        PARTIDA_BS,
        NIT,
        MAX(RAZON_SOCIAL) AS RAZON_SOCIAL
    FROM [FIBERTECH].[VISTA_BS_PREPARADO]
    GROUP BY CIA, YEAR(FECHA), PARTIDA_BS, NIT
),
monthly AS (
    SELECT
        CIA,
        YEAR(FECHA) AS YEAR,
        MES,
        PARTIDA_BS,
        NIT,
        CAST(SUM(SALDO) AS DECIMAL(28, 8)) AS SALDO_MENSUAL
    FROM [FIBERTECH].[VISTA_BS_PREPARADO]
    GROUP BY CIA, YEAR(FECHA), MES, PARTIDA_BS, NIT
),
dense AS (
    SELECT
        ny.CIA, ny.YEAR, m.MES,
        ny.PARTIDA_BS, ny.NIT, ny.RAZON_SOCIAL,
        COALESCE(mo.SALDO_MENSUAL, 0) AS SALDO_MENSUAL
    FROM nit_years ny
    CROSS JOIN months m
    LEFT JOIN monthly mo
      ON  mo.CIA        = ny.CIA
      AND mo.YEAR       = ny.YEAR
      AND mo.PARTIDA_BS = ny.PARTIDA_BS
      AND mo.MES        = m.MES
      AND (mo.NIT = ny.NIT OR (mo.NIT IS NULL AND ny.NIT IS NULL))
)
SELECT
    CIA, YEAR, MES,
    PARTIDA_BS, NIT, RAZON_SOCIAL,
    CAST(SALDO_MENSUAL AS DECIMAL(28, 8)) AS SALDO_MENSUAL,
    CAST(
        SUM(SALDO_MENSUAL) OVER (
            PARTITION BY CIA, YEAR, PARTIDA_BS, NIT
            ORDER BY MES
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        )
    AS DECIMAL(28, 8)) AS SALDO_CUMSUM
FROM dense;
GO


CREATE OR ALTER VIEW [NEXTNET].[VISTA_BS_DETALLE_NIT_CUMSUM] AS
WITH
months(MES) AS (
    SELECT 1  UNION ALL SELECT 2  UNION ALL SELECT 3  UNION ALL SELECT 4
    UNION ALL SELECT 5  UNION ALL SELECT 6  UNION ALL SELECT 7  UNION ALL SELECT 8
    UNION ALL SELECT 9  UNION ALL SELECT 10 UNION ALL SELECT 11 UNION ALL SELECT 12
),
nit_years AS (
    SELECT
        CIA,
        YEAR(FECHA) AS YEAR,
        PARTIDA_BS,
        NIT,
        MAX(RAZON_SOCIAL) AS RAZON_SOCIAL
    FROM [NEXTNET].[VISTA_BS_PREPARADO]
    GROUP BY CIA, YEAR(FECHA), PARTIDA_BS, NIT
),
monthly AS (
    SELECT
        CIA,
        YEAR(FECHA) AS YEAR,
        MES,
        PARTIDA_BS,
        NIT,
        CAST(SUM(SALDO) AS DECIMAL(28, 8)) AS SALDO_MENSUAL
    FROM [NEXTNET].[VISTA_BS_PREPARADO]
    GROUP BY CIA, YEAR(FECHA), MES, PARTIDA_BS, NIT
),
dense AS (
    SELECT
        ny.CIA, ny.YEAR, m.MES,
        ny.PARTIDA_BS, ny.NIT, ny.RAZON_SOCIAL,
        COALESCE(mo.SALDO_MENSUAL, 0) AS SALDO_MENSUAL
    FROM nit_years ny
    CROSS JOIN months m
    LEFT JOIN monthly mo
      ON  mo.CIA        = ny.CIA
      AND mo.YEAR       = ny.YEAR
      AND mo.PARTIDA_BS = ny.PARTIDA_BS
      AND mo.MES        = m.MES
      AND (mo.NIT = ny.NIT OR (mo.NIT IS NULL AND ny.NIT IS NULL))
)
SELECT
    CIA, YEAR, MES,
    PARTIDA_BS, NIT, RAZON_SOCIAL,
    CAST(SALDO_MENSUAL AS DECIMAL(28, 8)) AS SALDO_MENSUAL,
    CAST(
        SUM(SALDO_MENSUAL) OVER (
            PARTITION BY CIA, YEAR, PARTIDA_BS, NIT
            ORDER BY MES
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        )
    AS DECIMAL(28, 8)) AS SALDO_CUMSUM
FROM dense;
GO


CREATE OR ALTER VIEW [FIBERLUX].[VISTA_BS_DETALLE_NIT_CUMSUM] AS
WITH
months(MES) AS (
    SELECT 1  UNION ALL SELECT 2  UNION ALL SELECT 3  UNION ALL SELECT 4
    UNION ALL SELECT 5  UNION ALL SELECT 6  UNION ALL SELECT 7  UNION ALL SELECT 8
    UNION ALL SELECT 9  UNION ALL SELECT 10 UNION ALL SELECT 11 UNION ALL SELECT 12
),
nit_years AS (
    SELECT
        CIA,
        YEAR(FECHA) AS YEAR,
        PARTIDA_BS,
        NIT,
        MAX(RAZON_SOCIAL) AS RAZON_SOCIAL
    FROM [FIBERLUX].[VISTA_BS_PREPARADO]
    GROUP BY CIA, YEAR(FECHA), PARTIDA_BS, NIT
),
monthly AS (
    SELECT
        CIA,
        YEAR(FECHA) AS YEAR,
        MES,
        PARTIDA_BS,
        NIT,
        CAST(SUM(SALDO) AS DECIMAL(28, 8)) AS SALDO_MENSUAL
    FROM [FIBERLUX].[VISTA_BS_PREPARADO]
    GROUP BY CIA, YEAR(FECHA), MES, PARTIDA_BS, NIT
),
dense AS (
    SELECT
        ny.CIA, ny.YEAR, m.MES,
        ny.PARTIDA_BS, ny.NIT, ny.RAZON_SOCIAL,
        COALESCE(mo.SALDO_MENSUAL, 0) AS SALDO_MENSUAL
    FROM nit_years ny
    CROSS JOIN months m
    LEFT JOIN monthly mo
      ON  mo.CIA        = ny.CIA
      AND mo.YEAR       = ny.YEAR
      AND mo.PARTIDA_BS = ny.PARTIDA_BS
      AND mo.MES        = m.MES
      AND (mo.NIT = ny.NIT OR (mo.NIT IS NULL AND ny.NIT IS NULL))
)
SELECT
    CIA, YEAR, MES,
    PARTIDA_BS, NIT, RAZON_SOCIAL,
    CAST(SALDO_MENSUAL AS DECIMAL(28, 8)) AS SALDO_MENSUAL,
    CAST(
        SUM(SALDO_MENSUAL) OVER (
            PARTITION BY CIA, YEAR, PARTIDA_BS, NIT
            ORDER BY MES
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        )
    AS DECIMAL(28, 8)) AS SALDO_CUMSUM
FROM dense;
GO


-- ─────────────────────────────────────────────────────────────────────────────
-- Umbrella view in REPORTES.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR ALTER VIEW [REPORTES].[VISTA_BS_DETALLE_NIT_CUMSUM] AS
SELECT * FROM [FIBERLINE].[VISTA_BS_DETALLE_NIT_CUMSUM]
UNION ALL
SELECT * FROM [FIBERTECH].[VISTA_BS_DETALLE_NIT_CUMSUM]
UNION ALL
SELECT * FROM [NEXTNET].[VISTA_BS_DETALLE_NIT_CUMSUM]
UNION ALL
SELECT * FROM [FIBERLUX].[VISTA_BS_DETALLE_NIT_CUMSUM];
GO


-- =============================================================================
-- Expected query pattern from data_service (Phase F BS note path):
--
--   SELECT MES, NIT, RAZON_SOCIAL, SALDO_CUMSUM
--   FROM REPORTES.VISTA_BS_DETALLE_NIT_CUMSUM
--   WHERE CIA = ? AND YEAR = ? AND PARTIDA_BS IN (?, ...);
--
-- Python pivots MES → columns, zeroes future months past the last data month,
-- ranks by the last data month's cumulative value, takes top 20, fills
-- SIN NIT / SIN RAZON SOCIAL, and appends the TOTAL row.
--
-- Post-deploy verification (mirror the Phase E cumsum checks):
--   -- every (partida, NIT) has exactly 12 densified months:
--   SELECT CIA, YEAR, PARTIDA_BS, NIT, COUNT(*) AS n
--   FROM REPORTES.VISTA_BS_DETALLE_NIT_CUMSUM
--   WHERE CIA = 'FIBERLINE' AND YEAR = 2025
--   GROUP BY CIA, YEAR, PARTIDA_BS, NIT
--   HAVING COUNT(*) <> 12;          -- expect zero rows
--
--   -- per partida, the SUM of NIT cumsum at a given MES must equal the
--   -- cuenta-grain cumsum SUM for the same partida/MES (both roll up to the
--   -- same partida total), to within rounding:
--   -- (run as an ad hoc JOIN against VISTA_BS_PREPARADO_CUMSUM when validating.)
-- =============================================================================
