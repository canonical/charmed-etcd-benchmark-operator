#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manage the metrics exporter."""

import logging
import os
from typing import Any

from literals import (
    METRICS_EXPORTER_RUNNER_FILE_PATH,
    METRICS_PORT,
)

logger = logging.getLogger(__name__)


class MetricsExporterManager:
    """Manager class for etcd benchmark activity."""

    def setup_metrics_exporter(self, benchmark_config: dict[str, Any]) -> dict[str, Any]:
        """Set up the metrics exporter config for given test."""
        charm_dir = os.environ.get("CHARM_DIR", "")
        return {
            "jsonl_path": f"{benchmark_config.get('results_dir', '')}/stdout.jsonl",
            "test_id": str(benchmark_config.get("current_test_id", "")),
            "metrics_port": METRICS_PORT,
            "python_bin": f"{charm_dir}/venv/bin/python",
            "runner_path": METRICS_EXPORTER_RUNNER_FILE_PATH,
        }
