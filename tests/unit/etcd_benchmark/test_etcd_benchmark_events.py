#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for etcd benchmark related event handlers."""

from unittest.mock import PropertyMock, patch

import ops
import pytest
from ops import testing
from ops._private.harness import ActionFailed

from charm import CharmedEtcdBenchmarkOperatorCharm
from common.exceptions import (
    BenchmarkConfigurationError,
    BenchmarkResultsParseError,
    BenchmarkServiceError,
    BenchmarkStateError,
    MetricsExporterServiceError,
)


@pytest.fixture(autouse=True)
def patch_snap_cache():
    """Patch SnapCache so the charm/workload can be constructed safely."""
    with patch("workload.snap.SnapCache") as mock_snap_cache:
        mock_snap = mock_snap_cache.return_value.__getitem__.return_value
        yield mock_snap


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ctx():
    return testing.Context(CharmedEtcdBenchmarkOperatorCharm)


def _patch_is_test_active(value: bool):
    """Patch the cluster is_test_active property used by run/stop actions."""
    return patch(
        "core.cluster.EtcdBenchmarkCluster.is_test_active",
        new_callable=PropertyMock,
        return_value=value,
    )


# ---------------------------------------------------------------------------
# install hook
# ---------------------------------------------------------------------------


def test_install_blocks_when_runner_file_copy_fails():
    """_on_install should block the unit when copying a runner file fails."""
    ctx = _ctx()
    state_in = testing.State()

    with (
        patch("workload.EtcdBenchmarkWorkload.install"),
        patch("shutil.copyfile", side_effect=OSError("disk full")),
        patch("pathlib.Path.chmod"),
    ):
        state_out = ctx.run(ctx.on.install(), state_in)

    assert state_out.unit_status == ops.BlockedStatus("Error setting up runner file")


# ---------------------------------------------------------------------------
# run action
# ---------------------------------------------------------------------------


def test_run_action_fails_on_non_leader_unit():
    """Run should fail early when invoked on a non-leader unit."""
    ctx = _ctx()
    state_in = testing.State(leader=False)

    with pytest.raises(ActionFailed) as e:
        ctx.run(ctx.on.action("run"), state_in)

    assert "only supported on the leader unit" in str(e.value)
    assert ctx.action_results == {"error": "action not supported on non-leader units"}


def test_run_action_fails_when_benchmark_already_in_progress():
    """Run should fail when a benchmark is already active in cluster state."""
    ctx = _ctx()
    state_in = testing.State(leader=True)

    with _patch_is_test_active(True):
        with pytest.raises(ActionFailed) as e:
            ctx.run(ctx.on.action("run"), state_in)

    assert "already a benchmark in progress" in str(e.value)
    assert ctx.action_results == {"error": "A benchmark is already in progress"}


def test_run_action_fails_when_etcd_relation_missing():
    """Run should fail when the etcd relation or uris are not available."""
    ctx = _ctx()
    state_in = testing.State(leader=True)

    with (
        _patch_is_test_active(False),
        patch(
            "core.interfaces.EtcdInterfaceState.relation",
            new_callable=PropertyMock,
            return_value=None,
        ),
        patch(
            "core.interfaces.EtcdInterfaceState.uris",
            new_callable=PropertyMock,
            return_value=None,
        ),
    ):
        with pytest.raises(ActionFailed) as e:
            ctx.run(ctx.on.action("run"), state_in)

    assert "needed in order to run this action" in str(e.value)
    assert ctx.action_results == {"error": "etcd relation missing"}


def test_run_action_fails_on_benchmark_configuration_error():
    """Run should report BenchmarkConfigurationError details to action output."""
    ctx = _ctx()
    state_in = testing.State(leader=True)

    config_error = BenchmarkConfigurationError(
        message="invalid benchmark config",
        detailed_description="duration must be > 0",
    )

    with (
        _patch_is_test_active(False),
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
        patch(
            "managers.etcd_benchmark.EtcdBenchmarkManager.setup_test",
            side_effect=config_error,
        ),
        patch(
            "managers.etcd_benchmark.EtcdBenchmarkManager.mark_current_test_completed"
        ) as mark_completed,
    ):
        with pytest.raises(ActionFailed) as e:
            ctx.run(ctx.on.action("run"), state_in)

    assert "duration must be > 0" in str(e.value)
    assert ctx.action_results == {"error": "invalid benchmark config"}
    # setup_test raised before benchmark_config was assigned, so no cleanup expected
    mark_completed.assert_not_called()


def test_run_action_cleans_up_when_start_benchmark_fails():
    """Run should mark the current test completed when startup fails after setup."""
    ctx = _ctx()
    state_in = testing.State(leader=True)

    benchmark_config = {"results_dir": "/tmp/results", "current_test_id": "test-1"}
    metrics_config = {"jsonl_path": "/tmp/results/stdout.jsonl"}

    with (
        _patch_is_test_active(False),
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
        patch(
            "managers.etcd_benchmark.EtcdBenchmarkManager.setup_test",
            return_value=benchmark_config,
        ),
        patch(
            "managers.metrics_exporter.MetricsExporterManager.setup_metrics_exporter",
            return_value=metrics_config,
        ),
        patch("workload.EtcdBenchmarkWorkload.start_metrics_exporter"),
        patch(
            "workload.EtcdBenchmarkWorkload.start_benchmark",
            side_effect=BenchmarkServiceError(
                message="Benchmark service could not be started cleanly",
                detailed_description="Error starting benchmark service: failed",
            ),
        ),
        patch(
            "managers.etcd_benchmark.EtcdBenchmarkManager.mark_current_test_completed"
        ) as mark_completed,
    ):
        with pytest.raises(ActionFailed) as e:
            ctx.run(ctx.on.action("run"), state_in)

    assert "Error starting benchmark service: failed" in str(e.value)
    assert ctx.action_results == {"error": "Benchmark service could not be started cleanly"}
    mark_completed.assert_called_once_with()


# ---------------------------------------------------------------------------
# stop action
# ---------------------------------------------------------------------------


def test_stop_action_fails_on_non_leader_unit():
    """Stop should fail early when invoked on a non-leader unit."""
    ctx = _ctx()
    state_in = testing.State(leader=False)

    with pytest.raises(ActionFailed) as e:
        ctx.run(ctx.on.action("stop"), state_in)

    assert "only supported on the leader unit" in str(e.value)
    assert ctx.action_results == {"error": "action not supported on non-leader units"}


def test_stop_action_fails_when_no_active_benchmark(caplog):
    """Stop should fail if no benchmark is currently running."""
    ctx = _ctx()
    state_in = testing.State(leader=True)

    with _patch_is_test_active(False):
        with caplog.at_level("ERROR"):
            with pytest.raises(ActionFailed) as e:
                ctx.run(ctx.on.action("stop"), state_in)

    assert "no active benchmark" in str(e.value)
    assert "There is no active benchmark to stop." in caplog.text
    assert ctx.action_results == {"error": "no active benchmark to stop"}


def test_stop_action_stops_benchmark_exporter_and_persists_metadata():
    """Stop should stop services, write metadata, and mark the test completed."""
    ctx = _ctx()
    state_in = testing.State(leader=True)

    with (
        _patch_is_test_active(True),
        patch("workload.EtcdBenchmarkWorkload.stop_benchmark") as stop_benchmark,
        patch("workload.EtcdBenchmarkWorkload.stop_metrics_exporter") as stop_exporter,
        patch(
            "managers.etcd_benchmark.EtcdBenchmarkManager.write_metadata_to_summary_file"
        ) as write_metadata,
        patch(
            "managers.etcd_benchmark.EtcdBenchmarkManager.mark_current_test_completed"
        ) as mark_completed,
    ):
        ctx.run(ctx.on.action("stop"), state_in)

    stop_benchmark.assert_called_once_with()
    stop_exporter.assert_called_once_with()
    write_metadata.assert_called_once_with()
    mark_completed.assert_called_once_with()
    assert ctx.action_results is not None
    assert "Successfully signalled stop of current run." in ctx.action_results["results"]


def test_stop_action_fails_when_stop_benchmark_raises():
    """Stop should fail with a clear message when stopping the benchmark service fails."""
    ctx = _ctx()
    state_in = testing.State(leader=True)

    with (
        _patch_is_test_active(True),
        patch(
            "workload.EtcdBenchmarkWorkload.stop_benchmark",
            side_effect=BenchmarkServiceError(
                message="Benchmark service could not be stopped cleanly",
                detailed_description="Error stopping benchmark service: failed",
            ),
        ),
        patch("workload.EtcdBenchmarkWorkload.stop_metrics_exporter") as stop_exporter,
        patch(
            "managers.etcd_benchmark.EtcdBenchmarkManager.write_metadata_to_summary_file"
        ) as write_metadata,
        patch(
            "managers.etcd_benchmark.EtcdBenchmarkManager.mark_current_test_completed"
        ) as mark_completed,
    ):
        with pytest.raises(ActionFailed) as e:
            ctx.run(ctx.on.action("stop"), state_in)

    assert "Error stopping benchmark service: failed" in str(e.value)
    assert ctx.action_results == {"error": "Benchmark service could not be stopped cleanly"}
    stop_exporter.assert_not_called()
    write_metadata.assert_not_called()
    mark_completed.assert_not_called()


def test_stop_action_fails_when_stop_metrics_exporter_raises():
    """Stop should fail when stopping the metrics exporter service fails."""
    ctx = _ctx()
    state_in = testing.State(leader=True)

    with (
        _patch_is_test_active(True),
        patch("workload.EtcdBenchmarkWorkload.stop_benchmark"),
        patch(
            "workload.EtcdBenchmarkWorkload.stop_metrics_exporter",
            side_effect=MetricsExporterServiceError(
                message="Metrics exporter service could not be stopped cleanly",
                detailed_description="Error stopping metrics exporter service: failed",
            ),
        ),
        patch(
            "managers.etcd_benchmark.EtcdBenchmarkManager.write_metadata_to_summary_file"
        ) as write_metadata,
        patch(
            "managers.etcd_benchmark.EtcdBenchmarkManager.mark_current_test_completed"
        ) as mark_completed,
    ):
        with pytest.raises(ActionFailed) as e:
            ctx.run(ctx.on.action("stop"), state_in)

    assert "Error stopping metrics exporter service: failed" in str(e.value)
    assert ctx.action_results == {"error": "Metrics exporter service could not be stopped cleanly"}
    write_metadata.assert_not_called()
    mark_completed.assert_not_called()


def test_stop_action_fails_when_writing_metadata_raises_state_error():
    """Stop should fail when persisting metadata to summary.json raises BenchmarkStateError."""
    ctx = _ctx()
    state_in = testing.State(leader=True)

    with (
        _patch_is_test_active(True),
        patch("workload.EtcdBenchmarkWorkload.stop_benchmark"),
        patch("workload.EtcdBenchmarkWorkload.stop_metrics_exporter"),
        patch(
            "managers.etcd_benchmark.EtcdBenchmarkManager.write_metadata_to_summary_file",
            side_effect=BenchmarkStateError(
                message="Failed to write metadata to summary.json",
                detailed_description="Failed to write metadata to summary.json: boom",
            ),
        ),
        patch(
            "managers.etcd_benchmark.EtcdBenchmarkManager.mark_current_test_completed"
        ) as mark_completed,
    ):
        with pytest.raises(ActionFailed) as e:
            ctx.run(ctx.on.action("stop"), state_in)

    assert "Failed to write metadata to summary.json: boom" in str(e.value)
    assert ctx.action_results == {"error": "Failed to write metadata to summary.json"}
    mark_completed.assert_not_called()


# ---------------------------------------------------------------------------
# list-tests action
# ---------------------------------------------------------------------------


def test_list_tests_action_returns_no_tests_message():
    """list-tests should return a friendly message when no tests exist."""
    ctx = _ctx()
    state_in = testing.State(leader=True)

    with patch(
        "managers.etcd_benchmark.EtcdBenchmarkManager.list_tests", return_value=[]
    ) as list_tests:
        ctx.run(ctx.on.action("list-tests"), state_in)

    list_tests.assert_called_once_with()
    assert ctx.action_results == {"tests": "No tests found."}


def test_list_tests_action_formats_test_output():
    """list-tests should format test ids with status values."""
    ctx = _ctx()
    state_in = testing.State(leader=True)

    with patch(
        "managers.etcd_benchmark.EtcdBenchmarkManager.list_tests",
        return_value=[("test-1", "running"), ("test-2", "completed")],
    ) as list_tests:
        ctx.run(ctx.on.action("list-tests"), state_in)

    list_tests.assert_called_once_with()
    assert ctx.action_results == {"tests": "test-1 (running)\ntest-2 (completed)"}


# ---------------------------------------------------------------------------
# get-summary action
# ---------------------------------------------------------------------------


def test_get_summary_action_fails_on_non_leader_unit():
    """get-summary should fail early when invoked on a non-leader unit."""
    ctx = _ctx()
    state_in = testing.State(leader=False)

    with pytest.raises(ActionFailed) as e:
        ctx.run(ctx.on.action("get-summary", params={"test-id": "test-1"}), state_in)

    assert "only supported on the leader unit" in str(e.value)
    assert ctx.action_results == {"error": "action not supported on non-leader units"}


def test_get_summary_action_fails_with_empty_test_id(caplog):
    """get-summary should fail when test-id is missing."""
    ctx = _ctx()
    state_in = testing.State(leader=True)

    with caplog.at_level("ERROR"):
        with pytest.raises(ActionFailed) as e:
            ctx.run(ctx.on.action("get-summary", params={}), state_in)

    assert "valid, non-empty test-id" in str(e.value)
    assert ctx.action_results is not None
    assert "valid test-id not found" in ctx.action_results["error"]
    assert "Please provide a valid, non-empty test-id parameter." in caplog.text


def test_get_summary_action_fails_when_test_folder_missing(caplog):
    """get-summary should fail when the test results directory does not exist."""
    ctx = _ctx()
    state_in = testing.State(leader=True)

    with patch(
        "managers.etcd_benchmark.EtcdBenchmarkManager.get_test_summary",
        side_effect=FileNotFoundError("Test results directory not found for test ID: test-1."),
    ):
        with pytest.raises(ActionFailed) as e:
            ctx.run(ctx.on.action("get-summary", params={"test-id": "test-1"}), state_in)

    assert "Test results directory not found for test ID: test-1." in str(e.value)
    assert "Verify test ID" in str(e.value)


def test_get_summary_action_returns_summary():
    """get-summary should return the manager-rendered summary text."""
    ctx = _ctx()
    state_in = testing.State(leader=True)

    with patch(
        "managers.etcd_benchmark.EtcdBenchmarkManager.get_test_summary",
        return_value="summary output",
    ) as get_summary:
        ctx.run(ctx.on.action("get-summary", params={"test-id": "test-1"}), state_in)

    get_summary.assert_called_once_with("test-1")
    assert ctx.action_results == {"results": "summary output"}


def test_get_summary_action_fails_when_summary_generation_errors(caplog):
    """get-summary should fail when summary parsing raises BenchmarkResultsParseError."""
    ctx = _ctx()
    state_in = testing.State(leader=True)

    parse_error = BenchmarkResultsParseError(
        message="Error preparing/writing summary",
        detailed_description="Error preparing/writing summary: io",
    )

    with patch(
        "managers.etcd_benchmark.EtcdBenchmarkManager.get_test_summary",
        side_effect=parse_error,
    ):
        with caplog.at_level("ERROR"):
            with pytest.raises(ActionFailed) as e:
                ctx.run(ctx.on.action("get-summary", params={"test-id": "test-1"}), state_in)

    assert "Error preparing/writing summary" in str(e.value)
    assert ctx.action_results == {"error": "Error preparing/writing summary"}


# ---------------------------------------------------------------------------
# shared: non-leader guard
# ---------------------------------------------------------------------------


def test_list_tests_action_fails_on_non_leader_unit():
    """list-tests should fail early when invoked on a non-leader unit."""
    ctx = _ctx()
    state_in = testing.State(leader=False)

    with pytest.raises(ActionFailed) as e:
        ctx.run(ctx.on.action("list-tests"), state_in)

    assert "only supported on the leader unit" in str(e.value)
    assert ctx.action_results == {"error": "action not supported on non-leader units"}
