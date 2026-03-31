import logging

import numpy as np
import pandas as pd

from accounting.rules import (
    PROVISION_INCOBRABLE_CUENTAS, DYA_GASTO_PREFIXES,
    PARTICIPACION_TRABAJADORES_CUENTA, DIFERENCIA_CAMBIO_PREFIXES,
    RESULTADO_FINANCIERO_PREFIXES, INGRESOS_ORDINARIOS_PREFIX,
    INGRESOS_PROYECTOS_CUENTA, OTROS_INGRESOS_PREFIXES,
    IMPUESTO_RENTA_FIRST_CHAR, EXCLUDED_CUENTA,
    CECO_PREFIX_DYA_COSTO, CECO_PREFIX_RESULTADO_FINANCIERO,
    CECO_PREFIX_COSTO, CECO_PREFIX_GASTO_VENTA, CECO_PREFIX_GASTO_ADMIN,
    CECO_PREFIX_OTROS_EGRESOS,
    BS_CLASSIFICATION, BS_CLASSIFICATION_OVERRIDES,
)
from config.exceptions import DataValidationError
from config.fields import (
    CUENTA_CONTABLE, CENTRO_COSTO, FECHA, DESCRIPCION,
    NIT, RAZON_SOCIAL, DESC_CECO, SALDO, FIRST_CHAR,
    PARTIDA_PL, PARTIDA_BS, SECCION_BS, MES,
)


logger = logging.getLogger("plantillas.transforms")

_REQUIRED_COLUMNS = {
    CUENTA_CONTABLE, CENTRO_COSTO, FECHA,
    "DEBITO_LOCAL", "CREDITO_LOCAL", DESCRIPCION,
    NIT, RAZON_SOCIAL, DESC_CECO,
}


def _cuenta_digits(s: pd.Series) -> pd.Series:
    """Remove dots from CUENTA_CONTABLE, returning pure digit strings.

    Example: "68.0.1.01.001" → "680101001"
    Used for numeric prefix comparisons where dot positions vary.
    """
    return s.str.replace(".", "", regex=False)


def _cuenta_prefix(s: pd.Series, n: int) -> pd.Series:
    """First *n* characters of dotted CUENTA_CONTABLE codes.

    n=2: "68.0.1.01.001" → "68"  (pure digits — dot is at position 2+)
    n=4: "68.0.1.01.001" → "68.0" (dot included at position 2)

    The constants in rules.py are defined to match these exact slices:
    - 2-char constants: ("67", "77", "70", "73", "75") — always pure digits
    - 4-char constants: ("68.0", "68.1", "67.6", "77.6") — dot at position 2
    """
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


def prepare_pnl(df: pd.DataFrame) -> pd.DataFrame:
    """Clean raw P&L data and compute SALDO as CREDITO minus DEBITO."""
    _validate_columns(df, _REQUIRED_COLUMNS, "prepare_pnl")
    df = _clean_columns(df)
    df[SALDO] = df["CREDITO_LOCAL"] - df["DEBITO_LOCAL"]
    return df


def filter_for_statements(df: pd.DataFrame) -> pd.DataFrame:
    """Filter to statement-relevant accounts (prefix >= 619, excluding 79.1.1.1.01).

    Uses first 3 digits as integer to avoid floating-point ambiguity.
    """
    prefix_3 = pd.to_numeric(_cuenta_digits(df[CUENTA_CONTABLE]).str[:3], errors="coerce")
    df = df[prefix_3 >= 619].copy()
    df = df[df[CUENTA_CONTABLE] != EXCLUDED_CUENTA]
    return df


def assign_partida_pl(df: pd.DataFrame) -> pd.DataFrame:
    """Assign PARTIDA_PL label to each row based on account and cost-center rules.

    Uses np.select for a single vectorized pass; first matching condition wins.
    """
    df = df.copy()
    cuenta = df[CUENTA_CONTABLE]
    cuenta4 = _cuenta_prefix(cuenta, 4)   # e.g. "68.0" — matches DYA_GASTO_PREFIXES
    cuenta2 = _cuenta_prefix(cuenta, 2)   # e.g. "68"  — matches RESULTADO_FINANCIERO_PREFIXES
    ceco1 = df[CENTRO_COSTO].str[0]

    # Rules in priority order — np.select picks the first match
    conditions = [
        cuenta.isin(PROVISION_INCOBRABLE_CUENTAS),
        cuenta4.isin(DYA_GASTO_PREFIXES) & ceco1.isin(CECO_PREFIX_DYA_COSTO),
        cuenta4.isin(DYA_GASTO_PREFIXES),
        cuenta == PARTICIPACION_TRABAJADORES_CUENTA,
        cuenta4.isin(DIFERENCIA_CAMBIO_PREFIXES),
        cuenta2.isin(RESULTADO_FINANCIERO_PREFIXES),
        cuenta2 == INGRESOS_ORDINARIOS_PREFIX,
        cuenta == INGRESOS_PROYECTOS_CUENTA,
        cuenta2.isin(OTROS_INGRESOS_PREFIXES),
        df["FIRST_CHAR"] == IMPUESTO_RENTA_FIRST_CHAR,
        ceco1 == CECO_PREFIX_RESULTADO_FINANCIERO,
        ceco1.isin(CECO_PREFIX_COSTO),
        ceco1 == CECO_PREFIX_GASTO_VENTA,
        ceco1 == CECO_PREFIX_GASTO_ADMIN,
        ceco1 == CECO_PREFIX_OTROS_EGRESOS,
    ]
    choices = [
        "PROVISION INCOBRABLE",
        "D&A - COSTO",
        "D&A - GASTO",
        "PARTICIPACION DE TRABAJADORES",
        "DIFERENCIA DE CAMBIO",
        "RESULTADO FINANCIERO",
        "INGRESOS ORDINARIOS",
        "INGRESOS PROYECTOS",
        "OTROS INGRESOS",
        "IMPUESTO A LA RENTA",
        "RESULTADO FINANCIERO",
        "COSTO",
        "GASTO VENTA",
        "GASTO ADMIN",
        "OTROS EGRESOS",
    ]

    df[PARTIDA_PL] = pd.Categorical(np.select(conditions, choices, default="POR CLASIFICAR"))

    n_unclassified = (df[PARTIDA_PL] == "POR CLASIFICAR").sum()
    if n_unclassified > 0:
        sample = df.loc[df[PARTIDA_PL] == "POR CLASIFICAR", CUENTA_CONTABLE].unique()[:10]
        logger.warning(
            "%d rows could not be classified (PARTIDA_PL = 'POR CLASIFICAR'). "
            "Unrecognised CUENTA_CONTABLE values: %s.",
            n_unclassified, list(sample),
        )
    df = df.drop(columns=[FIRST_CHAR])
    return df


def prepare_stmt(raw_df: pd.DataFrame) -> pd.DataFrame:
    """Full pipeline: prepare_pnl -> filter_for_statements -> assign_partida_pl."""
    df = prepare_pnl(raw_df)
    df = filter_for_statements(df)
    return assign_partida_pl(df)


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
