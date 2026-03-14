#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Functions for managing and interacting with the workload.

The intention is that this module could be used outside the context of a charm.
"""

import logging
import subprocess
from pathlib import Path

from charmlibs import snap
from tenacity import Retrying, retry, stop_after_attempt, wait_fixed
from typing_extensions import override

from core.workload import WorkloadBase
from literals import CA_CERT_PATH, CLIENT_CERT_PATH, CLIENT_KEY_PATH, SNAP_CHANNEL, SNAP_NAME

logger = logging.getLogger(__name__)


class EtcdBenchmarkWorkload(WorkloadBase):
    """Implementation of WorkloadBase for running EtcdBenchmarkWorkload on VMs."""

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

    def run(self, endpoints: str) -> str:
        """Run `charmed-etcd.benchmark txn-mixed` command."""
        logger.info("Preparing to run benchmark put command...")
        put_benchmark = subprocess.check_output(
            [
                self.benchmark_tool,
                "txn-mixed",
                "--endpoints",
                endpoints,
                "--cert",
                CLIENT_CERT_PATH,
                "--key",
                CLIENT_KEY_PATH,
                "--cacert",
                CA_CERT_PATH,
            ]
        )
        logger.info(f"Benchmark put command successful: {put_benchmark.decode('utf-8').strip()}")
        return put_benchmark.decode("utf-8").strip()
