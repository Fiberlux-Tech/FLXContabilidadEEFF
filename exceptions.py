"""Custom exception hierarchy for consistent error handling across all layers."""


class PlantillasError(Exception):
    """Base exception for all plantillas errors."""


class ConfigurationError(PlantillasError):
    """Missing or invalid configuration (env vars, .env file)."""


class QueryError(PlantillasError):
    """Database query execution or data-fetching errors."""


class ExportError(PlantillasError):
    """File export errors (Excel, PDF)."""


class EmailError(PlantillasError):
    """Email sending or configuration errors."""


class DataValidationError(PlantillasError):
    """Missing columns or invalid data in input DataFrames."""
