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

BENCHMARK_ROOT_DIR = "/var/lib/charmed-etcd-benchmark-operator"
BENCHMARK_TESTS_ROOT_DIR = f"{BENCHMARK_ROOT_DIR}/tests"
RESULTS_CSV_FILE_NAME = "results.csv"
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

SERVICE_NAME = "charmed-etcd-benchmark"
SERVICE_FILE_PATH = f"/etc/systemd/system/{SERVICE_NAME}.service"
TEMPLATE_FILE_NAME = "charmed-etcd-benchmark.service.j2"
RUNNER_FILE_NAME = "charmed-etcd-benchmark.py"
RUNNER_FILE_PATH = f"/usr/local/bin/{RUNNER_FILE_NAME}"
