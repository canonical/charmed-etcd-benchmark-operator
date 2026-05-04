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


def test_setup_test_includes_cert_paths_in_config():
    """setup_test should add TLS cert paths to the returned config dict."""
    from literals import CA_CERT_PATH, CLIENT_CERT_PATH, CLIENT_KEY_PATH

    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()
    charm.etcd_interface_state.uris = "https://10.0.0.1:2379"
    charm.config = {"test-name": "tls-test"}
    charm.config_manager.get_charm_config.return_value = {"clients": 1, "report_interval": 5}

    with (
        patch("managers.etcd_benchmark.generate_test_id", return_value="tid-tls"),
        patch.object(
            etcd_benchmark_manager,
            "_create_initial_test_artifacts",
            return_value="/tmp/results-tls",
        ),
    ):
        config = etcd_benchmark_manager.setup_test()

    assert config["client_cert_path"] == CLIENT_CERT_PATH
    assert config["client_key_path"] == CLIENT_KEY_PATH
    assert config["ca_cert_path"] == CA_CERT_PATH


def test_list_tests_returns_unknown_status_when_metadata_is_malformed(tmp_path):
    """list_tests should return 'unknown' status for a tets if metadata JSON is invalid."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()

    tests_root = tmp_path / "tests"
    test_dir = tests_root / "test-bad"
    test_dir.mkdir(parents=True)
    (test_dir / METADATA_JSON_FILE_NAME).write_text("{not valid json")

    charm.workload.file_exists.side_effect = lambda file_path: Path(file_path).exists()

    results = etcd_benchmark_manager.list_tests(str(tests_root))
    assert results == [("test-bad", "unknown")]


def test_list_tests_returns_unknown_status_when_metadata_is_absent(tmp_path):
    """list_tests should return 'unknown' status when there is no metadata file."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()

    tests_root = tmp_path / "tests"
    test_dir = tests_root / "test-no-meta"
    test_dir.mkdir(parents=True)

    charm.workload.file_exists.side_effect = lambda file_path: Path(file_path).exists()

    results = etcd_benchmark_manager.list_tests(str(tests_root))
    assert results == [("test-no-meta", "unknown")]


# ---------------------------------------------------------------------------
# get_test_summary – delegates to _prepare_and_write_summary when no cache
# ---------------------------------------------------------------------------


def test_get_test_summary_calls_prepare_when_summary_file_absent(tmp_path):
    """get_test_summary should call _prepare_and_write_summary when summary.json is missing."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()

    test_dir = tmp_path / "test-1"
    test_dir.mkdir(parents=True)

    charm.workload.file_exists.side_effect = lambda file_path: Path(file_path).exists()

    with patch.object(
        etcd_benchmark_manager,
        "_prepare_and_write_summary",
        return_value="fresh-summary",
    ) as prepare_summary:
        result = etcd_benchmark_manager.get_test_summary(str(test_dir))

    prepare_summary.assert_called_once_with(str(test_dir))
    assert result == "fresh-summary"


# ---------------------------------------------------------------------------
# _prepare_and_write_summary – various branches
# ---------------------------------------------------------------------------


def _make_stderr_content():
    return "\n".join(
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


def _make_stdout_jsonl():
    row = json.dumps(
        {
            "read": {"ops": 100, "rps": 1000.0, "p50": 0.005, "p90": 0.020, "p99": 0.030, "avg": 0.010, "stddev": 0.001},
            "write": {"ops": 50, "rps": 500.0, "p50": 0.010, "p90": 0.030, "p99": 0.040, "avg": 0.020, "stddev": 0.002},
        }
    )
    return row + "\n"


def test_prepare_and_write_summary_fails_when_results_dir_missing(tmp_path):
    """_prepare_and_write_summary should fail when results dir is missing."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()

    test_dir = tmp_path / "test-1"
    test_dir.mkdir(parents=True)
    metadata = BenchmarkMetadata(
        test_id="test-1",
        test_name="t",
        started_at=datetime.now(UTC),
        test_config={},
        is_active=False,
    )
    (test_dir / METADATA_JSON_FILE_NAME).write_text(json.dumps(metadata.to_dict()))

    charm.workload.file_exists.side_effect = lambda file_path: Path(file_path).exists()

    with pytest.raises(FileNotFoundError) as e:
        etcd_benchmark_manager._prepare_and_write_summary(str(test_dir))

    assert "Missing results dir" in str(e.value)


def test_prepare_and_write_summary_for_completed_test_from_stderr(tmp_path):
    """_prepare_and_write_summary should build summary from stderr for completed tests."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()

    test_dir = tmp_path / "test-1"
    results_dir = test_dir / TEST_RESULTS_DIR_NAME
    results_dir.mkdir(parents=True)

    metadata = BenchmarkMetadata(
        test_id="test-1",
        test_name="done",
        started_at=datetime.now(UTC),
        test_config={},
        is_active=False,
    )
    (test_dir / METADATA_JSON_FILE_NAME).write_text(json.dumps(metadata.to_dict()))
    (results_dir / "stderr.log").write_text(_make_stderr_content())
    (results_dir / "stdout.jsonl").write_text(_make_stdout_jsonl())

    charm.workload.file_exists.side_effect = lambda file_path: Path(file_path).exists()

    summary_str = etcd_benchmark_manager._prepare_and_write_summary(str(test_dir))
    summary = json.loads(summary_str)

    assert summary["operations"]["read"]["total_ops"] == 100
    assert summary["operations"]["write"]["total_ops"] == 50
    # summary.json should have been written
    assert (test_dir / SUMMARY_JSON_FILE_NAME).exists()


def test_prepare_and_write_summary_falls_back_to_stdout_when_stderr_unparseable(tmp_path):
    """_prepare_and_write_summary should fall back to stdout.jsonl when stderr parse fails."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()

    test_dir = tmp_path / "test-1"
    results_dir = test_dir / TEST_RESULTS_DIR_NAME
    results_dir.mkdir(parents=True)

    metadata = BenchmarkMetadata(
        test_id="test-1",
        test_name="done",
        started_at=datetime.now(UTC),
        test_config={},
        is_active=False,
    )
    (test_dir / METADATA_JSON_FILE_NAME).write_text(json.dumps(metadata.to_dict()))
    (results_dir / "stderr.log").write_text("no useful content here")
    (results_dir / "stdout.jsonl").write_text(_make_stdout_jsonl())

    charm.workload.file_exists.side_effect = lambda file_path: Path(file_path).exists()

    summary_str = etcd_benchmark_manager._prepare_and_write_summary(str(test_dir))
    summary = json.loads(summary_str)

    assert "read" in summary["operations"]
    assert "write" in summary["operations"]


def test_prepare_and_write_summary_fails_when_stderr_missing_for_completed_test(tmp_path):
    """_prepare_and_write_summary should raise when stderr is absent for a completed test."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()

    test_dir = tmp_path / "test-1"
    results_dir = test_dir / TEST_RESULTS_DIR_NAME
    results_dir.mkdir(parents=True)

    metadata = BenchmarkMetadata(
        test_id="test-1",
        test_name="done",
        started_at=datetime.now(UTC),
        test_config={},
        is_active=False,
    )
    (test_dir / METADATA_JSON_FILE_NAME).write_text(json.dumps(metadata.to_dict()))
    # no stderr.log created

    charm.workload.file_exists.side_effect = lambda file_path: Path(file_path).exists()

    with pytest.raises(FileNotFoundError) as e:
        etcd_benchmark_manager._prepare_and_write_summary(str(test_dir))

    assert "Missing stderr file" in str(e.value)


def test_prepare_and_write_summary_for_active_test_from_stdout(tmp_path):
    """_prepare_and_write_summary should build summary from stdout for active tests."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()

    test_dir = tmp_path / "test-active"
    results_dir = test_dir / TEST_RESULTS_DIR_NAME
    results_dir.mkdir(parents=True)

    metadata = BenchmarkMetadata(
        test_id="test-active",
        test_name="running",
        started_at=datetime.now(UTC),
        test_config={},
        is_active=True,
    )
    (test_dir / METADATA_JSON_FILE_NAME).write_text(json.dumps(metadata.to_dict()))
    (results_dir / "stdout.jsonl").write_text(_make_stdout_jsonl())

    charm.workload.file_exists.side_effect = lambda file_path: Path(file_path).exists()

    summary_str = etcd_benchmark_manager._prepare_and_write_summary(str(test_dir))
    summary = json.loads(summary_str)

    assert "read" in summary["operations"]
    # summary.json should NOT have been written for active tests
    assert not (test_dir / SUMMARY_JSON_FILE_NAME).exists()


def test_prepare_and_write_summary_fails_when_stdout_missing_for_active_test(tmp_path):
    """_prepare_and_write_summary should raise when stdout is absent for an active test."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()

    test_dir = tmp_path / "test-active"
    results_dir = test_dir / TEST_RESULTS_DIR_NAME
    results_dir.mkdir(parents=True)

    metadata = BenchmarkMetadata(
        test_id="test-active",
        test_name="running",
        started_at=datetime.now(UTC),
        test_config={},
        is_active=True,
    )
    (test_dir / METADATA_JSON_FILE_NAME).write_text(json.dumps(metadata.to_dict()))
    # no stdout.jsonl created

    charm.workload.file_exists.side_effect = lambda file_path: Path(file_path).exists()

    with pytest.raises(FileNotFoundError) as e:
        etcd_benchmark_manager._prepare_and_write_summary(str(test_dir))

    assert "Missing stdout file" in str(e.value)


def test_prepare_and_write_summary_fails_when_fallback_stdout_missing_for_completed_test(tmp_path):
    """_prepare_and_write_summary should raise when stderr parse fails and stdout is absent."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()

    test_dir = tmp_path / "test-1"
    results_dir = test_dir / TEST_RESULTS_DIR_NAME
    results_dir.mkdir(parents=True)

    metadata = BenchmarkMetadata(
        test_id="test-1",
        test_name="done",
        started_at=datetime.now(UTC),
        test_config={},
        is_active=False,
    )
    (test_dir / METADATA_JSON_FILE_NAME).write_text(json.dumps(metadata.to_dict()))
    (results_dir / "stderr.log").write_text("no useful content here")
    # no stdout.jsonl created

    charm.workload.file_exists.side_effect = lambda file_path: Path(file_path).exists()

    with pytest.raises(FileNotFoundError) as e:
        etcd_benchmark_manager._prepare_and_write_summary(str(test_dir))

    assert "Missing stdout file" in str(e.value)


# ---------------------------------------------------------------------------
# _parse_final_operations_from_stderr – missing blocks
# ---------------------------------------------------------------------------


def test_parse_final_operations_from_stderr_raises_when_write_block_missing(tmp_path):
    """_parse_final_operations_from_stderr should raise when write block is absent."""
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
            ]
        )
    )

    with pytest.raises(ValueError) as e:
        etcd_benchmark_manager._parse_final_operations_from_stderr(stderr_path)

    assert "Could not find complete final read/write summary blocks" in str(e.value)


# ---------------------------------------------------------------------------
# _extract_float_metric – pattern not matched
# ---------------------------------------------------------------------------


def test_extract_float_metric_raises_when_pattern_not_found():
    """_extract_float_metric should raise ValueError when the pattern is absent."""
    etcd_benchmark_manager, _ = _make_etcd_benchmark_manager()

    with pytest.raises(ValueError) as e:
        etcd_benchmark_manager._extract_float_metric("no numbers here", r"Missing:\s*(\d+)")

    assert "Unable to extract metric" in str(e.value)


# ---------------------------------------------------------------------------
# _build_operations_from_aggregates – zero total_ops and zero stddev_weight paths
# ---------------------------------------------------------------------------


def test_build_operations_from_aggregates_handles_zero_total_ops():
    """_build_operations_from_aggregates should set avg_latency to 0 when total_ops == 0."""
    etcd_benchmark_manager, _ = _make_etcd_benchmark_manager()

    aggregates = {
        "read": {
            "samples": 1,
            "total_ops": 0,
            "throughput_sum": 0.0,
            "p50_sum": 0.0,
            "p90_sum": 0.0,
            "p99_sum": 0.0,
            "total_time_sum": 0.0,
            "stddev_accumulator": 0.0,
            "stddev_weight": 0,
            "min_throughput": 0.0,
            "max_throughput": 0.0,
        }
    }

    operations = etcd_benchmark_manager._build_operations_from_aggregates(aggregates)
    assert operations["read"]["avg_latency_sec"] == 0.0
    assert operations["read"]["avg_stddev_latency_sec"] == 0.0


# ---------------------------------------------------------------------------
# _parse_jsonl_payload – invalid JSON and non-dict payload
# ---------------------------------------------------------------------------


def test_parse_jsonl_payload_raises_on_invalid_json(tmp_path):
    """_parse_jsonl_payload should raise ValueError for malformed JSON."""
    etcd_benchmark_manager, _ = _make_etcd_benchmark_manager()
    stdout_path = tmp_path / "stdout.jsonl"

    with pytest.raises(ValueError) as e:
        etcd_benchmark_manager._parse_jsonl_payload("{bad json", stdout_path, 1)

    assert "Invalid JSON" in str(e.value)


def test_parse_jsonl_payload_raises_when_payload_is_not_dict(tmp_path):
    """_parse_jsonl_payload should raise ValueError when JSON is not an object."""
    etcd_benchmark_manager, _ = _make_etcd_benchmark_manager()
    stdout_path = tmp_path / "stdout.jsonl"

    with pytest.raises(ValueError) as e:
        etcd_benchmark_manager._parse_jsonl_payload("[1, 2, 3]", stdout_path, 1)

    assert "Invalid JSON object" in str(e.value)


# ---------------------------------------------------------------------------
# _extract_op_metrics – not-a-dict op block and missing keys
# ---------------------------------------------------------------------------


def test_extract_op_metrics_returns_none_when_op_absent(tmp_path):
    """_extract_op_metrics should return None when the op key is not present."""
    etcd_benchmark_manager, _ = _make_etcd_benchmark_manager()
    stdout_path = tmp_path / "stdout.jsonl"

    result = etcd_benchmark_manager._extract_op_metrics({}, "read", stdout_path, 1)
    assert result is None


def test_extract_op_metrics_raises_when_op_block_is_not_dict(tmp_path):
    """_extract_op_metrics should raise ValueError when op block is not a dict."""
    etcd_benchmark_manager, _ = _make_etcd_benchmark_manager()
    stdout_path = tmp_path / "stdout.jsonl"

    with pytest.raises(ValueError) as e:
        etcd_benchmark_manager._extract_op_metrics({"read": "bad"}, "read", stdout_path, 1)

    assert "Invalid 'read' metrics" in str(e.value)


def test_extract_op_metrics_raises_when_key_missing(tmp_path):
    """_extract_op_metrics should raise ValueError when a required key is missing."""
    etcd_benchmark_manager, _ = _make_etcd_benchmark_manager()
    stdout_path = tmp_path / "stdout.jsonl"

    incomplete = {"ops": 10, "rps": 100.0}  # missing p50, p90, p99, avg, stddev

    with pytest.raises(ValueError) as e:
        etcd_benchmark_manager._extract_op_metrics({"read": incomplete}, "read", stdout_path, 1)

    assert "Malformed 'read' metric" in str(e.value)


# ---------------------------------------------------------------------------
# _aggregate_jsonl_results – multi-row aggregation and stddev weight path
# ---------------------------------------------------------------------------


def test_aggregate_jsonl_results_aggregates_multiple_rows(tmp_path):
    """_aggregate_jsonl_results should correctly aggregate stats across multiple rows."""
    etcd_benchmark_manager, _ = _make_etcd_benchmark_manager()

    row = {
        "read": {"ops": 10, "rps": 100.0, "p50": 0.005, "p90": 0.020, "p99": 0.030, "avg": 0.010, "stddev": 0.001},
        "write": {"ops": 5, "rps": 50.0, "p50": 0.010, "p90": 0.030, "p99": 0.040, "avg": 0.020, "stddev": 0.002},
    }
    stdout_path = tmp_path / "stdout.jsonl"
    stdout_path.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n")

    aggregates = etcd_benchmark_manager._aggregate_jsonl_results(stdout_path)

    assert aggregates["read"]["samples"] == 2
    assert aggregates["read"]["total_ops"] == 20
    assert aggregates["write"]["total_ops"] == 10
    # stddev_weight should be (ops-1) * number_of_rows = 9 * 2 = 18
    assert aggregates["read"]["stddev_weight"] == 18

