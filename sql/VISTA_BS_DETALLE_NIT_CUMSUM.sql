-- =============================================================================
-- VISTA_BS_DETALLE_NIT_CUMSUM  —  Phase F: BS NIT-grain cumsum, top-50 per partida
-- =============================================================================
-- Feeds the BS note "top-20 by NIT" ranking tables (bs_cxc_*/bs_cxp_* _nit_top20)
-- so bs_top20_by_nit() stops scanning the cached row-level df_bs.
--
-- WHY TOP-50 IN SQL (2026-05-29 rewrite): the first cut of this view densified
-- every (partida, NIT) × 12 months and returned ALL of them, expecting Python to
-- rank + take top-20.  For FIBERLINE 'Cuentas por cobrar comerciales' that is
-- 51,593 distinct NITs → 619K rows for a table that shows 20 — a 42s query, and
-- 18 such queries per BS load.  That is slower than the row-level path it
-- replaces and defeats Phase F's purpose.  This view now ranks NITs server-side
-- by their last-activity-month cumulative balance and returns only the top 50
-- per (CIA, YEAR, PARTIDA_BS).  Python keeps the final top-20 cut (so the cut
-- logic stays byte-identical to today) — the extra 30-row margin means any
-- tie-at-the-boundary ambiguity falls well outside the displayed 20.
--
-- Ranking: by SALDO_CUMSUM at the LAST month with posted BS activity for the
-- (CIA, YEAR), descending, NIT ascending as a deterministic tiebreak.  The
-- last-activity month is MAX(MES) over the source rows (VISTA_BS_PREPARADO),
-- computed inline so the view is self-contained — matching the Python
-- last_data_month(df_bs) the old builder used.  All 12 densified months are
-- returned for each surviving NIT so Python can pivot + zero future months.
--
-- Grain: (CIA, YEAR, MES, PARTIDA_BS, NIT, RAZON_SOCIAL).  PARTIDA_BS is in the
-- grain because the note builder filters by a PARTIDA_BS list and a single NIT
-- can appear under more than one partida; the running balance is per (partida,
-- NIT), matching the Python path which filters to the partida list before
-- pivoting by NIT.  SECCION_BS is intentionally not carried.
--
-- Topology mirrors VISTA_BS_PREPARADO_CUMSUM — 4 per-CIA + REPORTES umbrella.
-- Calendar densification (months / nit_years / monthly / dense) so gap months
-- carry the prior cumulative balance forward.  NIT / RAZON_SOCIAL NULLs are NOT
-- coalesced here — Python fills 'SIN NIT' / 'SIN RAZON SOCIAL'; NULLs group
-- together in GROUP BY so the densified partition is stable.
--
-- Output columns:
--   CIA              VARCHAR
--   YEAR             INT
--   MES              INT             — 1..12 (densified)
--   PARTIDA_BS       VARCHAR(60)
--   NIT              VARCHAR         — may be NULL (filled in Python)
--   RAZON_SOCIAL     VARCHAR         — may be NULL (filled in Python)
--   SALDO_MENSUAL    DECIMAL(28,8)
--   SALDO_CUMSUM     DECIMAL(28,8)   — running total Jan 1 through end of MES
--
-- Row count: ≤ 50 NITs × 12 months per (CIA, YEAR, PARTIDA_BS) — bounded and small.
-- The top-N is the literal 50 in each view's "WHERE r.RN <= 50" below.
-- =============================================================================


CREATE OR ALTER VIEW [FIBERLINE].[VISTA_BS_DETALLE_NIT_CUMSUM] AS
WITH
months(MES) AS (
    SELECT 1  UNION ALL SELECT 2  UNION ALL SELECT 3  UNION ALL SELECT 4
    UNION ALL SELECT 5  UNION ALL SELECT 6  UNION ALL SELECT 7  UNION ALL SELECT 8
    UNION ALL SELECT 9  UNION ALL SELECT 10 UNION ALL SELECT 11 UNION ALL SELECT 12
),
last_month AS (
    SELECT CIA, YEAR(FECHA) AS YEAR, MAX(MES) AS LAST_MES
    FROM [FIBERLINE].[VISTA_BS_PREPARADO]
    GROUP BY CIA, YEAR(FECHA)
),
nit_years AS (
    SELECT CIA, YEAR(FECHA) AS YEAR, PARTIDA_BS, NIT, MAX(RAZON_SOCIAL) AS RAZON_SOCIAL
    FROM [FIBERLINE].[VISTA_BS_PREPARADO]
    GROUP BY CIA, YEAR(FECHA), PARTIDA_BS, NIT
),
monthly AS (
    SELECT CIA, YEAR(FECHA) AS YEAR, MES, PARTIDA_BS, NIT,
           CAST(SUM(SALDO) AS DECIMAL(28, 8)) AS SALDO_MENSUAL
    FROM [FIBERLINE].[VISTA_BS_PREPARADO]
    GROUP BY CIA, YEAR(FECHA), MES, PARTIDA_BS, NIT
),
dense AS (
    SELECT ny.CIA, ny.YEAR, m.MES, ny.PARTIDA_BS, ny.NIT, ny.RAZON_SOCIAL,
           COALESCE(mo.SALDO_MENSUAL, 0) AS SALDO_MENSUAL
    FROM nit_years ny
    CROSS JOIN months m
    LEFT JOIN monthly mo
      ON  mo.CIA = ny.CIA AND mo.YEAR = ny.YEAR AND mo.PARTIDA_BS = ny.PARTIDA_BS
      AND mo.MES = m.MES AND (mo.NIT = ny.NIT OR (mo.NIT IS NULL AND ny.NIT IS NULL))
),
cumsum AS (
    SELECT d.CIA, d.YEAR, d.MES, d.PARTIDA_BS, d.NIT, d.RAZON_SOCIAL,
           CAST(d.SALDO_MENSUAL AS DECIMAL(28, 8)) AS SALDO_MENSUAL,
           CAST(SUM(d.SALDO_MENSUAL) OVER (
                    PARTITION BY d.CIA, d.YEAR, d.PARTIDA_BS, d.NIT
                    ORDER BY d.MES ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                ) AS DECIMAL(28, 8)) AS SALDO_CUMSUM
    FROM dense d
),
ranked AS (
    -- Rank NITs within each (partida) by their cumulative balance AT the
    -- last-activity month, descending; NIT ascending breaks ties deterministically.
    SELECT c.CIA, c.YEAR, c.PARTIDA_BS, c.NIT,
           ROW_NUMBER() OVER (
               PARTITION BY c.CIA, c.YEAR, c.PARTIDA_BS
               ORDER BY c.SALDO_CUMSUM DESC, c.NIT ASC
           ) AS RN
    FROM cumsum c
    JOIN last_month lm ON lm.CIA = c.CIA AND lm.YEAR = c.YEAR
    WHERE c.MES = lm.LAST_MES
)
SELECT c.CIA, c.YEAR, c.MES, c.PARTIDA_BS, c.NIT, c.RAZON_SOCIAL,
       c.SALDO_MENSUAL, c.SALDO_CUMSUM
FROM cumsum c
JOIN ranked r
  ON  r.CIA = c.CIA AND r.YEAR = c.YEAR AND r.PARTIDA_BS = c.PARTIDA_BS
  AND (r.NIT = c.NIT OR (r.NIT IS NULL AND c.NIT IS NULL))
WHERE r.RN <= 50;
GO


CREATE OR ALTER VIEW [FIBERTECH].[VISTA_BS_DETALLE_NIT_CUMSUM] AS
WITH
months(MES) AS (
    SELECT 1  UNION ALL SELECT 2  UNION ALL SELECT 3  UNION ALL SELECT 4
    UNION ALL SELECT 5  UNION ALL SELECT 6  UNION ALL SELECT 7  UNION ALL SELECT 8
    UNION ALL SELECT 9  UNION ALL SELECT 10 UNION ALL SELECT 11 UNION ALL SELECT 12
),
last_month AS (
    SELECT CIA, YEAR(FECHA) AS YEAR, MAX(MES) AS LAST_MES
    FROM [FIBERTECH].[VISTA_BS_PREPARADO]
    GROUP BY CIA, YEAR(FECHA)
),
nit_years AS (
    SELECT CIA, YEAR(FECHA) AS YEAR, PARTIDA_BS, NIT, MAX(RAZON_SOCIAL) AS RAZON_SOCIAL
    FROM [FIBERTECH].[VISTA_BS_PREPARADO]
    GROUP BY CIA, YEAR(FECHA), PARTIDA_BS, NIT
),
monthly AS (
    SELECT CIA, YEAR(FECHA) AS YEAR, MES, PARTIDA_BS, NIT,
           CAST(SUM(SALDO) AS DECIMAL(28, 8)) AS SALDO_MENSUAL
    FROM [FIBERTECH].[VISTA_BS_PREPARADO]
    GROUP BY CIA, YEAR(FECHA), MES, PARTIDA_BS, NIT
),
dense AS (
    SELECT ny.CIA, ny.YEAR, m.MES, ny.PARTIDA_BS, ny.NIT, ny.RAZON_SOCIAL,
           COALESCE(mo.SALDO_MENSUAL, 0) AS SALDO_MENSUAL
    FROM nit_years ny
    CROSS JOIN months m
    LEFT JOIN monthly mo
      ON  mo.CIA = ny.CIA AND mo.YEAR = ny.YEAR AND mo.PARTIDA_BS = ny.PARTIDA_BS
      AND mo.MES = m.MES AND (mo.NIT = ny.NIT OR (mo.NIT IS NULL AND ny.NIT IS NULL))
),
cumsum AS (
    SELECT d.CIA, d.YEAR, d.MES, d.PARTIDA_BS, d.NIT, d.RAZON_SOCIAL,
           CAST(d.SALDO_MENSUAL AS DECIMAL(28, 8)) AS SALDO_MENSUAL,
           CAST(SUM(d.SALDO_MENSUAL) OVER (
                    PARTITION BY d.CIA, d.YEAR, d.PARTIDA_BS, d.NIT
                    ORDER BY d.MES ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                ) AS DECIMAL(28, 8)) AS SALDO_CUMSUM
    FROM dense d
),
ranked AS (
    SELECT c.CIA, c.YEAR, c.PARTIDA_BS, c.NIT,
           ROW_NUMBER() OVER (
               PARTITION BY c.CIA, c.YEAR, c.PARTIDA_BS
               ORDER BY c.SALDO_CUMSUM DESC, c.NIT ASC
           ) AS RN
    FROM cumsum c
    JOIN last_month lm ON lm.CIA = c.CIA AND lm.YEAR = c.YEAR
    WHERE c.MES = lm.LAST_MES
)
SELECT c.CIA, c.YEAR, c.MES, c.PARTIDA_BS, c.NIT, c.RAZON_SOCIAL,
       c.SALDO_MENSUAL, c.SALDO_CUMSUM
FROM cumsum c
JOIN ranked r
  ON  r.CIA = c.CIA AND r.YEAR = c.YEAR AND r.PARTIDA_BS = c.PARTIDA_BS
  AND (r.NIT = c.NIT OR (r.NIT IS NULL AND c.NIT IS NULL))
WHERE r.RN <= 50;
GO


CREATE OR ALTER VIEW [NEXTNET].[VISTA_BS_DETALLE_NIT_CUMSUM] AS
WITH
months(MES) AS (
    SELECT 1  UNION ALL SELECT 2  UNION ALL SELECT 3  UNION ALL SELECT 4
    UNION ALL SELECT 5  UNION ALL SELECT 6  UNION ALL SELECT 7  UNION ALL SELECT 8
    UNION ALL SELECT 9  UNION ALL SELECT 10 UNION ALL SELECT 11 UNION ALL SELECT 12
),
last_month AS (
    SELECT CIA, YEAR(FECHA) AS YEAR, MAX(MES) AS LAST_MES
    FROM [NEXTNET].[VISTA_BS_PREPARADO]
    GROUP BY CIA, YEAR(FECHA)
),
nit_years AS (
    SELECT CIA, YEAR(FECHA) AS YEAR, PARTIDA_BS, NIT, MAX(RAZON_SOCIAL) AS RAZON_SOCIAL
    FROM [NEXTNET].[VISTA_BS_PREPARADO]
    GROUP BY CIA, YEAR(FECHA), PARTIDA_BS, NIT
),
monthly AS (
    SELECT CIA, YEAR(FECHA) AS YEAR, MES, PARTIDA_BS, NIT,
           CAST(SUM(SALDO) AS DECIMAL(28, 8)) AS SALDO_MENSUAL
    FROM [NEXTNET].[VISTA_BS_PREPARADO]
    GROUP BY CIA, YEAR(FECHA), MES, PARTIDA_BS, NIT
),
dense AS (
    SELECT ny.CIA, ny.YEAR, m.MES, ny.PARTIDA_BS, ny.NIT, ny.RAZON_SOCIAL,
           COALESCE(mo.SALDO_MENSUAL, 0) AS SALDO_MENSUAL
    FROM nit_years ny
    CROSS JOIN months m
    LEFT JOIN monthly mo
      ON  mo.CIA = ny.CIA AND mo.YEAR = ny.YEAR AND mo.PARTIDA_BS = ny.PARTIDA_BS
      AND mo.MES = m.MES AND (mo.NIT = ny.NIT OR (mo.NIT IS NULL AND ny.NIT IS NULL))
),
cumsum AS (
    SELECT d.CIA, d.YEAR, d.MES, d.PARTIDA_BS, d.NIT, d.RAZON_SOCIAL,
           CAST(d.SALDO_MENSUAL AS DECIMAL(28, 8)) AS SALDO_MENSUAL,
           CAST(SUM(d.SALDO_MENSUAL) OVER (
                    PARTITION BY d.CIA, d.YEAR, d.PARTIDA_BS, d.NIT
                    ORDER BY d.MES ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                ) AS DECIMAL(28, 8)) AS SALDO_CUMSUM
    FROM dense d
),
ranked AS (
    SELECT c.CIA, c.YEAR, c.PARTIDA_BS, c.NIT,
           ROW_NUMBER() OVER (
               PARTITION BY c.CIA, c.YEAR, c.PARTIDA_BS
               ORDER BY c.SALDO_CUMSUM DESC, c.NIT ASC
           ) AS RN
    FROM cumsum c
    JOIN last_month lm ON lm.CIA = c.CIA AND lm.YEAR = c.YEAR
    WHERE c.MES = lm.LAST_MES
)
SELECT c.CIA, c.YEAR, c.MES, c.PARTIDA_BS, c.NIT, c.RAZON_SOCIAL,
       c.SALDO_MENSUAL, c.SALDO_CUMSUM
FROM cumsum c
JOIN ranked r
  ON  r.CIA = c.CIA AND r.YEAR = c.YEAR AND r.PARTIDA_BS = c.PARTIDA_BS
  AND (r.NIT = c.NIT OR (r.NIT IS NULL AND c.NIT IS NULL))
WHERE r.RN <= 50;
GO


CREATE OR ALTER VIEW [FIBERLUX].[VISTA_BS_DETALLE_NIT_CUMSUM] AS
WITH
months(MES) AS (
    SELECT 1  UNION ALL SELECT 2  UNION ALL SELECT 3  UNION ALL SELECT 4
    UNION ALL SELECT 5  UNION ALL SELECT 6  UNION ALL SELECT 7  UNION ALL SELECT 8
    UNION ALL SELECT 9  UNION ALL SELECT 10 UNION ALL SELECT 11 UNION ALL SELECT 12
),
last_month AS (
    SELECT CIA, YEAR(FECHA) AS YEAR, MAX(MES) AS LAST_MES
    FROM [FIBERLUX].[VISTA_BS_PREPARADO]
    GROUP BY CIA, YEAR(FECHA)
),
nit_years AS (
    SELECT CIA, YEAR(FECHA) AS YEAR, PARTIDA_BS, NIT, MAX(RAZON_SOCIAL) AS RAZON_SOCIAL
    FROM [FIBERLUX].[VISTA_BS_PREPARADO]
    GROUP BY CIA, YEAR(FECHA), PARTIDA_BS, NIT
),
monthly AS (
    SELECT CIA, YEAR(FECHA) AS YEAR, MES, PARTIDA_BS, NIT,
           CAST(SUM(SALDO) AS DECIMAL(28, 8)) AS SALDO_MENSUAL
    FROM [FIBERLUX].[VISTA_BS_PREPARADO]
    GROUP BY CIA, YEAR(FECHA), MES, PARTIDA_BS, NIT
),
dense AS (
    SELECT ny.CIA, ny.YEAR, m.MES, ny.PARTIDA_BS, ny.NIT, ny.RAZON_SOCIAL,
           COALESCE(mo.SALDO_MENSUAL, 0) AS SALDO_MENSUAL
    FROM nit_years ny
    CROSS JOIN months m
    LEFT JOIN monthly mo
      ON  mo.CIA = ny.CIA AND mo.YEAR = ny.YEAR AND mo.PARTIDA_BS = ny.PARTIDA_BS
      AND mo.MES = m.MES AND (mo.NIT = ny.NIT OR (mo.NIT IS NULL AND ny.NIT IS NULL))
),
cumsum AS (
    SELECT d.CIA, d.YEAR, d.MES, d.PARTIDA_BS, d.NIT, d.RAZON_SOCIAL,
           CAST(d.SALDO_MENSUAL AS DECIMAL(28, 8)) AS SALDO_MENSUAL,
           CAST(SUM(d.SALDO_MENSUAL) OVER (
                    PARTITION BY d.CIA, d.YEAR, d.PARTIDA_BS, d.NIT
                    ORDER BY d.MES ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                ) AS DECIMAL(28, 8)) AS SALDO_CUMSUM
    FROM dense d
),
ranked AS (
    SELECT c.CIA, c.YEAR, c.PARTIDA_BS, c.NIT,
           ROW_NUMBER() OVER (
               PARTITION BY c.CIA, c.YEAR, c.PARTIDA_BS
               ORDER BY c.SALDO_CUMSUM DESC, c.NIT ASC
           ) AS RN
    FROM cumsum c
    JOIN last_month lm ON lm.CIA = c.CIA AND lm.YEAR = c.YEAR
    WHERE c.MES = lm.LAST_MES
)
SELECT c.CIA, c.YEAR, c.MES, c.PARTIDA_BS, c.NIT, c.RAZON_SOCIAL,
       c.SALDO_MENSUAL, c.SALDO_CUMSUM
FROM cumsum c
JOIN ranked r
  ON  r.CIA = c.CIA AND r.YEAR = c.YEAR AND r.PARTIDA_BS = c.PARTIDA_BS
  AND (r.NIT = c.NIT OR (r.NIT IS NULL AND c.NIT IS NULL))
WHERE r.RN <= 50;
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
-- Returns ≤ 50 NITs × 12 months per partida.  Python fills SIN NIT / SIN RAZON
-- SOCIAL, pivots MES → columns, zeroes future months past the last data month,
-- ranks by the last data month's cumulative value, takes the final top 20, and
-- appends the TOTAL row.  (SQL pre-ranks to 50; the 30-row margin keeps any
-- tie-at-the-boundary outside the displayed 20.)
--
-- Parity note: the view ranks by SALDO_CUMSUM at MAX(MES)-with-data descending,
-- NIT ascending.  Python then re-sorts the ≤50 rows the same way and cuts to 20,
-- so the displayed set + order match the pre-Phase-F df_bs path to the centavo.
-- =============================================================================
