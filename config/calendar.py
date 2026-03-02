"""Calendar and period helpers — month names, quarters, period resolution."""


MONTH_NAMES = {
    1: "JAN", 2: "FEB", 3: "MAR", 4: "APR", 5: "MAY", 6: "JUN",
    7: "JUL", 8: "AUG", 9: "SEP", 10: "OCT", 11: "NOV", 12: "DEC",
}
MONTH_NAMES_SET = frozenset(MONTH_NAMES.values())

MONTH_NAMES_ES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
    5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
    9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}

QUARTER_MONTHS = {
    1: [1, 2, 3],
    2: [4, 5, 6],
    3: [7, 8, 9],
    4: [10, 11, 12],
}

MIN_YEAR = 2025


def derive_period_type(month: int | None, quarter: int | None) -> tuple[str, int | None]:
    """Return (period_type, period_num) from month/quarter CLI inputs."""
    if month is not None:
        return "month", month
    if quarter is not None:
        return "quarter", quarter
    return "year", None


def get_quarter_end_month(quarter_num: int) -> int:
    """Return the last month of the given quarter (e.g. Q1 -> 3, Q2 -> 6)."""
    return QUARTER_MONTHS[quarter_num][-1]


def get_period_months(period_type: str, period_num: int | None) -> list[int]:
    """Return the list of months in the specified period."""
    if period_type == "month":
        return [period_num]
    elif period_type == "quarter":
        return list(QUARTER_MONTHS[period_num])
    else:
        return list(range(1, 13))


def get_ytd_months(period_type: str, period_num: int | None) -> list[int]:
    """Return the list of months for year-to-date (Jan through end of period)."""
    if period_type == "month":
        return list(range(1, period_num + 1))
    elif period_type == "quarter":
        return list(range(1, get_quarter_end_month(period_num) + 1))
    else:
        return list(range(1, 13))


def get_end_month(period_type: str, period_num: int | None) -> int:
    """Return the last month number for a given period."""
    if period_type == "month":
        return period_num
    elif period_type == "quarter":
        return get_quarter_end_month(period_num)
    return 12
