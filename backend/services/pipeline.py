"""Pipeline orchestrator — fetches data, builds reports, exports files."""

import logging
import os
import time
from datetime import datetime

import pandas as pd  # noqa: E402

pd.set_option("mode.copy_on_write", True)

from config.calendar import MONTH_NAMES
from config.exceptions import ExportError
from accounting.transforms import prepare_bs_stmt
from data.fetcher import fetch_all_data
from excel.builder import build_excel_data, build_bs_data
from pdf.builder import build_pdf_data
from excel.export import export_to_excel
from pdf.export import export_to_pdf

logger = logging.getLogger("plantillas.pipeline")


def period_label(month: int | None, quarter: int | None) -> str:
    """Return a consistent filename-safe period label for both Excel and PDF."""
    if quarter is not None:
        return f"Q{quarter}"
    elif month is not None:
        return MONTH_NAMES[month]
    else:
        return "FULL"


def generate_output_path(output_dir: str, company: str, year: int, plabel: str, timestamp: str, ext: str) -> str:
    """Build a standardized output file path."""
    return os.path.join(output_dir, f"PL_{company}_{year}_{plabel}_{timestamp}.{ext}")


def safe_export(fn: callable, path: str, label: str, *args) -> None:
    """Call *fn*(*path*, *args) with standard error handling."""
    try:
        fn(path, *args)
    except PermissionError as exc:
        raise ExportError(
            f"Cannot write to {path} — file is open in another program. Close it and retry."
        ) from exc
    except (OSError, IOError) as exc:
        raise ExportError(f"I/O error exporting {label} file: {exc}") from exc
    except ValueError as exc:
        raise ExportError(f"Data error exporting {label} file: {exc}") from exc


def _resolve_raw_data(cached_raw, need_pdf, company, year, month, conn_factory):
    """Return raw data tuple, using cache when possible or fetching from DB.

    When *cached_raw* is provided but lacks previous-year data needed for PDF,
    a full fetch is performed instead.
    """
    if cached_raw is None:
        return fetch_all_data(company, year, month, conn_factory=conn_factory, need_pdf=need_pdf)

    raw, raw_current_full, raw_prev, raw_bs, raw_bs_prev = cached_raw
    if need_pdf and raw_prev.empty and raw_bs_prev.empty:
        logger.info("Cached raw missing prev-year data; re-fetching for PDF")
        return fetch_all_data(company, year, month, conn_factory=conn_factory, need_pdf=True)

    logger.info("Using cached raw DataFrames (fetch skipped)")
    return cached_raw


def run_report(
    company: str, year: int, month: int | None, quarter: int | None,
    period_type: str, period_num: int | None, *,
    conn_factory=None,
    excel_only: bool = False, output_dir: str | None = None,
    cached_raw: tuple | None = None,
    cached_bs_prepared: pd.DataFrame | None = None,
) -> tuple[str, str | None]:
    """Core report pipeline — injectable for testing.

    Returns (excel_path, pdf_path).  *pdf_path* is None when *excel_only* is True.

    When *cached_raw* is provided as (raw, raw_current_full, raw_prev, raw_bs,
    raw_bs_prev), the DB fetch step is skipped entirely.
    """
    from config.settings import get_config
    cfg = get_config()
    if output_dir is None:
        output_dir = cfg.output_dir

    # --- Fetch data (or use cached) ---
    t0 = time.perf_counter()
    need_pdf = not excel_only
    raw, raw_current_full, raw_prev, raw_bs, raw_bs_prev = _resolve_raw_data(
        cached_raw, need_pdf, company, year, month, conn_factory,
    )
    logger.info("Fetch/cache resolve: %.2fs", time.perf_counter() - t0)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    plabel = period_label(month, quarter)
    os.makedirs(output_dir, exist_ok=True)

    # --- Prepare BS data once (reused by both Excel and PDF) ---
    if cached_bs_prepared is not None:
        df_bs_prepared = cached_bs_prepared
        logger.info("Using cached prepared BS DataFrame")
    else:
        df_bs_prepared = prepare_bs_stmt(raw_bs) if not raw_bs.empty else None

    # --- Build and export Excel first, then release its data ---
    t0 = time.perf_counter()
    report_data = build_excel_data(raw)
    build_bs_data(raw_bs, report_data.pl_summary, report_data,
                  df_bs=df_bs_prepared,
                  strict_balance=cfg.strict_bs_balance, month=month, quarter=quarter)
    del raw

    output = generate_output_path(output_dir, company, year, plabel, timestamp, "xlsx")
    safe_export(export_to_excel, output, "Excel", year, report_data)
    logger.info("Excel build+export: %.2fs", time.perf_counter() - t0)
    logger.info("Excel saved to %s", output)
    del report_data

    # --- Build and export PDF (unless excel-only) ---
    pdf_output = None
    if not excel_only:
        t0 = time.perf_counter()
        pdf_report_data = build_pdf_data(raw_current_full, raw_prev, raw_bs, raw_bs_prev, company, year, period_type, period_num,
                                         df_bs_prepared=df_bs_prepared)
        logger.info("PDF data build: %.2fs", time.perf_counter() - t0)
        del raw_current_full, raw_prev, raw_bs, raw_bs_prev

        t0 = time.perf_counter()
        pdf_output = generate_output_path(output_dir, company, year, plabel, timestamp, "pdf")
        safe_export(export_to_pdf, pdf_output, "PDF", pdf_report_data)
        logger.info("PDF export: %.2fs", time.perf_counter() - t0)
        logger.info("PDF saved to %s", pdf_output)
        del pdf_report_data
    else:
        del raw_current_full, raw_prev, raw_bs, raw_bs_prev
        logger.info("PDF generation skipped (--excel-only).")

    return output, pdf_output
