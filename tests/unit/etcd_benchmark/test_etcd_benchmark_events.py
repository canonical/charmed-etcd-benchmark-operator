#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for etcd benchmark related event handlers."""

from unittest.mock import PropertyMock, patch

import pytest
from charmlibs import systemd
from ops import testing
from ops._private.harness import ActionFailed

from charm import CharmedEtcdBenchmarkOperatorCharm
from common.exceptions import BenchmarkConfigurationError
from literals import BENCHMARK_TESTS_ROOT_DIR


@pytest.fixture(autouse=True)
def patch_snap_cache():
    """Patch SnapCache so the charm/workload can be constructed safely."""
    with patch("workload.snap.SnapCache") as mock_snap_cache:
        mock_snap = mock_snap_cache.return_value.__getitem__.return_value
        yield mock_snap


def test_stop_action_fails_when_no_active_benchmark(caplog):
    """Stop should fail if no benchmark is currently running."""
    ctx = testing.Context(CharmedEtcdBenchmarkOperatorCharm)
    state_in = testing.State()

    with patch("workload.EtcdBenchmarkWorkload.is_running", return_value=False):
        with caplog.at_level("ERROR"):
            with pytest.raises(ActionFailed) as e:
                ctx.run(ctx.on.action("stop"), state_in)

    assert "no active benchmark" in str(e.value)
    assert "There is no active benchmark to stop." in caplog.text
    assert ctx.action_results == {"error": "no active benchmark to stop"}


def test_stop_action_stops_benchmark_and_exporter():
    """Stop should stop benchmark service and metrics exporter."""
    ctx = testing.Context(CharmedEtcdBenchmarkOperatorCharm)
    state_in = testing.State()

    with (
        patch("workload.EtcdBenchmarkWorkload.is_running", return_value=True),
        patch("workload.EtcdBenchmarkWorkload.stop_service") as stop_service,
        patch(
            "managers.metrics_exporter.MetricsExporterManager.stop_metrics_exporter"
        ) as stop_exporter,
    ):
        ctx.run(ctx.on.action("stop"), state_in)

    stop_service.assert_called_once_with()
    stop_exporter.assert_called_once_with()
    assert ctx.action_results is not None
    assert "Successfully signalled stop of current run." in ctx.action_results["results"]


def test_stop_action_fails_when_systemd_raises():
    """Stop should fail with a clear message when systemd actions fail."""
    ctx = testing.Context(CharmedEtcdBenchmarkOperatorCharm)
    state_in = testing.State()

    with (
        patch("workload.EtcdBenchmarkWorkload.is_running", return_value=True),
        patch(
            "workload.EtcdBenchmarkWorkload.stop_service",
            side_effect=systemd.SystemdError("failed"),
        ),
    ):
        with pytest.raises(ActionFailed) as e:
            ctx.run(ctx.on.action("stop"), state_in)

    assert "Internal charm error stopping benchmark service / metrics exporter" in str(e.value)
    assert ctx.action_results == {
        "error": "Internal charm error stopping benchmark service / metrics exporter"
    }


def test_list_tests_action_returns_no_tests_message():
    """list-tests should return a friendly message when no tests exist."""
    ctx = testing.Context(CharmedEtcdBenchmarkOperatorCharm)
    state_in = testing.State()

    with patch("managers.etcd_benchmark.EtcdBenchmarkManager.list_tests", return_value=[]):
        ctx.run(ctx.on.action("list-tests"), state_in)

    assert ctx.action_results == {"tests": "No tests found."}


def test_list_tests_action_formats_test_output():
    """list-tests should format test ids with status values."""
    ctx = testing.Context(CharmedEtcdBenchmarkOperatorCharm)
    state_in = testing.State()

    with patch(
        "managers.etcd_benchmark.EtcdBenchmarkManager.list_tests",
        return_value=[("test-1", "running"), ("test-2", "stopped")],
    ) as list_tests:
        ctx.run(ctx.on.action("list-tests"), state_in)

    list_tests.assert_called_once_with(BENCHMARK_TESTS_ROOT_DIR)
    assert ctx.action_results == {"tests": "test-1 (running)\ntest-2 (stopped)"}


def test_get_summary_action_fails_with_empty_test_id(caplog):
    """get-summary should fail when test-id is missing."""
    ctx = testing.Context(CharmedEtcdBenchmarkOperatorCharm)
    state_in = testing.State()

    with caplog.at_level("ERROR"):
        with pytest.raises(ActionFailed) as e:
            ctx.run(ctx.on.action("get-summary", params={}), state_in)

    assert "valid, non-empty test-id" in str(e.value)
    assert ctx.action_results is not None
    assert "valid test-id not found" in ctx.action_results["error"]
    assert "Please provide a valid, non-empty test-id parameter." in caplog.text


def test_get_summary_action_fails_when_test_folder_missing(caplog):
    """get-summary should fail when the test folder does not exist."""
    ctx = testing.Context(CharmedEtcdBenchmarkOperatorCharm)
    state_in = testing.State()

    with patch("workload.EtcdBenchmarkWorkload.file_exists", return_value=False):
        with caplog.at_level("ERROR"):
            with pytest.raises(ActionFailed) as e:
                ctx.run(ctx.on.action("get-summary", params={"test-id": "test-1"}), state_in)

    assert f"{BENCHMARK_TESTS_ROOT_DIR}/test-1 does not exist." in str(e.value)
    assert f"{BENCHMARK_TESTS_ROOT_DIR}/test-1 does not exist." in caplog.text


def test_get_summary_action_returns_summary():
    """get-summary should return the manager-rendered summary text."""
    ctx = testing.Context(CharmedEtcdBenchmarkOperatorCharm)
    state_in = testing.State()

    with (
        patch("workload.EtcdBenchmarkWorkload.file_exists", return_value=True),
        patch(
            "managers.etcd_benchmark.EtcdBenchmarkManager.get_test_summary",
            return_value="summary output",
        ) as get_summary,
    ):
        ctx.run(ctx.on.action("get-summary", params={"test-id": "test-1"}), state_in)

    get_summary.assert_called_once_with(f"{BENCHMARK_TESTS_ROOT_DIR}/test-1")
    assert ctx.action_results == {"results": "summary output"}


@pytest.mark.parametrize("error", [OSError("io"), ValueError("bad"), KeyError("missing")])
def test_get_summary_action_fails_when_summary_generation_errors(error, caplog):
    """get-summary should fail with explicit errors when summary generation crashes."""
    ctx = testing.Context(CharmedEtcdBenchmarkOperatorCharm)
    state_in = testing.State()

    with (
        patch("workload.EtcdBenchmarkWorkload.file_exists", return_value=True),
        patch("managers.etcd_benchmark.EtcdBenchmarkManager.get_test_summary", side_effect=error),
    ):
        with caplog.at_level("ERROR"):
            with pytest.raises(ActionFailed) as e:
                ctx.run(ctx.on.action("get-summary", params={"test-id": "test-1"}), state_in)

    assert "Error preparing/writing summary" in str(e.value)
    assert "Error preparing/writing summary" in caplog.text


def test_run_action_fails_on_benchmark_configuration_error():
    """Run should report BenchmarkConfigurationError details to action output."""
    ctx = testing.Context(CharmedEtcdBenchmarkOperatorCharm)
    state_in = testing.State()

    config_error = BenchmarkConfigurationError(
        message="invalid benchmark config",
        detailed_description="duration must be > 0",
    )

    with (
        patch("workload.EtcdBenchmarkWorkload.is_running", return_value=False),
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
        patch("managers.etcd_benchmark.EtcdBenchmarkManager.setup_test", side_effect=config_error),
    ):
        with pytest.raises(ActionFailed) as e:
            ctx.run(ctx.on.action("run"), state_in)

    assert "duration must be > 0" in str(e.value)
    assert ctx.action_results == {"error": "invalid benchmark config"}
