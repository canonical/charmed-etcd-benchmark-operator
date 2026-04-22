#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Base objects for workload operations."""

import logging
from abc import ABC, abstractmethod

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
