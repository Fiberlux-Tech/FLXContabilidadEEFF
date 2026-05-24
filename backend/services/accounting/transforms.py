import logging

import numpy as np
import pandas as pd

from accounting.rules import BS_CLASSIFICATION, BS_CLASSIFICATION_OVERRIDES
from config.exceptions import DataValidationError
from config.fields import (
    CUENTA_CONTABLE, CENTRO_COSTO, FECHA, DESCRIPCION,
    NIT, RAZON_SOCIAL, DESC_CECO, SALDO, FIRST_CHAR,
    PARTIDA_PL, PARTIDA_BS, SECCION_BS, MES, IS_INTERCOMPANY,
)


logger = logging.getLogger("plantillas.transforms")

_REQUIRED_COLUMNS = {
    CUENTA_CONTABLE, CENTRO_COSTO, FECHA,
    "DEBITO_LOCAL", "CREDITO_LOCAL", DESCRIPCION,
    NIT, RAZON_SOCIAL, DESC_CECO,
}


def _cuenta_prefix(s: pd.Series, n: int) -> pd.Series:
    """First *n* characters of dotted CUENTA_CONTABLE codes (e.g. n=2 → "10")."""
    return s.str[:n]


def _validate_columns(df: pd.DataFrame, required: set[str], context: str) -> None:
    """Raise DataValidationError if *df* is missing required columns or is empty."""
    if df.empty:
        raise DataValidationError(f"{context}: input DataFrame is empty")
    missing = required - set(df.columns)
    if missing:
        raise DataValidationError(f"{context}: missing columns {sorted(missing)}")


def _clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Shared column cleaning: copy, trim key columns, extract FIRST_CHAR, parse FECHA, extract MES."""
    df = df.copy()
    df[CUENTA_CONTABLE] = df[CUENTA_CONTABLE].str.strip()
    df[CENTRO_COSTO] = df[CENTRO_COSTO].str.strip()
    df[FIRST_CHAR] = df[CUENTA_CONTABLE].str[0]
    df[FECHA] = pd.to_datetime(df[FECHA])
    df[MES] = df[FECHA].dt.month
    df[CENTRO_COSTO] = df[CENTRO_COSTO].astype("category")
    return df


def prepare_pnl_from_view(raw_df: pd.DataFrame) -> pd.DataFrame:
    """Lightweight shape adapter for rows coming from VISTA_PNL_PREPARADO.

    The view already supplies SALDO, MES, PARTIDA_PL, and IS_INTERCOMPANY,
    so this function only fixes dtypes and applies the category encoding
    that downstream aggregation expects.

    If the input carries an IS_STATEMENT_ELIGIBLE column (eligible_only=False
    was passed to fetch_pnl_data, as Excel does), this function returns the
    *full* set unchanged — Excel needs both the unfiltered and statement-
    eligible subsets, and does the subset itself. Callers that only want
    the statement subset should either fetch with eligible_only=True or
    filter on IS_STATEMENT_ELIGIBLE before calling pl_summary.
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


def get_excluded_cuentas(df: pd.DataFrame, df_stmt: pd.DataFrame) -> set[str]:
    """Return the set of CUENTA_CONTABLE values present in *df* but not in *df_stmt*."""
    all_cuentas = set(df[CUENTA_CONTABLE].unique())
    kept = set(df_stmt[CUENTA_CONTABLE].unique())
    return all_cuentas - kept


# ── Balance Sheet transforms ─────────────────────────────────────────────────

def prepare_bs(df: pd.DataFrame) -> pd.DataFrame:
    """Clean raw BS data and compute SALDO with correct sign per account class."""
    _validate_columns(df, _REQUIRED_COLUMNS, "prepare_bs")
    df = _clean_columns(df)
    is_asset = df[FIRST_CHAR].isin(["1", "2", "3"])
    df.loc[is_asset, SALDO] = df.loc[is_asset, "DEBITO_LOCAL"] - df.loc[is_asset, "CREDITO_LOCAL"]
    df.loc[~is_asset, SALDO] = df.loc[~is_asset, "CREDITO_LOCAL"] - df.loc[~is_asset, "DEBITO_LOCAL"]
    return df


# Pre-sorted once — BS_CLASSIFICATION_OVERRIDES is a module-level constant.
_SORTED_BS_OVERRIDES = sorted(
    BS_CLASSIFICATION_OVERRIDES.items(), key=lambda x: -len(x[0])
)


def assign_partida_bs(df: pd.DataFrame) -> pd.DataFrame:
    """Classify BS accounts by prefix into PARTIDA_BS and SECCION_BS."""
    df = df.copy()
    cuenta = df[CUENTA_CONTABLE]

    # Override conditions: longest prefix first (np.select picks first match)
    override_conditions = [cuenta.str.startswith(prefix) for prefix, _ in _SORTED_BS_OVERRIDES]
    override_partidas = [partida for _, (partida, _) in _SORTED_BS_OVERRIDES]
    override_sections = [section or "" for _, (_, section) in _SORTED_BS_OVERRIDES]

    # Single vectorized pass for overrides
    df[PARTIDA_BS] = np.select(override_conditions, override_partidas, default="")
    df["_SECCION_OVERRIDE"] = np.select(override_conditions, override_sections, default="")

    still_empty = df[PARTIDA_BS] == ""
    prefix2 = _cuenta_prefix(cuenta, 2)
    df.loc[still_empty, PARTIDA_BS] = prefix2[still_empty].map(BS_CLASSIFICATION)

    unmatched = df[PARTIDA_BS].isna() | (df[PARTIDA_BS] == "")
    if unmatched.any():
        first_char = df.loc[unmatched, FIRST_CHAR]
        df.loc[unmatched & first_char.isin(["1", "2", "3"]), PARTIDA_BS] = "POR DEFINIR ACTIVO"
        df.loc[unmatched & (first_char == "4"), PARTIDA_BS] = "POR DEFINIR PASIVO"
        df.loc[unmatched & (first_char == "5"), PARTIDA_BS] = "POR DEFINIR PATRIMONIO"
        n = unmatched.sum()
        sample = df.loc[unmatched, CUENTA_CONTABLE].unique()[:5]
        logger.warning("%d BS rows unclassified. Sample: %s", n, list(sample))

    # Default section from FIRST_CHAR, then apply overrides
    df[SECCION_BS] = "PATRIMONIO"
    df.loc[df[FIRST_CHAR].isin(["1", "2", "3"]), SECCION_BS] = "ACTIVO"
    df.loc[df[FIRST_CHAR] == "4", SECCION_BS] = "PASIVO"
    has_override = df["_SECCION_OVERRIDE"] != ""
    df.loc[has_override, SECCION_BS] = df.loc[has_override, "_SECCION_OVERRIDE"]
    df[PARTIDA_BS] = df[PARTIDA_BS].astype("category")
    df[SECCION_BS] = df[SECCION_BS].astype("category")
    df = df.drop(columns=[FIRST_CHAR, "_SECCION_OVERRIDE"])
    return df


def prepare_bs_stmt(raw_df: pd.DataFrame) -> pd.DataFrame:
    """Full BS pipeline: prepare_bs -> assign_partida_bs (no filter step)."""
    df = prepare_bs(raw_df)
    return assign_partida_bs(df)
