# SQL Index Recommendations

## Context

The dashboard loads data via two queries against `REPORTES.VISTA_ANALISIS_CECOS`:

1. **P&L**: `WHERE CIA = ? AND FECHA >= ? AND FECHA < ? AND (CUENTA_CONTABLE LIKE '6%' OR ... '7%' OR ... '8%') AND FUENTE NOT LIKE 'CIERRE%'`
2. **BS**: `WHERE CIA = ? AND FECHA >= ? AND FECHA < ? AND (CUENTA_CONTABLE LIKE '1%' OR ... '5%') AND FUENTE NOT LIKE 'CIERRE%'`

For high-volume companies (e.g., FIBERLINE), these queries can take 60-120+ seconds, causing gateway timeouts.

## Recommended Index

On the **underlying table(s)** behind `REPORTES.VISTA_ANALISIS_CECOS`:

```sql
CREATE NONCLUSTERED INDEX IX_CECOS_CIA_FECHA
ON [table_name] (CIA, FECHA)
INCLUDE (CUENTA_CONTABLE, DESCRIPCION, NIT, RAZON_SOCIAL,
         CENTRO_COSTO, DESC_CECO, DEBITO_LOCAL, CREDITO_LOCAL,
         ASIENTO, FUENTE);
```

This is a **covering index** — the query can be satisfied entirely from the index without touching the base table. The `(CIA, FECHA)` key supports the `WHERE CIA = ? AND FECHA >= ? AND FECHA < ?` filter with an index seek.

## How to Identify the Base Table

If `VISTA_ANALISIS_CECOS` is a view:

```sql
SELECT OBJECT_NAME(referencing_id), referenced_entity_name
FROM sys.sql_expression_dependencies
WHERE referencing_id = OBJECT_ID('REPORTES.VISTA_ANALISIS_CECOS');
```

## Verification

Before and after creating the index, run:

```sql
SET STATISTICS TIME ON;
SET STATISTICS IO ON;

SELECT CIA, CUENTA_CONTABLE, DESCRIPCION, NIT, RAZON_SOCIAL,
       CENTRO_COSTO, DESC_CECO, FECHA, DEBITO_LOCAL, CREDITO_LOCAL, ASIENTO
FROM REPORTES.VISTA_ANALISIS_CECOS
WHERE CIA = 'FIBERLINE'
  AND FECHA >= '2026-01-01' AND FECHA < '2027-01-01'
  AND (CUENTA_CONTABLE LIKE '6%' OR CUENTA_CONTABLE LIKE '7%' OR CUENTA_CONTABLE LIKE '8%')
  AND FUENTE NOT LIKE 'CIERRE%';
```

Compare logical reads and elapsed time before/after. Expected improvement: 10-50x for large companies.
