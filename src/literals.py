#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Collection of global literals for the etcd benchmark charm."""

SNAP_NAME = "charmed-etcd"
SNAP_CHANNEL = "3.6/edge"

TLS_ROOT_DIR = "/var/snap/charmed-etcd/current/tls"
CLIENT_CERT_PATH = f"{TLS_ROOT_DIR}/client.pem"
CLIENT_KEY_PATH = f"{TLS_ROOT_DIR}/client.key"
CA_CERT_PATH = f"{TLS_ROOT_DIR}/ca.pem"

BENCHMARK_ROOT_DIR = "/var/snap/charmed-etcd/current/benchmark"
BENCHMARK_TESTS_ROOT_DIR = f"{BENCHMARK_ROOT_DIR}/tests"
TEST_RESULTS_DIR_NAME = "results"
METADATA_JSON_FILE_NAME = "metadata.json"
SUMMARY_JSON_FILE_NAME = "summary.json"

RESULT_CSV_HEADERS = [
    "timestamp",
    "sample_number",
    "test_id",
    "test_name",
    "op_type",
    "total_ops",
    "average_latency_sec",
    "stddev_latency_sec",
    "throughput_rps",
    "p50_latency_sec",
    "p90_latency_sec",
    "p99_latency_sec",
]

BENCHMARK_SERVICE_NAME = "charmed-etcd-benchmark"
BENCHMARK_SERVICE_FILE_PATH = f"/etc/systemd/system/{BENCHMARK_SERVICE_NAME}.service"
BENCHMARK_TEMPLATE_FILE_NAME = "charmed-etcd-benchmark.service.j2"
BENCHMARK_RUNNER_FILE_NAME = "charmed_etcd_benchmark.py"
BENCHMARK_RUNNER_FILE_PATH = f"/usr/local/bin/{BENCHMARK_RUNNER_FILE_NAME}"

METRICS_EXPORTER_SERVICE_NAME = "benchmark-metrics-exporter"
METRICS_EXPORTER_SERVICE_FILE_PATH = f"/etc/systemd/system/{METRICS_EXPORTER_SERVICE_NAME}.service"
METRICS_EXPORTER_TEMPLATE_FILE_NAME = "benchmark-metrics-exporter.service.j2"
METRICS_EXPORTER_RUNNER_FILE_NAME = "benchmark_metrics_exporter.py"
METRICS_EXPORTER_RUNNER_FILE_PATH = f"/usr/local/bin/{METRICS_EXPORTER_RUNNER_FILE_NAME}"
METRICS_PORT = "9100"
