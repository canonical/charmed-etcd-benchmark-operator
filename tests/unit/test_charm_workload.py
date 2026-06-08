#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for workload-related charm hooks and workload helpers."""

from pathlib import Path
from subprocess import CalledProcessError
from unittest.mock import MagicMock, PropertyMock, patch

import ops
import pytest
from charmlibs import snap, systemd
from ops import testing
from ops._private.harness import ActionFailed

from charm import CharmedEtcdBenchmarkOperatorCharm
from common.exceptions import (
    BenchmarkServiceError,
    BenchmarkWorkloadError,
    MetricsExporterServiceError,
)
from literals import (
    BENCHMARK_SERVICE_NAME,
    BENCHMARK_TEMPLATE_FILE_NAME,
    METRICS_EXPORTER_SERVICE_NAME,
    METRICS_EXPORTER_TEMPLATE_FILE_NAME,
    SNAP_CHANNEL,
    SNAP_NAME,
)
from workload import (
    EtcdBenchmarkWorkload,
    _render_benchmark_service,
    _render_metrics_exporter_service,
)


@pytest.fixture(autouse=True)
def patch_snap_cache():
    """Patch SnapCache for all tests so charm/workload can be constructed safely."""
    mock_snap = MagicMock()
    with patch("workload.snap.SnapCache") as mock_snap_cache:
        mock_snap_cache.return_value.__getitem__.return_value = mock_snap
        yield mock_snap


@pytest.fixture
def workload():
    """Create a workload instance with SnapCache mocked."""
    with patch("workload.snap.SnapCache") as mock_snap_cache:
        mock_snap = MagicMock()
        mock_snap_cache.return_value.__getitem__.return_value = mock_snap
        yield EtcdBenchmarkWorkload()


# Hook tests: install hook


def test_install_success(patch_snap_cache):
    """Install hook should execute real workload.install and install the snap."""
    ctx = testing.Context(CharmedEtcdBenchmarkOperatorCharm)
    state_in = testing.State()

    with (
        patch("shutil.copyfile"),
        patch("pathlib.Path.chmod"),
    ):
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

    with (
        patch("shutil.copyfile"),
        patch("pathlib.Path.chmod"),
    ):
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

    with (
        patch("shutil.copyfile"),
        patch("pathlib.Path.chmod"),
    ):
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
    assert state_out.unit_status == ops.BlockedStatus("Error with the workload")


# Hook tests: run action


def test_run_action_fails_when_already_running():
    """Run action should fail when a benchmark service is already running."""
    ctx = testing.Context(CharmedEtcdBenchmarkOperatorCharm)
    state_in = testing.State()

    with patch("workload.EtcdBenchmarkWorkload.is_benchmark_running", return_value=True):
        with pytest.raises(ActionFailed) as e:
            ctx.run(ctx.on.action("run"), state_in)

    assert "already a benchmark in progress" in str(e.value)
    assert ctx.action_results == {"error": "A benchmark is already in progress"}


def test_run_action_fails_without_relation():
    """Run action should fail if the etcd relation is missing."""
    ctx = testing.Context(CharmedEtcdBenchmarkOperatorCharm)
    state_in = testing.State()

    with (
        patch("workload.EtcdBenchmarkWorkload.is_benchmark_running", return_value=False),
        patch(
            "core.interfaces.EtcdInterfaceState.relation",
            new_callable=PropertyMock,
            return_value=None,
        ),
        patch(
            "core.interfaces.EtcdInterfaceState.uris", new_callable=PropertyMock, return_value=None
        ),
    ):
        with pytest.raises(ActionFailed) as e:
            ctx.run(ctx.on.action("run"), state_in)

    assert "needed in order to run this action" in str(e.value)
    assert ctx.action_results == {"error": "etcd relation missing"}


def test_run_action_success():
    """Run action should set up and start the benchmark service."""
    ctx = testing.Context(CharmedEtcdBenchmarkOperatorCharm)
    state_in = testing.State()

    benchmark_config = {"results_dir": "/tmp/results", "some": "config"}
    metrics_config = {
        "jsonl_path": "/tmp/results/stdout.jsonl",
        "test_id": "test-1",
        "metrics_port": "9100",
        "python_bin": "/tmp/charm/venv/bin/python",
        "runner_path": "/usr/local/bin/benchmark_metrics_exporter.py",
    }

    with (
        patch("workload.EtcdBenchmarkWorkload.is_benchmark_running", return_value=False),
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
        ) as setup_test,
        patch(
            "managers.metrics_exporter.MetricsExporterManager.setup_metrics_exporter",
            return_value=metrics_config,
        ) as setup_exporter,
        patch("workload.EtcdBenchmarkWorkload.start_metrics_exporter") as start_exporter,
        patch("workload.EtcdBenchmarkWorkload.start_benchmark") as start_benchmark,
        patch.dict("os.environ", {"CHARM_DIR": "/tmp/charm"}),
    ):
        ctx.run(ctx.on.action("run"), state_in)

    setup_test.assert_called_once_with()
    setup_exporter.assert_called_once_with(benchmark_config)
    start_exporter.assert_called_once_with(
        "/tmp/charm/templates",
        metrics_config,
    )
    start_benchmark.assert_called_once_with(
        "/tmp/charm/templates",
        benchmark_config,
    )
    assert ctx.action_results is not None
    assert "Benchmark started successfully." in ctx.action_results["results"]


def test_run_action_fails_when_start_service_raises_systemd_error():
    """Run action should fail with clear error when benchmark startup fails."""
    ctx = testing.Context(CharmedEtcdBenchmarkOperatorCharm)
    state_in = testing.State()

    with (
        patch("workload.EtcdBenchmarkWorkload.is_benchmark_running", return_value=False),
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
            return_value={"results_dir": "/tmp/results"},
        ),
        patch(
            "managers.metrics_exporter.MetricsExporterManager.setup_metrics_exporter",
            return_value={"jsonl_path": "/tmp/results/stdout.jsonl"},
        ),
        patch("workload.EtcdBenchmarkWorkload.start_metrics_exporter"),
        patch(
            "workload.EtcdBenchmarkWorkload.start_benchmark",
            side_effect=BenchmarkServiceError(
                message="Benchmark service could not be started cleanly",
                detailed_description="Error starting benchmark service: failed",
            ),
        ),
    ):
        with pytest.raises(ActionFailed) as e:
            ctx.run(ctx.on.action("run"), state_in)

    assert "Error starting benchmark service: failed" in str(e.value)
    assert ctx.action_results == {"error": "Benchmark service could not be started cleanly"}


# Direct workload tests: file utilities


def test_write_file_creates_parent_dirs_and_writes_content(workload, tmp_path):
    """write_file should create parent dirs and write content."""
    target = tmp_path / "nested" / "dir" / "test.txt"

    workload.write_file(content="hello world", file=str(target))

    assert target.exists()
    assert target.read_text() == "hello world"


def test_write_file_creates_empty_file_when_content_is_none(workload, tmp_path):
    """write_file should create/truncate files even when content is None."""
    target = tmp_path / "nested" / "empty.txt"

    workload.write_file(file=str(target))

    assert target.exists()
    assert target.read_text() == ""


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


def test_file_exists_reports_path_state(workload, tmp_path):
    """file_exists should return whether the path exists."""
    present = tmp_path / "present.txt"
    present.write_text("data")

    assert workload.file_exists(str(present)) is True
    assert workload.file_exists(str(tmp_path / "missing.txt")) is False


def test_render_service_writes_file_and_reloads_systemd(tmp_path):
    """_render_service should render, write the unit file, and reload systemd."""
    service_file = tmp_path / "benchmark.service"
    config = {"k": "v"}

    with (
        patch("workload.BENCHMARK_SERVICE_FILE_PATH", str(service_file)),
        patch(
            "workload.render_template", return_value="[Unit]\nDescription=benchmark\n"
        ) as render,
        patch("workload.systemd.daemon_reload") as daemon_reload,
    ):
        _render_benchmark_service("/tmp/templates", config)

    render.assert_called_once_with(Path(f"/tmp/templates/{BENCHMARK_TEMPLATE_FILE_NAME}"), config)
    assert service_file.read_text() == "[Unit]\nDescription=benchmark\n"
    daemon_reload.assert_called_once_with()


def test_render_metrics_exporter_service_writes_file_and_reloads_systemd(tmp_path):
    """_render_metrics_exporter_service should render, write, and reload systemd."""
    service_file = tmp_path / "metrics-exporter.service"
    config = {"k": "v"}

    with (
        patch("workload.METRICS_EXPORTER_SERVICE_FILE_PATH", str(service_file)),
        patch("workload.render_template", return_value="[Unit]\nDescription=metrics\n") as render,
        patch("workload.systemd.daemon_reload") as daemon_reload,
    ):
        _render_metrics_exporter_service("/tmp/templates", config)

    render.assert_called_once_with(
        Path(f"/tmp/templates/{METRICS_EXPORTER_TEMPLATE_FILE_NAME}"), config
    )
    assert service_file.read_text() == "[Unit]\nDescription=metrics\n"
    daemon_reload.assert_called_once_with()


# Direct workload tests: command methods


def test_workload_start_runs_help_check(workload):
    """Direct workload test for start()."""
    with patch("workload.subprocess.run") as mock_run:
        mock_run.return_value.stdout = b"help output"

        workload.verify_workload_ready()

    mock_run.assert_called_once_with(
        [f"{SNAP_NAME}.benchmark", "--help"],
        capture_output=True,
        check=True,
    )


def test_start_service_renders_and_enables_service(workload):
    """start_service should render and start the benchmark systemd unit."""
    with (
        patch("workload._render_benchmark_service") as render,
        patch("workload.systemd.service_enable") as enable,
        patch("workload.systemd.service_start") as start,
    ):
        workload.start_benchmark(template_dir="/tmp/templates", config={"a": 1})

    render.assert_called_once_with("/tmp/templates", {"a": 1})
    enable.assert_called_once_with(BENCHMARK_SERVICE_NAME)
    start.assert_called_once_with(BENCHMARK_SERVICE_NAME)


def test_start_service_raises_when_systemd_fails(workload):
    """start_service should re-raise systemd errors for caller handling."""
    with (
        patch("workload._render_benchmark_service"),
        patch("workload.systemd.service_enable", side_effect=systemd.SystemdError("failed")),
    ):
        with pytest.raises(BenchmarkServiceError) as e:
            workload.start_benchmark(template_dir="/tmp/templates", config={})

    assert e.value.message == "Benchmark service could not be started cleanly"


def test_stop_service_returns_early_when_not_running(workload):
    """stop_service should no-op when service is already inactive."""
    with (
        patch.object(workload, "is_benchmark_running", return_value=False),
        patch("workload.systemd.service_stop") as stop,
        patch("workload.systemd.service_disable") as disable,
    ):
        workload.stop_benchmark()

    stop.assert_not_called()
    disable.assert_not_called()


def test_stop_service_stops_and_disables_when_running(workload):
    """stop_service should stop and disable the service when active."""
    with (
        patch.object(workload, "is_benchmark_running", return_value=True),
        patch("workload.systemd.service_stop") as stop,
        patch("workload.systemd.service_disable") as disable,
    ):
        workload.stop_benchmark()

    stop.assert_called_once_with(BENCHMARK_SERVICE_NAME)
    disable.assert_called_once_with(BENCHMARK_SERVICE_NAME)


def test_stop_service_raises_when_systemd_fails(workload):
    """stop_service should re-raise systemd errors for caller handling."""
    with (
        patch.object(workload, "is_benchmark_running", return_value=True),
        patch("workload.systemd.service_stop", side_effect=systemd.SystemdError("failed")),
    ):
        with pytest.raises(BenchmarkServiceError) as e:
            workload.stop_benchmark()

    assert e.value.message == "Benchmark service could not be stopped cleanly"


def test_is_running_returns_true_when_service_is_active(workload):
    """is_running should return true when systemd reports active."""
    with patch("workload.systemd.service_running", return_value=True):
        assert workload.is_benchmark_running() is True


def test_is_running_returns_false_on_systemd_error(workload):
    """is_running should return false when service query raises."""
    with patch("workload.systemd.service_running", side_effect=systemd.SystemdError("failed")):
        assert workload.is_benchmark_running() is False


def test_start_metrics_exporter_renders_and_starts_service(workload):
    """start_metrics_exporter should render and start metrics exporter systemd unit."""
    with (
        patch("workload._render_metrics_exporter_service") as render,
        patch("workload.systemd.service_enable") as enable,
        patch("workload.systemd.service_start") as start,
    ):
        workload.start_metrics_exporter(template_dir="/tmp/templates", config={"a": 1})

    render.assert_called_once_with("/tmp/templates", {"a": 1})
    enable.assert_called_once_with(METRICS_EXPORTER_SERVICE_NAME)
    start.assert_called_once_with(METRICS_EXPORTER_SERVICE_NAME)


def test_start_metrics_exporter_raises_when_systemd_fails(workload):
    """start_metrics_exporter should raise MetricsExporterServiceError on systemd failure."""
    with (
        patch("workload._render_metrics_exporter_service"),
        patch("workload.systemd.service_enable", side_effect=systemd.SystemdError("failed")),
    ):
        with pytest.raises(MetricsExporterServiceError) as e:
            workload.start_metrics_exporter(template_dir="/tmp/templates", config={})

    assert e.value.message == "Metrics exporter service could not be started cleanly"


def test_stop_metrics_exporter_stops_and_disables_service(workload):
    """stop_metrics_exporter should stop and disable metrics exporter service."""
    with (
        patch("workload.systemd.service_stop") as stop,
        patch("workload.systemd.service_disable") as disable,
    ):
        workload.stop_metrics_exporter()

    stop.assert_called_once_with(METRICS_EXPORTER_SERVICE_NAME)
    disable.assert_called_once_with(METRICS_EXPORTER_SERVICE_NAME)


def test_stop_metrics_exporter_raises_when_systemd_fails(workload):
    """stop_metrics_exporter should raise MetricsExporterServiceError on systemd failure."""
    with patch("workload.systemd.service_stop", side_effect=systemd.SystemdError("failed")):
        with pytest.raises(MetricsExporterServiceError) as e:
            workload.stop_metrics_exporter()

    assert e.value.message == "Metrics exporter service could not be stopped cleanly"


def test_verify_workload_ready_raises_benchmark_workload_error(workload):
    """verify_workload_ready should wrap subprocess failures in BenchmarkWorkloadError."""
    with patch(
        "workload.subprocess.run",
        side_effect=CalledProcessError(1, [f"{SNAP_NAME}.benchmark", "--help"]),
    ):
        with pytest.raises(BenchmarkWorkloadError) as e:
            workload.verify_workload_ready()

    assert e.value.message == "Error verifying benchmark tool"
