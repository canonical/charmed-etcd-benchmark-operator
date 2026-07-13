#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Base objects for workload operations."""

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class WorkloadBase(ABC):
    """Base interface for workload operations."""

    @abstractmethod
    def verify_workload_ready(self) -> None:
        """Verify that the workload is available and ready."""
        pass

    @abstractmethod
    def write_file(self, file: str, content: str | None = None) -> None:
        """Write content to a file.

        Args:
            content (str): Content to write to the file.
            file (str): Path to the file.
        """
        pass

    @abstractmethod
    def read_file(self, file: str) -> str | None:
        """Read contents of a file.

        Args:
            file (str): Path to the file.
        """
        pass

    @abstractmethod
    def file_exists(self, file_path: str | Path) -> bool:
        """Check if a file exists."""
        pass

    @abstractmethod
    def start_benchmark(self, template_dir: str, config: dict[str, Any]) -> None:
        """Start the systemd benchmark service."""
        pass

    @abstractmethod
    def stop_benchmark(self) -> None:
        """Stop the systemd benchmark service."""
        pass

    @abstractmethod
    def is_benchmark_running(self) -> bool:
        """Return whether the benchmark service is active."""
        pass

    @abstractmethod
    def start_metrics_exporter(self, template_dir: str, config: dict[str, Any]) -> None:
        """Start the metrics exporter service."""
        pass

    @abstractmethod
    def stop_metrics_exporter(self) -> None:
        """Stop the metrics exporter service."""
        pass
