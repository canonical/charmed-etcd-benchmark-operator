#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for the benchmark service runner template script."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def runner_module() -> ModuleType:
    """Load the runner script as a Python module."""
    script_path = Path(__file__).resolve().parents[2] / "templates" / "charmed-etcd-benchmark.py"
    spec = importlib.util.spec_from_file_location("benchmark_runner", script_path)
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.keep_running = True
    return module


def test_env_helpers(runner_module: ModuleType) -> None:
    """Environment helper functions return parsed values and defaults."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("TEST_BOOL", None)
        os.environ.pop("TEST_INT", None)
        os.environ.pop("TEST_FLOAT", None)
        os.environ.pop("TEST_STR", None)

        assert runner_module._bool_env("TEST_BOOL", default=True) is True
        assert runner_module._int_env("TEST_INT", 5) == 5
        assert runner_module._float_env("TEST_FLOAT", 1.5) == 1.5
        assert runner_module._str_env("TEST_STR", "fallback") == "fallback"

        env_vars = {
            "TEST_BOOL": "yes",
            "TEST_INT": "42",
            "TEST_FLOAT": "3.25",
            "TEST_STR": "value",
        }
        with patch.dict(os.environ, env_vars):
            assert runner_module._bool_env("TEST_BOOL") is True
            assert runner_module._int_env("TEST_INT", 0) == 42
            assert runner_module._float_env("TEST_FLOAT", 0.0) == 3.25
            assert runner_module._str_env("TEST_STR") == "value"


def test_duration_expired(runner_module: ModuleType) -> None:
    """Duration helper uses monotonic elapsed time and disabled duration semantics."""
    with patch.object(runner_module.time, "monotonic", return_value=12.0):
        assert runner_module._duration_expired(start_time=10.0, duration=2) is True
        assert runner_module._duration_expired(start_time=10.0, duration=0) is False


def test_build_command_total_uses_report_interval(runner_module: ModuleType) -> None:
    """When duration is 0, --total is based on report interval."""
    env = {
        "ETCD_BENCHMARK_ENDPOINTS": "https://10.0.0.1:2379",
        "ETCD_BENCHMARK_CLIENTS": "2",
        "ETCD_BENCHMARK_CONNECTIONS": "3",
        "ETCD_BENCHMARK_RATE": "100",
        "ETCD_BENCHMARK_KEY_SIZE": "8",
        "ETCD_BENCHMARK_KEY_SPACE_SIZE": "100",
        "ETCD_BENCHMARK_VALUE_SIZE": "8",
        "ETCD_BENCHMARK_LIMIT": "1000",
        "ETCD_BENCHMARK_RW_RATIO": "0.6",
        "ETCD_BENCHMARK_DURATION": "0",
        "ETCD_BENCHMARK_REPORT_INTERVAL": "10",
        "ETCD_BENCHMARK_CLIENT_CERT_PATH": "/tmp/client.crt",
        "ETCD_BENCHMARK_CLIENT_KEY_PATH": "/tmp/client.key",
        "ETCD_BENCHMARK_CA_CERT_PATH": "/tmp/ca.crt",
    }

    with patch.dict(os.environ, env):
        command = runner_module.build_command()

    assert command[0:2] == ["charmed-etcd.benchmark", "txn-mixed"]
    assert "--total" in command
    total_index = command.index("--total")
    assert command[total_index + 1] == "1000"


def test_build_command_total_uses_short_duration(runner_module: ModuleType) -> None:
    """When duration is shorter than report interval, --total uses duration."""
    env = {
        "ETCD_BENCHMARK_ENDPOINTS": "https://10.0.0.1:2379",
        "ETCD_BENCHMARK_CLIENTS": "1",
        "ETCD_BENCHMARK_CONNECTIONS": "1",
        "ETCD_BENCHMARK_RATE": "50",
        "ETCD_BENCHMARK_KEY_SIZE": "8",
        "ETCD_BENCHMARK_KEY_SPACE_SIZE": "100",
        "ETCD_BENCHMARK_VALUE_SIZE": "8",
        "ETCD_BENCHMARK_LIMIT": "1000",
        "ETCD_BENCHMARK_RW_RATIO": "1.0",
        "ETCD_BENCHMARK_DURATION": "3",
        "ETCD_BENCHMARK_REPORT_INTERVAL": "10",
        "ETCD_BENCHMARK_CLIENT_CERT_PATH": "/tmp/client.crt",
        "ETCD_BENCHMARK_CLIENT_KEY_PATH": "/tmp/client.key",
        "ETCD_BENCHMARK_CA_CERT_PATH": "/tmp/ca.crt",
    }

    with patch.dict(os.environ, env):
        command = runner_module.build_command()

    total_index = command.index("--total")
    assert command[total_index + 1] == "150"


def test_parse_raw_benchmark_output_success(runner_module: ModuleType) -> None:
    """Benchmark output parser returns both read/write metric dictionaries."""
    output = """
Total Read Ops: 100
Average: 0.100 secs.
Stddev: 0.050 secs.
Requests/sec: 250.0
50% in 0.080 secs.
90% in 0.150 secs.
99% in 0.300 secs.

Total Write Ops: 70
Average: 0.120 secs.
Stddev: 0.060 secs.
Requests/sec: 200.0
50% in 0.090 secs.
90% in 0.170 secs.
99% in 0.350 secs.
"""

    parsed = runner_module._parse_raw_benchmark_output(output)

    assert parsed["read"]["total_ops"] == 100
    assert parsed["read"]["throughput_rps"] == 250.0
    assert parsed["write"]["total_ops"] == 70
    assert parsed["write"]["p99_latency_sec"] == 0.35


def test_parse_raw_benchmark_output_missing_write_fails(runner_module: ModuleType) -> None:
    """Parser should fail when output does not include both operation types."""
    output = """
Total Read Ops: 100
Average: 0.100 secs.
Stddev: 0.050 secs.
Requests/sec: 250.0
50% in 0.080 secs.
90% in 0.150 secs.
99% in 0.300 secs.
"""

    with pytest.raises(ValueError, match="both read and write"):
        runner_module._parse_raw_benchmark_output(output)


def test_append_csv_rows_missing_file_fails(runner_module: ModuleType, tmp_path: Path) -> None:
    """Appending to a non-existent CSV must raise FileNotFoundError."""
    csv_path = tmp_path / "results.csv"
    with pytest.raises(FileNotFoundError):
        runner_module._append_csv_rows(str(csv_path), [{"iteration": 1}])


def test_persist_benchmark_results_writes_two_rows(
    runner_module: ModuleType,
    tmp_path: Path,
) -> None:
    """Persisting one iteration writes one read and one write row."""
    csv_path = tmp_path / "results.csv"
    csv_path.write_text(
        ",".join(runner_module.RESULT_CSV_HEADERS) + os.linesep,
        encoding="utf-8",
    )

    output = """
Total Read Ops: 10
Average: 0.010 secs.
Stddev: 0.005 secs.
Requests/sec: 120.0
50% in 0.008 secs.
90% in 0.015 secs.
99% in 0.030 secs.

Total Write Ops: 20
Average: 0.020 secs.
Stddev: 0.006 secs.
Requests/sec: 220.0
50% in 0.009 secs.
90% in 0.018 secs.
99% in 0.040 secs.
"""

    results = runner_module._persist_benchmark_results(
        raw_output=output,
        iteration=3,
        results_csv_path=str(csv_path),
        test_id="test-123",
        test_name="smoke",
    )

    assert results.read.total_ops == 10
    assert results.write.total_ops == 20

    rows = csv_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) == 3
    assert "read" in rows[1]
    assert "write" in rows[2]


def test_set_test_inactive_success(runner_module: ModuleType, tmp_path: Path) -> None:
    """Runner exit should mark metadata is_active to False when metadata exists."""
    result_csv = tmp_path / "results.csv"
    result_csv.write_text("header\n", encoding="utf-8")
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(json.dumps({"is_active": True, "name": "bench"}), encoding="utf-8")

    runner_module._set_test_inactive(str(result_csv))

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["is_active"] is False
    assert metadata["name"] == "bench"


def test_clear_benchmark_data_invokes_etcdctl(
    runner_module: ModuleType,
) -> None:
    """Cleanup helper should call etcdctl delete with tls and endpoint flags."""
    env = {
        "ETCD_BENCHMARK_ENDPOINTS": "https://10.0.0.1:2379",
        "ETCD_BENCHMARK_CLIENT_CERT_PATH": "/tmp/client.crt",
        "ETCD_BENCHMARK_CLIENT_KEY_PATH": "/tmp/client.key",
        "ETCD_BENCHMARK_CA_CERT_PATH": "/tmp/ca.crt",
    }

    with patch.dict(os.environ, env):
        mock_run = MagicMock()
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = ""

        with patch.object(runner_module.subprocess, "run", mock_run):
            runner_module._clear_benchmark_data()

        called_cmd = mock_run.call_args.args[0]
        assert called_cmd[0:2] == ["charmed-etcd.etcdctl", "del"]
        assert "--from-key" in called_cmd
        assert "--endpoints" in called_cmd


class _FakeProcess:
    """Minimal process test-double for main loop subprocess handling."""

    def __init__(self, returncode: int, stdout: str, stderr: str, polls: list[int | None]):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self._polls = polls

    def poll(self) -> int | None:
        if self._polls:
            return self._polls.pop(0)
        return self.returncode

    def communicate(self) -> tuple[str, str]:
        return (self._stdout, self._stderr)


def _set_main_required_env(tmp_path: Path) -> dict[str, str]:
    """Set and return minimum environment required for main() to run."""
    csv_path = tmp_path / "results.csv"
    csv_path.write_text(",".join(["timestamp", "iteration"]) + os.linesep, encoding="utf-8")
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text('{"is_active": true}\n', encoding="utf-8")

    return {
        "ETCD_BENCHMARK_RESULTS_CSV_PATH": str(csv_path),
        "ETCD_BENCHMARK_CURRENT_TEST_ID": "id-1",
        "ETCD_BENCHMARK_CURRENT_TEST_NAME": "name-1",
        "ETCD_BENCHMARK_DURATION": "0",
    }


def test_main_returns_error_when_results_path_missing(
    runner_module: ModuleType,
) -> None:
    """Main should fail fast when results CSV env variable is absent."""
    with patch.dict(os.environ, {}, clear=True):
        with patch.object(runner_module.signal, "signal", lambda *_args, **_kwargs: None):
            assert runner_module.main() == 1


def test_main_exits_when_duration_expired_before_iteration(
    runner_module: ModuleType,
    tmp_path: Path,
) -> None:
    """If duration already elapsed, main exits cleanly without running benchmark."""
    env = _set_main_required_env(tmp_path)
    env["ETCD_BENCHMARK_DURATION"] = "1"

    monotonic_values = iter([10.0, 12.0])

    with (
        patch.dict(os.environ, env),
        patch.object(runner_module.time, "monotonic", side_effect=lambda: next(monotonic_values)),
        patch.object(runner_module.signal, "signal", lambda *_args, **_kwargs: None),
        patch.object(runner_module.subprocess, "Popen") as popen_mock,
        patch.object(runner_module, "_clear_benchmark_data") as clear_mock,
    ):
        assert runner_module.main() == 0
        assert clear_mock.call_count == 1
        assert popen_mock.call_count == 0


def test_main_persists_results_on_success_with_stderr(
    runner_module: ModuleType,
    tmp_path: Path,
) -> None:
    """Current main logic persists results when process succeeds and stderr is present."""
    env = _set_main_required_env(tmp_path)
    process = _FakeProcess(returncode=0, stdout="ok", stderr="warn", polls=[None, 0])

    with (
        patch.dict(os.environ, env),
        patch.object(runner_module.signal, "signal", lambda *_args, **_kwargs: None),
        patch.object(runner_module.time, "sleep", lambda _x: None),
        patch.object(runner_module.subprocess, "Popen", return_value=process),
        patch.object(runner_module, "_persist_benchmark_results") as persist_mock,
        patch.object(runner_module, "_clear_benchmark_data") as clear_mock,
    ):
        persist_mock.side_effect = lambda **_kwargs: setattr(runner_module, "keep_running", False)

        assert runner_module.main() == 0
        assert persist_mock.call_count == 1
        assert clear_mock.call_count == 1


def test_main_returns_process_code_on_failure(
    runner_module: ModuleType,
    tmp_path: Path,
) -> None:
    """If benchmark process exits non-zero, main returns that code."""
    env = _set_main_required_env(tmp_path)
    process = _FakeProcess(returncode=5, stdout="", stderr="error", polls=[0])

    with (
        patch.dict(os.environ, env),
        patch.object(runner_module.signal, "signal", lambda *_args, **_kwargs: None),
        patch.object(runner_module.time, "sleep", lambda _x: None),
        patch.object(runner_module.subprocess, "Popen", return_value=process),
    ):
        assert runner_module.main() == 5
