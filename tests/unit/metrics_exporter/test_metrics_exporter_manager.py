#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for the metrics exporter manager."""

from unittest.mock import patch

import pytest
from charmlibs import systemd

from literals import METRICS_EXPORTER_SERVICE_NAME
from managers.metrics_exporter import MetricsExporterManager


def test_start_metrics_exporter_renders_service_with_charm_venv_python(tmp_path):
    """start_metrics_exporter should render ExecStart with charm venv python and runner path."""
    service_file = tmp_path / "benchmark-metrics-exporter.service"

    with (
        patch("managers.metrics_exporter.METRICS_EXPORTER_SERVICE_FILE_PATH", str(service_file)),
        patch(
            "managers.metrics_exporter.render_template", return_value="[Unit]\nDescription=x\n"
        ) as render,
        patch("managers.metrics_exporter.systemd.daemon_reload") as daemon_reload,
        patch("managers.metrics_exporter.systemd.service_enable") as enable,
        patch("managers.metrics_exporter.systemd.service_start") as start,
        patch.dict("os.environ", {"CHARM_DIR": "/var/lib/juju/agents/unit-test/charm"}),
    ):
        MetricsExporterManager().start_metrics_exporter(
            {"results_dir": "/tmp/test-1/results", "current_test_id": "test-1"}
        )

    render.assert_called_once()
    _, context = render.call_args.args
    assert context == {
        "jsonl_path": "/tmp/test-1/results/stdout.jsonl",
        "test_id": "test-1",
        "metrics_port": "9100",
        "python_bin": "/var/lib/juju/agents/unit-test/charm/venv/bin/python",
        "runner_path": "/usr/local/bin/benchmark_metrics_exporter.py",
    }
    assert service_file.read_text() == "[Unit]\nDescription=x\n"
    daemon_reload.assert_called_once_with()
    enable.assert_called_once_with(METRICS_EXPORTER_SERVICE_NAME)
    start.assert_called_once_with(METRICS_EXPORTER_SERVICE_NAME)


def test_start_metrics_exporter_raises_when_service_enable_fails(tmp_path, caplog):
    """start_metrics_exporter should log and re-raise when service enable fails."""
    service_file = tmp_path / "benchmark-metrics-exporter.service"

    with (
        patch("managers.metrics_exporter.METRICS_EXPORTER_SERVICE_FILE_PATH", str(service_file)),
        patch("managers.metrics_exporter.render_template", return_value="[Unit]\nDescription=x\n"),
        patch("managers.metrics_exporter.systemd.daemon_reload"),
        patch(
            "managers.metrics_exporter.systemd.service_enable",
            side_effect=systemd.SystemdError("enable failed"),
        ),
        patch("managers.metrics_exporter.systemd.service_start") as start,
        patch.dict("os.environ", {"CHARM_DIR": "/var/lib/juju/agents/unit-test/charm"}),
    ):
        with pytest.raises(systemd.SystemdError):
            MetricsExporterManager().start_metrics_exporter(
                {"results_dir": "/tmp/test-1/results", "current_test_id": "test-1"}
            )

    start.assert_not_called()
    assert "Metric exporter service could not be enabled cleanly" in caplog.text


def test_start_metrics_exporter_raises_when_service_start_fails(tmp_path, caplog):
    """start_metrics_exporter should log and re-raise when service start fails."""
    service_file = tmp_path / "benchmark-metrics-exporter.service"

    with (
        patch("managers.metrics_exporter.METRICS_EXPORTER_SERVICE_FILE_PATH", str(service_file)),
        patch("managers.metrics_exporter.render_template", return_value="[Unit]\nDescription=x\n"),
        patch("managers.metrics_exporter.systemd.daemon_reload"),
        patch("managers.metrics_exporter.systemd.service_enable"),
        patch(
            "managers.metrics_exporter.systemd.service_start",
            side_effect=systemd.SystemdError("start failed"),
        ),
        patch.dict("os.environ", {"CHARM_DIR": "/var/lib/juju/agents/unit-test/charm"}),
    ):
        with pytest.raises(systemd.SystemdError):
            MetricsExporterManager().start_metrics_exporter(
                {"results_dir": "/tmp/test-1/results", "current_test_id": "test-1"}
            )

    assert "Metric exporter service could not be enabled cleanly" in caplog.text


def test_stop_metrics_exporter_stops_and_disables_service():
    """stop_metrics_exporter should stop and disable the service."""
    with (
        patch("managers.metrics_exporter.systemd.service_stop") as stop,
        patch("managers.metrics_exporter.systemd.service_disable") as disable,
    ):
        MetricsExporterManager().stop_metrics_exporter()

    stop.assert_called_once_with(METRICS_EXPORTER_SERVICE_NAME)
    disable.assert_called_once_with(METRICS_EXPORTER_SERVICE_NAME)


def test_stop_metrics_exporter_raises_when_service_stop_fails(caplog):
    """stop_metrics_exporter should log and re-raise when service stop fails."""
    with (
        patch(
            "managers.metrics_exporter.systemd.service_stop",
            side_effect=systemd.SystemdError("stop failed"),
        ),
        patch("managers.metrics_exporter.systemd.service_disable") as disable,
    ):
        with pytest.raises(systemd.SystemdError):
            MetricsExporterManager().stop_metrics_exporter()

    disable.assert_not_called()
    assert "Metric exporter service could not be stopped" in caplog.text


def test_stop_metrics_exporter_raises_when_service_disable_fails(caplog):
    """stop_metrics_exporter should log and re-raise when service disable fails."""
    with (
        patch("managers.metrics_exporter.systemd.service_stop"),
        patch(
            "managers.metrics_exporter.systemd.service_disable",
            side_effect=systemd.SystemdError("disable failed"),
        ),
    ):
        with pytest.raises(systemd.SystemdError):
            MetricsExporterManager().stop_metrics_exporter()

    assert "Metric exporter service could not be stopped" in caplog.text
