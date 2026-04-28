"""Source of truth for view IDs used by the permissions system.

Mirrors `frontend/src/config/viewRegistry.ts`. Drift is caught by the
`_verify_sync_with_frontend` check at module import (best-effort: skipped
silently if the TS file isn't reachable, e.g. in production deploys without
the frontend tree).
"""

import os
import re

ALL_VIEW_IDS: frozenset[str] = frozenset({
    # Estado de Resultados
    'pl', 'ingresos', 'costo', 'gasto_venta', 'gasto_admin',
    'otros_egresos', 'dya', 'resultado_financiero', 'diferencia_cambio',
    # Balance General
    'bs', 'bs_efectivo', 'bs_cxc_comerciales', 'bs_cxc_otras', 'bs_cxc_relacionadas',
    'bs_ppe', 'bs_otros_activos', 'bs_cxp_comerciales', 'bs_cxp_otras', 'bs_cxp_relacionadas',
    'bs_provisiones', 'bs_tributos',
    # Reportes Variados
    'analysis_pl_finanzas', 'analysis_planilla', 'analysis_proveedores', 'analysis_flujo_caja',
    # Carga de Datos
    'upload_planilla',
    # Administración
    'admin_users',
})


def _verify_sync_with_frontend() -> None:
    """Compare ALL_VIEW_IDS with the IDs declared in viewRegistry.ts.

    No-op if the TS file isn't found (the backend can ship without the
    frontend tree). Raises AssertionError if they're out of sync — this
    fires at module import so misalignment is caught before any request.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    ts_path = os.path.abspath(os.path.join(
        here, '..', '..', 'frontend', 'src', 'config', 'viewRegistry.ts'
    ))
    if not os.path.isfile(ts_path):
        return
    try:
        with open(ts_path, encoding='utf-8') as f:
            text = f.read()
    except OSError:
        return
    # Match: { id: 'foo', ... }
    ts_ids = set(re.findall(r"id:\s*'([a-z_][a-z0-9_]*)'", text))
    if not ts_ids:
        return  # parsing failed; don't block startup
    py_ids = set(ALL_VIEW_IDS)
    missing_in_py = ts_ids - py_ids
    missing_in_ts = py_ids - ts_ids
    if missing_in_py or missing_in_ts:
        raise AssertionError(
            "View ID drift between viewRegistry.ts and backend/config/views.py.\n"
            f"  Only in TS: {sorted(missing_in_py)}\n"
            f"  Only in PY: {sorted(missing_in_ts)}\n"
            "Update both files to match."
        )


_verify_sync_with_frontend()
