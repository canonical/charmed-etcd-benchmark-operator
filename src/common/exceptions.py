"""Charm-specific exceptions."""


class BenchmarkError(Exception):
    """Base exception for all benchmark charm errors."""

    def __init__(self, message: str, detailed_description: str = ""):
        self.message = message
        self.detailed_description = detailed_description
        super().__init__(message)


class BenchmarkConfigurationError(BenchmarkError):
    """Raised when invalid configurations are detected."""
