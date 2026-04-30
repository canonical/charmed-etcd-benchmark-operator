#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for etcd benchmark related managers."""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from common.exceptions import BenchmarkConfigurationError
from core.models import BenchmarkMetadata
from literals import METADATA_JSON_FILE_NAME, SUMMARY_JSON_FILE_NAME, TEST_RESULTS_DIR_NAME
from managers.etcd_benchmark import EtcdBenchmarkManager


def _make_etcd_benchmark_manager():
    """Create an EtcdBenchmarkManager with a mocked charm."""
    charm = MagicMock()
    charm.workload = MagicMock()
    charm.config_manager = MagicMock()
    charm.etcd_interface_state = MagicMock()
    charm.config = {}
    return EtcdBenchmarkManager(charm), charm


def test_setup_test_returns_enriched_config():
    """setup_test should enrich runner config with runtime details."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()

    charm.etcd_interface_state.uris = "https://10.0.0.1:2379"
    charm.config = {"test-name": "smoke-test"}
    charm.config_manager.get_charm_config.return_value = {
        "clients": 1,
        "report_interval": 10,
    }

    with (
        patch("managers.etcd_benchmark.generate_test_id", return_value="test-123"),
        patch.object(
            etcd_benchmark_manager,
            "_create_initial_test_artifacts",
            return_value="/tmp/results",
        ) as create_artifacts,
    ):
        config = etcd_benchmark_manager.setup_test()

    create_artifacts.assert_called_once()
    metadata = create_artifacts.call_args[0][0]
    assert isinstance(metadata, BenchmarkMetadata)
    assert metadata.test_id == "test-123"
    assert metadata.test_name == "smoke-test"

    assert config["current_test_id"] == "test-123"
    assert config["current_test_name"] == "smoke-test"
    assert config["results_dir"] == "/tmp/results"
    assert config["endpoints"] == "https://10.0.0.1:2379"


def test_setup_test_raises_on_invalid_report_interval():
    """setup_test should raise when report_interval is set below 1."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()

    charm.etcd_interface_state.uris = "https://10.0.0.1:2379"
    charm.config_manager.get_charm_config.return_value = {"report_interval": 0}

    with pytest.raises(BenchmarkConfigurationError) as e:
        etcd_benchmark_manager.setup_test()

    assert "report-interval" in e.value.detailed_description


def test_list_tests_returns_empty_when_tests_dir_missing(tmp_path):
    """list_tests should return an empty list when tests root is absent."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()

    missing_dir = tmp_path / "does-not-exist"
    charm.workload.file_exists.side_effect = lambda file_path: Path(file_path).exists()

    assert etcd_benchmark_manager.list_tests(str(missing_dir)) == []


def test_list_tests_returns_status_from_metadata(tmp_path):
    """list_tests should classify tests as in progress or completed from metadata."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()

    tests_root = tmp_path / "tests"
    test_1 = tests_root / "test-1"
    test_2 = tests_root / "test-2"
    test_1.mkdir(parents=True)
    test_2.mkdir(parents=True)

    active_metadata = BenchmarkMetadata(
        test_id="test-2",
        test_name="active",
        started_at=datetime.now(UTC),
        test_config={},
        is_active=True,
    )
    completed_metadata = BenchmarkMetadata(
        test_id="test-1",
        test_name="done",
        started_at=datetime.now(UTC),
        test_config={},
        is_active=False,
    )

    (test_2 / METADATA_JSON_FILE_NAME).write_text(json.dumps(active_metadata.to_dict()))
    (test_1 / METADATA_JSON_FILE_NAME).write_text(json.dumps(completed_metadata.to_dict()))

    charm.workload.file_exists.side_effect = lambda file_path: Path(file_path).exists()

    assert etcd_benchmark_manager.list_tests(str(tests_root)) == [
        ("test-2", "in progress"),
        ("test-1", "completed"),
    ]


def test_get_test_summary_returns_cached_summary(tmp_path):
    """get_test_summary should return formatted cached summary if available."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()

    test_dir = tmp_path / "test-1"
    test_dir.mkdir(parents=True)
    summary_path = test_dir / SUMMARY_JSON_FILE_NAME
    summary_data = {"metadata": {"test_id": "test-1"}, "operations": {}}
    summary_path.write_text(json.dumps(summary_data))

    charm.workload.file_exists.side_effect = lambda file_path: Path(file_path).exists()

    assert etcd_benchmark_manager.get_test_summary(str(test_dir)) == json.dumps(
        summary_data, indent=2
    )


def test_get_test_summary_falls_back_when_cached_summary_is_malformed(tmp_path):
    """get_test_summary should rebuild summary when cached summary is malformed."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()

    test_dir = tmp_path / "test-1"
    test_dir.mkdir(parents=True)
    (test_dir / SUMMARY_JSON_FILE_NAME).write_text("{not-json")

    charm.workload.file_exists.side_effect = lambda file_path: Path(file_path).exists()

    with patch.object(
        etcd_benchmark_manager,
        "_prepare_and_write_summary",
        return_value="rebuilt-summary",
    ) as prepare_summary:
        summary = etcd_benchmark_manager.get_test_summary(str(test_dir))

    prepare_summary.assert_called_once_with(str(test_dir))
    assert summary == "rebuilt-summary"


def test_prepare_and_write_summary_fails_when_metadata_missing(tmp_path):
    """_prepare_and_write_summary should fail when metadata is missing."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()

    test_dir = tmp_path / "test-1"
    (test_dir / TEST_RESULTS_DIR_NAME).mkdir(parents=True)

    charm.workload.file_exists.side_effect = lambda file_path: Path(file_path).exists()

    with pytest.raises(FileNotFoundError) as e:
        etcd_benchmark_manager._prepare_and_write_summary(str(test_dir))

    assert "Missing metadata file" in str(e.value)


def test_parse_final_operations_from_stderr_parses_read_and_write_blocks(tmp_path):
    """_parse_final_operations_from_stderr should parse complete read/write blocks."""
    etcd_benchmark_manager, _ = _make_etcd_benchmark_manager()

    stderr_path = tmp_path / "stderr.log"
    stderr_path.write_text(
        "\n".join(
            [
                "Total Read Ops: 100",
                "Average: 0.010 secs",
                "Stddev: 0.001 secs",
                "Requests/sec: 1000",
                "50% in 0.005 secs",
                "90% in 0.020 secs",
                "99% in 0.030 secs",
                "Total Write Ops: 50",
                "Average: 0.020 secs",
                "Stddev: 0.002 secs",
                "Requests/sec: 500",
                "50% in 0.010 secs",
                "90% in 0.030 secs",
                "99% in 0.040 secs",
            ]
        )
    )

    operations = etcd_benchmark_manager._parse_final_operations_from_stderr(stderr_path)

    assert operations["read"]["total_ops"] == 100
    assert operations["write"]["total_ops"] == 50


def test_aggregate_jsonl_results_fails_when_file_has_no_data(tmp_path):
    """_aggregate_jsonl_results should fail when stdout has no benchmark samples."""
    etcd_benchmark_manager, _ = _make_etcd_benchmark_manager()

    stdout_path = tmp_path / "stdout.jsonl"
    stdout_path.write_text("\n\n")

    with pytest.raises(ValueError) as e:
        etcd_benchmark_manager._aggregate_jsonl_results(stdout_path)

    assert "No benchmark data found" in str(e.value)
