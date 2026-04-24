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
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from tenacity import Retrying, retry, stop_after_attempt, wait_fixed
from typing_extensions import override

from core.workload import WorkloadBase
from literals import (
    SERVICE_FILE_PATH,
    SERVICE_NAME,
    SNAP_CHANNEL,
    SNAP_NAME,
    TEMPLATE_FILE_NAME,
)

logger = logging.getLogger(__name__)


def _render_template(templates_dir: str, context: dict[str, Any]) -> str:
    """Render a Jinja2 template from the charm templates directory."""
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template(TEMPLATE_FILE_NAME)
    return template.render(**context)


def _render_service(templates_dir: str, config: dict[str, Any]) -> None:
    """Render the systemd service file from current charm config."""
    rendered = _render_template(templates_dir, config)
    Path(SERVICE_FILE_PATH).write_text(rendered)
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
    def write_file(self, content: str, file: str) -> None:
        """Write a file at provided path."""
        path = Path(file)
        path.parent.mkdir(exist_ok=True, parents=True)
        path.write_text(content)

    @override
    def read_file(self, file: str) -> str | None:
        """Read the contents of a file at provided path."""
        path = Path(file)
        if not path.exists():
            return None
        return path.read_text()

    @override
    def file_exists(self, file_path: str) -> bool:
        """Check if a directory exists."""
        return Path(file_path).exists()

    @override
    def start_service(self, template_dir: str, config: dict[str, Any]) -> None:
        """Start the benchmark service."""
        _render_service(template_dir, config)
        try:
            systemd.service_enable(SERVICE_NAME)
        except systemd.SystemdError:
            # harmless if already enabled
            logger.debug("Service already enabled or could not enable cleanly")

        systemd.service_restart(SERVICE_NAME)

    @override
    def stop_service(self) -> None:
        """Stop the benchmark service."""
        if not self.is_running():
            logger.info("Benchmark service is not running")
            return
        systemd.service_stop(SERVICE_NAME)

    @override
    def is_running(self) -> bool:
        """Return whether the benchmark service is active."""
        try:
            return systemd.service_running(SERVICE_NAME)
        except systemd.SystemdError:
            return False
