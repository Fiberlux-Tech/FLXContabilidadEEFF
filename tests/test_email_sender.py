import sys
import pytest

from core.email_sender import (
    get_email_sender, OutlookEmailSender, SMTPEmailSender, EmailSender,
)
from config.exceptions import ConfigurationError


class TestGetEmailSender:
    def test_outlook_backend(self, monkeypatch):
        monkeypatch.setenv("EMAIL_BACKEND", "outlook")
        sender = get_email_sender()
        assert isinstance(sender, OutlookEmailSender)

    def test_smtp_backend(self, monkeypatch):
        monkeypatch.setenv("EMAIL_BACKEND", "smtp")
        sender = get_email_sender()
        assert isinstance(sender, SMTPEmailSender)

    def test_invalid_backend_raises(self, monkeypatch):
        monkeypatch.setenv("EMAIL_BACKEND", "invalid")
        with pytest.raises(ValueError, match="Unknown EMAIL_BACKEND"):
            get_email_sender()

    def test_default_on_windows(self, monkeypatch):
        monkeypatch.delenv("EMAIL_BACKEND", raising=False)
        monkeypatch.setattr(sys, "platform", "win32")
        sender = get_email_sender()
        assert isinstance(sender, OutlookEmailSender)

    def test_default_on_linux(self, monkeypatch):
        monkeypatch.delenv("EMAIL_BACKEND", raising=False)
        monkeypatch.setattr(sys, "platform", "linux")
        sender = get_email_sender()
        assert isinstance(sender, SMTPEmailSender)


class TestOutlookValidateConfig:
    def test_missing_email_to(self, monkeypatch):
        monkeypatch.delenv("EMAIL_TO", raising=False)
        sender = OutlookEmailSender()
        with pytest.raises(ConfigurationError, match="EMAIL_TO"):
            sender.validate_config()

    def test_valid_config(self, monkeypatch):
        monkeypatch.setenv("EMAIL_TO", "test@example.com")
        sender = OutlookEmailSender()
        sender.validate_config()  # Should not raise


class TestSMTPValidateConfig:
    def test_missing_vars(self, monkeypatch):
        for var in ["EMAIL_TO", "SMTP_HOST", "SMTP_PORT", "EMAIL_FROM"]:
            monkeypatch.delenv(var, raising=False)
        sender = SMTPEmailSender()
        with pytest.raises(ConfigurationError, match="Missing required environment variables"):
            sender.validate_config()

    def test_valid_config(self, monkeypatch):
        monkeypatch.setenv("EMAIL_TO", "test@example.com")
        monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("SMTP_PORT", "587")
        monkeypatch.setenv("EMAIL_FROM", "sender@example.com")
        sender = SMTPEmailSender()
        sender.validate_config()  # Should not raise


class TestProtocolCompliance:
    def test_outlook_is_email_sender(self):
        assert isinstance(OutlookEmailSender(), EmailSender)

    def test_smtp_is_email_sender(self):
        assert isinstance(SMTPEmailSender(), EmailSender)
