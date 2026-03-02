import pandas as pd
import pytest

from config import get_config


@pytest.fixture(autouse=True)
def _clear_config_cache():
    """Clear get_config() lru_cache before each test so env var changes take effect."""
    get_config.cache_clear()
    yield
    get_config.cache_clear()


@pytest.fixture
def raw_pnl_df():
    """Minimal DataFrame mimicking fetch_pnl_data output.

    Covers the main PARTIDA_PL categories via CUENTA_CONTABLE prefixes
    and CENTRO_COSTO prefixes used by assign_partida_pl.
    """
    rows = [
        # INGRESOS ORDINARIOS (cuenta starts with '70', ceco '2')
        ("CIA1", "70.1.1.1.01", "Ventas nacionales", "111", "Cliente A",
         "2100", "Ventas Lima", "2025-03-15", 0, 5000),
        # INGRESOS PROYECTOS (cuenta == '75.9.9.1.01')
        ("CIA1", "75.9.9.1.01", "Proyectos especiales", "222", "Cliente B",
         "2200", "Proyectos", "2025-03-20", 0, 2000),
        # COSTO (ceco starts with '1')
        ("CIA1", "62.1.1.1.01", "Sueldos produccion", "333", "Proveedor A",
         "1100", "Produccion", "2025-03-10", 3000, 0),
        # GASTO VENTA (ceco starts with '2')
        ("CIA1", "63.1.1.1.01", "Servicios ventas", "444", "Proveedor B",
         "2100", "Ventas Lima", "2025-04-05", 800, 0),
        # GASTO ADMIN (ceco starts with '3')
        ("CIA1", "63.2.1.1.01", "Servicios admin", "555", "Proveedor C",
         "3100", "Administracion", "2025-04-10", 500, 0),
        # D&A - COSTO (ceco starts with '6')
        ("CIA1", "68.1.1.1.01", "Depreciacion maquinaria", "666", "N/A",
         "6100", "Depreciacion Prod", "2025-05-01", 200, 0),
        # D&A - GASTO (cuenta starts with 68.x, ceco NOT '6')
        ("CIA1", "68.0.1.1.01", "Depreciacion oficina", "777", "N/A",
         "3200", "Depreciacion Admin", "2025-05-15", 150, 0),
        # RESULTADO FINANCIERO (cuenta starts with '67')
        ("CIA1", "67.1.1.1.01", "Gastos financieros", "888", "Banco X",
         "7100", "Financiero", "2025-06-01", 300, 0),
        # RESULTADO FINANCIERO - ingresos (cuenta starts with '77')
        ("CIA1", "77.1.1.1.01", "Ingresos financieros", "999", "Banco Y",
         "7200", "Financiero Ing", "2025-06-15", 0, 100),
        # IMPUESTO A LA RENTA (first char '8')
        ("CIA1", "88.1.1.1.01", "Impuesto renta", "000", "SUNAT",
         "3300", "Impuestos", "2025-06-30", 400, 0),
        # Low account that should be EXCLUDED by filter_for_statements (prefix < 61.9)
        ("CIA1", "60.1.1.1.01", "Compras", "111", "Proveedor D",
         "1200", "Compras", "2025-03-01", 1000, 0),
        # EXCLUDED_CUENTA (79.1.1.1.01) — filtered out by filter_for_statements
        ("CIA1", "79.1.1.1.01", "Cargas imputables", "000", "N/A",
         "1300", "Cargas", "2025-03-01", 0, 4000),
    ]
    return pd.DataFrame(rows, columns=[
        "CIA", "CUENTA_CONTABLE", "DESCRIPCION", "NIT", "RAZON_SOCIAL",
        "CENTRO_COSTO", "DESC_CECO", "FECHA", "DEBITO_LOCAL", "CREDITO_LOCAL",
    ])
