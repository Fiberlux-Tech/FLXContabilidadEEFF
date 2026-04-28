"""API routes — data loading, report exports, file downloads."""

import os
import functools
import logging
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from flask import Blueprint, jsonify, request, send_file, session

from auth import login_required, view_required, any_view_required, admin_required, require_view_or_403
from helpers import ok, error
from config.views import ALL_VIEW_IDS
from config.calendar import MONTH_NAMES_SET, MIN_YEAR
from config.company import VALID_COMPANIES, COMPANY_META, CONSOLIDADO
from config.fields import (
    CUENTA_CONTABLE, DESCRIPCION, NIT, RAZON_SOCIAL,
    CENTRO_COSTO, DESC_CECO,
)
from config.exceptions import (
    RequestValidationError, PlantillasError, QueryError,
    ExportError, DataValidationError,
)
from config.settings import get_config
from data_service import (
    load_report_data, load_pl_data, load_bs_data, load_pl_section,
    get_detail_records, get_raw_cached, get_bs_cached, get_cache_stats,
    VALID_PL_SECTIONS,
)
from pipeline import run_report
from headcount_service import (
    load_headcount, load_headcount_ym, save_headcount_csv, get_roster_detail,
)

api_bp = Blueprint('api', __name__)
logger = logging.getLogger('flxcontabilidad.routes')

# Drift guard: every PL section name must be a known view ID. Fails loudly
# at module import if SECTION_REGISTRY adds a section that isn't a view.
_unknown_sections = set(VALID_PL_SECTIONS) - set(ALL_VIEW_IDS)
assert not _unknown_sections, (
    f"VALID_PL_SECTIONS contains unknown view IDs: {_unknown_sections}. "
    f"Add them to backend/config/views.py and frontend/src/config/viewRegistry.ts."
)
del _unknown_sections

# In-memory map of generated export filename -> owning user_id. Populated by
# the export handler, checked by the download handler. Not persisted — a
# server restart drops the map and previously-generated files become
# undownloadable, which is acceptable (users can regenerate).
_export_owners: dict[str, int] = {}
_export_owners_lock = threading.Lock()


@api_bp.errorhandler(RequestValidationError)
def handle_validation_error(exc):
    return error(str(exc), exc.status_code)


def _validate_company_year(body: dict) -> tuple[str, int]:
    """Extract and validate company/year from request body.

    Returns (company, year) or raises RequestValidationError.
    """
    company = body.get('company', '').strip().upper()
    year = body.get('year')

    if company not in VALID_COMPANIES:
        raise RequestValidationError(f'Empresa invalida: {company}')
    if not isinstance(year, int) or year < MIN_YEAR or year > datetime.now().year + 1:
        raise RequestValidationError('Ano invalido')

    return company, year


@api_bp.route('/companies', methods=['GET'])
@login_required
def get_companies():
    """Return list of valid companies with metadata."""
    return ok(COMPANY_META)


@api_bp.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})


@api_bp.route('/cache-stats', methods=['GET'])
@admin_required
def cache_stats():
    """Return cache hit/miss counters and entry counts per store."""
    return ok(get_cache_stats())


# ── Shared error handling ──────────────────────────────────────────────

def _handle_data_errors(label: str):
    """Decorator that wraps a route handler with standard data-error handling.

    The wrapped function receives ``(body, company, year)`` — body is already
    parsed and company/year already validated.  ``label`` appears in log
    messages (e.g. "loading data", "loading P&L").
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            body = request.get_json(silent=True) or {}
            company, year = _validate_company_year(body)
            try:
                return fn(body, company, year)
            except RequestValidationError:
                # Let the blueprint errorhandler format this as a 400 with
                # the real message instead of masking it as a 500.
                raise
            except (ValueError, KeyError) as exc:
                return error(str(exc), 400)
            except (QueryError, DataValidationError) as exc:
                logger.exception("Data error %s %s/%s", label, company, year)
                return error(str(exc), 500)
            except PlantillasError as exc:
                logger.exception("Error %s %s/%s", label, company, year)
                return error('Error interno del servidor', 500)
        return wrapper
    return decorator


def _timed_load(service_fn, body, company, year):
    """Call a data-loading service function with timing."""
    force_refresh = body.get('force_refresh', False)
    t0 = time.perf_counter()
    data = service_fn(company, year, force_refresh=force_refresh)
    result = {k: v for k, v in data.items() if not k.startswith('_')}
    result['_timing_ms'] = round((time.perf_counter() - t0) * 1000)
    return ok(result)


# ── Data loading ────────────────────────────────────────────────────────

@api_bp.route('/data/load', methods=['POST'])
@any_view_required(['pl', 'bs'])
@_handle_data_errors("loading data")
def load_data(body, company, year):
    """Fetch and transform all report data for a company/year.

    Body: { "company": "FIBERLUX", "year": 2026 }
    Optional: { "force_refresh": true }
    """
    if company == CONSOLIDADO:
        raise RequestValidationError('Use load-pl y load-bs para vista consolidada')
    return _timed_load(load_report_data, body, company, year)


@api_bp.route('/data/load-pl', methods=['POST'])
@view_required('pl')
@_handle_data_errors("loading P&L")
def load_pl(body, company, year):
    """Fetch P&L data only (fast path). BS is pre-fetched in the background.

    Body: { "company": "FIBERLUX", "year": 2026 }
    Optional: { "force_refresh": true }
    """
    return _timed_load(load_pl_data, body, company, year)


@api_bp.route('/data/load-bs', methods=['POST'])
@view_required('bs')
@_handle_data_errors("loading BS")
def load_bs(body, company, year):
    """Fetch BS data. Requires P&L to be loaded first (for UTILIDAD NETA).

    Body: { "company": "FIBERLUX", "year": 2026 }
    Optional: { "force_refresh": true }
    """
    return _timed_load(load_bs_data, body, company, year)


@api_bp.route('/data/pl-section', methods=['POST'])
@login_required
@_handle_data_errors("loading P&L section")
def load_pl_section_route(body, company, year):
    """Compute a specific P&L detail section on demand.

    Body: { "company": "FIBERLUX", "year": 2026, "section": "ingresos" }
    Optional for analysis_proveedores: { "ceco": "100.113.01" }
    """
    section = (body.get('section') or '').strip()
    if not section or section not in VALID_PL_SECTIONS:
        raise RequestValidationError(
            f'Seccion invalida: {section!r}. Validas: {sorted(VALID_PL_SECTIONS)}')

    # Section names are 1:1 with view IDs (asserted at module import).
    forbidden = require_view_or_403(section)
    if forbidden is not None:
        return forbidden

    force_refresh = body.get('force_refresh', False)

    # Extra params for specific sections
    extra = {}
    if section == 'analysis_proveedores':
        ceco = (body.get('ceco') or '').strip()
        if ceco:
            from accounting.aggregation import ALLOWED_PROVEEDORES_CECOS
            if ceco not in ALLOWED_PROVEEDORES_CECOS:
                raise RequestValidationError(
                    f'CECO invalido: {ceco!r}. Validos: {ALLOWED_PROVEEDORES_CECOS}')
            extra['ceco'] = ceco

    t0 = time.perf_counter()
    data = load_pl_section(company, year, section, force_refresh=force_refresh, **extra)
    result = {**data, '_timing_ms': round((time.perf_counter() - t0) * 1000)}
    return ok(result)


# ── Detail drill-down ──────────────────────────────────────────────────

_ALLOWED_FILTER_COLS = {
    CUENTA_CONTABLE, DESCRIPCION, NIT, RAZON_SOCIAL,
    CENTRO_COSTO, DESC_CECO,
}


@api_bp.route('/data/detail', methods=['POST'])
@login_required
@_handle_data_errors("getting detail")
def get_detail(body, company, year):
    """Return raw journal entries for a specific cell in a P&L view.

    Body: { "company": "FIBERLUX", "year": 2026,
            "view_id": "ingresos",
            "partida": "INGRESOS ORDINARIOS", "month": "JAN",
            "filter_col": "CUENTA_CONTABLE", "filter_val": "7011101" }
    """
    view_id = (body.get('view_id') or '').strip()
    if not view_id:
        raise RequestValidationError('view_id es requerido')
    if view_id not in ALL_VIEW_IDS:
        raise RequestValidationError(f'view_id invalido: {view_id}')
    forbidden = require_view_or_403(view_id)
    if forbidden is not None:
        return forbidden

    partida = body.get('partida', '').strip()
    month = body.get('month', '').strip().upper() if body.get('month') else None
    filter_col = body.get('filter_col')
    filter_val = body.get('filter_val')
    ic_filter = body.get('ic_filter', 'all')

    if month and month not in MONTH_NAMES_SET:
        raise RequestValidationError(f'Mes invalido: {month}')

    if filter_col and filter_col not in _ALLOWED_FILTER_COLS:
        raise RequestValidationError(f'Columna de filtro no permitida: {filter_col}')

    if not partida:
        raise RequestValidationError('partida es requerido')

    if ic_filter not in ('all', 'ex_ic', 'only_ic'):
        raise RequestValidationError(f'ic_filter invalido: {ic_filter}')

    records = get_detail_records(company, year, partida, month,
                                 filter_col=filter_col, filter_val=filter_val,
                                 ic_filter=ic_filter)
    return ok({'records': records})


# ── Exports ─────────────────────────────────────────────────────────────

def _run_export(company: str, year: int, excel_only: bool = False) -> dict:
    """Run the export pipeline and return file paths.

    Attempts to reuse cached raw DataFrames from a prior dashboard load,
    eliminating redundant SQL Server round-trips.
    """
    cfg = get_config()
    output_dir = cfg.output_dir

    # Reuse cached data from prior dashboard load if available
    cached_raw = get_raw_cached(company, year)
    cached_bs = get_bs_cached(company, year)

    excel_path, pdf_path = run_report(
        company, year, None, None,
        "year", None,
        excel_only=excel_only,
        output_dir=output_dir,
        cached_raw=cached_raw,
        cached_bs_prepared=cached_bs,
    )
    result = {}
    if excel_path:
        result['excel'] = os.path.basename(excel_path)
    if pdf_path:
        result['pdf'] = os.path.basename(pdf_path)
    return result


_EXPORT_TYPE_MAP = {
    'excel': True,   # excel_only=True
    'pdf':   False,  # excel_only=False
    'all':   False,  # excel_only=False
}


def _export_handler(export_type: str):
    """Shared logic for all export endpoints."""
    body = request.get_json(silent=True) or {}

    company, year = _validate_company_year(body)

    if company == CONSOLIDADO:
        raise RequestValidationError('Exportacion no disponible para vista consolidada')

    try:
        result = _run_export(company, year, excel_only=_EXPORT_TYPE_MAP[export_type])
        # Track ownership of generated files so other users can't download them.
        user_id = session.get('user_id')
        if user_id is not None:
            with _export_owners_lock:
                for fname in result.values():
                    _export_owners[fname] = user_id
        return ok(result)
    except FileNotFoundError:
        return error('Archivo de reporte no encontrado', 404)
    except ExportError as exc:
        logger.exception("Export error during %s for %s/%s", export_type, company, year)
        return error(str(exc), 500)
    except OSError as exc:
        logger.exception("OS error during %s export for %s/%s", export_type, company, year)
        return error('Error de sistema de archivos', 500)
    except PlantillasError as exc:
        logger.exception("Error exporting %s for %s/%s", export_type, company, year)
        return error('Error interno del servidor', 500)


@api_bp.route('/export/excel', methods=['POST'])
@any_view_required(['pl', 'bs'])
def export_excel():
    """Generate Excel report and return download filename."""
    return _export_handler('excel')


@api_bp.route('/export/pdf', methods=['POST'])
@any_view_required(['pl', 'bs'])
def export_pdf():
    """Generate PDF report and return download filename."""
    return _export_handler('pdf')


@api_bp.route('/export/all', methods=['POST'])
@any_view_required(['pl', 'bs'])
def export_all():
    """Generate both Excel and PDF reports."""
    return _export_handler('all')


@api_bp.route('/export/download/<filename>', methods=['GET'])
@login_required
def download_file(filename):
    """Download a generated report file. Only the user who generated the
    file (or an admin) can download it.
    """
    cfg = get_config()

    # Sanitize: only allow basename, no path traversal
    safe_name = os.path.basename(filename)
    filepath = os.path.join(cfg.output_dir, safe_name)

    # Defense-in-depth: ensure resolved path stays within output_dir
    real_output = os.path.realpath(cfg.output_dir)
    real_file = os.path.realpath(filepath)
    if not real_file.startswith(real_output + os.sep):
        return error('Acceso denegado', 403)

    # Ownership check — admins bypass; everyone else must own the file.
    if not session.get('is_admin'):
        with _export_owners_lock:
            owner_id = _export_owners.get(safe_name)
        if owner_id != session.get('user_id'):
            return error('Acceso denegado', 403)

    if not os.path.isfile(filepath):
        return error('Archivo no encontrado', 404)

    return send_file(filepath, as_attachment=True, download_name=safe_name)


# ── Headcount ──────────────────────────────────────────────────────────

def _hc_db_path() -> str:
    from flask import current_app
    return current_app.config['HEADCOUNT_DB_PATH']


def _validate_company_query() -> tuple[str, int]:
    """Validate company/year from query string parameters."""
    company = (request.args.get('company') or '').strip().upper()
    if company not in VALID_COMPANIES:
        raise RequestValidationError(f'Empresa invalida: {company}')
    try:
        year = int(request.args.get('year', ''))
    except (ValueError, TypeError):
        raise RequestValidationError('Ano invalido')
    if year < MIN_YEAR or year > datetime.now().year + 1:
        raise RequestValidationError('Ano invalido')
    return company, year


@api_bp.route('/headcount', methods=['GET'])
@view_required('analysis_planilla')
def get_headcount():
    """Return headcount map for a company/year.

    Query: ?company=FIBERLINE&year=2025
    """
    company, year = _validate_company_query()
    data = load_headcount(_hc_db_path(), company, year)
    return ok({'headcount': data})


@api_bp.route('/headcount/ym', methods=['GET'])
@view_required('analysis_planilla')
def get_headcount_ym():
    """Return headcount map keyed by year_month integers.

    Query: ?company=FIBERLINE&years=2025,2026
    Returns: { headcount: { "100.101.00": { "202501": 22, ... } } }
    """
    company = (request.args.get('company') or '').strip().upper()
    if company not in VALID_COMPANIES:
        raise RequestValidationError(f'Empresa invalida: {company}')
    years_raw = (request.args.get('years') or '').strip()
    if not years_raw:
        raise RequestValidationError('Parametro years es requerido')
    try:
        years = [int(y) for y in years_raw.split(',')]
    except ValueError:
        raise RequestValidationError('Formato de years invalido')
    now_year = datetime.now().year
    for y in years:
        if y < MIN_YEAR or y > now_year + 1:
            raise RequestValidationError(f'Ano invalido: {y}')

    data = load_headcount_ym(_hc_db_path(), company, years)
    return ok({'headcount': data})


@api_bp.route('/admin/headcount/upload', methods=['POST'])
@view_required('upload_planilla')
def upload_headcount_csv():
    """Upload an employee-roster CSV to compute and store headcount per CECO.

    Multipart form: file=<csv>, company=FIBERLINE (optional — if omitted,
    processes all non-ROP companies found in the file).
    """
    company_raw = (request.form.get('company') or '').strip().upper()
    company = company_raw if company_raw in VALID_COMPANIES else None

    file = request.files.get('file')
    if file is None:
        raise RequestValidationError('Archivo CSV es requerido')

    try:
        csv_content = file.read().decode('utf-8-sig')
    except UnicodeDecodeError:
        raise RequestValidationError('Archivo debe ser UTF-8 o CSV valido')

    try:
        count = save_headcount_csv(_hc_db_path(), company, csv_content)
    except ValueError as exc:
        raise RequestValidationError(str(exc))

    return ok({'saved': count})


@api_bp.route('/headcount/roster', methods=['GET'])
@view_required('analysis_planilla')
def get_roster():
    """Return individual employees for a company/CECO/month.

    Query params: company, centro_costo, year_month
    """
    company = (request.args.get('company') or '').strip().upper()
    if company not in VALID_COMPANIES:
        raise RequestValidationError(f'Empresa invalida: {company}')
    if company == CONSOLIDADO:
        raise RequestValidationError('Detalle de planilla no disponible para vista consolidada')

    centro_costo = (request.args.get('centro_costo') or '').strip()
    if not centro_costo:
        raise RequestValidationError('centro_costo es requerido')

    try:
        year_month = int(request.args.get('year_month', ''))
    except (ValueError, TypeError):
        raise RequestValidationError('year_month es requerido (entero YYYYMM)')

    employees = get_roster_detail(_hc_db_path(), company, centro_costo, year_month)
    return ok({'employees': employees})
