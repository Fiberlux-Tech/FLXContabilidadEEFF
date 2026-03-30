"""Period resolution helpers — business logic for month/quarter/year calculations."""

from config.calendar import QUARTER_MONTHS


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


def month_end_boundary(year: int, month: int | None) -> tuple[int, int]:
    """Return (end_year, end_month_1st) representing the exclusive upper bound.

    For month=None or month=12, returns (year+1, 1).
    Otherwise returns (year, month+1).
    Use with date()/Timestamp() to build the half-open range [start, end).
    """
    if month is None or month == 12:
        return (year + 1, 1)
    return (year, month + 1)
