"""Company metadata — legal names, RUCs, valid company set."""

CONSOLIDADO = "CONSOLIDADO"

COMPANY_META = {
    "FIBERLINE": {"legal_name": "FIBERLINE PERU S.A.C.",  "ruc": "20601594791"},
    "FIBERLUX":  {"legal_name": "FIBERLUX S.A.C.",        "ruc": "20557425889"},
    "FIBERTECH": {"legal_name": "FIBERLUX TECH S.A.C.",   "ruc": "20607403903"},
    "NEXTNET":   {"legal_name": "NEXTNET S.A.C.",         "ruc": "20546904106"},
    CONSOLIDADO: {"legal_name": "GRUPO FLX (CONSOLIDADO)", "ruc": ""},
}

VALID_COMPANIES = frozenset(COMPANY_META.keys())
REAL_COMPANIES = tuple(k for k in COMPANY_META if k != CONSOLIDADO)
