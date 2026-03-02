# Nota Grouping Pattern

## Overview

Some balance sheet notes display **aggregated group rows** in the PDF (instead of individual
`CUENTA_CONTABLE` rows), while the Excel sheet keeps the full account-level detail plus an extra
column showing which PDF group each account belongs to.

Nota 01 — Efectivo y Equivalentes de Efectivo is the reference implementation.

---

## Pattern Summary

| Layer | What it shows |
|---|---|
| **Excel (Nota sheet)** | One row per `CUENTA_CONTABLE` + monthly columns + `Categoria PDF` column at the end |
| **PDF (Nota page)** | One row per group label + TOTAL row; individual accounts are hidden |

---

## How to implement for a new nota

### Step 1 — Define the group mapping in `pdf_export.py`

Add a module-level list of `(account_prefix, group_label)` tuples. Rules are evaluated in order;
the first matching prefix wins.

```python
_MYKEY_GROUPS: list[tuple[str, str]] = [
    ("prefix.A.", "Label A"),
    ("prefix.B.", "Label B"),
    ("prefix.C.", "Label B"),   # two prefixes can share the same label
]
```

Add a resolver function:

```python
def _get_mykey_group(cuenta: str) -> str | None:
    for prefix, label in _MYKEY_GROUPS:
        if str(cuenta).startswith(prefix):
            return label
    return None
```

### Step 2 — Add an aggregation function in `pdf_export.py`

Clone `_aggregate_efectivo_by_group` and adapt it to the new key.  The function must:

1. Strip any pre-existing TOTAL row from the incoming DataFrame (checking **both**
   `CUENTA_CONTABLE` and `DESCRIPCION` for `"TOTAL"`, because `append_total_row` writes
   the label into whichever column was passed as `label_col`).
2. Apply the group resolver to each remaining row.
3. `groupby` on `_group`, summing all value columns.
4. Sort groups in canonical order (as defined in the groups list).
5. Append a fresh computed TOTAL row at the end.

```python
def _aggregate_mykey_by_group(df: pd.DataFrame, value_cols: list[str]) -> pd.DataFrame:
    seen_labels: list[str] = []
    for _, label in _MYKEY_GROUPS:
        if label not in seen_labels:
            seen_labels.append(label)
    group_order = {label: i for i, label in enumerate(seen_labels)}
    group_order["Sin clasificar"] = len(seen_labels)

    is_total = (
        df["CUENTA_CONTABLE"].astype(str).str.strip().str.upper().eq(_TOTAL_LABEL) |
        df["DESCRIPCION"].astype(str).str.strip().str.upper().eq(_TOTAL_LABEL)
    )
    data_rows = df[~is_total].copy()

    data_rows["_group"] = data_rows["CUENTA_CONTABLE"].apply(_get_mykey_group).fillna("Sin clasificar")
    data_rows["_group_order"] = data_rows["_group"].map(group_order).fillna(999).astype(int)

    agg = data_rows.groupby(["_group", "_group_order"], observed=True)[value_cols].sum().reset_index()
    agg = agg.sort_values("_group_order").reset_index(drop=True)

    result_rows = []
    for _, row in agg.iterrows():
        rec = {"CUENTA_CONTABLE": "", "DESCRIPCION": row["_group"]}
        for vc in value_cols:
            rec[vc] = row[vc]
        result_rows.append(rec)

    result = pd.DataFrame(result_rows, columns=df.columns)
    for vc in value_cols:
        result[vc] = result[vc].astype(float)

    total_rec = {"CUENTA_CONTABLE": _TOTAL_LABEL, "DESCRIPCION": _TOTAL_LABEL}
    for vc in value_cols:
        total_rec[vc] = result[vc].sum()
    total_row = pd.DataFrame([total_rec], columns=df.columns)
    for vc in value_cols:
        total_row[vc] = total_row[vc].astype(float)

    return pd.concat([result, total_row], ignore_index=True)[df.columns]
```

### Step 3 — Wire it in `pdf_export.py` → `export_to_pdf()`

Inside the BS detail rendering loop, add a branch for the new `bs_key`:

```python
if entry.bs_key == "bs_mykey":
    bs_df = _aggregate_mykey_by_group(bs_df, bs_col_names)
    label_cols = ["DESCRIPCION"]
    header_labels = ["DESCRIPCION"]
    eff_widths = [sum(bs_det_widths)]
```

This collapses the two label columns (`CUENTA_CONTABLE` + `DESCRIPCION`) into a single
`DESCRIPCION` column and merges their widths so the table still fits correctly.

### Step 4 — Wire it in `excel_export.py`

Add a resolver import and a helper (or extend `_add_pdf_category_col` if the resolver is
exported), then call it in `_write_single_nota` before `_write_single_bs_sheet`:

```python
def _add_mykey_category_col(df: pd.DataFrame) -> pd.DataFrame:
    from pdf_export import _get_mykey_group
    df = df.copy()
    df["Categoria PDF"] = df["CUENTA_CONTABLE"].apply(
        lambda c: _get_mykey_group(c) or "Sin clasificar"
    )
    return df
```

```python
case RenderPattern.BS_DETAIL:
    if entry.bs_key == "bs_efectivo":
        df = _add_pdf_category_col(df)
    elif entry.bs_key == "bs_mykey":
        df = _add_mykey_category_col(df)
    _write_single_bs_sheet(writer, df, sheet_name, title)
```

---

## Key gotcha — TOTAL row stripping

`bs_detail_by_cuenta_pdf` is called with `with_total_row=True` in `pipeline.py`. The appended
TOTAL row has:

- `CUENTA_CONTABLE = None` (NaN)
- `DESCRIPCION = "TOTAL"`

The stripping check must cover **both** columns:

```python
is_total = (
    df["CUENTA_CONTABLE"].astype(str).str.strip().str.upper().eq(_TOTAL_LABEL) |
    df["DESCRIPCION"].astype(str).str.strip().str.upper().eq(_TOTAL_LABEL)
)
```

Failing to strip this row causes two bugs simultaneously:
1. The row falls into "Sin clasificar" (no prefix matches `None`).
2. Its values are included in the group sums, then a second TOTAL is computed → **doubled total**.

---

## Reference implementation

- Groups definition: `pdf_export.py` — `_EFECTIVO_GROUPS`, `_get_efectivo_group`
- Aggregation: `pdf_export.py` — `_aggregate_efectivo_by_group`
- PDF wiring: `pdf_export.py` — `export_to_pdf()`, search for `bs_efectivo`
- Excel wiring: `excel_export.py` — `_add_pdf_category_col`, `_write_single_nota`
