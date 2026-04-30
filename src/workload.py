#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Functions for managing and interacting with the workload.

The intention is that this module could be used outside the context of a charm.
"""

import logging
import subprocess
from pathlib import Path
from typing import Any

from charmlibs import snap, systemd
from tenacity import Retrying, retry, stop_after_attempt, wait_fixed
from typing_extensions import override

from core.workload import WorkloadBase
from literals import (
    BENCHMARK_SERVICE_FILE_PATH,
    BENCHMARK_SERVICE_NAME,
    BENCHMARK_TEMPLATE_FILE_NAME,
    SNAP_CHANNEL,
    SNAP_NAME,
)
from utils.utils import render_template

logger = logging.getLogger(__name__)


def _render_service(templates_dir: str, config: dict[str, Any]) -> None:
    """Render the systemd service file from current charm config."""
    rendered = render_template(Path(f"{templates_dir}/{BENCHMARK_TEMPLATE_FILE_NAME}"), config)
    Path(BENCHMARK_SERVICE_FILE_PATH).write_text(rendered)
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
    def start(self) -> None:
        """Start the workload."""
        logger.info("Benchmarking tool should be available. Checking...")
        help_text = subprocess.run(
            [self.benchmark_tool, "--help"], capture_output=True, check=True
        )
        logger.debug(f"Benchmark health check successful: {help_text.stdout}")

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
    def start_service(self, template_dir: str, config: dict[str, Any]) -> None:
        """Start the benchmark service."""
        _render_service(template_dir, config)
        try:
            systemd.service_enable(BENCHMARK_SERVICE_NAME)
            systemd.service_start(BENCHMARK_SERVICE_NAME)
        except systemd.SystemdError as e:
            logger.error("Benchmark service could not be started cleanly")
            raise e

    @override
    def stop_service(self) -> None:
        """Stop the benchmark service."""
        if not self.is_running():
            logger.info("Benchmark service is not running")
            return
        try:
            systemd.service_stop(BENCHMARK_SERVICE_NAME)
            systemd.service_disable(BENCHMARK_SERVICE_NAME)
        except systemd.SystemdError as e:
            logger.error("Benchmark service could not be stopped cleanly")
            raise e

    @override
    def is_running(self) -> bool:
        """Return whether the benchmark service is active."""
        try:
            return systemd.service_running(BENCHMARK_SERVICE_NAME)
        except systemd.SystemdError:
            return False
