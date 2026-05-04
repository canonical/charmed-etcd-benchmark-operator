#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manage the metrics exporter."""

import logging
import os
from pathlib import Path
from typing import Any

from charmlibs import systemd

from literals import (
    METRICS_EXPORTER_RUNNER_FILE_PATH,
    METRICS_EXPORTER_SERVICE_FILE_PATH,
    METRICS_EXPORTER_SERVICE_NAME,
    METRICS_EXPORTER_TEMPLATE_FILE_NAME,
    METRICS_PORT,
)
from utils.utils import render_template

logger = logging.getLogger(__name__)


class MetricsExporterManager:
    """Manager class for etcd benchmark activity."""

    def start_metrics_exporter(self, config: dict[str, Any]) -> None:
        """Start the metrics exporter service for given test."""
        charm_dir = os.environ.get("CHARM_DIR", "")
        metrics_config = {
            "jsonl_path": f"{config.get('results_dir', '')}/stdout.jsonl",
            "test_id": str(config.get("current_test_id", "")),
            "metrics_port": METRICS_PORT,
            "python_bin": f"{charm_dir}/venv/bin/python",
            "runner_path": METRICS_EXPORTER_RUNNER_FILE_PATH,
        }

        rendered = render_template(
            Path(f"{charm_dir}/templates/{METRICS_EXPORTER_TEMPLATE_FILE_NAME}"), metrics_config
        )
        Path(METRICS_EXPORTER_SERVICE_FILE_PATH).write_text(rendered)
        systemd.daemon_reload()

        try:
            systemd.service_enable(METRICS_EXPORTER_SERVICE_NAME)
            systemd.service_start(METRICS_EXPORTER_SERVICE_NAME)
        except systemd.SystemdError as e:
            logger.error("Metric exporter service could not be enabled cleanly")
            raise e

    def stop_metrics_exporter(self) -> None:
        """Stop the metrics exporter service."""
        try:
            systemd.service_stop(METRICS_EXPORTER_SERVICE_NAME)
            systemd.service_disable(METRICS_EXPORTER_SERVICE_NAME)
        except systemd.SystemdError as e:
            logger.error("Metric exporter service could not be stopped")
            raise e
