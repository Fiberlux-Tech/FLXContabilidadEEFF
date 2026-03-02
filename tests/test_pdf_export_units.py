"""Unit tests for the refactored pdf_export helper functions.

Covers:
  - _filter_zero_rows
  - _remove_orphaned_group_headers
  - _drop_zero_rows (composition)
  - _pl_row_type / _bs_row_type classifiers
  - _df_to_rows (including __GROUP__ sentinel path)
  - _df_to_rows_bs (thin wrapper correctness)
  - _inject_efectivo_groups (vectorized output)
"""

import pandas as pd
import pytest

from pdf_export import (
    _GROUP_SENTINEL,
    _filter_zero_rows,
    _remove_orphaned_group_headers,
    _drop_zero_rows,
    _pl_row_type,
    _bs_row_type,
    _df_to_rows,
    _df_to_rows_bs,
    _inject_efectivo_groups,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row(row_type, nums=None, labels=None):
    return {
        "row_type": row_type,
        "nums": nums or ["-"],
        "labels": labels or ["X"],
    }


def _normal(nums):
    return _row("normal", nums=nums)


def _nonzero():
    return _normal(["1,234"])


def _zero():
    return _normal(["-"])


def _blank():
    return _row("blank", nums=[""])


def _total():
    return _row("total", nums=["1,000"])


def _subtotal():
    return _row("subtotal", nums=["500"])


def _group_header(label="Group A"):
    return _row("group_header", nums=[""], labels=["", label])


# ---------------------------------------------------------------------------
# _filter_zero_rows
# ---------------------------------------------------------------------------

class TestFilterZeroRows:
    def test_removes_all_zero_normal_rows(self):
        rows = [_zero(), _zero()]
        assert _filter_zero_rows(rows) == []

    def test_keeps_nonzero_normal_rows(self):
        rows = [_nonzero(), _zero()]
        result = _filter_zero_rows(rows)
        assert len(result) == 1
        assert result[0]["nums"] == ["1,234"]

    def test_keeps_non_normal_rows_regardless_of_nums(self):
        rows = [_blank(), _total(), _subtotal(), _group_header()]
        assert _filter_zero_rows(rows) == rows

    def test_zero_strings_all_caught(self):
        for zero_str in ("", "-", "0", "(0)"):
            rows = [_normal([zero_str])]
            assert _filter_zero_rows(rows) == [], f"Expected {zero_str!r} to be treated as zero"

    def test_mixed_nums_kept_if_any_nonzero(self):
        rows = [_normal(["-", "1,000", "-"])]
        assert len(_filter_zero_rows(rows)) == 1

    def test_empty_input(self):
        assert _filter_zero_rows([]) == []


# ---------------------------------------------------------------------------
# _remove_orphaned_group_headers
# ---------------------------------------------------------------------------

class TestRemoveOrphanedGroupHeaders:
    def test_keeps_header_with_normal_after(self):
        rows = [_group_header(), _nonzero()]
        assert len(_remove_orphaned_group_headers(rows)) == 2

    def test_removes_header_with_no_normal_after(self):
        rows = [_group_header(), _total()]
        result = _remove_orphaned_group_headers(rows)
        assert all(r["row_type"] != "group_header" for r in result)

    def test_removes_header_at_end_of_list(self):
        rows = [_nonzero(), _group_header()]
        result = _remove_orphaned_group_headers(rows)
        assert all(r["row_type"] != "group_header" for r in result)

    def test_removes_header_followed_by_another_header(self):
        rows = [_group_header("A"), _group_header("B"), _nonzero()]
        result = _remove_orphaned_group_headers(rows)
        headers = [r for r in result if r["row_type"] == "group_header"]
        assert len(headers) == 1
        assert headers[0]["labels"][1] == "B"

    def test_keeps_header_when_normal_after_blank(self):
        rows = [_group_header(), _blank(), _nonzero()]
        result = _remove_orphaned_group_headers(rows)
        assert any(r["row_type"] == "group_header" for r in result)

    def test_removes_header_when_only_blank_then_total(self):
        rows = [_group_header(), _blank(), _total()]
        result = _remove_orphaned_group_headers(rows)
        assert all(r["row_type"] != "group_header" for r in result)

    def test_empty_input(self):
        assert _remove_orphaned_group_headers([]) == []


# ---------------------------------------------------------------------------
# _drop_zero_rows (composition)
# ---------------------------------------------------------------------------

class TestDropZeroRows:
    def test_composes_both_passes(self):
        # Zero normal row under a group header → header becomes orphaned
        rows = [_group_header(), _zero()]
        result = _drop_zero_rows(rows)
        assert result == []

    def test_nonzero_under_header_kept(self):
        rows = [_group_header(), _nonzero()]
        result = _drop_zero_rows(rows)
        assert len(result) == 2

    def test_does_not_remove_total_rows(self):
        rows = [_total(), _zero()]
        result = _drop_zero_rows(rows)
        assert any(r["row_type"] == "total" for r in result)


# ---------------------------------------------------------------------------
# _pl_row_type
# ---------------------------------------------------------------------------

class TestPlRowType:
    def test_blank_when_all_missing_and_empty_labels(self):
        assert _pl_row_type(["", ""], [None, None]) == "blank"

    def test_total_when_label_is_TOTAL(self):
        assert _pl_row_type(["TOTAL", ""], [100.0]) == "total"

    def test_final_total_for_utilidad_neta(self):
        assert _pl_row_type(["UTILIDAD NETA", ""], [500.0]) == "final_total"

    def test_subtotal_for_ingresos_totales(self):
        assert _pl_row_type(["INGRESOS TOTALES", ""], [1000.0]) == "subtotal"

    def test_normal_for_regular_account(self):
        assert _pl_row_type(["70.1.1.1.01", "Ventas"], [500.0]) == "normal"

    def test_blank_requires_both_missing_values_and_empty_labels(self):
        # Label is non-empty → NOT blank even if value is missing; classifies as final_total
        assert _pl_row_type(["UTILIDAD NETA", ""], [None]) == "final_total"
        # Both label and value empty → blank
        assert _pl_row_type(["", ""], [None]) == "blank"


# ---------------------------------------------------------------------------
# _bs_row_type
# ---------------------------------------------------------------------------

class TestBsRowType:
    def test_blank_when_all_missing(self):
        assert _bs_row_type(["", ""], [None]) == "blank"

    def test_final_total_for_total_activo(self):
        assert _bs_row_type(["TOTAL ACTIVO", ""], [5000.0]) == "final_total"

    def test_final_total_for_pasivo_patrimonio(self):
        assert _bs_row_type(["TOTAL PASIVO Y PATRIMONIO", ""], [5000.0]) == "final_total"

    def test_normal_for_partida_row(self):
        assert _bs_row_type(["Efectivo y equivalentes de efectivo", ""], [200.0]) == "normal"

    def test_no_subtotal_type_in_bs(self):
        # BS classifier never returns "subtotal"
        result = _bs_row_type(["INGRESOS TOTALES", ""], [100.0])
        assert result != "subtotal"


# ---------------------------------------------------------------------------
# _df_to_rows
# ---------------------------------------------------------------------------

def _make_pl_df():
    return pd.DataFrame({
        "PARTIDA_PL": ["INGRESOS ORDINARIOS", "INGRESOS TOTALES", "", "UTILIDAD NETA", "TOTAL"],
        "NOTA": ["-", "-", "", "-", ""],
        "2025": [1000.0, 1000.0, None, 800.0, 800.0],
        "2024": [900.0, 900.0, None, 700.0, 700.0],
    })


class TestDfToRows:
    def test_basic_pl_row_types(self):
        df = _make_pl_df()
        rows = _df_to_rows(df, ["PARTIDA_PL", "NOTA"], ["2025", "2024"])
        types = [r["row_type"] for r in rows]
        assert types[0] == "normal"          # INGRESOS ORDINARIOS
        assert types[1] == "subtotal"        # INGRESOS TOTALES
        assert types[2] == "blank"           # empty row
        assert types[3] == "final_total"      # UTILIDAD NETA
        assert types[4] == "total"           # TOTAL

    def test_labels_extracted_correctly(self):
        df = _make_pl_df()
        rows = _df_to_rows(df, ["PARTIDA_PL", "NOTA"], ["2025", "2024"])
        assert rows[0]["labels"] == ["INGRESOS ORDINARIOS", "-"]

    def test_none_label_converted_to_empty_string(self):
        df = pd.DataFrame({"A": [None], "B": ["x"], "V": [1.0]})
        rows = _df_to_rows(df, ["A", "B"], ["V"])
        assert rows[0]["labels"][0] == ""

    def test_numeric_column_names_work(self):
        """Column names like '2025' (digits) must not cause AttributeError."""
        df = pd.DataFrame({"LABEL": ["X"], "2025": [500.0], "2024": [400.0]})
        rows = _df_to_rows(df, ["LABEL"], ["2025", "2024"])
        assert len(rows) == 1
        assert rows[0]["nums"] == ["500", "400"]

    def test_group_header_sentinel_handled(self):
        df = pd.DataFrame({
            "CUENTA_CONTABLE": [_GROUP_SENTINEL, "10.4.1.1.01"],
            "DESCRIPCION": ["Cuentas corrientes", "BCP"],
            "2025": [None, 50000.0],
        })
        rows = _df_to_rows(df, ["CUENTA_CONTABLE", "DESCRIPCION"], ["2025"])
        assert rows[0]["row_type"] == "group_header"
        assert rows[0]["labels"] == ["", "Cuentas corrientes"]
        assert rows[0]["nums"] == [""]
        assert rows[1]["row_type"] == "normal"

    def test_bs_row_type_classifier(self):
        df = pd.DataFrame({
            "PARTIDA_BS": ["Efectivo y equivalentes de efectivo", "TOTAL ACTIVO"],
            "NOTA": ["-", ""],
            "2025": [200.0, 200.0],
        })
        rows = _df_to_rows(df, ["PARTIDA_BS", "NOTA"], ["2025"],
                           row_type_classifier=_bs_row_type)
        assert rows[0]["row_type"] == "normal"
        assert rows[1]["row_type"] == "final_total"

    def test_fmt_numbers_applied(self):
        df = pd.DataFrame({"L": ["A"], "V": [-1234.0]})
        rows = _df_to_rows(df, ["L"], ["V"])
        assert rows[0]["nums"] == ["(1,234)"]


# ---------------------------------------------------------------------------
# _df_to_rows_bs
# ---------------------------------------------------------------------------

class TestDfToRowsBs:
    def test_wrapper_uses_bs_classifier(self):
        df = pd.DataFrame({
            "PARTIDA_BS": ["TOTAL ACTIVO", "Efectivo y equivalentes de efectivo"],
            "NOTA": ["", "-"],
            "2025": [5000.0, 200.0],
        })
        rows = _df_to_rows_bs(df, ["PARTIDA_BS", "NOTA"], ["2025"])
        assert rows[0]["row_type"] == "final_total"
        assert rows[1]["row_type"] == "normal"

    def test_no_subtotal_rows_produced(self):
        df = pd.DataFrame({
            "PARTIDA_BS": ["INGRESOS TOTALES"],  # PL label, not a BS label
            "NOTA": ["-"],
            "2025": [1000.0],
        })
        rows = _df_to_rows_bs(df, ["PARTIDA_BS", "NOTA"], ["2025"])
        assert rows[0]["row_type"] == "normal"  # not subtotal in BS context


# ---------------------------------------------------------------------------
# _inject_efectivo_groups
# ---------------------------------------------------------------------------

def _make_efectivo_df(value_cols=("DEC",)):
    """Minimal efectivo DataFrame with accounts from multiple groups."""
    data = {
        "CUENTA_CONTABLE": [
            "10.4.1.1.01",  # Cuentas corrientes
            "10.1.1.1.01",  # Caja chica
            "10.4.2.1.01",  # Cuentas corrientes
            "10.6.1.1.01",  # Depositos a plazo
            "TOTAL",
        ],
        "DESCRIPCION": ["BCP", "Caja Lima", "Scotiabank", "Deposito 30d", "TOTAL"],
    }
    amounts = [50000.0, 500.0, 30000.0, 100000.0, 180500.0]
    for col in value_cols:
        data[col] = amounts
    return pd.DataFrame(data)


class TestInjectEfectivoGroups:
    def test_output_columns_match_input(self):
        df = _make_efectivo_df()
        result = _inject_efectivo_groups(df, ["DEC"])
        assert list(result.columns) == list(df.columns)

    def test_total_row_is_last(self):
        df = _make_efectivo_df()
        result = _inject_efectivo_groups(df, ["DEC"])
        assert result.iloc[-1]["CUENTA_CONTABLE"].strip().upper() == "TOTAL"

    def test_group_headers_injected(self):
        df = _make_efectivo_df()
        result = _inject_efectivo_groups(df, ["DEC"])
        sentinels = result[result["CUENTA_CONTABLE"] == _GROUP_SENTINEL]
        assert len(sentinels) >= 2  # at least Caja chica and Cuentas corrientes

    def test_sentinel_description_matches_group_label(self):
        df = _make_efectivo_df()
        result = _inject_efectivo_groups(df, ["DEC"])
        sentinel_labels = set(
            result[result["CUENTA_CONTABLE"] == _GROUP_SENTINEL]["DESCRIPCION"].tolist()
        )
        assert "Cuentas corrientes" in sentinel_labels
        assert "Caja chica" in sentinel_labels

    def test_group_header_precedes_its_data_rows(self):
        df = _make_efectivo_df()
        result = _inject_efectivo_groups(df, ["DEC"])
        rows = result.to_dict("records")
        current_group = None
        for row in rows:
            if row["CUENTA_CONTABLE"] == _GROUP_SENTINEL:
                current_group = row["DESCRIPCION"]
            elif row["CUENTA_CONTABLE"].strip().upper() != "TOTAL":
                # Every data row should be preceded by its group header somewhere above
                assert current_group is not None

    def test_data_rows_sorted_descending_within_group(self):
        df = _make_efectivo_df()
        result = _inject_efectivo_groups(df, ["DEC"])
        rows = result[result["CUENTA_CONTABLE"] != _GROUP_SENTINEL].copy()
        rows = rows[rows["CUENTA_CONTABLE"].str.upper().str.strip() != "TOTAL"]
        # Within Cuentas corrientes group: BCP (50000) before Scotiabank (30000)
        bcp_pos = rows.index[rows["CUENTA_CONTABLE"] == "10.4.1.1.01"][0]
        scotiabank_pos = rows.index[rows["CUENTA_CONTABLE"] == "10.4.2.1.01"][0]
        assert bcp_pos < scotiabank_pos

    def test_sentinel_value_cols_are_none(self):
        df = _make_efectivo_df()
        result = _inject_efectivo_groups(df, ["DEC"])
        sentinels = result[result["CUENTA_CONTABLE"] == _GROUP_SENTINEL]
        assert sentinels["DEC"].isna().all()

    def test_sin_clasificar_header_when_no_recognised_accounts(self):
        # Unrecognised accounts are grouped under "Sin clasificar", so one
        # group-header sentinel is injected.
        df = pd.DataFrame({
            "CUENTA_CONTABLE": ["99.9.9.9.99", "TOTAL"],
            "DESCRIPCION": ["Unknown", "TOTAL"],
            "DEC": [100.0, 100.0],
        })
        result = _inject_efectivo_groups(df, ["DEC"])
        sentinels = result[result["CUENTA_CONTABLE"] == _GROUP_SENTINEL]
        assert len(sentinels) == 1
        assert sentinels.iloc[0]["DESCRIPCION"] == "Sin clasificar"

    def test_multiple_value_cols(self):
        df = _make_efectivo_df(value_cols=("JAN", "DEC"))
        result = _inject_efectivo_groups(df, ["JAN", "DEC"])
        assert list(result.columns) == list(df.columns)
        assert result.iloc[-1]["CUENTA_CONTABLE"].strip().upper() == "TOTAL"
