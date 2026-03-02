import pandas as pd
import pytest

from transforms import prepare_pnl, filter_for_statements, assign_partida_pl
from aggregation import (
    summarize_by_cuenta, summarize_by_ceco,
    append_total_row, detail_resultado_financiero, sales_details,
    detail_by_ceco,
)
from statement_builder import pl_summary
from calendar_config import MONTH_NAMES_SET


@pytest.fixture
def classified_df(raw_pnl_df):
    """DataFrame after full classification pipeline."""
    df = prepare_pnl(raw_pnl_df)
    df = filter_for_statements(df)
    return assign_partida_pl(df)


class TestSummarizeByCuenta:
    def test_has_total_column(self, raw_pnl_df):
        df = prepare_pnl(raw_pnl_df)
        result = summarize_by_cuenta(df)
        assert "TOTAL" in result.columns

    def test_has_month_columns(self, raw_pnl_df):
        df = prepare_pnl(raw_pnl_df)
        result = summarize_by_cuenta(df)
        month_cols = [c for c in result.columns if c in MONTH_NAMES_SET]
        assert len(month_cols) > 0

    def test_index_columns(self, raw_pnl_df):
        df = prepare_pnl(raw_pnl_df)
        result = summarize_by_cuenta(df)
        assert "CUENTA_CONTABLE" in result.columns
        assert "DESCRIPCION" in result.columns


class TestSummarizeByCeco:
    def test_has_total_column(self, raw_pnl_df):
        df = prepare_pnl(raw_pnl_df)
        result = summarize_by_ceco(df)
        assert "TOTAL" in result.columns
        assert "CENTRO_COSTO" in result.columns
        assert "DESC_CECO" in result.columns


class TestPlSummary:
    def test_structure(self, classified_df):
        result = pl_summary(classified_df)
        assert "PARTIDA_PL" in result.columns
        labels = result["PARTIDA_PL"].tolist()
        assert "INGRESOS TOTALES" in labels
        assert "UTILIDAD BRUTA" in labels
        assert "UTILIDAD OPERATIVA" in labels
        assert "UTILIDAD ANTES DE IMPUESTO A LA RENTA" in labels
        assert "UTILIDAD NETA" in labels

    def test_has_value_columns(self, classified_df):
        result = pl_summary(classified_df)
        assert "TOTAL" in result.columns


class TestAppendTotalRow:
    def test_adds_total(self):
        df = pd.DataFrame({
            "DESC_CECO": ["A", "B"],
            "JAN": [100, 200],
            "FEB": [50, 75],
        })
        result = append_total_row(df, "DESC_CECO")
        assert len(result) == 3
        total_row = result.iloc[-1]
        assert total_row["DESC_CECO"] == "TOTAL"
        assert total_row["JAN"] == 300
        assert total_row["FEB"] == 125

    def test_preserves_original_rows(self):
        df = pd.DataFrame({
            "DESCRIPCION": ["X"],
            "TOTAL": [42],
        })
        result = append_total_row(df, "DESCRIPCION")
        assert result.iloc[0]["DESCRIPCION"] == "X"
        assert result.iloc[0]["TOTAL"] == 42


class TestDetailResultadoFinanciero:
    def test_splits_ingresos_gastos(self, classified_df):
        result = detail_resultado_financiero(classified_df)
        assert hasattr(result, "ingresos")
        assert hasattr(result, "gastos")

    def test_ingresos_has_77_accounts(self, classified_df):
        result = detail_resultado_financiero(classified_df)
        if len(result.ingresos) > 1:  # More than just TOTAL row
            non_total = result.ingresos[result.ingresos["DESCRIPCION"] != "TOTAL"]
            assert all(
                str(c).startswith("77")
                for c in non_total["CUENTA_CONTABLE"]
            )

    def test_gastos_no_77_accounts(self, classified_df):
        result = detail_resultado_financiero(classified_df)
        if len(result.gastos) > 1:
            non_total = result.gastos[result.gastos["DESCRIPCION"] != "TOTAL"]
            assert all(
                not str(c).startswith("77")
                for c in non_total["CUENTA_CONTABLE"]
            )


class TestSalesDetails:
    def test_filters_ingresos_ordinarios(self, classified_df):
        result = sales_details(classified_df)
        assert len(result) > 0
        assert "TOTAL" in result.columns


class TestWithTotalRow:
    """Verify with_total_row=True produces a TOTAL row from public pivot functions."""

    def test_detail_by_ceco_with_total(self, classified_df):
        result = detail_by_ceco(classified_df, ["COSTO"], ascending=True, with_total_row=True)
        assert len(result) > 0
        assert result.iloc[-1]["DESC_CECO"] == "TOTAL"

    def test_detail_by_ceco_without_total(self, classified_df):
        result = detail_by_ceco(classified_df, ["COSTO"], ascending=True)
        if len(result) > 0:
            assert result.iloc[-1]["DESC_CECO"] != "TOTAL"

    def test_sales_details_with_total(self, classified_df):
        result = sales_details(classified_df, with_total_row=True)
        assert len(result) > 0
        assert result.iloc[-1]["DESCRIPCION"] == "TOTAL"

    def test_sales_details_without_total(self, classified_df):
        result = sales_details(classified_df)
        if len(result) > 0:
            assert result.iloc[-1]["DESCRIPCION"] != "TOTAL"
