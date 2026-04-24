#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manage the benchmarking activity."""

import csv
import json
import logging
from datetime import UTC, datetime
from math import sqrt
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ops import Object

from common.exceptions import BenchmarkConfigurationError
from core.models import BenchmarkMetadata
from literals import (
    BENCHMARK_TESTS_ROOT_DIR,
    CA_CERT_PATH,
    CLIENT_CERT_PATH,
    CLIENT_KEY_PATH,
    METADATA_JSON_FILE_NAME,
    RESULT_CSV_HEADERS,
    RESULTS_CSV_FILE_NAME,
    SUMMARY_JSON_FILE_NAME,
)
from utils.utils import generate_test_id

if TYPE_CHECKING:
    from charm import CharmedEtcdBenchmarkOperatorCharm

logger = logging.getLogger(__name__)


class EtcdBenchmarkManager(Object):
    """Manager class for etcd benchmark activity."""

    def __init__(self, charm: "CharmedEtcdBenchmarkOperatorCharm"):
        super().__init__(charm, key="etcd-benchmark-manager")
        self.charm = charm

    def setup_test(self) -> dict[str, Any]:
        """Handle run action."""
        # Create unique test folder in the unit and create initial artifacts:
        # e.g: metadata file and a CSV in which to write benchmarking results.
        # Fire workload's start_service method, with charm configs, endpoints and CSV path.
        # Return success to console.

        uris = self.charm.etcd_interface_state.uris
        logger.debug(f"Endpoints available for txn-mixed: {uris}")

        started_at = datetime.now(UTC)
        test_id = generate_test_id(started_at)

        config = self.charm.config_manager.get_charm_config()

        if config.get("duration", 0) != 0 and config.get("total-transactions", 0) != 0:
            detailed_error_str = (
                "Both duration and total-transactions configs are set to non-zero values, "
                "which is invalid. "
                "Only ONE of the two can be specified. "
                "Please re-check, set valid config values and try again."
            )
            logger.error(detailed_error_str)
            raise BenchmarkConfigurationError(
                message="Both duration and total-transactions configs set",
                detailed_description=detailed_error_str,
            )

        results_csv_path = self._create_initial_test_artifacts(
            BenchmarkMetadata(
                test_name=str(self.charm.config.get("test-name")),
                test_id=test_id,
                started_at=started_at,
                test_config=config,
            )
        )

        config["current_test_id"] = test_id
        config["current_test_name"] = self.charm.config.get("test-name")
        config["results_csv_path"] = results_csv_path
        config["endpoints"] = uris
        config["client_cert_path"] = CLIENT_CERT_PATH
        config["client_key_path"] = CLIENT_KEY_PATH
        config["ca_cert_path"] = CA_CERT_PATH

        return config

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

    def get_test_summary(self, test_dir: str) -> str | None:
        """Get the summary of a benchmark test, given test ID."""
        # if summary.json exists and is_finalized, return the summary.
        # Else, try to prepare summary from CSV results (if they exist),
        # write to summary.json and return it.

        summary_path = Path(test_dir) / SUMMARY_JSON_FILE_NAME
        if summary_path.exists():
            try:
                with summary_path.open() as f:
                    summary = json.load(f)
                if summary.get("is_finalized", False):
                    return json.dumps(summary, indent=2)
            except (ValueError, OSError):
                logger.warning(
                    "summary.json at %s malformed; preparing summary from CSV results.",
                    summary_path,
                )

        return self._prepare_and_write_summary(test_dir)

    def _create_initial_test_artifacts(self, benchmark_metadata: BenchmarkMetadata) -> str:
        """Create filesystem artifacts for a newly started benchmark.

        Returns:
             path to the created results CSV.
        """
        # This test's metadata: Create the test directory for this benchmark test
        test_dir = Path(BENCHMARK_TESTS_ROOT_DIR) / benchmark_metadata.test_id
        Path(str(test_dir)).mkdir(parents=True, exist_ok=True)

        self.charm.workload.write_file(
            file=str(test_dir / METADATA_JSON_FILE_NAME),
            content=json.dumps(benchmark_metadata.to_dict(), indent=2) + "\n",
        )
        self.charm.workload.write_file(
            file=str(test_dir / RESULTS_CSV_FILE_NAME),
            content=(",".join(RESULT_CSV_HEADERS)) + "\n",
        )
        return str(test_dir / RESULTS_CSV_FILE_NAME)

    def _prepare_and_write_summary(self, test_dir: str) -> str:
        """Prepare summary from CSV results in test_dir, write to summary.json, and return it."""
        test_dir_path = Path(test_dir)
        summary_path = test_dir_path / SUMMARY_JSON_FILE_NAME
        metadata_path = test_dir_path / METADATA_JSON_FILE_NAME
        results_path = test_dir_path / RESULTS_CSV_FILE_NAME

        if not metadata_path.is_file():
            raise FileNotFoundError(f"Missing metadata file: {metadata_path}")
        if not results_path.is_file():
            raise FileNotFoundError(f"Missing results file: {results_path}")

        # Load metadata, to be appended to summary
        with metadata_path.open() as f:
            metadata = json.load(f)

        # Aggregation structure per op_type
        aggregates = self._aggregate_csv_results(results_path)

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
                "avg_stddev_latency_sec": round(sqrt(pooled_variance), 6),
            }

        summary = {
            "test_id": metadata.get("test_id"),
            "test_name": metadata.get("test_name"),
            "started_at": metadata.get("started_at"),
            "test_config": metadata.get("test_config", {}),
            "operations": operations,
            "is_finalized": not metadata.get("is_active", True),
        }

        summary_json = json.dumps(summary, indent=2)

        with summary_path.open("w") as f:
            f.write(summary_json + "\n")

        return summary_json

    def _aggregate_csv_results(self, results_path: Path) -> dict[str, dict[str, Any]]:
        """Read the CSV results file and return aggregated stats per op_type."""
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

                ops = int(r["total_ops"])
                rps = float(r["throughput_rps"])
                p50 = float(r["p50_latency_sec"])
                p90 = float(r["p90_latency_sec"])
                p99 = float(r["p99_latency_sec"])
                avg_lat = float(r["average_latency_sec"])
                stddev = float(r["stddev_latency_sec"])

                agg["samples"] += 1
                agg["total_ops"] += ops
                agg["throughput_sum"] += rps
                agg["p50_sum"] += p50
                agg["p90_sum"] += p90
                agg["p99_sum"] += p99
                agg["total_time_sum"] += avg_lat * ops

                if ops > 1:
                    weight = ops - 1
                    agg["stddev_accumulator"] += weight * (stddev * stddev)
                    agg["stddev_weight"] += weight

                agg["min_throughput"] = min(agg["min_throughput"], rps)
                agg["max_throughput"] = max(agg["max_throughput"], rps)

            if not seen_rows:
                raise ValueError(f"No benchmark data found in {results_path}")

        return aggregates
