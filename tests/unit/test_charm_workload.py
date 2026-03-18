#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for workload-related charm hooks and workload helpers."""

from subprocess import CalledProcessError
from unittest.mock import MagicMock, PropertyMock, patch

import ops
import pytest
from _pytest.raises import raises
from charmlibs import snap
from ops import testing
from ops._private.harness import ActionFailed

from charm import CharmedEtcdBenchmarkOperatorCharm
from literals import CA_CERT_PATH, CLIENT_CERT_PATH, CLIENT_KEY_PATH, SNAP_CHANNEL, SNAP_NAME
from workload import EtcdBenchmarkWorkload

# Helpers


def _mock_snap_cache():
    """Return a patched SnapCache and the mocked snap object."""
    mock_snap = MagicMock()
    patcher = patch("workload.snap.SnapCache")
    mock_snap_cache = patcher.start()
    mock_snap_cache.return_value.__getitem__.return_value = mock_snap
    return patcher, mock_snap


@pytest.fixture(autouse=True)
def patch_snap_cache():
    """Patch SnapCache for all tests so charm/workload can be constructed safely."""
    mock_snap = MagicMock()
    with patch("workload.snap.SnapCache") as mock_snap_cache:
        mock_snap_cache.return_value.__getitem__.return_value = mock_snap
        yield mock_snap


# Hook tests: install hook


def test_install_success(patch_snap_cache):
    """Install hook should execute real workload.install and install the snap."""
    ctx = testing.Context(CharmedEtcdBenchmarkOperatorCharm)
    state_in = testing.State()

    state_out = ctx.run(ctx.on.install(), state_in)

    patch_snap_cache.ensure.assert_called_once_with(
        snap.SnapState.Present,
        channel=SNAP_CHANNEL,
    )
    patch_snap_cache.hold.assert_called_once_with()
    assert state_out.unit_status == ops.MaintenanceStatus("installed workload")


def test_install_failure_when_ensure_fails(patch_snap_cache):
    """Install hook should block the unit if snap installation fails."""
    ctx = testing.Context(CharmedEtcdBenchmarkOperatorCharm)
    state_in = testing.State()

    patch_snap_cache.ensure.side_effect = snap.SnapError("snap install failed")

    state_out = ctx.run(ctx.on.install(), state_in)

    assert patch_snap_cache.ensure.call_count == 3
    patch_snap_cache.ensure.assert_called_with(
        snap.SnapState.Present,
        channel=SNAP_CHANNEL,
    )
    patch_snap_cache.hold.assert_not_called()
    assert state_out.unit_status == ops.BlockedStatus("Error installing the workload")


def test_install_failure_when_hold_fails(patch_snap_cache):
    """Install hook should block the unit if snap hold fails."""
    ctx = testing.Context(CharmedEtcdBenchmarkOperatorCharm)
    state_in = testing.State()

    patch_snap_cache.hold.side_effect = snap.SnapError("snap hold failed")

    state_out = ctx.run(ctx.on.install(), state_in)

    assert patch_snap_cache.ensure.call_count == 3
    patch_snap_cache.ensure.assert_called_with(
        snap.SnapState.Present,
        channel=SNAP_CHANNEL,
    )
    assert patch_snap_cache.hold.call_count == 3
    patch_snap_cache.hold.assert_called_with()
    assert state_out.unit_status == ops.BlockedStatus("Error installing the workload")


# Hook tests: start hook


def test_start_success():
    """Start hook should execute real workload.start and set unit to active."""
    ctx = testing.Context(CharmedEtcdBenchmarkOperatorCharm)
    state_in = testing.State()

    with (
        patch("workload.snap.SnapCache") as mock_snap_cache,
        patch("workload.subprocess.run") as mock_run,
    ):
        mock_snap = MagicMock()
        mock_snap_cache.return_value.__getitem__.return_value = mock_snap
        mock_run.return_value.stdout = b"help output"

        state_out = ctx.run(ctx.on.start(), state_in)

    mock_run.assert_called_once_with(
        [f"{SNAP_NAME}.benchmark", "--help"],
        capture_output=True,
        check=True,
    )
    assert state_out.unit_status == ops.ActiveStatus()


def test_start_failure():
    """Start hook should block the unit if workload.start fails."""
    ctx = testing.Context(CharmedEtcdBenchmarkOperatorCharm)
    state_in = testing.State()

    error = CalledProcessError(
        1,
        [f"{SNAP_NAME}.benchmark", "--help"],
        stderr="help failed",
    )

    with (
        patch("workload.snap.SnapCache") as mock_snap_cache,
        patch("workload.subprocess.run", side_effect=error) as mock_run,
    ):
        mock_snap = MagicMock()
        mock_snap_cache.return_value.__getitem__.return_value = mock_snap

        state_out = ctx.run(ctx.on.start(), state_in)

    mock_run.assert_called_once_with(
        [f"{SNAP_NAME}.benchmark", "--help"],
        capture_output=True,
        check=True,
    )
    assert state_out.unit_status == ops.BlockedStatus("Error starting the workload")


# Hook tests: run action


def test_run_action_fails_without_relation():
    """Run action should fail if the etcd relation is missing."""
    ctx = testing.Context(CharmedEtcdBenchmarkOperatorCharm)
    state_in = testing.State()

    with patch("workload.snap.SnapCache") as mock_snap_cache:
        mock_snap = MagicMock()
        mock_snap_cache.return_value.__getitem__.return_value = mock_snap

        with raises(ActionFailed) as e:
            ctx.run(ctx.on.action("run"), state_in)

    assert str(e.value) == "The etcd relation is needed in order to run this action"
    assert ctx.action_results == {
        "error": "The etcd relation is needed in order to run this action"
    }


def test_run_action_fails_without_uris():
    """Run action should fail if relation exists but no URIs are available."""
    ctx = testing.Context(CharmedEtcdBenchmarkOperatorCharm)
    state_in = testing.State()

    with (
        patch("workload.snap.SnapCache") as mock_snap_cache,
        patch(
            "core.interfaces.EtcdInterfaceState.relation",
            new_callable=PropertyMock,
            return_value=object(),
        ),
        patch(
            "core.interfaces.EtcdInterfaceState.uris",
            new_callable=PropertyMock,
            return_value="",
        ),
    ):
        mock_snap = MagicMock()
        mock_snap_cache.return_value.__getitem__.return_value = mock_snap

        with raises(ActionFailed) as e:
            ctx.run(ctx.on.action("run"), state_in)

    assert str(e.value) == "No etcd uris available"
    assert ctx.action_results == {"error": "No etcd uris available"}


def test_run_action_success():
    """Run action should execute real workload.run and return benchmark results."""
    ctx = testing.Context(CharmedEtcdBenchmarkOperatorCharm)
    state_in = testing.State()

    with (
        patch("workload.snap.SnapCache") as mock_snap_cache,
        patch(
            "core.interfaces.EtcdInterfaceState.relation",
            new_callable=PropertyMock,
            return_value=object(),
        ),
        patch(
            "core.interfaces.EtcdInterfaceState.uris",
            new_callable=PropertyMock,
            return_value="https://10.0.0.1:2379",
        ),
        patch("workload.subprocess.run") as mock_subprocess_run,
    ):
        mock_snap = MagicMock()
        mock_snap_cache.return_value.__getitem__.return_value = mock_snap

        mock_subprocess_run.return_value.stdout = b"benchmark success\n"

        ctx.run(ctx.on.action("run"), state_in)

    mock_subprocess_run.assert_called_once_with(
        [
            f"{SNAP_NAME}.benchmark",
            "txn-mixed",
            "--endpoints",
            "https://10.0.0.1:2379",
            "--cert",
            CLIENT_CERT_PATH,
            "--key",
            CLIENT_KEY_PATH,
            "--cacert",
            CA_CERT_PATH,
        ],
        capture_output=True,
        check=True,
    )
    assert ctx.action_results == {"results": ["benchmark success"]}


def test_run_action_benchmark_failure():
    """Run action should fail cleanly if workload.run raises CalledProcessError."""
    ctx = testing.Context(CharmedEtcdBenchmarkOperatorCharm)
    state_in = testing.State()

    error = CalledProcessError(
        returncode=1,
        cmd=[f"{SNAP_NAME}.benchmark", "txn-mixed"],
        stderr="benchmark failed",
    )

    with (
        patch("workload.snap.SnapCache") as mock_snap_cache,
        patch(
            "core.interfaces.EtcdInterfaceState.relation",
            new_callable=PropertyMock,
            return_value=object(),
        ),
        patch(
            "core.interfaces.EtcdInterfaceState.uris",
            new_callable=PropertyMock,
            return_value="https://10.0.0.1:2379",
        ),
        patch("workload.subprocess.run", side_effect=error) as mock_subprocess_run,
    ):
        mock_snap = MagicMock()
        mock_snap_cache.return_value.__getitem__.return_value = mock_snap

        with raises(ActionFailed) as e:
            ctx.run(ctx.on.action("run"), state_in)

    assert str(e.value) == "Benchmark run failed. Check logs for more information."
    mock_subprocess_run.assert_called_once_with(
        [
            f"{SNAP_NAME}.benchmark",
            "txn-mixed",
            "--endpoints",
            "https://10.0.0.1:2379",
            "--cert",
            CLIENT_CERT_PATH,
            "--key",
            CLIENT_KEY_PATH,
            "--cacert",
            CA_CERT_PATH,
        ],
        capture_output=True,
        check=True,
    )
    assert ctx.action_results == {"error": "benchmark failed"}


# Direct workload tests: file utilities


@pytest.fixture
def workload():
    """Create a workload instance with SnapCache mocked."""
    with patch("workload.snap.SnapCache") as mock_snap_cache:
        mock_snap = MagicMock()
        mock_snap_cache.return_value.__getitem__.return_value = mock_snap
        yield EtcdBenchmarkWorkload()


def test_write_file_creates_parent_dirs_and_writes_content(workload, tmp_path):
    """write_file should create parent dirs and write content."""
    target = tmp_path / "nested" / "dir" / "test.txt"

    workload.write_file("hello world", str(target))

    assert target.exists()
    assert target.read_text() == "hello world"


def test_read_file_returns_content_if_present(workload, tmp_path):
    """read_file should return file contents when file exists."""
    target = tmp_path / "present.txt"
    target.write_text("sample data")

    result = workload.read_file(str(target))

    assert result == "sample data"


def test_read_file_returns_none_if_missing(workload, tmp_path):
    """read_file should return None if file does not exist."""
    target = tmp_path / "missing.txt"

    result = workload.read_file(str(target))

    assert result is None


# Direct workload tests: command methods


def test_workload_start_runs_help_check(workload):
    """Direct workload test for start()."""
    with patch("workload.subprocess.run") as mock_run:
        mock_run.return_value.stdout = b"help output"

        workload.start()

    mock_run.assert_called_once_with(
        [f"{SNAP_NAME}.benchmark", "--help"],
        capture_output=True,
        check=True,
    )


def test_workload_run_executes_txn_mixed_command(workload):
    """Direct workload test for run()."""
    with patch("workload.subprocess.run") as mock_run:
        mock_run.return_value.stdout = b"benchmark success\n"

        result = workload.run(endpoints="https://10.0.0.1:2379")

    mock_run.assert_called_once_with(
        [
            f"{SNAP_NAME}.benchmark",
            "txn-mixed",
            "--endpoints",
            "https://10.0.0.1:2379",
            "--cert",
            CLIENT_CERT_PATH,
            "--key",
            CLIENT_KEY_PATH,
            "--cacert",
            CA_CERT_PATH,
        ],
        capture_output=True,
        check=True,
    )
    assert result == ["benchmark success"]
