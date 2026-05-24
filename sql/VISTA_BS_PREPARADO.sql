-- =============================================================================
-- VISTA_BS_PREPARADO  —  per-company views + REPORTES umbrella
-- =============================================================================
-- Topology mirrors VISTA_ANALISIS_CECOS / VISTA_PNL_PREPARADO:
--
--     REPORTES.VISTA_BS_PREPARADO   = UNION ALL of the four per-CIA views
--     [FIBERLINE].VISTA_BS_PREPARADO   selects from [FIBERLINE].VISTA_ANALISIS_CECOS
--     etc.
--
-- Replaces in Python: prepare_bs + assign_partida_bs
--   (backend/services/accounting/transforms.py:185-238)
--
-- Output columns:
--   CIA, CUENTA_CONTABLE, DESCRIPCION, NIT, RAZON_SOCIAL,
--   CENTRO_COSTO, DESC_CECO, FECHA, ASIENTO,
--   DEBITO_LOCAL, CREDITO_LOCAL, FUENTE, CONTABILIDAD,
--   SALDO        DECIMAL(28,8)   -- DEBITO-CREDITO for classes 1/2/3, else CREDITO-DEBITO
--   MES          INT             -- MONTH(FECHA)
--   PARTIDA_BS   VARCHAR(60)     -- override→2-char dict→POR DEFINIR fallback
--   SECCION_BS   VARCHAR(12)     -- ACTIVO / PASIVO / PATRIMONIO
--
-- Filters baked in:
--   * Class 1-5 accounts only        (BS_ACCOUNT_PREFIXES)
--   * Exclude FUENTE LIKE 'CIERRE%'  (year-end closing entries)
--
-- Out of scope (Phase B):
--   * Cumulative sum across months (statements.py bs_summary cumsum)
--   * Reclassification when end-of-period balance is negative
--   * UTILIDAD NETA injection from P&L
--   * CORRIENTE / NO CORRIENTE sub-section split
--
-- Override semantics (transforms.py:_SORTED_BS_OVERRIDES):
--   Longest prefix wins; CASE evaluates top-to-bottom so longest is listed first.
-- =============================================================================


-- The PARTIDA_BS / SECCION_BS CASE blocks are identical across companies, so
-- the only thing that changes per-CIA is the schema reference.  If you want
-- to edit the classification rules later, do it in all five places — and run
-- sql/PARITY_CHECKS.sql plus eyeball dashboard / Excel totals for a known
-- month.  The Python-side parity harness was removed in Phase A Step 4.


CREATE OR ALTER VIEW [FIBERLINE].[VISTA_BS_PREPARADO] AS
SELECT
    CIA,
    CUENTA_CONTABLE, DESCRIPCION, NIT, RAZON_SOCIAL,
    CENTRO_COSTO, DESC_CECO, FECHA, ASIENTO,
    DEBITO_LOCAL, CREDITO_LOCAL, FUENTE, CONTABILIDAD,

    CAST(
        CASE
            WHEN FIRST_CHAR IN ('1','2','3') THEN DEBITO_LOCAL - CREDITO_LOCAL
            ELSE CREDITO_LOCAL - DEBITO_LOCAL
        END
    AS DECIMAL(28, 8)) AS SALDO,

    MONTH(FECHA) AS MES,

    -- PARTIDA_BS (transforms.py:201-227)
    CASE
        WHEN CUENTA_CONTABLE LIKE '16.7.1.1.01%' THEN 'Tributos por Pagar'
        WHEN CUENTA_CONTABLE LIKE '16.7.2.1.01%' THEN 'Tributos por Pagar'
        WHEN CUENTA_CONTABLE LIKE '16.7%'        THEN 'Tributos por acreditar'
        WHEN CUENTA_CONTABLE LIKE '37.3%'        THEN 'Otros Activos'
        WHEN CUENTA_CONTABLE LIKE '39.6%'        THEN 'Intangible'
        WHEN CUENTA_CONTABLE LIKE '49.1%'        THEN 'Impuesto a la renta diferido'
        WHEN CUENTA_CONTABLE LIKE '49.2%'        THEN 'Participaciones de los trabajadores diferidas'
        WHEN CUENTA_CONTABLE LIKE '49.3%'        THEN 'Intereses diferidos'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '10' THEN 'Efectivo y equivalentes de efectivo'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '12' THEN 'Cuentas por cobrar comerciales (neto)'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '13' THEN 'Otras cuentas por cobrar relacionadas'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '14' THEN 'Otras cuentas por cobrar (neto)'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '16' THEN 'Otras cuentas por cobrar (neto)'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '17' THEN 'Otras cuentas por cobrar relacionadas'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '18' THEN 'Anticipos Otorgados'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '19' THEN 'Cuentas por cobrar comerciales (neto)'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '25' THEN 'Existencias'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '28' THEN 'Existencias'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '30' THEN 'Inversiones Mobiliarias'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '32' THEN 'Propiedades, planta y equipo (neto)'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '33' THEN 'Propiedades, planta y equipo (neto)'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '34' THEN 'Intangible'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '37' THEN 'Activo Diferido'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '39' THEN 'Propiedades, planta y equipo (neto)'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '40' THEN 'Tributos por Pagar'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '41' THEN 'Provisiones por beneficios a empleados'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '42' THEN 'Cuentas por pagar comerciales'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '43' THEN 'Otras cuentas por Pagar Relacionadas'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '45' THEN 'Obligaciones Financieras'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '46' THEN 'Otras cuentas por pagar'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '47' THEN 'Otras cuentas por Pagar Relacionadas'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '50' THEN 'Capital Emitido'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '52' THEN 'Aportes'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '57' THEN 'Excedente de revaluación'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '58' THEN 'Reservas'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '59' THEN 'Resultados Acumulados'
        WHEN FIRST_CHAR IN ('1','2','3') THEN 'POR DEFINIR ACTIVO'
        WHEN FIRST_CHAR = '4'            THEN 'POR DEFINIR PASIVO'
        WHEN FIRST_CHAR = '5'            THEN 'POR DEFINIR PATRIMONIO'
        ELSE NULL
    END AS PARTIDA_BS,

    -- SECCION_BS (transforms.py:229-234)
    CASE
        WHEN CUENTA_CONTABLE LIKE '16.7.1.1.01%' THEN 'PASIVO'
        WHEN CUENTA_CONTABLE LIKE '16.7.2.1.01%' THEN 'PASIVO'
        WHEN FIRST_CHAR IN ('1','2','3') THEN 'ACTIVO'
        WHEN FIRST_CHAR = '4'            THEN 'PASIVO'
        WHEN FIRST_CHAR = '5'            THEN 'PATRIMONIO'
    END AS SECCION_BS

FROM (
    SELECT
        CIA,
        RTRIM(CUENTA_CONTABLE) AS CUENTA_CONTABLE,
        RTRIM(DESCRIPCION) AS DESCRIPCION,
        RTRIM(NIT) AS NIT, RTRIM(RAZON_SOCIAL) AS RAZON_SOCIAL,
        RTRIM(CENTRO_COSTO) AS CENTRO_COSTO, RTRIM(DESC_CECO) AS DESC_CECO,
        FECHA, RTRIM(ASIENTO) AS ASIENTO,
        DEBITO_LOCAL, CREDITO_LOCAL, RTRIM(FUENTE) AS FUENTE, CONTABILIDAD,
        LEFT(CUENTA_CONTABLE, 1) AS FIRST_CHAR
    FROM [FIBERLINE].[VISTA_ANALISIS_CECOS]
    WHERE LEFT(CUENTA_CONTABLE, 1) IN ('1','2','3','4','5')
      AND FUENTE NOT LIKE 'CIERRE%'
) src;
GO


CREATE OR ALTER VIEW [FIBERTECH].[VISTA_BS_PREPARADO] AS
SELECT
    CIA, CUENTA_CONTABLE, DESCRIPCION, NIT, RAZON_SOCIAL,
    CENTRO_COSTO, DESC_CECO, FECHA, ASIENTO,
    DEBITO_LOCAL, CREDITO_LOCAL, FUENTE, CONTABILIDAD,
    CAST(
        CASE WHEN FIRST_CHAR IN ('1','2','3') THEN DEBITO_LOCAL - CREDITO_LOCAL
             ELSE CREDITO_LOCAL - DEBITO_LOCAL END
    AS DECIMAL(28, 8)) AS SALDO,
    MONTH(FECHA) AS MES,
    CASE
        WHEN CUENTA_CONTABLE LIKE '16.7.1.1.01%' THEN 'Tributos por Pagar'
        WHEN CUENTA_CONTABLE LIKE '16.7.2.1.01%' THEN 'Tributos por Pagar'
        WHEN CUENTA_CONTABLE LIKE '16.7%'        THEN 'Tributos por acreditar'
        WHEN CUENTA_CONTABLE LIKE '37.3%'        THEN 'Otros Activos'
        WHEN CUENTA_CONTABLE LIKE '39.6%'        THEN 'Intangible'
        WHEN CUENTA_CONTABLE LIKE '49.1%'        THEN 'Impuesto a la renta diferido'
        WHEN CUENTA_CONTABLE LIKE '49.2%'        THEN 'Participaciones de los trabajadores diferidas'
        WHEN CUENTA_CONTABLE LIKE '49.3%'        THEN 'Intereses diferidos'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '10' THEN 'Efectivo y equivalentes de efectivo'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '12' THEN 'Cuentas por cobrar comerciales (neto)'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '13' THEN 'Otras cuentas por cobrar relacionadas'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '14' THEN 'Otras cuentas por cobrar (neto)'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '16' THEN 'Otras cuentas por cobrar (neto)'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '17' THEN 'Otras cuentas por cobrar relacionadas'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '18' THEN 'Anticipos Otorgados'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '19' THEN 'Cuentas por cobrar comerciales (neto)'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '25' THEN 'Existencias'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '28' THEN 'Existencias'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '30' THEN 'Inversiones Mobiliarias'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '32' THEN 'Propiedades, planta y equipo (neto)'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '33' THEN 'Propiedades, planta y equipo (neto)'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '34' THEN 'Intangible'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '37' THEN 'Activo Diferido'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '39' THEN 'Propiedades, planta y equipo (neto)'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '40' THEN 'Tributos por Pagar'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '41' THEN 'Provisiones por beneficios a empleados'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '42' THEN 'Cuentas por pagar comerciales'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '43' THEN 'Otras cuentas por Pagar Relacionadas'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '45' THEN 'Obligaciones Financieras'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '46' THEN 'Otras cuentas por pagar'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '47' THEN 'Otras cuentas por Pagar Relacionadas'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '50' THEN 'Capital Emitido'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '52' THEN 'Aportes'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '57' THEN 'Excedente de revaluación'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '58' THEN 'Reservas'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '59' THEN 'Resultados Acumulados'
        WHEN FIRST_CHAR IN ('1','2','3') THEN 'POR DEFINIR ACTIVO'
        WHEN FIRST_CHAR = '4'            THEN 'POR DEFINIR PASIVO'
        WHEN FIRST_CHAR = '5'            THEN 'POR DEFINIR PATRIMONIO'
        ELSE NULL
    END AS PARTIDA_BS,
    CASE
        WHEN CUENTA_CONTABLE LIKE '16.7.1.1.01%' THEN 'PASIVO'
        WHEN CUENTA_CONTABLE LIKE '16.7.2.1.01%' THEN 'PASIVO'
        WHEN FIRST_CHAR IN ('1','2','3') THEN 'ACTIVO'
        WHEN FIRST_CHAR = '4'            THEN 'PASIVO'
        WHEN FIRST_CHAR = '5'            THEN 'PATRIMONIO'
    END AS SECCION_BS
FROM (
    SELECT
        CIA, RTRIM(CUENTA_CONTABLE) AS CUENTA_CONTABLE,
        RTRIM(DESCRIPCION) AS DESCRIPCION, RTRIM(NIT) AS NIT,
        RTRIM(RAZON_SOCIAL) AS RAZON_SOCIAL,
        RTRIM(CENTRO_COSTO) AS CENTRO_COSTO, RTRIM(DESC_CECO) AS DESC_CECO,
        FECHA, RTRIM(ASIENTO) AS ASIENTO,
        DEBITO_LOCAL, CREDITO_LOCAL, RTRIM(FUENTE) AS FUENTE, CONTABILIDAD,
        LEFT(CUENTA_CONTABLE, 1) AS FIRST_CHAR
    FROM [FIBERTECH].[VISTA_ANALISIS_CECOS]
    WHERE LEFT(CUENTA_CONTABLE, 1) IN ('1','2','3','4','5')
      AND FUENTE NOT LIKE 'CIERRE%'
) src;
GO


CREATE OR ALTER VIEW [NEXTNET].[VISTA_BS_PREPARADO] AS
SELECT
    CIA, CUENTA_CONTABLE, DESCRIPCION, NIT, RAZON_SOCIAL,
    CENTRO_COSTO, DESC_CECO, FECHA, ASIENTO,
    DEBITO_LOCAL, CREDITO_LOCAL, FUENTE, CONTABILIDAD,
    CAST(
        CASE WHEN FIRST_CHAR IN ('1','2','3') THEN DEBITO_LOCAL - CREDITO_LOCAL
             ELSE CREDITO_LOCAL - DEBITO_LOCAL END
    AS DECIMAL(28, 8)) AS SALDO,
    MONTH(FECHA) AS MES,
    CASE
        WHEN CUENTA_CONTABLE LIKE '16.7.1.1.01%' THEN 'Tributos por Pagar'
        WHEN CUENTA_CONTABLE LIKE '16.7.2.1.01%' THEN 'Tributos por Pagar'
        WHEN CUENTA_CONTABLE LIKE '16.7%'        THEN 'Tributos por acreditar'
        WHEN CUENTA_CONTABLE LIKE '37.3%'        THEN 'Otros Activos'
        WHEN CUENTA_CONTABLE LIKE '39.6%'        THEN 'Intangible'
        WHEN CUENTA_CONTABLE LIKE '49.1%'        THEN 'Impuesto a la renta diferido'
        WHEN CUENTA_CONTABLE LIKE '49.2%'        THEN 'Participaciones de los trabajadores diferidas'
        WHEN CUENTA_CONTABLE LIKE '49.3%'        THEN 'Intereses diferidos'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '10' THEN 'Efectivo y equivalentes de efectivo'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '12' THEN 'Cuentas por cobrar comerciales (neto)'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '13' THEN 'Otras cuentas por cobrar relacionadas'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '14' THEN 'Otras cuentas por cobrar (neto)'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '16' THEN 'Otras cuentas por cobrar (neto)'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '17' THEN 'Otras cuentas por cobrar relacionadas'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '18' THEN 'Anticipos Otorgados'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '19' THEN 'Cuentas por cobrar comerciales (neto)'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '25' THEN 'Existencias'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '28' THEN 'Existencias'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '30' THEN 'Inversiones Mobiliarias'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '32' THEN 'Propiedades, planta y equipo (neto)'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '33' THEN 'Propiedades, planta y equipo (neto)'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '34' THEN 'Intangible'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '37' THEN 'Activo Diferido'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '39' THEN 'Propiedades, planta y equipo (neto)'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '40' THEN 'Tributos por Pagar'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '41' THEN 'Provisiones por beneficios a empleados'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '42' THEN 'Cuentas por pagar comerciales'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '43' THEN 'Otras cuentas por Pagar Relacionadas'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '45' THEN 'Obligaciones Financieras'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '46' THEN 'Otras cuentas por pagar'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '47' THEN 'Otras cuentas por Pagar Relacionadas'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '50' THEN 'Capital Emitido'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '52' THEN 'Aportes'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '57' THEN 'Excedente de revaluación'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '58' THEN 'Reservas'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '59' THEN 'Resultados Acumulados'
        WHEN FIRST_CHAR IN ('1','2','3') THEN 'POR DEFINIR ACTIVO'
        WHEN FIRST_CHAR = '4'            THEN 'POR DEFINIR PASIVO'
        WHEN FIRST_CHAR = '5'            THEN 'POR DEFINIR PATRIMONIO'
        ELSE NULL
    END AS PARTIDA_BS,
    CASE
        WHEN CUENTA_CONTABLE LIKE '16.7.1.1.01%' THEN 'PASIVO'
        WHEN CUENTA_CONTABLE LIKE '16.7.2.1.01%' THEN 'PASIVO'
        WHEN FIRST_CHAR IN ('1','2','3') THEN 'ACTIVO'
        WHEN FIRST_CHAR = '4'            THEN 'PASIVO'
        WHEN FIRST_CHAR = '5'            THEN 'PATRIMONIO'
    END AS SECCION_BS
FROM (
    SELECT
        CIA, RTRIM(CUENTA_CONTABLE) AS CUENTA_CONTABLE,
        RTRIM(DESCRIPCION) AS DESCRIPCION, RTRIM(NIT) AS NIT,
        RTRIM(RAZON_SOCIAL) AS RAZON_SOCIAL,
        RTRIM(CENTRO_COSTO) AS CENTRO_COSTO, RTRIM(DESC_CECO) AS DESC_CECO,
        FECHA, RTRIM(ASIENTO) AS ASIENTO,
        DEBITO_LOCAL, CREDITO_LOCAL, RTRIM(FUENTE) AS FUENTE, CONTABILIDAD,
        LEFT(CUENTA_CONTABLE, 1) AS FIRST_CHAR
    FROM [NEXTNET].[VISTA_ANALISIS_CECOS]
    WHERE LEFT(CUENTA_CONTABLE, 1) IN ('1','2','3','4','5')
      AND FUENTE NOT LIKE 'CIERRE%'
) src;
GO


CREATE OR ALTER VIEW [FIBERLUX].[VISTA_BS_PREPARADO] AS
SELECT
    CIA, CUENTA_CONTABLE, DESCRIPCION, NIT, RAZON_SOCIAL,
    CENTRO_COSTO, DESC_CECO, FECHA, ASIENTO,
    DEBITO_LOCAL, CREDITO_LOCAL, FUENTE, CONTABILIDAD,
    CAST(
        CASE WHEN FIRST_CHAR IN ('1','2','3') THEN DEBITO_LOCAL - CREDITO_LOCAL
             ELSE CREDITO_LOCAL - DEBITO_LOCAL END
    AS DECIMAL(28, 8)) AS SALDO,
    MONTH(FECHA) AS MES,
    CASE
        WHEN CUENTA_CONTABLE LIKE '16.7.1.1.01%' THEN 'Tributos por Pagar'
        WHEN CUENTA_CONTABLE LIKE '16.7.2.1.01%' THEN 'Tributos por Pagar'
        WHEN CUENTA_CONTABLE LIKE '16.7%'        THEN 'Tributos por acreditar'
        WHEN CUENTA_CONTABLE LIKE '37.3%'        THEN 'Otros Activos'
        WHEN CUENTA_CONTABLE LIKE '39.6%'        THEN 'Intangible'
        WHEN CUENTA_CONTABLE LIKE '49.1%'        THEN 'Impuesto a la renta diferido'
        WHEN CUENTA_CONTABLE LIKE '49.2%'        THEN 'Participaciones de los trabajadores diferidas'
        WHEN CUENTA_CONTABLE LIKE '49.3%'        THEN 'Intereses diferidos'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '10' THEN 'Efectivo y equivalentes de efectivo'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '12' THEN 'Cuentas por cobrar comerciales (neto)'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '13' THEN 'Otras cuentas por cobrar relacionadas'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '14' THEN 'Otras cuentas por cobrar (neto)'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '16' THEN 'Otras cuentas por cobrar (neto)'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '17' THEN 'Otras cuentas por cobrar relacionadas'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '18' THEN 'Anticipos Otorgados'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '19' THEN 'Cuentas por cobrar comerciales (neto)'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '25' THEN 'Existencias'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '28' THEN 'Existencias'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '30' THEN 'Inversiones Mobiliarias'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '32' THEN 'Propiedades, planta y equipo (neto)'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '33' THEN 'Propiedades, planta y equipo (neto)'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '34' THEN 'Intangible'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '37' THEN 'Activo Diferido'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '39' THEN 'Propiedades, planta y equipo (neto)'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '40' THEN 'Tributos por Pagar'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '41' THEN 'Provisiones por beneficios a empleados'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '42' THEN 'Cuentas por pagar comerciales'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '43' THEN 'Otras cuentas por Pagar Relacionadas'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '45' THEN 'Obligaciones Financieras'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '46' THEN 'Otras cuentas por pagar'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '47' THEN 'Otras cuentas por Pagar Relacionadas'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '50' THEN 'Capital Emitido'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '52' THEN 'Aportes'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '57' THEN 'Excedente de revaluación'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '58' THEN 'Reservas'
        WHEN LEFT(CUENTA_CONTABLE, 2) = '59' THEN 'Resultados Acumulados'
        WHEN FIRST_CHAR IN ('1','2','3') THEN 'POR DEFINIR ACTIVO'
        WHEN FIRST_CHAR = '4'            THEN 'POR DEFINIR PASIVO'
        WHEN FIRST_CHAR = '5'            THEN 'POR DEFINIR PATRIMONIO'
        ELSE NULL
    END AS PARTIDA_BS,
    CASE
        WHEN CUENTA_CONTABLE LIKE '16.7.1.1.01%' THEN 'PASIVO'
        WHEN CUENTA_CONTABLE LIKE '16.7.2.1.01%' THEN 'PASIVO'
        WHEN FIRST_CHAR IN ('1','2','3') THEN 'ACTIVO'
        WHEN FIRST_CHAR = '4'            THEN 'PASIVO'
        WHEN FIRST_CHAR = '5'            THEN 'PATRIMONIO'
    END AS SECCION_BS
FROM (
    SELECT
        CIA, RTRIM(CUENTA_CONTABLE) AS CUENTA_CONTABLE,
        RTRIM(DESCRIPCION) AS DESCRIPCION, RTRIM(NIT) AS NIT,
        RTRIM(RAZON_SOCIAL) AS RAZON_SOCIAL,
        RTRIM(CENTRO_COSTO) AS CENTRO_COSTO, RTRIM(DESC_CECO) AS DESC_CECO,
        FECHA, RTRIM(ASIENTO) AS ASIENTO,
        DEBITO_LOCAL, CREDITO_LOCAL, RTRIM(FUENTE) AS FUENTE, CONTABILIDAD,
        LEFT(CUENTA_CONTABLE, 1) AS FIRST_CHAR
    FROM [FIBERLUX].[VISTA_ANALISIS_CECOS]
    WHERE LEFT(CUENTA_CONTABLE, 1) IN ('1','2','3','4','5')
      AND FUENTE NOT LIKE 'CIERRE%'
) src;
GO


-- ─────────────────────────────────────────────────────────────────────────────
-- Umbrella view in REPORTES.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR ALTER VIEW [REPORTES].[VISTA_BS_PREPARADO] AS
SELECT * FROM [FIBERLINE].[VISTA_BS_PREPARADO]
UNION ALL
SELECT * FROM [FIBERTECH].[VISTA_BS_PREPARADO]
UNION ALL
SELECT * FROM [NEXTNET].[VISTA_BS_PREPARADO]
UNION ALL
SELECT * FROM [FIBERLUX].[VISTA_BS_PREPARADO];
GO
