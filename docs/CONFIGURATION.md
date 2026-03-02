# Configuration Reference

> All environment variables, business rules, and configuration constants.

## Environment Variables

All environment variables are read in `config.py` via `os.environ.get()`. Store them in `.env` at project root (loaded by `python-dotenv`).

### Database Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DB_DRIVER` | Yes | — | ODBC driver name (e.g., "ODBC Driver 17 for SQL Server") |
| `DB_SERVER` | Yes | — | SQL Server hostname or IP |
| `DB_DATABASE` | Yes | — | Database name |
| `DB_UID` | Yes | — | SQL Server username |
| `DB_PWD` | Yes | — | SQL Server password |
| `DB_CONNECT_TIMEOUT` | No | `30` | Connection timeout in seconds |
| `DB_QUERY_TIMEOUT` | No | `120` | Query timeout in seconds |
| `DB_ENCRYPT` | No | `"yes"` | Enable TLS encryption |
| `DB_TRUST_CERT` | No | `"no"` | Trust server certificate |

### Email Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `EMAIL_BACKEND` | No | Auto-detect | `"outlook"` or `"smtp"` (auto: Windows→Outlook, others→SMTP) |
| `EMAIL_TO` | Yes* | — | Comma-separated recipient emails |
| `EMAIL_FROM` | SMTP only | — | Sender email address |
| `SMTP_HOST` | SMTP only | — | SMTP server hostname |
| `SMTP_PORT` | SMTP only | `587` | SMTP port (TLS) |
| `SMTP_USER` | No | — | SMTP auth username (optional if no auth required) |
| `SMTP_PASSWORD` | No | — | SMTP auth password |

*Required if sending email (not with `--no-email`).

### General Settings

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LOG_LEVEL` | No | `"INFO"` | Python logging level |
| `OUTPUT_DIR` | No | `"."` | Directory for generated reports |
| `STRICT_BS_BALANCE` | No | `False` | Raise error (vs warning) on BS imbalance. Values: "1", "true", "yes" |

### Example .env File

```env
# Database
DB_DRIVER=ODBC Driver 17 for SQL Server
DB_SERVER=192.168.1.100
DB_DATABASE=FLEXLINE_PROD
DB_UID=report_user
DB_PWD=secure_password_here
DB_CONNECT_TIMEOUT=30
DB_QUERY_TIMEOUT=120

# Email
EMAIL_BACKEND=outlook
EMAIL_TO=finance@company.com,controller@company.com

# General
LOG_LEVEL=INFO
OUTPUT_DIR=.
STRICT_BS_BALANCE=0
```

## CLI Arguments

```
python -m main [OPTIONS]

Options:
  --company COMPANY      Company code (auto-uppercased). If omitted, prompts interactively.
  --year YEAR            Fiscal year (>= 2025). If omitted, prompts interactively.
  --month 1-12           Report month (mutually exclusive with --quarter)
  --quarter 1-4          Report quarter (mutually exclusive with --month)
  --no-email             Skip email sending
  --excel-only           Generate Excel only (no PDF)
  --test-email           Send test email and exit (validates email config)
```

### Execution Modes

| Mode | Args | Behavior |
|------|------|----------|
| Full CLI | All provided | Batch/automation, no prompts |
| Partial CLI | Some provided | Prompts for missing args |
| Interactive | None | Prompts for all args |
| Test email | `--test-email` | Validates email config, sends test, exits |

## Company Configuration (company_config.py)

| Code | Legal Name | RUC |
|------|-----------|-----|
| `FIBERLINE` | FIBERLINE PERU S.A.C. | 20601594791 |
| `FIBERLUX` | FIBERLUX S.A.C. | 20557425889 |
| `FIBERTECH` | FIBERLUX TECH S.A.C. | 20607403903 |
| `NEXTNET` | NEXTNET S.A.C. | 20546904106 |

Accessed via `COMPANY_META[code]["legal_name"]` and `COMPANY_META[code]["ruc"]`. Valid codes: `VALID_COMPANIES = frozenset(COMPANY_META.keys())`.

## Calendar Configuration (calendar_config.py)

### Constants

| Constant | Value | Purpose |
|----------|-------|---------|
| `MIN_YEAR` | 2025 | Earliest allowed reporting year |
| `MONTH_NAMES` | `{1: "JAN", 2: "FEB", ..., 12: "DEC"}` | English month abbreviations |
| `MONTH_NAMES_ES` | `{1: "Enero", ..., 12: "Diciembre"}` | Spanish full month names |
| `MONTH_NAMES_SET` | `frozenset(MONTH_NAMES.values())` | Validation set |
| `QUARTER_MONTHS` | `{1: [1,2,3], 2: [4,5,6], 3: [7,8,9], 4: [10,11,12]}` | Quarter definitions |

### Period Functions

| Function | Input | Output | Example |
|----------|-------|--------|---------|
| `derive_period_type(month, quarter)` | CLI args | `(type, num)` | `(3, None)` → `("month", 3)` |
| `get_period_months(type, num)` | Period spec | `list[int]` | `("quarter", 2)` → `[4, 5, 6]` |
| `get_ytd_months(type, num)` | Period spec | `list[int]` | `("month", 6)` → `[1,2,3,4,5,6]` |
| `get_end_month(type, num)` | Period spec | `int` | `("quarter", 3)` → `9` |
| `get_quarter_end_month(quarter)` | Quarter num | `int` | `2` → `6` |

## Account Classification Rules (account_rules.py)

### P&L Account Rules (14 Classification Rules)

All rules are evaluated in priority order via `np.select()` in `transforms.assign_partida_pl()`.

| Rule | Matching Logic | PARTIDA_PL |
|------|---------------|------------|
| PROVISION_INCOBRABLE_CUENTAS | Exact match on 2 account codes | "PROVISION INCOBRABLE" |
| CECO prefix "6" | Cost center starts with 6 | "D&A - COSTO" |
| DYA_GASTO_PREFIXES | Account starts with 68.0-68.6 (7 prefixes) | "D&A - GASTO" |
| PARTICIPACION_TRABAJADORES_CUENTA | Single exact account | "PARTICIPACION DE TRABAJADORES" |
| DIFERENCIA_CAMBIO_PREFIXES | Account starts with 67.6 or 77.6 | "DIFERENCIA DE CAMBIO" |
| RESULTADO_FINANCIERO_PREFIXES | Account starts with 67 or 77 | "RESULTADO FINANCIERO" |
| INGRESOS_ORDINARIOS_PREFIX | Account starts with 70 | "INGRESOS ORDINARIOS" |
| INGRESOS_PROYECTOS_CUENTA | Exact match | "INGRESOS PROYECTOS" |
| OTROS_INGRESOS_PREFIXES | Account starts with 73 or 75 | "OTROS INGRESOS" |
| IMPUESTO_RENTA_FIRST_CHAR | First char = "8" | "IMPUESTO A LA RENTA" |
| CECO prefix "7" | Cost center starts with 7 | "RESULTADO FINANCIERO" |
| CECO prefix "1" or "4" | Cost center starts with 1 or 4 | "COSTO" |
| CECO prefix "2" | Cost center starts with 2 | "GASTO VENTA" |
| CECO prefix "3" | Cost center starts with 3 | "GASTO ADMIN" |
| Default | No match | "POR DEFINIR" |

### P&L Subtotal Labels

```python
PL_SUBTOTAL_LABELS = {
    "INGRESOS TOTALES",
    "UTILIDAD BRUTA",
    "UTILIDAD OPERATIVA",
    "UTILIDAD ANTES DE IMPUESTO A LA RENTA",
    "UTILIDAD NETA",
}
```

### BS Classification (2-Digit Prefix Mapping)

| Prefix | Label | Section |
|--------|-------|---------|
| 10 | Efectivo y equivalentes de efectivo | ACTIVO |
| 12 | Cuentas por cobrar comerciales (neto) | ACTIVO |
| 13 | Otras cuentas por cobrar (neto) | ACTIVO |
| 14 | Otras cuentas por cobrar (neto) | ACTIVO |
| 16 | Otras cuentas por cobrar (neto) | ACTIVO |
| 17 | Otras cuentas por cobrar (neto) | ACTIVO |
| 18 | Servicios y otros contratados por anticipado | ACTIVO |
| 19 | Cuentas por cobrar comerciales (neto) | ACTIVO |
| 20 | Mercaderias | ACTIVO |
| 25 | Materiales auxiliares y suministros | ACTIVO |
| 26 | Materiales auxiliares y suministros | ACTIVO |
| 32 | Activos por derecho de uso | ACTIVO |
| 33 | Inmuebles, maquinaria y equipo (neto) | ACTIVO |
| 34 | Intangibles (neto) | ACTIVO |
| 37 | Activo diferido | ACTIVO |
| 39 | Depreciacion, amortizacion y agotamiento | ACTIVO |
| 40 | Tributos por pagar | PASIVO |
| 41 | Remuneraciones y participaciones por pagar | PASIVO |
| 42 | Cuentas por pagar comerciales | PASIVO |
| 44 | Cuentas por pagar a los accionistas | PASIVO |
| 45 | Obligaciones financieras | PASIVO |
| 46 | Cuentas por pagar diversas | PASIVO |
| 48 | Provisiones por beneficios a empleados | PASIVO |
| 49 | Pasivo diferido | PASIVO |
| 50-59 | (various) | PATRIMONIO |

### BS Classification Overrides (Longer Prefix)

These override the 2-digit defaults when a longer prefix matches:

| Prefix | Override Label | Section Override |
|--------|---------------|-----------------|
| 13.4 | Otras cuentas por cobrar relacionadas | ACTIVO |
| 46.9 | Otras cuentas por Pagar Relacionadas | PASIVO |
| 12.1.2 | Cuentas por cobrar comerciales relacionadas (neto) | ACTIVO |
| 46.3 | (specific override) | PASIVO |
| 46.8 | (specific override) | PASIVO |

### BS Dynamic Reclassification Rules

| Account | Condition | Action |
|---------|-----------|--------|
| 12.2.1.1.01 | Balance is negative | Move from ACTIVO to PASIVO as "Anticipos Recibidos" (flip sign) |
| Prefix "14" | Any account negative | Move from ACTIVO to PASIVO as "Provisiones por beneficios a empleados" (flip sign) |
| Prefix "42.2" | Any account negative | Move from PASIVO to ACTIVO as "Anticipos Otorgados" (flip sign) |

### BS Section and Partida Order

```python
BS_SECTION_ORDER = ["ACTIVO", "PASIVO", "PATRIMONIO"]

BS_PARTIDA_ORDER = [
    "Efectivo y equivalentes de efectivo",
    "Cuentas por cobrar comerciales (neto)",
    "Cuentas por cobrar comerciales relacionadas (neto)",
    "Otras cuentas por cobrar (neto)",
    "Otras cuentas por cobrar relacionadas",
    "Mercaderias",
    "Materiales auxiliares y suministros",
    "Servicios y otros contratados por anticipado",
    "Inmuebles, maquinaria y equipo (neto)",
    "Activos por derecho de uso",
    "Intangibles (neto)",
    "Depreciacion, amortizacion y agotamiento",
    "Activo diferido",
    "Cuentas por pagar comerciales",
    "Otras cuentas por Pagar Relacionadas",
    "Obligaciones financieras",
    "Remuneraciones y participaciones por pagar",
    "Tributos por pagar",
    "Provisiones por beneficios a empleados",
    "Cuentas por pagar diversas",
]
```

## Nota Configuration (nota_config.py)

### Render Patterns

| Pattern | Layout | Used By |
|---------|--------|---------|
| `BS_DETAIL` | Single BS detail table | Most BS notes |
| `BS_DETAIL_WITH_NIT` | BS detail + NIT pivot table | Related-party notes |
| `PL_DETAIL_CECO` | P&L detail by cost center | Cost/expense notes |
| `PL_DETAIL_CUENTA` | P&L detail by account | D&A, financial results |
| `SALES_INGRESOS` | Revenue detail | Ingresos Ordinarios |
| `SALES_PROYECTOS` | Projects by NIT | Ingresos Proyectos |

### Note Groups (16 total)

| Group | Type | Content |
|-------|------|---------|
| 1 | BS | Efectivo y Equivalentes |
| 2-3 | BS | Cuentas por Cobrar (Comerciales, Otras, Relacionadas) |
| 4 | BS | PP&E, Intangibles, D&A |
| 5 | BS | Otros Activos |
| 6-7 | BS | Cuentas por Pagar (Comerciales, Otras, Relacionadas) |
| 8 | BS | Provisiones por Beneficios |
| 9 | BS | Tributos por Pagar |
| 10 | P&L | Ingresos (Ordinarios + Proyectos) |
| 11 | P&L | Costo de Operaciones |
| 12 | P&L | Gastos de Ventas |
| 13 | P&L | Gastos de Administracion |
| 14 | P&L | D&A (Costo & Gasto) |
| 15 | P&L | Ingresos/Gastos Financieros |

Notes are auto-numbered sequentially. Reordering `NOTA_GROUPS` changes numbering in both Excel and PDF.

### Data Source Resolution

`_resolve_excel_df(entry, data)` maps `NotaEntry` fields to actual DataFrames:

| Field | Source | Used By |
|-------|--------|---------|
| `entry.bs_key` | `data.bs_sheets[bs_key]` | BS notes |
| `entry.data_attr` | `getattr(data, data_attr)` | P&L notes |
| `entry.nit_pivot_key` | `data.nit_pivots[key]` | Related-party details |

## Connection Pool Configuration

| Parameter | Value | Source |
|-----------|-------|--------|
| Max connections | 5 | Hardcoded in `db._ConnectionPool` |
| Borrow timeout | 30 seconds | Hardcoded (blocks when pool exhausted) |
| Validation query | `SELECT 1` | Before reuse from pool |
| Shutdown | `atexit` registered | Automatic on process exit |

## Caching Configuration

| Parameter | Value | Location |
|-----------|-------|----------|
| Cache directory | `.cache/` | `pipeline.py` |
| Cache format | pickle (`.pkl`) | `pipeline.py` |
| TTL | 30 days | `pipeline.py` |
| Cached data | Previous-year P&L and BS DataFrames | Immutable historical data only |
