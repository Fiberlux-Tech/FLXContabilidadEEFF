import pytest

from config import DatabaseConfig
from db import _build_conn_str
from exceptions import ConfigurationError


class TestBuildConnStr:
    def test_missing_env_raises(self):
        cfg = DatabaseConfig()  # all fields empty
        with pytest.raises(ConfigurationError, match="Missing required database"):
            _build_conn_str(cfg)

    def test_tls_defaults_secure(self):
        cfg = DatabaseConfig(
            driver="ODBC Driver 18", server="localhost",
            database="testdb", uid="user", pwd="pass",
        )
        conn_str = _build_conn_str(cfg)
        assert "Encrypt=yes;" in conn_str
        assert "TrustServerCertificate=no;" in conn_str

    def test_tls_override(self):
        cfg = DatabaseConfig(
            driver="ODBC Driver 18", server="localhost",
            database="testdb", uid="user", pwd="pass",
            encrypt="no", trust_cert="yes",
        )
        conn_str = _build_conn_str(cfg)
        assert "Encrypt=no;" in conn_str
        assert "TrustServerCertificate=yes;" in conn_str
