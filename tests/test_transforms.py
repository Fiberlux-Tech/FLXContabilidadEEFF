import pandas as pd
import pytest

from transforms import (
    prepare_pnl, filter_for_statements, assign_partida_pl,
    prepare_stmt, get_excluded_cuentas,
)
from account_rules import EXCLUDED_CUENTA


class TestPreparePnl:
    def test_adds_expected_columns(self, raw_pnl_df):
        result = prepare_pnl(raw_pnl_df)
        assert "SALDO" in result.columns
        assert "MES" in result.columns

    def test_saldo_is_credit_minus_debit(self, raw_pnl_df):
        result = prepare_pnl(raw_pnl_df)
        row = result.iloc[0]
        assert row["SALDO"] == row["CREDITO_LOCAL"] - row["DEBITO_LOCAL"]

    def test_preserves_already_trimmed_values(self):
        """Whitespace trimming is handled in SQL (LTRIM/RTRIM in queries.py).
        _clean_columns no longer strips — verify pre-trimmed values pass through."""
        df = pd.DataFrame({
            "CIA": ["X"], "CUENTA_CONTABLE": ["70.1"], "DESCRIPCION": ["test"],
            "NIT": ["1"], "RAZON_SOCIAL": ["A"], "CENTRO_COSTO": ["2100"],
            "DESC_CECO": ["B"], "FECHA": ["2025-01-01"],
            "DEBITO_LOCAL": [0], "CREDITO_LOCAL": [100],
        })
        result = prepare_pnl(df)
        assert result.iloc[0]["CUENTA_CONTABLE"] == "70.1"
        assert result.iloc[0]["CENTRO_COSTO"] == "2100"

    def test_mes_extracted_from_fecha(self, raw_pnl_df):
        result = prepare_pnl(raw_pnl_df)
        march_rows = result[result["FECHA"].dt.month == 3]
        assert (march_rows["MES"] == 3).all()

    def test_does_not_mutate_input(self, raw_pnl_df):
        original_cols = list(raw_pnl_df.columns)
        prepare_pnl(raw_pnl_df)
        assert list(raw_pnl_df.columns) == original_cols


class TestFilterForStatements:
    def test_excludes_low_accounts(self, raw_pnl_df):
        df = prepare_pnl(raw_pnl_df)
        result = filter_for_statements(df)
        prefixes = pd.to_numeric(result["CUENTA_CONTABLE"].str[:4], errors="coerce")
        assert (prefixes >= 61.9).all()

    def test_excludes_cuenta_79(self, raw_pnl_df):
        df = prepare_pnl(raw_pnl_df)
        result = filter_for_statements(df)
        assert EXCLUDED_CUENTA not in result["CUENTA_CONTABLE"].values

    def test_keeps_valid_accounts(self, raw_pnl_df):
        df = prepare_pnl(raw_pnl_df)
        result = filter_for_statements(df)
        assert len(result) > 0
        assert "70.1.1.1.01" in result["CUENTA_CONTABLE"].values


class TestAssignPartidaPl:
    def test_all_rows_labelled(self, raw_pnl_df):
        df = prepare_pnl(raw_pnl_df)
        df = filter_for_statements(df)
        result = assign_partida_pl(df)
        assert result["PARTIDA_PL"].notna().all()

    def test_ingresos_ordinarios(self, raw_pnl_df):
        df = prepare_pnl(raw_pnl_df)
        df = filter_for_statements(df)
        result = assign_partida_pl(df)
        row = result[result["CUENTA_CONTABLE"] == "70.1.1.1.01"]
        assert row.iloc[0]["PARTIDA_PL"] == "INGRESOS ORDINARIOS"

    def test_costo(self, raw_pnl_df):
        df = prepare_pnl(raw_pnl_df)
        df = filter_for_statements(df)
        result = assign_partida_pl(df)
        row = result[result["CUENTA_CONTABLE"] == "62.1.1.1.01"]
        assert row.iloc[0]["PARTIDA_PL"] == "COSTO"

    def test_gasto_venta(self, raw_pnl_df):
        df = prepare_pnl(raw_pnl_df)
        df = filter_for_statements(df)
        result = assign_partida_pl(df)
        row = result[result["CUENTA_CONTABLE"] == "63.1.1.1.01"]
        assert row.iloc[0]["PARTIDA_PL"] == "GASTO VENTA"

    def test_gasto_admin(self, raw_pnl_df):
        df = prepare_pnl(raw_pnl_df)
        df = filter_for_statements(df)
        result = assign_partida_pl(df)
        row = result[result["CUENTA_CONTABLE"] == "63.2.1.1.01"]
        assert row.iloc[0]["PARTIDA_PL"] == "GASTO ADMIN"

    def test_dya_costo(self, raw_pnl_df):
        df = prepare_pnl(raw_pnl_df)
        df = filter_for_statements(df)
        result = assign_partida_pl(df)
        row = result[result["CUENTA_CONTABLE"] == "68.1.1.1.01"]
        assert row.iloc[0]["PARTIDA_PL"] == "D&A - COSTO"

    def test_dya_gasto(self, raw_pnl_df):
        df = prepare_pnl(raw_pnl_df)
        df = filter_for_statements(df)
        result = assign_partida_pl(df)
        row = result[result["CUENTA_CONTABLE"] == "68.0.1.1.01"]
        assert row.iloc[0]["PARTIDA_PL"] == "D&A - GASTO"

    def test_resultado_financiero(self, raw_pnl_df):
        df = prepare_pnl(raw_pnl_df)
        df = filter_for_statements(df)
        result = assign_partida_pl(df)
        row67 = result[result["CUENTA_CONTABLE"] == "67.1.1.1.01"]
        assert row67.iloc[0]["PARTIDA_PL"] == "RESULTADO FINANCIERO"
        row77 = result[result["CUENTA_CONTABLE"] == "77.1.1.1.01"]
        assert row77.iloc[0]["PARTIDA_PL"] == "RESULTADO FINANCIERO"

    def test_impuesto_renta(self, raw_pnl_df):
        df = prepare_pnl(raw_pnl_df)
        df = filter_for_statements(df)
        result = assign_partida_pl(df)
        row = result[result["CUENTA_CONTABLE"] == "88.1.1.1.01"]
        assert row.iloc[0]["PARTIDA_PL"] == "IMPUESTO A LA RENTA"

    def test_por_definir_for_unknown(self):
        df = pd.DataFrame({
            "CIA": ["X"], "CUENTA_CONTABLE": ["99.9.9.9.99"], "DESCRIPCION": ["Unknown"],
            "NIT": ["0"], "RAZON_SOCIAL": ["N/A"], "CENTRO_COSTO": ["9999"],
            "DESC_CECO": ["Unknown"], "FECHA": ["2025-01-01"],
            "DEBITO_LOCAL": [100], "CREDITO_LOCAL": [0],
        })
        df = prepare_pnl(df)
        df = filter_for_statements(df)
        if len(df) > 0:
            result = assign_partida_pl(df)
            assert "POR DEFINIR" in result["PARTIDA_PL"].values

    def test_first_char_column_removed(self, raw_pnl_df):
        df = prepare_pnl(raw_pnl_df)
        df = filter_for_statements(df)
        result = assign_partida_pl(df)
        assert "FIRST_CHAR" not in result.columns


class TestPrepareStmt:
    def test_pipeline(self, raw_pnl_df):
        result = prepare_stmt(raw_pnl_df)
        assert "PARTIDA_PL" in result.columns
        assert "SALDO" in result.columns
        assert EXCLUDED_CUENTA not in result["CUENTA_CONTABLE"].values


class TestGetExcludedCuentas:
    def test_returns_excluded(self, raw_pnl_df):
        df = prepare_pnl(raw_pnl_df)
        df_stmt = filter_for_statements(df)
        excluded = get_excluded_cuentas(df, df_stmt)
        assert isinstance(excluded, set)
        assert len(excluded) > 0
        # Low accounts and 79.1.1.1.01 should be excluded
        assert "60.1.1.1.01" in excluded
        assert EXCLUDED_CUENTA in excluded
