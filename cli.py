import argparse
import logging

from company_config import VALID_COMPANIES
from calendar_config import MIN_YEAR, derive_period_type


logger = logging.getLogger("plantillas.cli")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments and return the argparse Namespace."""
    parser = argparse.ArgumentParser(
        description="Generate P&L Excel + PDF reports and optionally email them.",
    )
    parser.add_argument(
        "--company",
        type=str.upper,
        choices=sorted(VALID_COMPANIES),
        metavar="COMPANY",
        help=f"Company name. One of: {', '.join(sorted(VALID_COMPANIES))}",
    )
    parser.add_argument("--year", type=int, help="Fiscal year (e.g. 2025)")
    parser.add_argument(
        "--month",
        type=int,
        choices=range(1, 13),
        metavar="1-12",
        help="Month number (omit for full year)",
    )
    parser.add_argument(
        "--quarter",
        type=int,
        choices=range(1, 5),
        metavar="1-4",
        help="Quarter number (1-4). Mutually exclusive with --month.",
    )
    parser.add_argument("--no-email", action="store_true", help="Skip the email step")
    parser.add_argument("--excel-only", action="store_true", help="Generate only the Excel report (skip PDF)")
    parser.add_argument("--test-email", action="store_true", help="Send a test email and exit")
    return parser.parse_args()


def resolve_period(args: argparse.Namespace) -> tuple[str, int, int | None, int | None, str, int | None] | None:
    """Resolve company, year, month, quarter from CLI args or interactive input.

    Returns (company, year, month, quarter, period_type, period_num) or None on error.
    """
    # --- Company ---
    if args.company:
        company = args.company
    else:
        company = input("Company (FIBERLINE / FIBERLUX / FIBERTECH / NEXTNET): ").strip().upper()
    if company not in VALID_COMPANIES:
        logger.error("'%s' is not a valid company. Choose from: %s", company, ", ".join(sorted(VALID_COMPANIES)))
        return None

    # --- Year ---
    if args.year is not None:
        year = args.year
    else:
        try:
            year = int(input("Year (e.g. 2025): "))
        except ValueError:
            logger.error("Year must be a number (e.g. 2025).")
            return None
    if year < MIN_YEAR:
        logger.error("Year %d is not supported. Minimum year is %d.", year, MIN_YEAR)
        return None

    # --- Month / Quarter ---
    if args.month is not None and args.quarter is not None:
        logger.error("--month and --quarter are mutually exclusive. Specify one or neither.")
        return None

    if args.month is not None:
        month = args.month
        quarter = None
    elif args.quarter is not None:
        month = None
        quarter = args.quarter
    else:
        period_input = input("Period — month (1-12), quarter (Q1-Q4), or leave blank for full year: ").strip()
        if period_input:
            upper = period_input.upper()
            if upper.startswith("Q") and upper[1:].isdigit():
                quarter = int(upper[1:])
                if quarter < 1 or quarter > 4:
                    logger.error("Quarter %d is out of range (1-4).", quarter)
                    return None
                month = None
            else:
                try:
                    month = int(period_input)
                except ValueError:
                    logger.error("Enter a month (1-12), quarter (Q1-Q4), or leave blank.")
                    return None
                if month < 1 or month > 12:
                    logger.error("Month %d is out of range (1-12).", month)
                    return None
                quarter = None
        else:
            month = None
            quarter = None

    period_type, period_num = derive_period_type(month, quarter)
    return company, year, month, quarter, period_type, period_num
