import logging
import os
import sys
from typing import Any, Protocol, runtime_checkable

from config.settings import get_config
from config.exceptions import ConfigurationError, EmailError


logger = logging.getLogger("plantillas.email")

# Maximum attachment size accepted before raising EmailError (25 MB)
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024

SUBJECT_TEMPLATE = "Reporte Automatico - Estado de Resultados — {company} {period} {year}"
BODY_TEMPLATE = (
    "Buenas tardes,"
    "\n\n"
    "Adjunto reporte financiero de {company} ({period} {year}) "
    "generado de forma automatica."
    "\n\n"
    "Saludos,\n"
    "ContaBot"
)

TEST_SUBJECT = "[TEST] ContaBot — Email service check"
TEST_BODY = (
    "Este es un correo de prueba enviado por ContaBot.\n\n"
    "Si recibes este mensaje, la configuracion de correo es correcta.\n\n"
    "Saludos,\nContaBot"
)


def _get_recipients() -> list[str]:
    """Return a list of recipient email addresses from config."""
    raw = get_config().email.to
    if not raw:
        raise ConfigurationError("EMAIL_TO environment variable is not set. Check your .env file.")
    return [r.strip() for r in raw.split(",")]


def _ensure_list(file_paths: list[str] | str) -> list[str]:
    """Coerce a single path string into a one-element list."""
    return [file_paths] if isinstance(file_paths, str) else file_paths


@runtime_checkable
class EmailSender(Protocol):
    """Protocol defining the interface for email sender backends."""

    def validate_config(self) -> None: ...
    def send(self, file_paths: list[str] | str, *, company: str = "", period: str = "", year: int | str = "") -> None: ...
    def send_test(self) -> None: ...


class OutlookEmailSender:
    """Send emails via the local Outlook COM automation (Windows only)."""

    def _new_mail_item(self) -> Any:
        """Create a new Outlook MailItem pre-addressed to the configured recipients."""
        import win32com.client
        outlook = win32com.client.Dispatch("Outlook.Application")
        mail = outlook.CreateItem(0)  # 0 = olMailItem
        mail.To = "; ".join(_get_recipients())
        return mail

    def validate_config(self) -> None:
        """Raise ConfigurationError if EMAIL_TO is not set."""
        _get_recipients()  # raises ConfigurationError if EMAIL_TO is empty

    def send(self, file_paths: list[str] | str, *, company: str = "", period: str = "", year: int | str = "") -> None:
        """Send the report files as email attachments via Outlook."""
        file_paths = _ensure_list(file_paths)

        mail = self._new_mail_item()
        mail.Subject = SUBJECT_TEMPLATE.format(company=company, period=period, year=year)
        mail.Body = BODY_TEMPLATE.format(company=company, period=period, year=year)

        for file_path in file_paths:
            mail.Attachments.Add(os.path.abspath(file_path))

        recipients = mail.To
        mail.Send()
        logger.info("Email sent to %s", recipients)

    def send_test(self) -> None:
        """Send a test email to verify Outlook configuration."""
        mail = self._new_mail_item()
        mail.Subject = TEST_SUBJECT
        mail.Body = TEST_BODY
        recipients = mail.To
        mail.Send()
        logger.info("Test email sent to %s", recipients)


class SMTPEmailSender:
    """Send emails via SMTP (cross-platform)."""

    def validate_config(self) -> None:
        """Raise ConfigurationError if any required SMTP setting is missing."""
        cfg = get_config().email
        missing = []
        if not cfg.to:
            missing.append("EMAIL_TO")
        if not cfg.smtp_host:
            missing.append("SMTP_HOST")
        if not cfg.smtp_port:
            missing.append("SMTP_PORT")
        if not cfg.from_addr:
            missing.append("EMAIL_FROM")
        if missing:
            raise ConfigurationError(
                f"Missing required environment variables: {', '.join(missing)}. "
                "Check your .env file."
            )

    def _send_message(self, subject: str, body: str, attachments: list[str] | None = None) -> None:
        """Build and send a MIME message with optional file attachments."""
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        from email.mime.base import MIMEBase
        from email import encoders

        cfg = get_config().email

        msg = MIMEMultipart()
        msg["From"] = cfg.from_addr
        msg["To"] = ", ".join(_get_recipients())
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        for path in (attachments or []):
            file_size = os.path.getsize(path)
            if file_size > MAX_ATTACHMENT_BYTES:
                raise EmailError(
                    f"Attachment too large ({file_size / 1024 / 1024:.1f} MB): {os.path.basename(path)}"
                )
            with open(path, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f"attachment; filename={os.path.basename(path)}")
            msg.attach(part)

        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port) as server:
            server.starttls()
            if cfg.smtp_user:
                server.login(cfg.smtp_user, cfg.smtp_password)
            server.sendmail(msg["From"], _get_recipients(), msg.as_string())

        logger.info("Email sent via SMTP to %s", msg["To"])

    def send(self, file_paths: list[str] | str, *, company: str = "", period: str = "", year: int | str = "") -> None:
        """Send the report files as email attachments via SMTP."""
        file_paths = _ensure_list(file_paths)
        subject = SUBJECT_TEMPLATE.format(company=company, period=period, year=year)
        body = BODY_TEMPLATE.format(company=company, period=period, year=year)
        self._send_message(subject, body, attachments=file_paths)

    def send_test(self) -> None:
        """Send a test email to verify SMTP configuration."""
        self._send_message(TEST_SUBJECT, TEST_BODY)


def get_email_sender() -> EmailSender:
    """Return the appropriate EmailSender backend based on config and platform."""
    cfg = get_config().email
    backend = cfg.backend
    if not backend:
        backend = "outlook" if sys.platform == "win32" else "smtp"
    backend = backend.lower()

    if backend == "outlook":
        return OutlookEmailSender()
    elif backend == "smtp":
        return SMTPEmailSender()
    else:
        raise ValueError(
            f"Unknown EMAIL_BACKEND '{backend}'. Use 'outlook' or 'smtp'."
        )
