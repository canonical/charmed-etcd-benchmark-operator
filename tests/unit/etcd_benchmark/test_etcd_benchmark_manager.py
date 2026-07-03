#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for etcd benchmark related managers."""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from common.exceptions import (
    BenchmarkConfigurationError,
    BenchmarkResultsParseError,
    BenchmarkStateError,
)
from core.models import BenchmarkMetadata
from literals import (
    SUMMARY_JSON_FILE_NAME,
    TEST_RESULTS_DIR_NAME,
)
from managers.etcd_benchmark import EtcdBenchmarkManager


def _make_etcd_benchmark_manager():
    """Create an EtcdBenchmarkManager with a mocked charm."""
    charm = MagicMock()
    charm.workload = MagicMock()
    charm.etcd_interface_state = MagicMock()
    charm.cluster_state = MagicMock()
    charm.cluster_state.get_all_test_metadata.return_value = {}
    charm.cluster_state.get_test_metadata.return_value = None
    charm.config = {}
    return EtcdBenchmarkManager(charm), charm


def test_setup_test_returns_enriched_config():
    """setup_test should enrich runner config with runtime details."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()

    charm.etcd_interface_state.uris = "https://10.0.0.1:2379"
    charm.config = {
        "test-name": "smoke-test",
        "clients": 1,
        "report-interval": 10,
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
    charm.cluster_state.cluster.update.assert_called_once()
    cluster_update = charm.cluster_state.cluster.update.call_args[0][0]
    assert cluster_update["current_test_id"] == "test-123"
    assert cluster_update["current_test_name"] == "smoke-test"
    assert cluster_update["current_test_config"]["clients"] == 1
    assert cluster_update["current_test_started_at"]

    assert config["current_test_id"] == "test-123"
    assert config["current_test_name"] == "smoke-test"
    assert config["results_dir"] == "/tmp/results"
    assert config["endpoints"] == "https://10.0.0.1:2379"


def test_setup_test_raises_on_invalid_report_interval():
    """setup_test should raise when report_interval is set below 1."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()

    charm.etcd_interface_state.uris = "https://10.0.0.1:2379"
    charm.config = {"test-name": "bad-config", "report-interval": 0}

    with pytest.raises(BenchmarkConfigurationError) as e:
        etcd_benchmark_manager.setup_test()

    assert "report-interval" in e.value.detailed_description


def test_list_tests_returns_empty_when_tests_dir_missing(tmp_path):
    """list_tests should return an empty list when tests root is absent."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()

    with patch(
        "managers.etcd_benchmark.BENCHMARK_TESTS_ROOT_DIR", str(tmp_path / "does-not-exist")
    ):
        assert etcd_benchmark_manager.list_tests() == []


def test_list_tests_returns_status_from_metadata(tmp_path):
    """list_tests should classify tests as in progress or completed from metadata."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()

    # Create test directories
    tests_dir = tmp_path / "tests"
    (tests_dir / "test-2").mkdir(parents=True)
    (tests_dir / "test-1").mkdir(parents=True)

    # Set up mock to indicate test-2 is the current active test
    charm.cluster_state.cluster.current_test_id = "test-2"

    with patch("managers.etcd_benchmark.BENCHMARK_TESTS_ROOT_DIR", str(tests_dir)):
        results = etcd_benchmark_manager.list_tests()

    # Should have both tests, with test-2 marked as in progress
    assert ("test-2", "in progress") in results
    assert ("test-1", "completed") in results


def test_get_test_summary_returns_cached_summary(tmp_path):
    """get_test_summary should return formatted cached summary if available."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()

    test_dir = tmp_path / "test-1"
    test_dir.mkdir(parents=True)
    summary_path = test_dir / SUMMARY_JSON_FILE_NAME
    summary_data = {"metadata": {"test_id": "test-1"}, "operations": {"read": {"total_ops": 1}}}
    summary_path.write_text(json.dumps(summary_data))

    charm.workload.file_exists.side_effect = lambda file_path: Path(file_path).exists()

    with patch("managers.etcd_benchmark.BENCHMARK_TESTS_ROOT_DIR", str(tmp_path)):
        assert etcd_benchmark_manager.get_test_summary("test-1") == json.dumps(
            summary_data, indent=2
        )


def test_get_test_summary_falls_back_when_cached_summary_is_malformed(tmp_path):
    """get_test_summary should rebuild summary when cached summary is malformed."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()

    test_dir = tmp_path / "test-1"
    test_dir.mkdir(parents=True)
    (test_dir / SUMMARY_JSON_FILE_NAME).write_text("{not-json")

    charm.workload.file_exists.side_effect = lambda file_path: Path(file_path).exists()

    with (
        patch("managers.etcd_benchmark.BENCHMARK_TESTS_ROOT_DIR", str(tmp_path)),
        patch.object(
            etcd_benchmark_manager,
            "_prepare_and_write_summary",
            return_value="rebuilt-summary",
        ) as prepare_summary,
    ):
        summary = etcd_benchmark_manager.get_test_summary("test-1")

    prepare_summary.assert_called_once_with(str(test_dir))
    assert summary == "rebuilt-summary"


def test_get_test_summary_wraps_errors_from_prepare_summary(tmp_path):
    """get_test_summary should wrap OSError/ValueError/KeyError into BenchmarkResultsParseError."""
    from common.exceptions import BenchmarkResultsParseError

    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()
    test_dir = tmp_path / "test-wrap"
    test_dir.mkdir(parents=True)

    charm.workload.file_exists.side_effect = lambda file_path: Path(file_path).exists()

    with (
        patch("managers.etcd_benchmark.BENCHMARK_TESTS_ROOT_DIR", str(tmp_path)),
        patch.object(
            etcd_benchmark_manager,
            "_prepare_and_write_summary",
            side_effect=OSError("disk io failed"),
        ),
        pytest.raises(BenchmarkResultsParseError) as e,
    ):
        etcd_benchmark_manager.get_test_summary("test-wrap")

    assert e.value.message == "Error preparing/writing summary"
    assert "disk io failed" in e.value.detailed_description


def test_write_metadata_to_summary_file_is_noop_when_metadata_exists(tmp_path):
    """write_metadata_to_summary_file should not overwrite existing metadata."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()

    test_dir = tmp_path / "test-1"
    test_dir.mkdir(parents=True)
    summary_path = test_dir / SUMMARY_JSON_FILE_NAME
    summary_path.write_text(
        json.dumps(
            {
                "metadata": {"test_id": "existing-test", "test_name": "existing"},
                "operations": {"read": {"total_ops": 1}},
            }
        )
    )

    metadata = BenchmarkMetadata(
        test_id="test-1",
        test_name="new",
        started_at=datetime.now(UTC),
        test_config={},
    )

    with (
        patch("managers.etcd_benchmark.BENCHMARK_TESTS_ROOT_DIR", str(tmp_path)),
        patch.object(
            etcd_benchmark_manager,
            "_read_test_metadata_from_peer_relation_databag",
            return_value=metadata,
        ),
    ):
        etcd_benchmark_manager.write_metadata_to_summary_file()

    saved_summary = json.loads(summary_path.read_text())
    assert saved_summary["metadata"]["test_id"] == "existing-test"
    assert saved_summary["operations"]["read"]["total_ops"] == 1


def test_write_metadata_to_summary_file_writes_when_metadata_missing(tmp_path):
    """write_metadata_to_summary_file should inject metadata when key is missing."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()

    test_dir = tmp_path / "test-2"
    test_dir.mkdir(parents=True)
    summary_path = test_dir / SUMMARY_JSON_FILE_NAME
    summary_path.write_text(json.dumps({"operations": {"write": {"total_ops": 2}}}))

    metadata = BenchmarkMetadata(
        test_id="test-2",
        test_name="new-meta",
        started_at=datetime.now(UTC),
        test_config={"clients": 2},
    )

    with (
        patch("managers.etcd_benchmark.BENCHMARK_TESTS_ROOT_DIR", str(tmp_path)),
        patch.object(
            etcd_benchmark_manager,
            "_read_test_metadata_from_peer_relation_databag",
            return_value=metadata,
        ),
    ):
        etcd_benchmark_manager.write_metadata_to_summary_file()

    saved_summary = json.loads(summary_path.read_text())
    assert saved_summary["metadata"]["test_id"] == "test-2"
    assert saved_summary["operations"]["write"]["total_ops"] == 2


def test_create_initial_test_artifacts_writes_metadata_and_result_files(tmp_path):
    """_create_initial_test_artifacts should write both result output files."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()

    with patch("managers.etcd_benchmark.BENCHMARK_TESTS_ROOT_DIR", str(tmp_path)):
        results_dir = etcd_benchmark_manager._create_initial_test_artifacts("test-artifacts")

    expected_test_dir = tmp_path / "test-artifacts"
    assert results_dir == str(expected_test_dir / TEST_RESULTS_DIR_NAME)
    assert charm.workload.write_file.call_count == 2
    charm.workload.write_file.assert_any_call(
        file=str(expected_test_dir / TEST_RESULTS_DIR_NAME / "stdout.jsonl"),
    )
    charm.workload.write_file.assert_any_call(
        file=str(expected_test_dir / TEST_RESULTS_DIR_NAME / "stderr.log"),
    )


def test_prepare_and_write_summary_fails_when_summary_file_missing_for_completed_test(tmp_path):
    """_prepare_and_write_summary should fail when summary.json is missing for completed test."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()

    test_dir = tmp_path / "test-1"
    (test_dir / TEST_RESULTS_DIR_NAME).mkdir(parents=True)

    charm.workload.file_exists.side_effect = lambda file_path: Path(file_path).exists()
    charm.cluster_state.cluster.is_test_active = False

    with pytest.raises(FileNotFoundError) as e:
        etcd_benchmark_manager._prepare_and_write_summary(str(test_dir))

    assert "Missing summary file" in str(e.value)


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
    charm.config = {
        "test-name": "tls-test",
        "clients": 1,
        "report-interval": 5,
    }

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


def test_retrieve_config_maps_all_expected_keys():
    """_retrieve_config should map charm options to benchmark runner keys."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()

    charm.config = {
        "clients": 10,
        "connections": 20,
        "rate": 30,
        "key-size": 40,
        "key-space-size": 50,
        "value-size": 60,
        "limit": 70,
        "rw-ratio": 2.5,
        "duration": 80,
        "total-transactions": 90,
        "report-interval": 15,
        "test-name": "ignored",
    }

    assert etcd_benchmark_manager._retrieve_config() == {
        "clients": 10,
        "connections": 20,
        "rate": 30,
        "key_size": 40,
        "key_space_size": 50,
        "value_size": 60,
        "limit": 70,
        "rw_ratio": 2.5,
        "duration": 80,
        "total_transactions": 90,
        "report_interval": 15,
    }


def test_retrieve_config_returns_none_for_missing_options():
    """_retrieve_config should default missing options to None."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()
    charm.config = {"clients": 3, "rw-ratio": 1.0}

    assert etcd_benchmark_manager._retrieve_config() == {
        "clients": 3,
        "connections": None,
        "rate": None,
        "key_size": None,
        "key_space_size": None,
        "value_size": None,
        "limit": None,
        "rw_ratio": 1.0,
        "duration": None,
        "total_transactions": None,
        "report_interval": None,
    }


def test_list_tests_returns_empty_when_no_test_dirs_exist(tmp_path):
    """list_tests should return empty list when no test dirs exist."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(parents=True)

    with patch("managers.etcd_benchmark.BENCHMARK_TESTS_ROOT_DIR", str(tests_dir)):
        results = etcd_benchmark_manager.list_tests()
    assert results == []


# ---------------------------------------------------------------------------
# get_test_summary – delegates to _prepare_and_write_summary when no cache
# ---------------------------------------------------------------------------


def test_get_test_summary_calls_prepare_when_summary_file_absent(tmp_path):
    """get_test_summary should call _prepare_and_write_summary when summary.json is missing."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()

    test_dir = tmp_path / "test-1"
    test_dir.mkdir(parents=True)

    charm.workload.file_exists.side_effect = lambda file_path: Path(file_path).exists()

    with (
        patch("managers.etcd_benchmark.BENCHMARK_TESTS_ROOT_DIR", str(tmp_path)),
        patch.object(
            etcd_benchmark_manager,
            "_prepare_and_write_summary",
            return_value="fresh-summary",
        ) as prepare_summary,
    ):
        result = etcd_benchmark_manager.get_test_summary("test-1")

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
            "read": {
                "ops": 100,
                "rps": 1000.0,
                "p50": 0.005,
                "p90": 0.020,
                "p99": 0.030,
                "avg": 0.010,
                "stddev": 0.001,
            },
            "write": {
                "ops": 50,
                "rps": 500.0,
                "p50": 0.010,
                "p90": 0.030,
                "p99": 0.040,
                "avg": 0.020,
                "stddev": 0.002,
            },
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
    )
    (test_dir / SUMMARY_JSON_FILE_NAME).write_text(
        json.dumps({"metadata": metadata.to_dict(), "operations": {}})
    )

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
    )
    (test_dir / SUMMARY_JSON_FILE_NAME).write_text(
        json.dumps({"metadata": metadata.to_dict(), "operations": {}})
    )
    (results_dir / "stderr.log").write_text(_make_stderr_content())
    (results_dir / "stdout.jsonl").write_text(_make_stdout_jsonl())

    charm.workload.file_exists.side_effect = lambda file_path: Path(file_path).exists()
    charm.cluster_state.cluster.is_test_active = False

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
    )
    (test_dir / SUMMARY_JSON_FILE_NAME).write_text(
        json.dumps({"metadata": metadata.to_dict(), "operations": {}})
    )
    (results_dir / "stderr.log").write_text("no useful content here")
    (results_dir / "stdout.jsonl").write_text(_make_stdout_jsonl())

    charm.workload.file_exists.side_effect = lambda file_path: Path(file_path).exists()
    charm.cluster_state.cluster.is_test_active = False

    summary_str = etcd_benchmark_manager._prepare_and_write_summary(str(test_dir))
    summary = json.loads(summary_str)

    assert "read" in summary["operations"]
    assert "write" in summary["operations"]


def test_prepare_and_write_summary_fails_when_both_stderr_and_stdout_missing_for_completed_test(
    tmp_path,
):
    """_prepare_and_write_summary should raise when both stderr and stdout are unusable."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()

    test_dir = tmp_path / "test-1"
    results_dir = test_dir / TEST_RESULTS_DIR_NAME
    results_dir.mkdir(parents=True)

    metadata = BenchmarkMetadata(
        test_id="test-1",
        test_name="done",
        started_at=datetime.now(UTC),
        test_config={},
    )
    (test_dir / SUMMARY_JSON_FILE_NAME).write_text(
        json.dumps({"metadata": metadata.to_dict(), "operations": {}})
    )
    # Create unparsable stderr so it falls back to stdout, which is missing
    (results_dir / "stderr.log").write_text("unparsable")
    # no stdout.jsonl created

    charm.workload.file_exists.side_effect = lambda file_path: Path(file_path).exists()
    charm.cluster_state.cluster.is_test_active = False

    with pytest.raises(FileNotFoundError) as e:
        etcd_benchmark_manager._prepare_and_write_summary(str(test_dir))

    assert "Missing stdout file" in str(e.value)


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
    )
    (results_dir / "stdout.jsonl").write_text(_make_stdout_jsonl())

    charm.workload.file_exists.side_effect = lambda file_path: Path(file_path).exists()
    charm.cluster_state.cluster.is_test_active = True

    with patch.object(
        etcd_benchmark_manager,
        "_read_test_metadata_from_peer_relation_databag",
        return_value=metadata,
    ):
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
    )
    # no stdout.jsonl created

    charm.workload.file_exists.side_effect = lambda file_path: Path(file_path).exists()
    charm.cluster_state.cluster.is_test_active = True

    with (
        patch.object(
            etcd_benchmark_manager,
            "_read_test_metadata_from_peer_relation_databag",
            return_value=metadata,
        ),
        pytest.raises(FileNotFoundError) as e,
    ):
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
    )
    (test_dir / SUMMARY_JSON_FILE_NAME).write_text(
        json.dumps({"metadata": metadata.to_dict(), "operations": {}})
    )
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
        "read": {
            "ops": 10,
            "rps": 100.0,
            "p50": 0.005,
            "p90": 0.020,
            "p99": 0.030,
            "avg": 0.010,
            "stddev": 0.001,
        },
        "write": {
            "ops": 5,
            "rps": 50.0,
            "p50": 0.010,
            "p90": 0.030,
            "p99": 0.040,
            "avg": 0.020,
            "stddev": 0.002,
        },
    }
    stdout_path = tmp_path / "stdout.jsonl"
    stdout_path.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n")

    aggregates = etcd_benchmark_manager._aggregate_jsonl_results(stdout_path)

    assert aggregates["read"]["samples"] == 2
    assert aggregates["read"]["total_ops"] == 20
    assert aggregates["write"]["total_ops"] == 10
    # stddev_weight should be (ops-1) * number_of_rows = 9 * 2 = 18
    assert aggregates["read"]["stddev_weight"] == 18


def test_aggregate_jsonl_results_skips_missing_op_metrics_and_still_aggregates(tmp_path):
    """_aggregate_jsonl_results should skip missing op blocks and keep valid ones."""
    etcd_benchmark_manager, _ = _make_etcd_benchmark_manager()

    row = {
        "read": {
            "ops": 12,
            "rps": 120.0,
            "p50": 0.005,
            "p90": 0.020,
            "p99": 0.030,
            "avg": 0.010,
            "stddev": 0.001,
        }
    }
    stdout_path = tmp_path / "stdout.jsonl"
    stdout_path.write_text(json.dumps(row) + "\n")

    aggregates = etcd_benchmark_manager._aggregate_jsonl_results(stdout_path)

    assert "read" in aggregates
    assert "write" not in aggregates
    assert aggregates["read"]["samples"] == 1
    assert aggregates["read"]["total_ops"] == 12


def test_aggregate_jsonl_results_keeps_zero_stddev_weight_when_ops_is_one(tmp_path):
    """_aggregate_jsonl_results should not accumulate stddev weight for single-op samples."""
    etcd_benchmark_manager, _ = _make_etcd_benchmark_manager()

    row = {
        "read": {
            "ops": 1,
            "rps": 10.0,
            "p50": 0.005,
            "p90": 0.010,
            "p99": 0.020,
            "avg": 0.005,
            "stddev": 0.123,
        }
    }
    stdout_path = tmp_path / "stdout.jsonl"
    stdout_path.write_text(json.dumps(row) + "\n")

    aggregates = etcd_benchmark_manager._aggregate_jsonl_results(stdout_path)

    assert aggregates["read"]["stddev_weight"] == 0
    assert aggregates["read"]["stddev_accumulator"] == 0.0
    assert aggregates["read"]["min_throughput"] == 10.0
    assert aggregates["read"]["max_throughput"] == 10.0


# ---------------------------------------------------------------------------
# write_metadata_to_summary_file – unreadable/malformed summary branches
# ---------------------------------------------------------------------------


def test_write_metadata_to_summary_file_creates_when_summary_absent(tmp_path):
    """write_metadata_to_summary_file should create summary.json when none exists."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()

    test_dir = tmp_path / "test-3"
    test_dir.mkdir(parents=True)
    summary_path = test_dir / SUMMARY_JSON_FILE_NAME

    metadata = BenchmarkMetadata(
        test_id="test-3",
        test_name="new",
        started_at=datetime.now(UTC),
        test_config={"clients": 3},
    )

    with (
        patch("managers.etcd_benchmark.BENCHMARK_TESTS_ROOT_DIR", str(tmp_path)),
        patch.object(
            etcd_benchmark_manager,
            "_read_test_metadata_from_peer_relation_databag",
            return_value=metadata,
        ),
    ):
        etcd_benchmark_manager.write_metadata_to_summary_file()

    saved = json.loads(summary_path.read_text())
    assert saved["metadata"]["test_id"] == "test-3"
    assert saved["operations"] == {}


def test_write_metadata_to_summary_file_recreates_when_summary_is_malformed(tmp_path):
    """write_metadata_to_summary_file should recreate summary.json when it is unreadable JSON."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()

    test_dir = tmp_path / "test-1"
    test_dir.mkdir(parents=True)
    summary_path = test_dir / SUMMARY_JSON_FILE_NAME
    summary_path.write_text("{not-json")

    metadata = BenchmarkMetadata(
        test_id="test-1",
        test_name="new",
        started_at=datetime.now(UTC),
        test_config={"clients": 1},
    )

    with (
        patch("managers.etcd_benchmark.BENCHMARK_TESTS_ROOT_DIR", str(tmp_path)),
        patch.object(
            etcd_benchmark_manager,
            "_read_test_metadata_from_peer_relation_databag",
            return_value=metadata,
        ),
    ):
        etcd_benchmark_manager.write_metadata_to_summary_file()

    saved = json.loads(summary_path.read_text())
    assert saved["metadata"]["test_id"] == "test-1"
    assert saved["operations"] == {}


def test_write_metadata_to_summary_file_recreates_when_summary_is_non_dict(tmp_path):
    """write_metadata_to_summary_file should recreate when existing summary is a JSON list."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()

    test_dir = tmp_path / "test-2"
    test_dir.mkdir(parents=True)
    summary_path = test_dir / SUMMARY_JSON_FILE_NAME
    summary_path.write_text(json.dumps(["not", "an", "object"]))

    metadata = BenchmarkMetadata(
        test_id="test-2",
        test_name="new",
        started_at=datetime.now(UTC),
        test_config={},
    )

    with (
        patch("managers.etcd_benchmark.BENCHMARK_TESTS_ROOT_DIR", str(tmp_path)),
        patch.object(
            etcd_benchmark_manager,
            "_read_test_metadata_from_peer_relation_databag",
            return_value=metadata,
        ),
    ):
        etcd_benchmark_manager.write_metadata_to_summary_file()

    saved = json.loads(summary_path.read_text())
    assert saved["metadata"]["test_id"] == "test-2"


def test_write_metadata_to_summary_file_raises_state_error_when_metadata_unavailable(tmp_path):
    """write_metadata_to_summary_file should wrap ValueError into BenchmarkStateError."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()

    with (
        patch("managers.etcd_benchmark.BENCHMARK_TESTS_ROOT_DIR", str(tmp_path)),
        patch.object(
            etcd_benchmark_manager,
            "_read_test_metadata_from_peer_relation_databag",
            side_effect=ValueError("Benchmark metadata unavailable/incomplete"),
        ),
    ):
        with pytest.raises(BenchmarkStateError) as e:
            etcd_benchmark_manager.write_metadata_to_summary_file()

    assert e.value.message == "Failed to write metadata to summary.json"
    assert "Benchmark metadata unavailable/incomplete" in e.value.detailed_description


# ---------------------------------------------------------------------------
# get_test_summary – directory missing and cached-without-operations branches
# ---------------------------------------------------------------------------


def test_get_test_summary_raises_file_not_found_when_test_dir_missing(tmp_path):
    """get_test_summary should raise FileNotFoundError when the test directory is absent."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()

    charm.workload.file_exists.return_value = False

    with patch("managers.etcd_benchmark.BENCHMARK_TESTS_ROOT_DIR", str(tmp_path)):
        with pytest.raises(FileNotFoundError) as e:
            etcd_benchmark_manager.get_test_summary("missing-test")

    assert "Test results directory not found for test ID: missing-test" in str(e.value)


def test_get_test_summary_rebuilds_when_cached_summary_has_no_operations(tmp_path):
    """get_test_summary should rebuild when cached summary lacks operations data."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()

    test_dir = tmp_path / "test-1"
    test_dir.mkdir(parents=True)
    summary_path = test_dir / SUMMARY_JSON_FILE_NAME
    # Valid JSON object, but no operations key -> falls through to rebuild
    summary_path.write_text(json.dumps({"metadata": {"test_id": "test-1"}}))

    charm.workload.file_exists.side_effect = lambda file_path: Path(file_path).exists()

    with (
        patch("managers.etcd_benchmark.BENCHMARK_TESTS_ROOT_DIR", str(tmp_path)),
        patch.object(
            etcd_benchmark_manager,
            "_prepare_and_write_summary",
            return_value="rebuilt-summary",
        ) as prepare_summary,
    ):
        result = etcd_benchmark_manager.get_test_summary("test-1")

    prepare_summary.assert_called_once_with(str(test_dir))
    assert result == "rebuilt-summary"


def test_get_test_summary_rebuilds_when_cached_summary_is_not_dict(tmp_path):
    """get_test_summary should rebuild when cached summary is a JSON non-object."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()

    test_dir = tmp_path / "test-1"
    test_dir.mkdir(parents=True)
    summary_path = test_dir / SUMMARY_JSON_FILE_NAME
    summary_path.write_text(json.dumps(["not", "an", "object"]))

    charm.workload.file_exists.side_effect = lambda file_path: Path(file_path).exists()

    with (
        patch("managers.etcd_benchmark.BENCHMARK_TESTS_ROOT_DIR", str(tmp_path)),
        patch.object(
            etcd_benchmark_manager,
            "_prepare_and_write_summary",
            return_value="rebuilt-summary",
        ) as prepare_summary,
    ):
        result = etcd_benchmark_manager.get_test_summary("test-1")

    prepare_summary.assert_called_once_with(str(test_dir))
    assert result == "rebuilt-summary"


# ---------------------------------------------------------------------------
# mark_current_test_completed
# ---------------------------------------------------------------------------


def test_mark_current_test_completed_clears_peer_metadata():
    """mark_current_test_completed should delegate to cluster.clear_current_test_metadata."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()

    etcd_benchmark_manager.mark_current_test_completed()

    charm.cluster_state.cluster.clear_current_test_metadata.assert_called_once_with()


# ---------------------------------------------------------------------------
# _read_test_metadata_from_peer_relation_databag – error branches
# ---------------------------------------------------------------------------


def test_read_metadata_from_peer_relation_raises_when_relation_missing():
    """_read_test_metadata_from_peer_relation_databag should raise when no peer relation."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()
    charm.cluster_state.cluster.relation = None

    with pytest.raises(ValueError) as e:
        etcd_benchmark_manager._read_test_metadata_from_peer_relation_databag()

    assert "Peer relation is not available" in str(e.value)


def test_read_metadata_from_peer_relation_raises_when_metadata_incomplete():
    """_read_test_metadata_from_peer_relation_databag should raise when metadata is incomplete."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()
    cluster = charm.cluster_state.cluster
    cluster.relation = object()
    # All current_test_* fields are MagicMock by default; force them falsy.
    cluster.current_test_id = None
    cluster.current_test_name = "some-name"
    cluster.current_test_started_at = datetime.now(UTC)
    cluster.current_test_config = {"a": 1}

    with pytest.raises(ValueError) as e:
        etcd_benchmark_manager._read_test_metadata_from_peer_relation_databag()

    assert "Benchmark metadata unavailable/incomplete" in str(e.value)


# ---------------------------------------------------------------------------
# _read_test_metadata_from_summary_file – error branches
# ---------------------------------------------------------------------------


def test_read_metadata_from_summary_file_raises_when_summary_missing(tmp_path):
    """_read_test_metadata_from_summary_file should raise when summary.json is absent."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()
    test_dir = tmp_path / "test-1"
    test_dir.mkdir(parents=True)

    charm.workload.file_exists.side_effect = lambda file_path: Path(file_path).exists()

    with pytest.raises(FileNotFoundError) as e:
        etcd_benchmark_manager._read_test_metadata_from_summary_file(test_dir)

    assert "Missing summary file in" in str(e.value)


def test_read_metadata_from_summary_file_raises_when_summary_is_non_dict(tmp_path):
    """_read_test_metadata_from_summary_file should raise when summary is a JSON list."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()
    test_dir = tmp_path / "test-1"
    test_dir.mkdir(parents=True)
    (test_dir / SUMMARY_JSON_FILE_NAME).write_text(json.dumps(["not", "an", "object"]))

    charm.workload.file_exists.side_effect = lambda file_path: Path(file_path).exists()

    with pytest.raises(ValueError) as e:
        etcd_benchmark_manager._read_test_metadata_from_summary_file(test_dir)

    assert "expected JSON object" in str(e.value)


def test_read_metadata_from_summary_file_raises_when_metadata_missing(tmp_path):
    """_read_test_metadata_from_summary_file should raise when the metadata object is absent."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()
    test_dir = tmp_path / "test-1"
    test_dir.mkdir(parents=True)
    (test_dir / SUMMARY_JSON_FILE_NAME).write_text(
        json.dumps({"operations": {"read": {"total_ops": 1}}})
    )

    charm.workload.file_exists.side_effect = lambda file_path: Path(file_path).exists()

    with pytest.raises(ValueError) as e:
        etcd_benchmark_manager._read_test_metadata_from_summary_file(test_dir)

    assert "missing 'metadata' object" in str(e.value)


def test_read_metadata_from_summary_file_returns_metadata_when_valid(tmp_path):
    """_read_test_metadata_from_summary_file should return a BenchmarkMetadata when valid."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()
    test_dir = tmp_path / "test-1"
    test_dir.mkdir(parents=True)
    metadata = BenchmarkMetadata(
        test_id="test-1",
        test_name="done",
        started_at=datetime.now(UTC),
        test_config={"clients": 2},
    )
    (test_dir / SUMMARY_JSON_FILE_NAME).write_text(
        json.dumps({"metadata": metadata.to_dict(), "operations": {}})
    )

    charm.workload.file_exists.side_effect = lambda file_path: Path(file_path).exists()

    result = etcd_benchmark_manager._read_test_metadata_from_summary_file(test_dir)

    assert result.test_id == "test-1"
    assert result.test_config == {"clients": 2}


# ---------------------------------------------------------------------------
# _parse_final_operations_from_stderr – missing stderr file
# ---------------------------------------------------------------------------


def test_parse_final_operations_from_stderr_raises_when_stderr_missing(tmp_path):
    """_parse_final_operations_from_stderr should raise FileNotFoundError when stderr absent."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()
    stderr_path = tmp_path / "stderr.log"

    charm.workload.file_exists.return_value = False

    with pytest.raises(FileNotFoundError) as e:
        etcd_benchmark_manager._parse_final_operations_from_stderr(stderr_path)

    assert "Missing stderr file" in str(e.value)


# ---------------------------------------------------------------------------
# get_test_summary – KeyError is wrapped into BenchmarkResultsParseError
# ---------------------------------------------------------------------------


def test_get_test_summary_wraps_key_error_from_prepare_summary(tmp_path):
    """get_test_summary should wrap KeyError into BenchmarkResultsParseError."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()

    test_dir = tmp_path / "test-1"
    test_dir.mkdir(parents=True)

    charm.workload.file_exists.side_effect = lambda file_path: Path(file_path).exists()

    with (
        patch("managers.etcd_benchmark.BENCHMARK_TESTS_ROOT_DIR", str(tmp_path)),
        patch.object(
            etcd_benchmark_manager,
            "_prepare_and_write_summary",
            side_effect=KeyError("missing-key"),
        ),
        pytest.raises(BenchmarkResultsParseError) as e,
    ):
        etcd_benchmark_manager.get_test_summary("test-1")

    assert e.value.message == "Error preparing/writing summary"
    assert "missing-key" in e.value.detailed_description


# ---------------------------------------------------------------------------
# _prepare_and_write_summary – active test with missing summary persists skip
# ---------------------------------------------------------------------------


def test_prepare_and_write_summary_does_not_persist_when_test_active(tmp_path):
    """_prepare_and_write_summary should not write summary.json for active tests."""
    etcd_benchmark_manager, charm = _make_etcd_benchmark_manager()

    test_dir = tmp_path / "test-active"
    results_dir = test_dir / TEST_RESULTS_DIR_NAME
    results_dir.mkdir(parents=True)
    (results_dir / "stdout.jsonl").write_text(_make_stdout_jsonl())

    metadata = BenchmarkMetadata(
        test_id="test-active",
        test_name="running",
        started_at=datetime.now(UTC),
        test_config={},
    )

    charm.workload.file_exists.side_effect = lambda file_path: Path(file_path).exists()
    charm.cluster_state.cluster.is_test_active = True

    with patch.object(
        etcd_benchmark_manager,
        "_read_test_metadata_from_peer_relation_databag",
        return_value=metadata,
    ):
        etcd_benchmark_manager._prepare_and_write_summary(str(test_dir))

    assert not (test_dir / SUMMARY_JSON_FILE_NAME).exists()
