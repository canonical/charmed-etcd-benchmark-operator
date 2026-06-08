#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Functions for managing and interacting with the workload.

The intention is that this module could be used outside the context of a charm.
"""

import logging
import subprocess
from pathlib import Path
from subprocess import CalledProcessError
from typing import Any

from charmlibs import snap, systemd
from tenacity import Retrying, retry, stop_after_attempt, wait_fixed
from typing_extensions import override

from common.exceptions import (
    BenchmarkServiceError,
    BenchmarkWorkloadError,
    MetricsExporterServiceError,
)
from core.workload import WorkloadBase
from literals import (
    BENCHMARK_SERVICE_FILE_PATH,
    BENCHMARK_SERVICE_NAME,
    BENCHMARK_TEMPLATE_FILE_NAME,
    METRICS_EXPORTER_SERVICE_FILE_PATH,
    METRICS_EXPORTER_SERVICE_NAME,
    METRICS_EXPORTER_TEMPLATE_FILE_NAME,
    SNAP_CHANNEL,
    SNAP_NAME,
)
from utils.utils import render_template

logger = logging.getLogger(__name__)


def _render_benchmark_service(templates_dir: str, config: dict[str, Any]) -> None:
    """Render the systemd service file from current charm config."""
    rendered = render_template(Path(f"{templates_dir}/{BENCHMARK_TEMPLATE_FILE_NAME}"), config)
    Path(BENCHMARK_SERVICE_FILE_PATH).write_text(rendered)
    systemd.daemon_reload()


def _render_metrics_exporter_service(templates_dir: str, config: dict[str, Any]) -> None:
    """Render the systemd service file from current charm config."""
    rendered = render_template(
        Path(f"{templates_dir}/{METRICS_EXPORTER_TEMPLATE_FILE_NAME}"), config
    )
    Path(METRICS_EXPORTER_SERVICE_FILE_PATH).write_text(rendered)
    systemd.daemon_reload()


class EtcdBenchmarkWorkload(WorkloadBase):
    """Implementation of WorkloadBase for running EtcdBenchmarkWorkload on VMs.

    This class manages the charmed-etcd snap (which includes the benchmark tool),
    and the systemd service that runs the benchmark.
    """

    def __init__(self):
        super().__init__()
        for attempt in Retrying(stop=stop_after_attempt(5), wait=wait_fixed(5)):
            with attempt:
                self.charmed_etcd_snap = snap.SnapCache()[SNAP_NAME]
        self.benchmark_tool = f"{SNAP_NAME}.benchmark"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(5),
        reraise=True,
    )
    def install(self) -> None:
        """Attempt charmed-etcd snap installation; raise on failure so tenacity retries."""
        self.charmed_etcd_snap.ensure(snap.SnapState.Present, channel=SNAP_CHANNEL)
        self.charmed_etcd_snap.hold()

    @override
    def verify_workload_ready(self) -> None:
        """Verify that the workload is available and ready."""
        logger.info("Benchmarking tool should be available. Checking...")
        try:
            help_text = subprocess.run(
                [self.benchmark_tool, "--help"], capture_output=True, check=True
            )
            logger.debug(f"Benchmark health check successful: {help_text.stdout}")
        except CalledProcessError as e:
            detailed_description = f"Error running --help smoke-test: {e}"
            logger.error(detailed_description)
            raise BenchmarkWorkloadError(
                message="Error verifying benchmark tool", detailed_description=detailed_description
            )

    @override
    def write_file(self, file: str, content: str | None = None) -> None:
        """Write a file at provided path."""
        path = Path(file)
        path.parent.mkdir(exist_ok=True, parents=True)
        # Ensure the file is created even when no payload is provided.
        path.write_text(content or "")

    @override
    def read_file(self, file: str) -> str | None:
        """Read the contents of a file at provided path."""
        path = Path(file)
        if not path.exists():
            return None
        return path.read_text()

    @override
    def file_exists(self, file_path: str | Path) -> bool:
        """Check if a directory exists."""
        return Path(file_path).exists()

    @override
    def start_benchmark(self, template_dir: str, config: dict[str, Any]) -> None:
        """Start the systemd benchmark service."""
        _render_benchmark_service(template_dir, config)
        try:
            systemd.service_enable(BENCHMARK_SERVICE_NAME)
            systemd.service_start(BENCHMARK_SERVICE_NAME)
        except systemd.SystemdError as e:
            detailed_error_str = f"Error starting benchmark service: {e}"
            logger.error(detailed_error_str)
            raise BenchmarkServiceError(
                message="Benchmark service could not be started cleanly",
                detailed_description=detailed_error_str,
            )

    @override
    def stop_benchmark(self) -> None:
        """Stop the systemd benchmark service."""
        if not self.is_benchmark_running():
            logger.info("Benchmark service is not running")
            return
        try:
            systemd.service_stop(BENCHMARK_SERVICE_NAME)
            systemd.service_disable(BENCHMARK_SERVICE_NAME)
        except systemd.SystemdError as e:
            detailed_error_str = f"Error stopping benchmark service: {e}"
            logger.error(detailed_error_str)
            raise BenchmarkServiceError(
                message="Benchmark service could not be stopped cleanly",
                detailed_description=detailed_error_str,
            )

    @override
    def is_benchmark_running(self) -> bool:
        """Return whether the benchmark service is active."""
        try:
            return systemd.service_running(BENCHMARK_SERVICE_NAME)
        except systemd.SystemdError:
            return False

    @override
    def start_metrics_exporter(self, template_dir: str, config: dict[str, Any]) -> None:
        """Start the metrics exporter service."""
        _render_metrics_exporter_service(template_dir, config)
        try:
            systemd.service_enable(METRICS_EXPORTER_SERVICE_NAME)
            systemd.service_start(METRICS_EXPORTER_SERVICE_NAME)
        except systemd.SystemdError as e:
            detailed_error_str = f"Error starting metrics exporter service: {e}"
            logger.error(detailed_error_str)
            raise MetricsExporterServiceError(
                message="Metrics exporter service could not be started cleanly",
                detailed_description=detailed_error_str,
            )

    @override
    def stop_metrics_exporter(self) -> None:
        """Stop the metrics exporter service."""
        try:
            systemd.service_stop(METRICS_EXPORTER_SERVICE_NAME)
            systemd.service_disable(METRICS_EXPORTER_SERVICE_NAME)
        except systemd.SystemdError as e:
            detailed_error_str = f"Error stopping metrics exporter service: {e}"
            logger.error(detailed_error_str)
            raise MetricsExporterServiceError(
                message="Metrics exporter service could not be stopped cleanly",
                detailed_description=detailed_error_str,
            )
