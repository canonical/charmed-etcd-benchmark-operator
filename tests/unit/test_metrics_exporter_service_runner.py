#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for the benchmark metrics exporter template script."""

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
    """Load the metrics exporter script as a Python module."""
    pytest.importorskip("prometheus_client")

    script_path = (
        Path(__file__).resolve().parents[2] / "templates" / "benchmark_metrics_exporter.py"
    )
    spec = importlib.util.spec_from_file_location("metrics_exporter_runner", script_path)
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_benchmark_metrics_sets_exporter_up(runner_module: ModuleType) -> None:
    """BenchmarkMetrics should mark exporter_up as healthy on initialization."""
    fake_gauge = MagicMock()

    with (
        patch.object(runner_module, "Gauge", return_value=fake_gauge),
        patch.object(runner_module, "Counter", return_value=MagicMock()),
    ):
        runner_module.BenchmarkMetrics()

    fake_gauge.set.assert_called_with(1)


def test_handle_record_ignores_non_newer_sample_ids(
    runner_module: ModuleType, tmp_path: Path
) -> None:
    """_handle_record should skip records whose id is not strictly newer."""
    metrics = MagicMock()
    tailer = runner_module.JsonlTailer(tmp_path / "stdout.jsonl", metrics)
    tailer._latest_id = 10

    with patch.object(tailer, "_publish") as publish:
        tailer._handle_record({"id": 10})

    publish.assert_not_called()


def test_handle_record_publishes_newer_sample_ids(
    runner_module: ModuleType, tmp_path: Path
) -> None:
    """_handle_record should publish records with strictly increasing ids."""
    metrics = MagicMock()
    tailer = runner_module.JsonlTailer(tmp_path / "stdout.jsonl", metrics)

    payload = {"id": 1, "ts": "2026-04-30T12:00:00Z", "read": {}, "write": {}}

    with patch.object(tailer, "_publish") as publish:
        tailer._handle_record(payload)

    publish.assert_called_once_with(payload)
    assert tailer._latest_id == 1


def test_process_new_data_increments_parse_errors_on_invalid_json(
    runner_module: ModuleType, tmp_path: Path
) -> None:
    """_process_new_data should track parse errors when JSON decoding fails."""
    path = tmp_path / "stdout.jsonl"
    path.write_text("{bad-json}\n", encoding="utf-8")

    metrics = MagicMock()
    tailer = runner_module.JsonlTailer(path, metrics)

    tailer._process_new_data()

    metrics.parse_errors.inc.assert_called_once_with()


def test_process_new_data_processes_complete_line_once(
    runner_module: ModuleType, tmp_path: Path
) -> None:
    """_process_new_data should process complete newline-terminated records."""
    path = tmp_path / "stdout.jsonl"
    payload = {"id": 1, "ts": "2026-04-30T12:00:00Z", "read": {}, "write": {}}
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    metrics = MagicMock()
    tailer = runner_module.JsonlTailer(path, metrics)

    with patch.object(tailer, "_handle_record") as handle_record:
        tailer._process_new_data()

    handle_record.assert_called_once_with(payload)
    metrics.rows_processed.inc.assert_called_once_with()


def test_process_new_data_ignores_partial_line(runner_module: ModuleType, tmp_path: Path) -> None:
    """_process_new_data should ignore partial records without a trailing newline."""
    path = tmp_path / "stdout.jsonl"
    path.write_text('{"id": 1', encoding="utf-8")

    metrics = MagicMock()
    tailer = runner_module.JsonlTailer(path, metrics)

    with patch.object(tailer, "_handle_record") as handle_record:
        tailer._process_new_data()

    handle_record.assert_not_called()
    metrics.rows_processed.inc.assert_not_called()


def test_publish_updates_metric_values(runner_module: ModuleType, tmp_path: Path) -> None:
    """_publish should emit gauges for both read and write operations."""
    metrics = MagicMock()

    label_gauge = MagicMock()
    for metric_name in (
        "total_ops",
        "avg_latency",
        "stddev_latency",
        "throughput",
        "latency_quantile",
    ):
        getattr(metrics, metric_name).labels.return_value = label_gauge

    tailer = runner_module.JsonlTailer(tmp_path / "stdout.jsonl", metrics)

    payload = {
        "id": 7,
        "ts": "2026-04-30T12:00:00Z",
        "read": {
            "ops": 10,
            "avg": 0.1,
            "stddev": 0.01,
            "rps": 100,
            "p50": 0.05,
            "p90": 0.09,
            "p99": 0.12,
        },
        "write": {
            "ops": 20,
            "avg": 0.2,
            "stddev": 0.02,
            "rps": 200,
            "p50": 0.15,
            "p90": 0.19,
            "p99": 0.22,
        },
    }

    tailer._publish(payload)

    metrics.iteration.set.assert_called_once_with(7)
    metrics.last_ts.set.assert_called_once()
    assert metrics.total_ops.labels.call_count == 2
    assert metrics.avg_latency.labels.call_count == 2
    assert metrics.latency_quantile.labels.call_count == 6


def test_main_raises_when_jsonl_path_env_is_missing(runner_module: ModuleType) -> None:
    """Main should fail fast when ETCD_BENCHMARK_JSONL_PATH is not configured."""
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(RuntimeError) as e:
            runner_module.main()

    assert "ETCD_BENCHMARK_JSONL_PATH must be set" in str(e.value)


def test_main_starts_server_and_thread(runner_module: ModuleType) -> None:
    """Main should start Prometheus HTTP server and spawn tailer thread."""
    env = {
        "ETCD_BENCHMARK_JSONL_PATH": "/tmp/stdout.jsonl",
        "ETCD_BENCHMARK_METRICS_PORT": "9999",
    }

    with (
        patch.dict(os.environ, env, clear=True),
        patch.object(runner_module, "start_http_server") as start_server,
        patch.object(runner_module, "Thread") as thread_cls,
        patch.object(runner_module, "BenchmarkMetrics", return_value=MagicMock()),
        patch.object(runner_module, "JsonlTailer") as tailer_cls,
        patch.object(runner_module.time, "sleep", side_effect=KeyboardInterrupt),
    ):
        with pytest.raises(KeyboardInterrupt):
            runner_module.main()

    start_server.assert_called_once_with(9999)
    tailer_cls.assert_called_once()
    thread_cls.assert_called_once()
    thread_cls.return_value.start.assert_called_once_with()
