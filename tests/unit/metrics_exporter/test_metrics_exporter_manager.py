#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for the metrics exporter manager."""

from unittest.mock import patch

from literals import METRICS_EXPORTER_RUNNER_FILE_PATH, METRICS_PORT
from managers.metrics_exporter import MetricsExporterManager


def test_setup_metrics_exporter_returns_expected_config_with_charm_dir():
    """setup_metrics_exporter must return exporter runtime config derived from benchmark config."""
    with patch.dict("os.environ", {"CHARM_DIR": "/var/lib/juju/agents/unit-test/charm"}):
        config = MetricsExporterManager().setup_metrics_exporter(
            {"results_dir": "/tmp/test-1/results", "current_test_id": "test-1"}
        )

    assert config == {
        "jsonl_path": "/tmp/test-1/results/stdout.jsonl",
        "test_id": "test-1",
        "metrics_port": METRICS_PORT,
        "python_bin": "/var/lib/juju/agents/unit-test/charm/venv/bin/python",
        "runner_path": METRICS_EXPORTER_RUNNER_FILE_PATH,
    }


def test_setup_metrics_exporter_uses_defaults_when_values_missing():
    """setup_metrics_exporter should gracefully default missing benchmark and env values."""
    with patch.dict("os.environ", {}, clear=True):
        config = MetricsExporterManager().setup_metrics_exporter({})

    assert config == {
        "jsonl_path": "/stdout.jsonl",
        "test_id": "",
        "metrics_port": METRICS_PORT,
        "python_bin": "/venv/bin/python",
        "runner_path": METRICS_EXPORTER_RUNNER_FILE_PATH,
    }
