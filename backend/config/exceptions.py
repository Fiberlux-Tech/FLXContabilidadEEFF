"""Custom exception hierarchy for consistent error handling across all layers."""


class PlantillasError(Exception):
    """Base exception for all plantillas errors."""


class ConfigurationError(PlantillasError):
    """Missing or invalid configuration (env vars, .env file)."""


class QueryError(PlantillasError):
    """Database query execution or data-fetching errors."""


class ExportError(PlantillasError):
    """File export errors (Excel, PDF)."""


class DataValidationError(PlantillasError):
    """Missing columns or invalid data in input DataFrames."""


class RequestValidationError(PlantillasError):
    """Invalid input in an API request (company, year, etc.)."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code
