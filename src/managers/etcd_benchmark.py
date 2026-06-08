#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manage the benchmarking activity."""

import json
import logging
import re
from datetime import UTC, datetime
from math import sqrt
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ops import Object

from common.exceptions import BenchmarkConfigurationError, BenchmarkResultsParseError
from core.models import BenchmarkMetadata
from literals import (
    BENCHMARK_TESTS_ROOT_DIR,
    CA_CERT_PATH,
    CLIENT_CERT_PATH,
    CLIENT_KEY_PATH,
    METADATA_JSON_FILE_NAME,
    SUMMARY_JSON_FILE_NAME,
    TEST_RESULTS_DIR_NAME,
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
        """Handle run action.

        Returns:
            config dict to be passed to benchmark runner
        """
        # Create unique test folder in the unit and create initial artifacts:
        # 1) metadata file,
        # 2) /results dir in which to put stdout.jsonl and stderr.log from benchmark tool.
        # Return test configs to be passed to runner.

        uris = self.charm.etcd_interface_state.uris
        logger.debug(f"Endpoints available for txn-mixed: {uris}")

        started_at = datetime.now(UTC)
        test_id = generate_test_id(started_at)

        config = self._retrieve_config()

        if config.get("report_interval", 10) < 1:
            detailed_error_str = "`report-interval` must be set to an integer >= 1."
            logger.error(detailed_error_str)
            raise BenchmarkConfigurationError(
                message="Invalid report interval config set",
                detailed_description=detailed_error_str,
            )

        results_dir = self._create_initial_test_artifacts(
            BenchmarkMetadata(
                test_name=str(self.charm.config.get("test-name")),
                test_id=test_id,
                started_at=started_at,
                test_config=config,
            )
        )

        config["current_test_id"] = test_id
        config["current_test_name"] = self.charm.config.get("test-name")
        config["results_dir"] = results_dir
        config["endpoints"] = uris
        config["client_cert_path"] = CLIENT_CERT_PATH
        config["client_key_path"] = CLIENT_KEY_PATH
        config["ca_cert_path"] = CA_CERT_PATH

        return config

    def list_tests(self, tests_dir: str) -> list[tuple[str, str]]:
        """Return available benchmark result directory names and status, newest first."""
        test_dir = Path(tests_dir)
        if not self.charm.workload.file_exists(test_dir):
            return []

        results: list[tuple[str, str]] = []

        for path in sorted([p for p in test_dir.iterdir() if p.is_dir()], reverse=True):
            metadata_path = path / METADATA_JSON_FILE_NAME
            status = "unknown"

            if self.charm.workload.file_exists(metadata_path):
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
        # if summary.json exists, return this JSON.
        # Else, prepare summary afresh.

        try:
            summary_path = Path(test_dir) / SUMMARY_JSON_FILE_NAME
            if self.charm.workload.file_exists(summary_path):
                try:
                    return json.dumps(
                        json.loads(summary_path.read_text(encoding="utf-8")), indent=2
                    )
                except (ValueError, OSError):
                    logger.warning(
                        "summary.json at %s malformed; preparing summary from stdout.jsonl.",
                        summary_path,
                    )

            return self._prepare_and_write_summary(test_dir)
        except (OSError, ValueError, KeyError) as e:
            error_str = "Error preparing/writing summary"
            logger.error(f"{error_str}: {e}")
            raise BenchmarkResultsParseError(
                message=error_str, detailed_description=f"{error_str}: {e}"
            )

    def _retrieve_config(self) -> dict[str, Any]:
        """Read current charm config."""
        config = self.charm.config

        return {
            "clients": config.get("clients"),
            "connections": config.get("connections"),
            "rate": config.get("rate"),
            "key_size": config.get("key-size"),
            "key_space_size": config.get("key-space-size"),
            "value_size": config.get("value-size"),
            "limit": config.get("limit"),
            "rw_ratio": config.get("rw-ratio"),
            "duration": config.get("duration"),
            "total_transactions": config.get("total-transactions"),
            "report_interval": config.get("report-interval"),
        }

    def _create_initial_test_artifacts(self, benchmark_metadata: BenchmarkMetadata) -> str:
        """Create filesystem artifacts for a newly started benchmark.

        Returns:
             path to the created results dir, with stdout.jsonl and stderr.log.
        """
        # This test's metadata: Create the test directory for this benchmark test
        test_dir = Path(BENCHMARK_TESTS_ROOT_DIR) / benchmark_metadata.test_id
        Path(str(test_dir)).mkdir(parents=True, exist_ok=True)

        self.charm.workload.write_file(
            file=str(test_dir / METADATA_JSON_FILE_NAME),
            content=json.dumps(benchmark_metadata.to_dict(), indent=2) + "\n",
        )
        self.charm.workload.write_file(
            file=str(test_dir / TEST_RESULTS_DIR_NAME / "stdout.jsonl"),
        )
        self.charm.workload.write_file(
            file=str(test_dir / TEST_RESULTS_DIR_NAME / "stderr.log"),
        )
        return str(test_dir / TEST_RESULTS_DIR_NAME)

    def _prepare_and_write_summary(self, test_dir: str) -> str:
        """Prepare summary.

        Prepare summary from stdout/stderr in results dir,
        optionally write to summary.json, and return it.
        """
        # First try to find summary on stderr.log. Parse and persist to summary.json file.
        # If not found, prepare summary from stdout.jsonl.
        # If test has concluded, persist to summary.json file.

        test_dir_path = Path(test_dir)
        summary_path = test_dir_path / SUMMARY_JSON_FILE_NAME
        metadata_path = test_dir_path / METADATA_JSON_FILE_NAME
        results_dir = test_dir_path / TEST_RESULTS_DIR_NAME
        stdout_file = results_dir / "stdout.jsonl"
        stderr_file = results_dir / "stderr.log"

        if not self.charm.workload.file_exists(metadata_path):
            raise FileNotFoundError(f"Missing metadata file: {metadata_path}")
        if not self.charm.workload.file_exists(results_dir):
            raise FileNotFoundError(f"Missing results dir: {results_dir}")

        # Load metadata
        with metadata_path.open() as f:
            data = json.load(f)
        metadata = BenchmarkMetadata.from_dict(data)

        operations: dict[str, Any]

        if (
            not metadata.is_active
        ):  # test has concluded, so we can look for final summary in stderr
            if not self.charm.workload.file_exists(stderr_file):
                raise FileNotFoundError(f"Missing stderr file: {stderr_file}")
            try:
                operations = self._parse_final_operations_from_stderr(stderr_file)
            except ValueError as e:
                logger.warning(
                    "Failed to parse final summary from %s: %s. Falling back to stdout.jsonl.",
                    stderr_file,
                    e,
                )
                if not self.charm.workload.file_exists(stdout_file):
                    raise FileNotFoundError(f"Missing stdout file: {stdout_file}")
                aggregates = self._aggregate_jsonl_results(stdout_file)
                operations = self._build_operations_from_aggregates(aggregates)
        else:
            if not self.charm.workload.file_exists(stdout_file):
                raise FileNotFoundError(f"Missing stdout file: {stdout_file}")
            aggregates = self._aggregate_jsonl_results(stdout_file)
            operations = self._build_operations_from_aggregates(aggregates)

        summary = {
            "metadata": metadata.to_dict(),
            "operations": operations,
        }

        summary_json = json.dumps(summary, indent=2)

        # persist summary if test has stopped, as no further changes expected
        if not metadata.is_active:
            with summary_path.open("w") as f:
                f.write(summary_json + "\n")

        return summary_json

    def _parse_final_operations_from_stderr(self, stderr_path: Path) -> dict[str, dict[str, Any]]:
        """Parse the final read/write summary blocks from stderr.log."""
        stderr_text = stderr_path.read_text(encoding="utf-8")

        block_pattern = re.compile(
            r"Total\s+(?P<op>Read|Write)\s+Ops:\s*(?P<ops>\d+)"
            r"(?P<body>.*?)"
            r"(?=Total\s+(?:Read|Write)\s+Ops:|\Z)",
            flags=re.DOTALL,
        )

        operations: dict[str, dict[str, Any]] = {}

        for match in block_pattern.finditer(stderr_text):
            op_type = match.group("op").lower()
            ops = int(match.group("ops"))
            body = match.group("body")

            avg_latency = self._extract_float_metric(
                body, r"Average:\s*([0-9]*\.?[0-9]+)\s*secs\.?"
            )
            stddev = self._extract_float_metric(body, r"Stddev:\s*([0-9]*\.?[0-9]+)\s*secs\.?")
            rps = self._extract_float_metric(body, r"Requests/sec:\s*([0-9]*\.?[0-9]+)")
            p50 = self._extract_float_metric(body, r"\b50%\s+in\s+([0-9]*\.?[0-9]+)\s*secs\.?")
            p90 = self._extract_float_metric(body, r"\b90%\s+in\s+([0-9]*\.?[0-9]+)\s*secs\.?")
            p99 = self._extract_float_metric(body, r"\b99%\s+in\s+([0-9]*\.?[0-9]+)\s*secs\.?")

            operations[op_type] = {
                "total_ops": ops,
                "mean_throughput_rps": round(rps, 4),
                "min_throughput_rps": round(rps, 4),
                "max_throughput_rps": round(rps, 4),
                "avg_latency_sec": round(avg_latency, 6),
                "mean_p50_latency_sec": round(p50, 6),
                "mean_p90_latency_sec": round(p90, 6),
                "mean_p99_latency_sec": round(p99, 6),
                "avg_stddev_latency_sec": round(stddev, 6),
            }

        if "read" not in operations or "write" not in operations:
            raise ValueError("Could not find complete final read/write summary blocks")

        return operations

    def _extract_float_metric(self, text: str, pattern: str) -> float:
        """Extract a float value from text using a regex with one capturing group."""
        match = re.search(pattern, text)
        if not match:
            raise ValueError(f"Unable to extract metric with pattern: {pattern}")
        return float(match.group(1))

    def _build_operations_from_aggregates(
        self, aggregates: dict[str, dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        """Convert aggregated metrics into the summary operations structure."""
        operations: dict[str, dict[str, Any]] = {}

        for op_type, agg in aggregates.items():
            n = agg["samples"]
            total_ops = agg["total_ops"]

            avg_latency = 0.0 if total_ops == 0 else agg["total_time_sum"] / total_ops
            pooled_variance = (
                agg["stddev_accumulator"] / agg["stddev_weight"]
                if agg["stddev_weight"] > 0
                else 0.0
            )

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

        return operations

    def _parse_jsonl_payload(
        self, payload_raw: str, stdout_path: Path, line_no: int
    ) -> dict[str, Any]:
        """Parse one JSONL payload row and validate that it is a JSON object."""
        try:
            payload = json.loads(payload_raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in {stdout_path} at line {line_no}: {e.msg}") from e

        if not isinstance(payload, dict):
            raise ValueError(f"Invalid JSON object in {stdout_path} at line {line_no}")

        return payload

    def _extract_op_metrics(
        self, payload: dict[str, Any], op_type: str, stdout_path: Path, line_no: int
    ) -> tuple[int, float, float, float, float, float, float] | None:
        """Extract and coerce metrics for one op type from a parsed payload row."""
        op_metrics = payload.get(op_type)
        if op_metrics is None:
            return None
        if not isinstance(op_metrics, dict):
            raise ValueError(f"Invalid '{op_type}' metrics in {stdout_path} at line {line_no}")

        try:
            ops = int(op_metrics["ops"])
            rps = float(op_metrics["rps"])
            p50 = float(op_metrics["p50"])
            p90 = float(op_metrics["p90"])
            p99 = float(op_metrics["p99"])
            avg_lat = float(op_metrics["avg"])
            stddev = float(op_metrics["stddev"])
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(
                f"Malformed '{op_type}' metric in {stdout_path} , line {line_no}: {e}"
            ) from e

        return ops, rps, p50, p90, p99, avg_lat, stddev

    def _aggregate_jsonl_results(self, stdout_path: Path) -> dict[str, dict[str, Any]]:
        """Read stdout.jsonl results and return aggregated stats per op_type."""
        aggregates: dict[str, dict[str, Any]] = {}

        with stdout_path.open(encoding="utf-8") as f:
            seen_rows = False

            for line_no, line in enumerate(f, start=1):
                payload_raw = line.strip()
                if not payload_raw:
                    continue
                seen_rows = True

                payload = self._parse_jsonl_payload(payload_raw, stdout_path, line_no)

                for op_type in ("read", "write"):
                    metrics = self._extract_op_metrics(payload, op_type, stdout_path, line_no)
                    if metrics is None:
                        continue

                    ops, rps, p50, p90, p99, avg_lat, stddev = metrics

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

            if not seen_rows or not aggregates:
                raise ValueError(f"No benchmark data found in {stdout_path}")

        return aggregates
