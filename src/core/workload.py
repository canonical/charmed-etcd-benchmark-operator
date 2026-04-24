#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Base objects for workload operations."""

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class WorkloadBase(ABC):
    """Base interface for workload operations."""

    @abstractmethod
    def start(self) -> None:
        """Start the workload service."""
        pass

    @abstractmethod
    def write_file(self, content: str, file: str) -> None:
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
    def file_exists(self, file_path: str) -> bool:
        """Check if a file exists."""
        pass

    @abstractmethod
    def start_service(self, template_dir: str, config: dict[str, Any]) -> None:
        """Start the workload service."""
        pass

    @abstractmethod
    def stop_service(self) -> None:
        """Stop the workload service."""
        pass

    @abstractmethod
    def is_running(self) -> bool:
        """Return whether the benchmark service is active."""
        pass
