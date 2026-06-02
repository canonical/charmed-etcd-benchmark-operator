#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import os
import time
from datetime import datetime
from pathlib import Path
from threading import Thread

from prometheus_client import Counter, Gauge, start_http_server


def _positive_int_env(name: str, default: int) -> int:
    value = os.environ.get(name)
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


class BenchmarkMetrics:
    def __init__(self, test_id: str):
        self.test_id = test_id

        # Core metrics
        self.iteration = Gauge(
            "etcd_benchmark_iteration", "Latest completed sample id", ["test_id"]
        )
        self.last_ts = Gauge(
            "etcd_benchmark_last_result_timestamp_seconds",
            "Timestamp of last completed sample",
            ["test_id"],
        )
        self.total_ops = Gauge("etcd_benchmark_total_ops", "Total operations", ["test_id", "op_type"])
        self.avg_latency = Gauge(
            "etcd_benchmark_average_latency_seconds", "Average latency", ["test_id", "op_type"]
        )
        self.stddev_latency = Gauge(
            "etcd_benchmark_stddev_latency_seconds", "Stddev latency", ["test_id", "op_type"]
        )
        self.throughput = Gauge(
            "etcd_benchmark_throughput_rps", "Throughput (req/sec)", ["test_id", "op_type"]
        )
        self.latency_quantile = Gauge(
            "etcd_benchmark_latency_seconds",
            "Latency percentiles",
            ["test_id", "op_type", "quantile"],
        )

        # Health metrics
        self.rows_processed = Counter(
            "etcd_benchmark_jsonl_rows_processed_total", "JSONL rows processed", ["test_id"]
        )
        self.parse_errors = Counter(
            "etcd_benchmark_jsonl_parse_errors_total", "JSONL parse errors", ["test_id"]
        )
        self.exporter_up = Gauge("etcd_benchmark_exporter_up", "Exporter health", ["test_id"])
        self.total_elapsed = Counter(
            "etcd_benchmark_elapsed_seconds_total",
            "Cumulative elapsed seconds across processed benchmark samples",
            ["test_id"],
        )
        self.total_read_ops = Counter(
            "etcd_benchmark_read_ops_total",
            "Cumulative read operations across processed benchmark samples",
            ["test_id"],
        )
        self.total_write_ops = Counter(
            "etcd_benchmark_write_ops_total",
            "Cumulative write operations across processed benchmark samples",
            ["test_id"],
        )

        self.exporter_up.labels(self.test_id).set(1)

    def add_benchmark_sample(self, obj: dict):
        ts_epoch = datetime.fromisoformat(obj["ts"].replace("Z", "+00:00")).timestamp()

        self.iteration.labels(self.test_id).set(float(obj["id"]))
        self.last_ts.labels(self.test_id).set(ts_epoch)
        self.total_elapsed.labels(self.test_id).inc(float(obj.get("elapsed_sec", 0.0)))
        self.total_read_ops.labels(self.test_id).inc(float(obj.get("read", {}).get("ops", 0.0)))
        self.total_write_ops.labels(self.test_id).inc(float(obj.get("write", {}).get("ops", 0.0)))

        for op_type in ["read", "write"]:
            data = obj[op_type]
            self.total_ops.labels(self.test_id, op_type).set(float(data["ops"]))
            self.avg_latency.labels(self.test_id, op_type).set(float(data["avg"]))
            self.stddev_latency.labels(self.test_id, op_type).set(float(data["stddev"]))
            self.throughput.labels(self.test_id, op_type).set(float(data["rps"]))
            self.latency_quantile.labels(self.test_id, op_type, "0.50").set(float(data["p50"]))
            self.latency_quantile.labels(self.test_id, op_type, "0.90").set(float(data["p90"]))
            self.latency_quantile.labels(self.test_id, op_type, "0.99").set(float(data["p99"]))


class JsonlTailer:
    def __init__(self, path: Path, metrics: BenchmarkMetrics, poll_interval_seconds: int):
        self.path = path
        self.metrics = metrics
        self.poll_interval_seconds = poll_interval_seconds

        self._position = 0
        self._inode = None
        self._latest_id = -1

    def run(self):
        while True:
            self._process_new_data()
            time.sleep(self.poll_interval_seconds)

    def _process_new_data(self):
        if not self.path.exists():
            return

        stat = self.path.stat()

        # Detect file rotation / replacement
        if self._inode is None or self._inode != stat.st_ino:
            self._inode = stat.st_ino
            self._position = 0

        # Detect truncation
        if stat.st_size < self._position:
            self._position = 0

        with self.path.open() as f:
            f.seek(self._position)

            while True:
                line = f.readline()

                if not line:
                    break

                # Handle partial line (no newline yet)
                if not line.endswith("\n"):
                    break

                line = line.strip()
                if not line:
                    continue

                try:
                    obj = json.loads(line)
                    self._handle_record(obj)
                    self.metrics.rows_processed.labels(self.metrics.test_id).inc()
                except Exception:
                    self.metrics.parse_errors.labels(self.metrics.test_id).inc()

            self._position = f.tell()

    def _handle_record(self, obj: dict):
        sample_id = int(obj["id"])

        # Only process strictly newer samples
        if sample_id <= self._latest_id:
            return

        self._latest_id = sample_id

        self._publish(obj)

    def _publish(self, obj: dict):
        self.metrics.add_benchmark_sample(obj)


def main():
    # --- ENV CONFIG ---
    jsonl_path = os.environ.get("ETCD_BENCHMARK_JSONL_PATH")
    test_id = os.environ.get("ETCD_BENCHMARK_TEST_ID")
    port = int(os.environ.get("ETCD_BENCHMARK_METRICS_PORT", "9645"))
    report_interval = _positive_int_env("ETCD_BENCHMARK_REPORT_INTERVAL", 10)

    if not jsonl_path:
        raise RuntimeError("ETCD_BENCHMARK_JSONL_PATH must be set")
    if not test_id:
        raise RuntimeError("ETCD_BENCHMARK_TEST_ID must be set")

    metrics = BenchmarkMetrics(test_id=test_id)

    start_http_server(port)

    tailer = JsonlTailer(Path(jsonl_path), metrics, poll_interval_seconds=report_interval)

    t = Thread(target=tailer.run, daemon=True)
    t.start()

    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()