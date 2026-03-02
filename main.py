import logging
import sys

from dotenv import load_dotenv


# load_dotenv() must run before any local imports that read env vars at import time
load_dotenv()

from config.settings import get_config  # noqa: E402
from config.exceptions import PlantillasError, ConfigurationError, EmailError  # noqa: E402

logging.basicConfig(
    level=get_config().log_level,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("plantillas.main")

from core.cli import parse_args, resolve_period  # noqa: E402
from core.pipeline import run_report  # noqa: E402
from core.email_sender import get_email_sender  # noqa: E402


def main():
    """Entry point: parse CLI args, resolve period, run report pipeline, and email."""
    import pandas as pd
    pd.set_option("mode.copy_on_write", True)

    args = parse_args()

    sender = get_email_sender()

    # --- Test-email mode: verify config and exit ---
    if args.test_email:
        try:
            sender.send_test()
            logger.info("Test email sent successfully.")
        except EmailError as exc:
            logger.error("Test email failed: %s", exc)
            sys.exit(1)
        except (OSError, RuntimeError) as exc:
            logger.error("Test email failed unexpectedly: %s", exc)
            sys.exit(1)
        return

    # --- Validate email config eagerly (before heavy computation) ---
    if not args.no_email:
        try:
            sender.validate_config()
        except ConfigurationError as exc:
            logger.error("%s", exc)
            sys.exit(1)

    # --- Resolve period parameters ---
    resolved = resolve_period(args)
    if resolved is None:
        return
    company, year, month, quarter, period_type, period_num = resolved

    # --- Determine email preference ---
    if args.no_email:
        send_email = False
    else:
        send_input = input("Send by email? (y/n): ").strip().lower()
        send_email = send_input == "y"

    # --- Run report pipeline ---
    try:
        run_report(
            company, year, month, quarter, period_type, period_num,
            email_sender=sender, no_email=args.no_email,
            send_email=send_email, excel_only=args.excel_only,
        )
    except PlantillasError as exc:
        logger.error("%s: %s", type(exc).__name__, exc)
        sys.exit(1)
    except Exception:
        logger.exception("Unexpected error during report generation")
        sys.exit(1)


if __name__ == "__main__":
    main()
