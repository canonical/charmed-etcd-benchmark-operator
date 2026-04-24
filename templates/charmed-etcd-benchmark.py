#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Run the charmed-etcd.benchmark snap command."""

from __future__ import annotations

import csv
import json
import logging
import os
import re
import select
import shlex
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, UTC
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [etcd-benchmark-runner] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

keep_running = True


RESULT_CSV_HEADERS = [
    "timestamp",
    "sample_number",
    "test_id",
    "test_name",
    "op_type",
    "total_ops",
    "average_latency_sec",
    "stddev_latency_sec",
    "throughput_rps",
    "p50_latency_sec",
    "p90_latency_sec",
    "p99_latency_sec",
]

FINAL_SUMMARY_BLOCK_RE = re.compile(
    r"Total (?P<type>Read|Write) Ops:\s*(?P<total>\d+)(?P<body>.*?)(?=Total (?:Read|Write) Ops:|\Z)",
    re.S,
)
FINAL_SUMMARY_AVERAGE_RE = re.compile(r"Average:\s*(?P<value>[0-9.]+)\s*secs\.")
FINAL_SUMMARY_STDDEV_RE = re.compile(r"Stddev:\s*(?P<value>[0-9.]+)\s*secs\.")
FINAL_SUMMARY_RPS_RE = re.compile(r"Requests/sec:\s*(?P<value>[0-9.]+)")
FINAL_SUMMARY_P50_RE = re.compile(r"50%\s+in\s+(?P<value>[0-9.]+)\s+secs\.")
FINAL_SUMMARY_P90_RE = re.compile(r"90%\s+in\s+(?P<value>[0-9.]+)\s+secs\.")
FINAL_SUMMARY_P99_RE = re.compile(r"99%\s+in\s+(?P<value>[0-9.]+)\s+secs\.")


@dataclass
class BenchmarkOperationResult:
    """Typed result for one benchmark operation class (read/write)."""

    total_ops: int
    average_latency_sec: float
    stddev_latency_sec: float
    throughput_rps: float
    p50_latency_sec: float
    p90_latency_sec: float
    p99_latency_sec: float


@dataclass
class BenchmarkResults:
    """Typed results for one benchmark sample collected."""

    read: BenchmarkOperationResult
    write: BenchmarkOperationResult


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}

def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    return int(value)

def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if not value:
        return default
    return float(value)

def _str_env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def _handle_exit(*_args, **_kwargs) -> None:
    """Handle SIGTERM/SIGINT by requesting a stop."""
    global keep_running
    if keep_running:
        logger.info(
            "Received termination signal; will stop the test."
        )
    keep_running = False


def _build_command() -> list[str]:
    """Build the benchmark command from environment variables."""
    endpoints = _str_env("ETCD_BENCHMARK_ENDPOINTS", "")
    clients = _int_env("ETCD_BENCHMARK_CLIENTS", 1)
    connections = _int_env("ETCD_BENCHMARK_CONNECTIONS", 1)
    rate = _int_env("ETCD_BENCHMARK_RATE", 0)
    key_size = _int_env("ETCD_BENCHMARK_KEY_SIZE", 8)
    key_space_size = _int_env("ETCD_BENCHMARK_KEY_SPACE_SIZE", 1000)
    value_size = _int_env("ETCD_BENCHMARK_VALUE_SIZE", 8)
    limit = _int_env("ETCD_BENCHMARK_LIMIT", 1000)
    rw_ratio = _float_env("ETCD_BENCHMARK_RW_RATIO", 1.0)
    report_interval = _int_env("ETCD_BENCHMARK_REPORT_INTERVAL", 10)
    total_transactions = _int_env("ETCD_BENCHMARK_TOTAL_TRANSACTIONS", 0)
    client_cert_path = _str_env("ETCD_BENCHMARK_CLIENT_CERT_PATH", "")
    client_key_path = _str_env("ETCD_BENCHMARK_CLIENT_KEY_PATH", "")
    ca_cert_path = _str_env("ETCD_BENCHMARK_CA_CERT_PATH", "")

    if total_transactions == 0:
        total_transactions = 2147483647
        # If no total set,
        # the --total passed to the benchmark tool is set to the max int in Go, i.e 2^31-1 in 32-bit systems.
        # This means the test goes on "indefinitely" (as long as 2^31 transactions take as per rate and given machine),
        # until either (case 1). stop action is run OR (case 2). duration, if set to a non-zero value, is exceeded.

    cmd = [
        #TODO replace with charmed-etcd.benchmark snap command when available
        "/var/lib/juju/agents/unit-charmed-etcd-benchmark-operator-0/charm/bin/benchmark",
        "txn-mixed",
        "--endpoints", endpoints,
        "--cert", client_cert_path,
        "--key", client_key_path,
        "--cacert", ca_cert_path,
        "--clients", str(clients),
        "--conns", str(connections),
        "--rate", str(rate),
        "--key-size", str(key_size),
        "--key-space-size", str(key_space_size),
        "--val-size", str(value_size),
        "--limit", str(limit),
        "--rw-ratio", str(rw_ratio),
        "--total", str(total_transactions),
        "--report-interval", str(report_interval)
    ]

    return cmd


def _duration_expired(start_time: float, duration: int) -> bool:
    """Return True if total runtime duration has been crossed."""
    if duration <= 0:
        return False
    return (time.monotonic() - start_time) >= duration


def _build_csv_row(
    *,
    timestamp: str,
    sample_number: int,
    test_id: str,
    test_name: str,
    op_type: str,
    result: BenchmarkOperationResult,
) -> dict[str, str | int | float]:
    """Build a single CSV row for one benchmark operation result."""
    return {
        "timestamp": timestamp,
        "sample_number": sample_number,
        "test_id": test_id,
        "test_name": test_name,
        "op_type": op_type,
        "total_ops": result.total_ops,
        "average_latency_sec": result.average_latency_sec,
        "stddev_latency_sec": result.stddev_latency_sec,
        "throughput_rps": result.throughput_rps,
        "p50_latency_sec": result.p50_latency_sec,
        "p90_latency_sec": result.p90_latency_sec,
        "p99_latency_sec": result.p99_latency_sec,
    }


def _append_csv_rows(
    results_csv_path: str,
    rows: list[dict[str, str | int | float]],
) -> None:
    """Append result rows to the already-initialized CSV file."""
    path = Path(results_csv_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Results CSV does not exist: {results_csv_path}. "
            "The manager should create it with headers before starting the service."
        )

    with path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=RESULT_CSV_HEADERS)
        writer.writerows(rows)


def _mark_test_complete(results_csv_path: str) -> None:
    """Update metadata.json with is_active=false on runner exit."""
    if not results_csv_path:
        return

    metadata_path = Path(results_csv_path).parent / "metadata.json"
    if not metadata_path.exists():
        logger.warning("metadata.json not found at %s; skipping is_active update", metadata_path)
        return

    try:
        with metadata_path.open("r", encoding="utf-8") as f:
            metadata = json.load(f)
    except json.JSONDecodeError:
        logger.exception("metadata.json is not valid JSON: %s", metadata_path)
        return
    except OSError:
        logger.exception("Failed to read metadata.json: %s", metadata_path)
        return

    if not isinstance(metadata, dict):
        logger.error("metadata.json does not contain a JSON object: %s", metadata_path)
        return

    metadata["is_active"] = False

    try:
        with metadata_path.open("w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
            f.write("\n")
    except OSError:
        logger.exception("Failed to write metadata.json: %s", metadata_path)
        return

    logger.info("Marked test inactive in metadata.json at %s", metadata_path)


def _parse_intermediate_json_result(json_line: str) -> BenchmarkResults | None:
    """Parse a single JSON intermediate result line from benchmark output.

    Returns BenchmarkResults if parsing succeeds, None if the line is not valid JSON.
    Raises ValueError if JSON structure is invalid.
    """
    try:
        data = json.loads(json_line)
    except json.JSONDecodeError:
        return None

    try:
        read_data = data.get("read", {})
        write_data = data.get("write", {})

        # Intermediate results use "ops" for total operations and "rps" for throughput
        read_result = BenchmarkOperationResult(
            total_ops=read_data.get("ops", 0),
            average_latency_sec=read_data.get("avg", 0.0),
            stddev_latency_sec=read_data.get("stddev", 0.0),
            throughput_rps=read_data.get("rps", 0.0),
            p50_latency_sec=read_data.get("p50", 0.0),
            p90_latency_sec=read_data.get("p90", 0.0),
            p99_latency_sec=read_data.get("p99", 0.0),
        )

        write_result = BenchmarkOperationResult(
            total_ops=write_data.get("ops", 0),
            average_latency_sec=write_data.get("avg", 0.0),
            stddev_latency_sec=write_data.get("stddev", 0.0),
            throughput_rps=write_data.get("rps", 0.0),
            p50_latency_sec=write_data.get("p50", 0.0),
            p90_latency_sec=write_data.get("p90", 0.0),
            p99_latency_sec=write_data.get("p99", 0.0),
        )

        return BenchmarkResults(read=read_result, write=write_result)
    except (KeyError, TypeError) as e:
        raise ValueError(f"Invalid intermediate JSON result structure: {e}")


def _persist_intermediate_results(
    *,
    json_line: str,
    sample_number: int,
    results_csv_path: str,
    test_id: str,
    test_name: str,
) -> BenchmarkResults:
    """Parse intermediate JSON result and append to the CSV."""
    results = _parse_intermediate_json_result(json_line)
    if results is None:
        raise ValueError(f"Line is not valid JSON: {json_line}")

    timestamp = datetime.now(UTC).isoformat()

    rows = [
        _build_csv_row(
            timestamp=timestamp,
            sample_number=sample_number,
            test_id=test_id,
            test_name=test_name,
            op_type="read",
            result=results.read,
        ),
        _build_csv_row(
            timestamp=timestamp,
            sample_number=sample_number,
            test_id=test_id,
            test_name=test_name,
            op_type="write",
            result=results.write,
        ),
    ]

    _append_csv_rows(results_csv_path, rows)

    logger.info(
        "Persisted intermediate benchmark results for test_id=%s sample_number=%s",
        test_id,
        sample_number,
    )

    return results


def _parse_final_benchmark_output(raw_output: str) -> BenchmarkResults:
    """Parse final benchmark output into final read/write summary metrics."""
    results: dict[str, BenchmarkOperationResult] = {}

    for match in FINAL_SUMMARY_BLOCK_RE.finditer(raw_output):
        op_type = match.group("type").lower()
        total_ops = int(match.group("total"))
        body = match.group("body")

        average_match = FINAL_SUMMARY_AVERAGE_RE.search(body)
        stddev_match = FINAL_SUMMARY_STDDEV_RE.search(body)
        rps_match = FINAL_SUMMARY_RPS_RE.search(body)
        p50_match = FINAL_SUMMARY_P50_RE.search(body)
        p90_match = FINAL_SUMMARY_P90_RE.search(body)
        p99_match = FINAL_SUMMARY_P99_RE.search(body)

        if not all(
            [
                average_match,
                stddev_match,
                rps_match,
                p50_match,
                p90_match,
                p99_match,
            ]
        ):
            raise ValueError(f"Failed to parse complete benchmark metrics for {op_type} output")

        results[op_type] = BenchmarkOperationResult(
            total_ops=total_ops,
            average_latency_sec=float(average_match.group("value")),
            stddev_latency_sec=float(stddev_match.group("value")),
            throughput_rps=float(rps_match.group("value")),
            p50_latency_sec=float(p50_match.group("value")),
            p90_latency_sec=float(p90_match.group("value")),
            p99_latency_sec=float(p99_match.group("value")),
        )

    if "read" not in results or "write" not in results:
        raise ValueError("Benchmark output did not contain both read and write results")

    return BenchmarkResults(read=results["read"], write=results["write"])


def _summary_operation_dict(result: BenchmarkOperationResult) -> dict[str, int | float]:
    """Return JSON-serializable summary fields for one operation type."""
    return {
        "total_ops": result.total_ops,
        "throughput_rps": result.throughput_rps,
        "average_latency_sec": result.average_latency_sec,
        "stddev_latency_sec": result.stddev_latency_sec,
        "p50_latency_sec": result.p50_latency_sec,
        "p90_latency_sec": result.p90_latency_sec,
        "p99_latency_sec": result.p99_latency_sec,
    }


def _persist_final_summary(results_csv_path: str, summary: BenchmarkResults) -> None:
    """Write (rewrite, if previously generated) summary.json with final benchmark summary stats."""
    summary_path = Path(results_csv_path).parent / "summary.json"
    metadata_path = Path(results_csv_path).parent / "metadata.json"

    read_summary = _summary_operation_dict(summary.read)
    write_summary = _summary_operation_dict(summary.write)
    payload : dict[str, object] = {
        "operations": {
            "read": read_summary,
            "write": write_summary,
        },
        "test_id": None,
        "test_name": None,
        "started_at": None,
        "test_config": {},
        "is_finalized": True,
    }

    # Include test metadata when available; still persist summary if metadata is absent.
    metadata: dict[str, object] = {}
    if not metadata_path.exists():
        logger.warning("metadata.json not found at %s; writing summary without metadata", metadata_path)
    else:
        try:
            with metadata_path.open("r", encoding="utf-8") as f:
                raw_metadata = json.load(f)
            if isinstance(raw_metadata, dict):
                metadata = raw_metadata
            else:
                logger.error(
                    "metadata.json does not contain a JSON object: %s; writing summary without metadata",
                    metadata_path,
                )
        except json.JSONDecodeError:
            logger.exception("metadata.json is not valid JSON: %s", metadata_path)
        except OSError:
            logger.exception("Failed to read metadata.json: %s", metadata_path)

    payload["test_id"] = metadata.get("test_id")
    payload["test_name"] = metadata.get("test_name")
    payload["started_at"] = metadata.get("started_at")
    payload["test_config"] = metadata.get("test_config", {})

    try:
        with summary_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
    except OSError:
        logger.exception("Failed to write final summary to %s", summary_path)
        return

    logger.info("Wrote final benchmark summary to %s", summary_path)


def _clear_benchmark_data() -> None:
    """Clear any benchmark-written data left in etcd."""
    endpoints = _str_env("ETCD_BENCHMARK_ENDPOINTS", "")
    client_cert_path = _str_env("ETCD_BENCHMARK_CLIENT_CERT_PATH", "")
    client_key_path = _str_env("ETCD_BENCHMARK_CLIENT_KEY_PATH", "")
    ca_cert_path = _str_env("ETCD_BENCHMARK_CA_CERT_PATH", "")

    cmd = [
        "charmed-etcd.etcdctl",
        "del",
        "",
        "--from-key",
        "--endpoints", endpoints,
        "--cert", client_cert_path,
        "--key", client_key_path,
        "--cacert", ca_cert_path,
    ]

    logger.info("Clearing benchmark data from etcd: %s", shlex.join(cmd))

    try:
        proc = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except Exception:
        logger.exception("Failed to clear benchmark data")
        return

    if proc.stdout:
        logger.info("Benchmark cleanup stdout:\n%s", proc.stdout)
    if proc.stderr:
        logger.info("Benchmark cleanup stderr:\n%s", proc.stderr)

    if proc.returncode != 0:
        logger.error("Benchmark cleanup failed with return code %s", proc.returncode)


def main() -> int:
    """Main service."""
    signal.signal(signal.SIGTERM, _handle_exit)
    signal.signal(signal.SIGINT, _handle_exit)

    duration = _int_env("ETCD_BENCHMARK_DURATION", 0)
    start_time = time.monotonic()
    results_csv_path = _str_env("ETCD_BENCHMARK_RESULTS_CSV_PATH", "")
    current_test_id = _str_env("ETCD_BENCHMARK_CURRENT_TEST_ID", "")
    current_test_name = _str_env("ETCD_BENCHMARK_CURRENT_TEST_NAME", "")

    sample_number = 1
    summary_output_parts: list[str] = []
    stop_requested = False
    stop_request_monotonic: float | None = None
    graceful_stop_timeout_seconds = 30

    def _terminate_benchmark_process(p: subprocess.Popen, *, timeout_seconds: int = 5) -> None:
        """Terminate process and escalate to kill if it does not exit in time."""
        if p.poll() is not None:
            return  # already exited

        # terminate gracefully. If timed out, kill.
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        try:
            p.wait(timeout=timeout_seconds)
            return
        except subprocess.TimeoutExpired:
            logger.warning("Process did not terminate in time; killing (pid=%s)", p.pid)

        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            logger.error("Process refused to die (pid=%s)", p.pid)

    def _finalize_exit(exit_code: int) -> int:
        _clear_benchmark_data()
        _mark_test_complete(results_csv_path)
        return exit_code

    if not results_csv_path:
        logger.error("ETCD_BENCHMARK_RESULTS_CSV_PATH is not set")
        return 1
    if not current_test_id:
        logger.error("ETCD_BENCHMARK_CURRENT_TEST_ID is not set")
        return _finalize_exit(1)
    if not current_test_name:
        logger.error("ETCD_BENCHMARK_CURRENT_TEST_NAME is not set")
        return _finalize_exit(1)

    def _process_output_line(line: str) -> bool:
        nonlocal sample_number
        raw_line = line if line.endswith("\n") else f"{line}\n"
        line = line.rstrip("\n")

        try:
            parsed_result = _parse_intermediate_json_result(line)
            if parsed_result is not None:
                _persist_intermediate_results(
                    json_line=line,
                    sample_number=sample_number,
                    results_csv_path=results_csv_path,
                    test_id=current_test_id,
                    test_name=current_test_name,
                )
                sample_number += 1
                return True

            summary_output_parts.append(raw_line)

            if not line:
                return True

            logger.debug("Benchmark output: %s", line)
        except ValueError:
            logger.debug("Could not parse benchmark output line: %s", line)
        except Exception:
            logger.exception("Failed processing benchmark output line: %s", line)
            return False

        return True

    logger.info("Benchmark service triggered for test id=%s, name=%s", current_test_id, current_test_name)

    if _duration_expired(start_time, duration):
        logger.info("Configured duration (%s seconds) elapsed before start", duration)
        return _finalize_exit(0)

    cmd = _build_command()
    logger.info("Triggering benchmark command: %s", shlex.join(cmd))

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,  # Line buffering
            preexec_fn=os.setsid,
        )
    except FileNotFoundError:
        logger.exception("Benchmark command not found")
        return _finalize_exit(1)
    except Exception:
        logger.exception("Failed to start benchmark command")
        return _finalize_exit(1)

    if proc.stdout is None:
        logger.error("Failed to get stdout stream from benchmark process")
        _terminate_benchmark_process(proc)
        return _finalize_exit(1)

    # Non-blocking read loop using select, continue reading after SIGTERM to drain final summary
    try:
        while True:
            if not stop_requested:
                if not keep_running or _duration_expired(start_time, duration):
                    logger.info("Termination requested; waiting for benchmark to exit")
                    _terminate_benchmark_process(proc, timeout_seconds=20)
                    stop_requested = True
                    stop_request_monotonic = time.monotonic()

            rlist, _, _ = select.select([proc.stdout], [], [], 1.0)
            if rlist:
                line = proc.stdout.readline()
                if line and not _process_output_line(line):
                    _terminate_benchmark_process(proc)
                    return _finalize_exit(1)

            if proc.poll() is not None:
                # Process has exited; drain remaining stdout (for final summary) before breaking
                remaining_in_loop = proc.stdout.read()
                if remaining_in_loop:
                    for line in remaining_in_loop.splitlines(keepends=True):
                        _process_output_line(line)
                break

            if stop_requested and stop_request_monotonic is not None:
                elapsed = time.monotonic() - stop_request_monotonic
                if elapsed >= graceful_stop_timeout_seconds:
                    logger.warning(
                        "Benchmark did not exit after SIGTERM within %s seconds; forcing stop",
                        graceful_stop_timeout_seconds,
                    )
                    _terminate_benchmark_process(proc, timeout_seconds=0)
                    break

    except Exception:
        logger.exception("Error while reading benchmark output")
        _terminate_benchmark_process(proc)
        return _finalize_exit(1)

    # Drain remaining stdout/stderr after process exits.
    try:
        remaining_stdout, _ = proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        logger.warning("Timeout while collecting process output; forcing termination")
        _terminate_benchmark_process(proc)
        remaining_stdout, _ = proc.communicate()

    for line in remaining_stdout.splitlines(keepends=True):
        if not _process_output_line(line):
            return _finalize_exit(1)

    # gather the collected final summary lines and parse to obtain final summary.json
    raw_summary_output = "".join(summary_output_parts)
    try:
        summary_results = _parse_final_benchmark_output(raw_summary_output)
    except ValueError as exc:
        if stop_requested or "Total Read Ops:" in raw_summary_output or "Total Write Ops:" in raw_summary_output:
            logger.warning("Benchmark exited without a complete final summary: %s", exc)
    else:
        _persist_final_summary(results_csv_path, summary_results)

    rc = proc.returncode
    if rc is None:
        logger.error("Benchmark process exit code unavailable")
        return _finalize_exit(1)

    if rc != 0 and rc != -15:  # -15 is SIGTERM
        logger.error("Benchmark exited unexpectedly with return code %s", rc)
        return _finalize_exit(rc)

    logger.info("Benchmark runner exiting cleanly...")
    return _finalize_exit(0)


if __name__ == "__main__":
    sys.exit(main())