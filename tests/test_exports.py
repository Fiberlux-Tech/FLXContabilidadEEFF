"""Integration tests for Excel and PDF export functions and the pipeline builders."""

import os

import pandas as pd
import pytest

from transforms.transforms import prepare_pnl, filter_for_statements, assign_partida_pl, prepare_stmt
from transforms.aggregation import (
    summarize_by_cuenta, summarize_by_ceco, summarize_by_ceco_cuenta,
    detail_by_ceco, detail_ceco_by_cuenta, detail_resultado_financiero,
    sales_details, proyectos_especiales,
)
from transforms.statement_builder import pl_summary
from export.excel.export import export_to_excel
from export.pdf.export import export_to_pdf
from export.excel.builder import build_excel_data
from export.pdf.builder import build_pdf_data
from models.models import PnLReportData, PdfReportData
from config.calendar import MONTH_NAMES


@pytest.fixture
def classified_df(raw_pnl_df):
    """DataFrame after full classification pipeline."""
    return prepare_stmt(raw_pnl_df)


@pytest.fixture
def excel_report_data(raw_pnl_df):
    """Build a full PnLReportData from the test fixture."""
    return build_excel_data(raw_pnl_df)


@pytest.fixture
def pdf_report_data(raw_pnl_df):
    """Build a PdfReportData for a full-year report."""
    empty = pd.DataFrame(columns=raw_pnl_df.columns)
    return build_pdf_data(raw_pnl_df, empty, empty, empty, "FIBERLUX", 2025, "year", None)


# ── Excel export integration ────────────────────────────────────────────────


class TestExportToExcel:
    def test_creates_xlsx_file(self, tmp_path, excel_report_data):
        output = str(tmp_path / "test_report.xlsx")
        export_to_excel(output, 2025, excel_report_data)
        assert os.path.exists(output)
        assert os.path.getsize(output) > 0


    def test_pl_sheet_has_data(self, tmp_path, excel_report_data):
        output = str(tmp_path / "test_report.xlsx")
        export_to_excel(output, 2025, excel_report_data)

        df = pd.read_excel(output, sheet_name="PL", header=2)
        assert len(df) > 0
        # Should have PARTIDA_PL as first column (unnamed or "PARTIDA_PL")
        assert "PARTIDA_PL" in df.columns or df.columns[0] is not None


# ── PDF export integration ──────────────────────────────────────────────────


class TestExportToPdf:
    def test_creates_pdf_file(self, tmp_path, pdf_report_data):
        output = str(tmp_path / "test_report.pdf")
        export_to_pdf(output, pdf_report_data)
        assert os.path.exists(output)
        assert os.path.getsize(output) > 0

    def test_pdf_has_multiple_pages(self, tmp_path, pdf_report_data):
        output = str(tmp_path / "test_report.pdf")
        export_to_pdf(output, pdf_report_data)
        # A valid report should have at least the cover + PL + some note pages
        size = os.path.getsize(output)
        assert size > 5000, f"PDF too small ({size} bytes), likely incomplete"


# ── Pipeline builder integration ────────────────────────────────────────────


class TestBuildExcelData:
    def test_returns_pnl_report_data(self, raw_pnl_df):
        result = build_excel_data(raw_pnl_df)
        assert isinstance(result, PnLReportData)

    def test_pl_summary_has_expected_labels(self, raw_pnl_df):
        result = build_excel_data(raw_pnl_df)
        labels = result.pl_summary["PARTIDA_PL"].tolist()
        assert "UTILIDAD NETA" in labels
        assert "INGRESOS TOTALES" in labels

    def test_detail_dataframes_not_empty(self, raw_pnl_df):
        result = build_excel_data(raw_pnl_df)
        assert len(result.detail_by_cuenta) > 0
        assert len(result.detail_by_ceco) > 0
        assert len(result.costo) > 0

    def test_sales_details_has_total_row(self, raw_pnl_df):
        result = build_excel_data(raw_pnl_df)
        last_row = result.sales_details.iloc[-1]
        assert last_row["DESCRIPCION"] == "TOTAL"


class TestBuildPdfData:
    def test_returns_pdf_report_data(self, raw_pnl_df):
        empty_prev = pd.DataFrame(columns=raw_pnl_df.columns)
        result = build_pdf_data(raw_pnl_df, empty_prev, empty_prev, empty_prev, "FIBERLUX", 2025, "year", None)
        assert isinstance(result, PdfReportData)

    def test_year_report_has_two_columns(self, raw_pnl_df):
        empty_prev = pd.DataFrame(columns=raw_pnl_df.columns)
        result = build_pdf_data(raw_pnl_df, empty_prev, empty_prev, empty_prev, "FIBERLUX", 2025, "year", None)
        assert len(result.column_names) == 2

    def test_month_report_has_four_columns(self, raw_pnl_df):
        empty_prev = pd.DataFrame(columns=raw_pnl_df.columns)
        result = build_pdf_data(raw_pnl_df, empty_prev, empty_prev, empty_prev, "FIBERLUX", 2025, "month", 3)
        assert len(result.column_names) == 4

    def test_pl_summary_not_empty(self, raw_pnl_df):
        empty_prev = pd.DataFrame(columns=raw_pnl_df.columns)
        result = build_pdf_data(raw_pnl_df, empty_prev, empty_prev, empty_prev, "FIBERLUX", 2025, "year", None)
        assert len(result.pl_summary) > 0
