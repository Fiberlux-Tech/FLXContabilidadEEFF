from data.queries import SQL_SCHEMA, SQL_VIEW, PNL_ACCOUNT_PREFIXES, fetch_pnl_data, _fetch_data
import inspect


class TestQueryConstants:
    def test_schema_defined(self):
        assert SQL_SCHEMA == "REPORTES"

    def test_view_defined(self):
        assert SQL_VIEW == "VISTA_ANALISIS_CECOS"

    def test_account_prefixes(self):
        assert PNL_ACCOUNT_PREFIXES == ("6", "7", "8")

    def test_constants_used_in_query(self):
        """Verify the shared query builder references the module constants, not hardcoded strings."""
        source = inspect.getsource(_fetch_data)
        assert "SQL_SCHEMA" in source
        assert "SQL_VIEW" in source

    def test_fetch_pnl_delegates_to_shared_helper(self):
        """Verify fetch_pnl_data delegates to _fetch_data with correct prefixes."""
        source = inspect.getsource(fetch_pnl_data)
        assert "_fetch_data" in source
        assert "PNL_ACCOUNT_PREFIXES" in source
