import logging

import pandas as pd

from config.exceptions import DataValidationError
from config.fields import (
    CUENTA_CONTABLE, CENTRO_COSTO, FECHA, DESCRIPCION,
    NIT, RAZON_SOCIAL, DESC_CECO, SALDO,
    PARTIDA_PL, PARTIDA_BS, SECCION_BS, MES, IS_INTERCOMPANY,
)


logger = logging.getLogger("plantillas.transforms")

_REQUIRED_COLUMNS = {
    CUENTA_CONTABLE, CENTRO_COSTO, FECHA,
    "DEBITO_LOCAL", "CREDITO_LOCAL", DESCRIPCION,
    NIT, RAZON_SOCIAL, DESC_CECO,
}


def _validate_columns(df: pd.DataFrame, required: set[str], context: str) -> None:
    """Raise DataValidationError if *df* is missing required columns or is empty."""
    if df.empty:
        raise DataValidationError(f"{context}: input DataFrame is empty")
    missing = required - set(df.columns)
    if missing:
        raise DataValidationError(f"{context}: missing columns {sorted(missing)}")


def prepare_pnl_from_view(raw_df: pd.DataFrame) -> pd.DataFrame:
    """Lightweight shape adapter for rows coming from VISTA_PNL_PREPARADO.

    The view already supplies SALDO, MES, PARTIDA_PL, and IS_INTERCOMPANY,
    so this function only fixes dtypes and applies the category encoding
    that downstream aggregation expects.

    If the input carries an IS_STATEMENT_ELIGIBLE column (eligible_only=False
    was passed to fetch_pnl_data), this function returns the *full* set
    unchanged — callers that only want the statement subset should fetch
    with eligible_only=True or filter on IS_STATEMENT_ELIGIBLE themselves.
    The P&L summary itself is now built from VISTA_PNL_SUMARIO via
    pl_summary_from_view, which is fed by fetch_pnl_summary (statement-eligible
    rows only, baked into the view).
    """
    if raw_df.empty:
        return raw_df.copy()
    _validate_columns(raw_df, _REQUIRED_COLUMNS | {SALDO, MES, PARTIDA_PL, IS_INTERCOMPANY},
                      "prepare_pnl_from_view")
    df = raw_df.copy()
    df[FECHA] = pd.to_datetime(df[FECHA])
    df[CENTRO_COSTO] = df[CENTRO_COSTO].astype("category")
    df[PARTIDA_PL] = df[PARTIDA_PL].astype("category")
    df[IS_INTERCOMPANY] = df[IS_INTERCOMPANY].astype(bool)
    return df


def prepare_bs_from_view(raw_df: pd.DataFrame) -> pd.DataFrame:
    """Lightweight shape adapter for rows coming from VISTA_BS_PREPARADO.

    The view already supplies SALDO, MES, PARTIDA_BS, and SECCION_BS, so this
    function only fixes dtypes and applies the category encoding that the
    downstream BS detail aggregations (bs_detail_by_cuenta, bs_top20_by_nit)
    expect.  The BS summary itself is built from VISTA_BS_SUMARIO via
    bs_summary_from_view.
    """
    if raw_df.empty:
        return raw_df.copy()
    _validate_columns(raw_df, _REQUIRED_COLUMNS | {SALDO, MES, PARTIDA_BS, SECCION_BS},
                      "prepare_bs_from_view")
    df = raw_df.copy()
    df[FECHA] = pd.to_datetime(df[FECHA])
    df[CENTRO_COSTO] = df[CENTRO_COSTO].astype("category")
    df[PARTIDA_BS] = df[PARTIDA_BS].astype("category")
    df[SECCION_BS] = df[SECCION_BS].astype("category")
    return df



