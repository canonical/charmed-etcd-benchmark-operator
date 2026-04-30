#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Run the charmed-etcd.benchmark snap command."""

from __future__ import annotations

import json
import logging
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [etcd-benchmark-runner] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

keep_running = True


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
        # TODO replace with charmed-etcd.benchmark snap command when available
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


def _mark_test_complete(results_dir: str) -> None:
    """Update metadata.json with is_active=false on runner exit."""
    metadata_path = Path(results_dir).parent / "metadata.json"
    if not metadata_path.exists():
        logger.warning("metadata.json not found at %s; skipping is_active update", metadata_path)
        return

    try:
        with metadata_path.open("r", encoding="utf-8") as f:
            metadata = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.exception("Failed to read metadata.json: %s", e)
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
    results_dir = _str_env("ETCD_BENCHMARK_RESULTS_DIR", "")
    stdout_path = Path(results_dir) / "stdout.jsonl"
    stderr_path = Path(results_dir) / "stderr.log"
    current_test_id = _str_env("ETCD_BENCHMARK_CURRENT_TEST_ID", "")
    current_test_name = _str_env("ETCD_BENCHMARK_CURRENT_TEST_NAME", "")

    stop_requested = False
    stop_request_monotonic: float | None = None
    graceful_stop_timeout_seconds = 30

    def _terminate_benchmark_process(p: subprocess.Popen, *, timeout_seconds: int = 5) -> None:
        """Terminate process and escalate to kill if it does not exit in time."""
        if p.poll() is not None:
            return  # already exited

        # terminate gracefully. If timed out, kill.
        os.killpg(os.getpgid(p.pid), signal.SIGTERM)
        try:
            p.wait(timeout=timeout_seconds)
            return
        except subprocess.TimeoutExpired:
            logger.warning("Process did not terminate in time; killing (pid=%s)", p.pid)

        os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            logger.error("Process refused to die (pid=%s)", p.pid)

    def _finalize_exit(exit_code: int) -> int:
        _clear_benchmark_data()
        _mark_test_complete(results_dir)
        return exit_code

    if not results_dir:
        logger.error("ETCD_BENCHMARK_RESULTS_DIR is not set")
        return 1
    if not current_test_id:
        logger.error("ETCD_BENCHMARK_CURRENT_TEST_ID is not set")
        return _finalize_exit(1)
    if not current_test_name:
        logger.error("ETCD_BENCHMARK_CURRENT_TEST_NAME is not set")
        return _finalize_exit(1)

    logger.info("Benchmark service triggered for test id=%s, name=%s", current_test_id, current_test_name)

    if _duration_expired(start_time, duration):
        logger.info("Configured duration (%s seconds) elapsed before start", duration)
        return _finalize_exit(0)

    cmd = _build_command()
    logger.info("Triggering benchmark command: %s", shlex.join(cmd))

    try:
        stdout_file = stdout_path.open("a", encoding="utf-8")
        stderr_file = stderr_path.open("a", encoding="utf-8")
    except OSError:
        logger.exception(
            "Failed to open output files stdout=%s stderr=%s",
            stdout_path,
            stderr_path,
        )
        return _finalize_exit(1)

    try:
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                text=True,
                preexec_fn=os.setsid,
            )
        except FileNotFoundError:
            logger.exception("Benchmark command not found")
            return _finalize_exit(1)
        except Exception:
            logger.exception("Failed to start benchmark command")
            return _finalize_exit(1)

        try:
            while True:
                if not stop_requested:
                    if not keep_running or _duration_expired(start_time, duration):
                        logger.info("Termination requested; waiting for benchmark to exit")
                        _terminate_benchmark_process(proc, timeout_seconds=20)
                        stop_requested = True
                        stop_request_monotonic = time.monotonic()

                if proc.poll() is not None:
                    # Process has exited
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

                time.sleep(1)

        except Exception:
            logger.exception("Error while waiting for benchmark process")
            _terminate_benchmark_process(proc)
            return _finalize_exit(1)

        rc = proc.returncode
        if rc is None:
            logger.error("Benchmark process exit code unavailable")
            return _finalize_exit(1)

        if rc != 0 and rc != -15:  # -15 is SIGTERM
            logger.error("Benchmark exited unexpectedly with return code %s", rc)
            return _finalize_exit(rc)

        logger.info("Benchmark runner exiting cleanly...")
        return _finalize_exit(0)
    finally:
        stdout_file.close()
        stderr_file.close()


if __name__ == "__main__":
    sys.exit(main())