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
    script_path = Path(__file__).resolve().parents[2] / "templates" / "charmed_etcd_benchmark.py"
    spec = importlib.util.spec_from_file_location("benchmark_runner", script_path)
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    setattr(module, "keep_running", True)
    return module


# Environment helper tests


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


# _build_command tests


def test_build_command_includes_all_required_flags(runner_module: ModuleType) -> None:
    """_build_command should include txn-mixed and all benchmark flags from env vars."""
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
        "ETCD_BENCHMARK_REPORT_INTERVAL": "10",
        "ETCD_BENCHMARK_CLIENT_CERT_PATH": "/tmp/client.crt",
        "ETCD_BENCHMARK_CLIENT_KEY_PATH": "/tmp/client.key",
        "ETCD_BENCHMARK_CA_CERT_PATH": "/tmp/ca.crt",
    }
    with patch.dict(os.environ, env):
        command = runner_module._build_command()

    assert command[1] == "txn-mixed"
    assert "--endpoints" in command
    assert command[command.index("--endpoints") + 1] == "https://10.0.0.1:2379"
    assert "--cert" in command
    assert command[command.index("--cert") + 1] == "/tmp/client.crt"
    assert "--key" in command
    assert "--cacert" in command
    assert "--clients" in command
    assert "--conns" in command
    assert "--rate" in command
    assert "--rw-ratio" in command
    assert "--report-interval" in command


def test_build_command_uses_max_int_total_when_total_transactions_unset(
    runner_module: ModuleType,
) -> None:
    """When ETCD_BENCHMARK_TOTAL_TRANSACTIONS is 0 or absent, --total is max int (2^31-1)."""
    env = {
        "ETCD_BENCHMARK_ENDPOINTS": "https://10.0.0.1:2379",
        "ETCD_BENCHMARK_CLIENT_CERT_PATH": "/tmp/client.crt",
        "ETCD_BENCHMARK_CLIENT_KEY_PATH": "/tmp/client.key",
        "ETCD_BENCHMARK_CA_CERT_PATH": "/tmp/ca.crt",
        "ETCD_BENCHMARK_TOTAL_TRANSACTIONS": "0",
    }
    with patch.dict(os.environ, env):
        command = runner_module._build_command()

    total_idx = command.index("--total")
    assert command[total_idx + 1] == "2147483647"


def test_build_command_uses_explicit_total_transactions_when_set(
    runner_module: ModuleType,
) -> None:
    """When ETCD_BENCHMARK_TOTAL_TRANSACTIONS is non-zero, --total uses that value."""
    env = {
        "ETCD_BENCHMARK_ENDPOINTS": "https://10.0.0.1:2379",
        "ETCD_BENCHMARK_CLIENT_CERT_PATH": "/tmp/client.crt",
        "ETCD_BENCHMARK_CLIENT_KEY_PATH": "/tmp/client.key",
        "ETCD_BENCHMARK_CA_CERT_PATH": "/tmp/ca.crt",
        "ETCD_BENCHMARK_TOTAL_TRANSACTIONS": "500",
    }
    with patch.dict(os.environ, env):
        command = runner_module._build_command()

    total_idx = command.index("--total")
    assert command[total_idx + 1] == "500"


# _mark_test_complete tests


def test_mark_test_complete_sets_is_active_false(
    runner_module: ModuleType, tmp_path: Path
) -> None:
    """_mark_test_complete should flip is_active to False in metadata.json."""
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(json.dumps({"is_active": True, "name": "bench"}), encoding="utf-8")

    runner_module._mark_test_complete(str(results_dir))

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["is_active"] is False
    assert metadata["name"] == "bench"


def test_mark_test_complete_preserves_other_metadata_fields(
    runner_module: ModuleType, tmp_path: Path
) -> None:
    """_mark_test_complete should preserve all existing fields beyond is_active."""
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(
        json.dumps({"is_active": True, "test_id": "abc-123", "config": {"rate": 100}}),
        encoding="utf-8",
    )

    runner_module._mark_test_complete(str(results_dir))

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["is_active"] is False
    assert metadata["test_id"] == "abc-123"
    assert metadata["config"] == {"rate": 100}


def test_mark_test_complete_does_nothing_when_metadata_missing(
    runner_module: ModuleType, tmp_path: Path
) -> None:
    """_mark_test_complete should log a warning and return when metadata.json is absent."""
    results_dir = tmp_path / "results"
    results_dir.mkdir()

    # No metadata.json created — should not raise.
    runner_module._mark_test_complete(str(results_dir))


# _clear_benchmark_data tests


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


def test_clear_benchmark_data_handles_subprocess_exception(
    runner_module: ModuleType,
) -> None:
    """_clear_benchmark_data should swallow exceptions and not propagate them."""
    with patch.object(runner_module.subprocess, "run", side_effect=OSError("connection refused")):
        # Should not raise.
        runner_module._clear_benchmark_data()


# Main function tests


class _FakeProcess:
    """Minimal process test-double for main loop subprocess handling."""

    def __init__(self, returncode: int, polls: list[int | None]):
        self.returncode = returncode
        self._polls = polls
        self.pid = 12345

    def poll(self) -> int | None:
        if self._polls:
            return self._polls.pop(0)
        return self.returncode


def _set_main_required_env(tmp_path: Path) -> dict[str, str]:
    """Create required filesystem artifacts and return minimum env for main() to run."""
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    (results_dir / "stdout.jsonl").write_text("", encoding="utf-8")
    (results_dir / "stderr.log").write_text("", encoding="utf-8")
    (tmp_path / "metadata.json").write_text('{"is_active": true}\n', encoding="utf-8")

    return {
        "ETCD_BENCHMARK_RESULTS_DIR": str(results_dir),
        "ETCD_BENCHMARK_CURRENT_TEST_ID": "id-1",
        "ETCD_BENCHMARK_CURRENT_TEST_NAME": "name-1",
        "ETCD_BENCHMARK_DURATION": "0",
    }


def test_main_returns_error_when_results_dir_missing(
    runner_module: ModuleType,
) -> None:
    """Main should fail fast when ETCD_BENCHMARK_RESULTS_DIR is absent."""
    with patch.dict(os.environ, {}, clear=True):
        with patch.object(runner_module.signal, "signal", lambda *_args, **_kwargs: None):
            assert runner_module.main() == 1


def test_main_returns_error_when_test_id_missing(
    runner_module: ModuleType, tmp_path: Path
) -> None:
    """Main should call _finalize_exit(1) when ETCD_BENCHMARK_CURRENT_TEST_ID is absent."""
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    (tmp_path / "metadata.json").write_text('{"is_active": true}\n', encoding="utf-8")

    env = {
        "ETCD_BENCHMARK_RESULTS_DIR": str(results_dir),
        "ETCD_BENCHMARK_CURRENT_TEST_NAME": "name-1",
    }
    with (
        patch.dict(os.environ, env, clear=True),
        patch.object(runner_module.signal, "signal", lambda *_args, **_kwargs: None),
        patch.object(runner_module, "_clear_benchmark_data"),
        patch.object(runner_module, "_mark_test_complete"),
    ):
        assert runner_module.main() == 1


def test_main_returns_error_when_test_name_missing(
    runner_module: ModuleType, tmp_path: Path
) -> None:
    """Main should call _finalize_exit(1) when ETCD_BENCHMARK_CURRENT_TEST_NAME is absent."""
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    (tmp_path / "metadata.json").write_text('{"is_active": true}\n', encoding="utf-8")

    env = {
        "ETCD_BENCHMARK_RESULTS_DIR": str(results_dir),
        "ETCD_BENCHMARK_CURRENT_TEST_ID": "id-1",
    }
    with (
        patch.dict(os.environ, env, clear=True),
        patch.object(runner_module.signal, "signal", lambda *_args, **_kwargs: None),
        patch.object(runner_module, "_clear_benchmark_data"),
        patch.object(runner_module, "_mark_test_complete"),
    ):
        assert runner_module.main() == 1


def test_main_exits_when_duration_expired_before_iteration(
    runner_module: ModuleType,
    tmp_path: Path,
) -> None:
    """If duration already elapsed before process launch, main exits cleanly."""
    env = _set_main_required_env(tmp_path)
    env["ETCD_BENCHMARK_DURATION"] = "1"

    monotonic_values = iter([10.0, 12.0])

    with (
        patch.dict(os.environ, env),
        patch.object(runner_module.time, "monotonic", side_effect=lambda: next(monotonic_values)),
        patch.object(runner_module.signal, "signal", lambda *_args, **_kwargs: None),
        patch.object(runner_module.subprocess, "Popen") as popen_mock,
        patch.object(runner_module, "_clear_benchmark_data") as clear_mock,
        patch.object(runner_module, "_mark_test_complete") as mark_mock,
    ):
        assert runner_module.main() == 0
        assert clear_mock.call_count == 1
        assert mark_mock.call_count == 1
        assert popen_mock.call_count == 0


def test_main_returns_zero_when_process_exits_cleanly(
    runner_module: ModuleType,
    tmp_path: Path,
) -> None:
    """Main should return 0 and call finalize when process exits with rc=0."""
    env = _set_main_required_env(tmp_path)
    process = _FakeProcess(returncode=0, polls=[None, 0])

    with (
        patch.dict(os.environ, env),
        patch.object(runner_module.signal, "signal", lambda *_args, **_kwargs: None),
        patch.object(runner_module.time, "sleep", lambda _x: None),
        patch.object(runner_module.subprocess, "Popen", return_value=process),
        patch.object(runner_module, "_clear_benchmark_data") as clear_mock,
        patch.object(runner_module, "_mark_test_complete") as mark_mock,
    ):
        assert runner_module.main() == 0
        assert clear_mock.call_count == 1
        assert mark_mock.call_count == 1


def test_main_returns_process_code_on_failure(
    runner_module: ModuleType,
    tmp_path: Path,
) -> None:
    """If benchmark process exits non-zero, main returns that exit code."""
    env = _set_main_required_env(tmp_path)
    process = _FakeProcess(returncode=5, polls=[0])

    with (
        patch.dict(os.environ, env),
        patch.object(runner_module.signal, "signal", lambda *_args, **_kwargs: None),
        patch.object(runner_module.time, "sleep", lambda _x: None),
        patch.object(runner_module.subprocess, "Popen", return_value=process),
        patch.object(runner_module, "_clear_benchmark_data"),
        patch.object(runner_module, "_mark_test_complete"),
    ):
        assert runner_module.main() == 5


def test_main_treats_sigterm_exit_code_as_clean(
    runner_module: ModuleType,
    tmp_path: Path,
) -> None:
    """SIGTERM exit code (-15) should be treated as a clean exit, returning 0."""
    env = _set_main_required_env(tmp_path)
    process = _FakeProcess(returncode=-15, polls=[0])

    with (
        patch.dict(os.environ, env),
        patch.object(runner_module.signal, "signal", lambda *_args, **_kwargs: None),
        patch.object(runner_module.time, "sleep", lambda _x: None),
        patch.object(runner_module.subprocess, "Popen", return_value=process),
        patch.object(runner_module, "_clear_benchmark_data"),
        patch.object(runner_module, "_mark_test_complete"),
    ):
        assert runner_module.main() == 0
