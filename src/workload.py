#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Functions for managing and interacting with the workload.

The intention is that this module could be used outside the context of a charm.
"""

import csv
import json
import logging
import subprocess
from pathlib import Path
from typing import Any

from charmlibs import snap, systemd
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from tenacity import Retrying, retry, stop_after_attempt, wait_fixed
from typing_extensions import override

from core.models import BenchmarkMetadata
from core.workload import WorkloadBase
from literals import (
    METADATA_JSON_FILE_NAME,
    SERVICE_FILE_PATH,
    SERVICE_NAME,
    SNAP_CHANNEL,
    SNAP_NAME,
    SUMMARY_JSON_FILE_NAME,
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
    def start_service(self, templates_dir: str, config: dict[str, Any]) -> None:
        """Start the benchmark service."""
        _render_service(templates_dir, config)
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
    def list_tests(self, tests_dir: str) -> list[tuple[str, str]]:
        """Return available benchmark result directory names and status, newest first."""
        test_dir = Path(tests_dir)
        if not test_dir.exists():
            return []

        results: list[tuple[str, str]] = []

        for path in sorted([p for p in test_dir.iterdir() if p.is_dir()], reverse=True):
            metadata_path = path / METADATA_JSON_FILE_NAME
            status = "unknown"

            if metadata_path.exists():
                try:
                    with metadata_path.open() as f:
                        data = json.load(f)
                    metadata = BenchmarkMetadata.from_dict(data)
                    status = "in progress" if metadata.is_active else "completed"
                except (OSError, json.JSONDecodeError, KeyError, ValueError) as e:
                    logger.warning("Failed to read metadata for test %s: %s", path.name, e)

            results.append((path.name, status))

        return results

    @override
    def prepare_and_write_summary(self, results_csv_path: str) -> str:
        """Prepare a summary from CSV results, write to a summary.json, return the serialized summary."""
        results_path = Path(results_csv_path)
        summary_path = results_path.parent / SUMMARY_JSON_FILE_NAME
        metadata_path = results_path.parent / METADATA_JSON_FILE_NAME

        if not metadata_path.is_file():
            raise FileNotFoundError(f"Missing metadata file: {metadata_path}")
        if not results_path.is_file():
            raise FileNotFoundError(f"Missing results file: {results_path}")

        # Load metadata
        with metadata_path.open() as f:
            metadata = json.load(f)

        # Aggregation structure per op_type
        aggregates: dict[str, dict[str, Any]] = {}

        with results_path.open(newline="") as f:
            reader = csv.DictReader(f)

            seen_rows = False

            for r in reader:
                seen_rows = True

                op_type = r["op_type"]

                agg = aggregates.setdefault(
                    op_type,
                    {
                        "samples": 0,
                        "total_ops": 0,
                        "throughput_sum": 0.0,
                        "p50_sum": 0.0,
                        "p90_sum": 0.0,
                        "p99_sum": 0.0,
                        "total_time_sum": 0.0,
                        "stddev_accumulator": 0.0,
                        "stddev_weight": 0,  # sum of (n_i - 1)
                        "min_throughput": float("inf"),
                        "max_throughput": float("-inf"),
                    },
                )

                # Parse once per row
                ops = int(r["total_ops"])
                rps = float(r["throughput_rps"])
                p50 = float(r["p50_latency_sec"])
                p90 = float(r["p90_latency_sec"])
                p99 = float(r["p99_latency_sec"])
                avg_lat = float(r["average_latency_sec"])
                stddev = float(r["stddev_latency_sec"])

                # Update aggregates
                agg["samples"] += 1
                agg["total_ops"] += ops

                agg["throughput_sum"] += rps
                agg["p50_sum"] += p50
                agg["p90_sum"] += p90
                agg["p99_sum"] += p99

                agg["total_time_sum"] += avg_lat * ops

                # Correct pooled variance accumulation
                if ops > 1:
                    weight = ops - 1
                    agg["stddev_accumulator"] += weight * (stddev * stddev)
                    agg["stddev_weight"] += weight

                if rps < agg["min_throughput"]:
                    agg["min_throughput"] = rps
                if rps > agg["max_throughput"]:
                    agg["max_throughput"] = rps

            if not seen_rows:
                raise ValueError(f"No benchmark data found in {results_path}")

        # Finalize metrics
        operations: dict[str, Any] = {}

        for op_type, agg in aggregates.items():
            n = agg["samples"]
            total_ops = agg["total_ops"]

            # Guard against division by 0 edge cases
            if total_ops == 0:
                avg_latency = 0.0
            else:
                avg_latency = agg["total_time_sum"] / total_ops

            if agg["stddev_weight"] > 0:
                pooled_variance = agg["stddev_accumulator"] / agg["stddev_weight"]
            else:
                pooled_variance = 0.0

            operations[op_type] = {
                "samples": n,
                "total_ops": total_ops,
                "mean_total_ops_per_sample": round(total_ops / n, 4),
                "mean_throughput_rps": round(agg["throughput_sum"] / n, 4),
                "min_throughput_rps": round(agg["min_throughput"], 4),
                "max_throughput_rps": round(agg["max_throughput"], 4),
                "avg_latency_sec": round(avg_latency, 6),
                "mean_p50_latency_sec": round(agg["p50_sum"] / n, 6),
                "mean_p90_latency_sec": round(agg["p90_sum"] / n, 6),
                "mean_p99_latency_sec": round(agg["p99_sum"] / n, 6),
                "avg_stddev_latency_sec": round(pooled_variance, 6),
            }

        summary = {
            "test_id": metadata.get("test_id"),
            "test_name": metadata.get("test_name"),
            "started_at": metadata.get("started_at"),
            "test_config": metadata.get("test_config", {}),
            "operations": operations,
        }

        summary_json = json.dumps(summary, indent=2)

        with summary_path.open("w") as f:
            f.write(summary_json + "\n")

        return summary_json

    def is_running(self) -> bool:
        """Return whether the benchmark service is active."""
        try:
            return systemd.service_running(SERVICE_NAME)
        except systemd.SystemdError:
            return False
