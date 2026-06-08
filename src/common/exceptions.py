"""Charm-specific exceptions."""


class BenchmarkError(Exception):
    """Base exception for all benchmark charm errors."""

    def __init__(self, message: str, detailed_description: str = ""):
        self.message = message
        self.detailed_description = detailed_description
        super().__init__(message)


class BenchmarkWorkloadError(BenchmarkError):
    """Raised when there is an error with the charm workload, i.e. benchmark tool."""


class BenchmarkConfigurationError(BenchmarkError):
    """Raised when invalid configurations are detected."""


class BenchmarkServiceError(BenchmarkError):
    """Raised when there is an error running the benchmark service."""


class MetricsExporterServiceError(BenchmarkError):
    """Raised when there is an error running the benchmark metrics exporter service."""


class BenchmarkResultsParseError(BenchmarkError):
    """Raised when there is an error parsing the benchmark results file."""
