#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import os
import time
from pathlib import Path
from threading import Thread
from datetime import datetime

from prometheus_client import start_http_server, Gauge, Counter


class BenchmarkMetrics:
    def __init__(self):
        # Core metrics
        self.iteration = Gauge("etcd_benchmark_iteration", "Latest completed sample id")
        self.last_ts = Gauge(
            "etcd_benchmark_last_result_timestamp_seconds",
            "Timestamp of last completed sample",
        )

        self.total_ops = Gauge("etcd_benchmark_total_ops", "Total operations", ["op_type"])
        self.avg_latency = Gauge("etcd_benchmark_average_latency_seconds", "Average latency", ["op_type"])
        self.stddev_latency = Gauge("etcd_benchmark_stddev_latency_seconds", "Stddev latency", ["op_type"])
        self.throughput = Gauge("etcd_benchmark_throughput_rps", "Throughput (req/sec)", ["op_type"])

        self.latency_quantile = Gauge(
            "etcd_benchmark_latency_seconds",
            "Latency percentiles",
            ["op_type", "quantile"],
        )

        # Health metrics
        self.rows_processed = Counter("etcd_benchmark_jsonl_rows_processed_total", "JSONL rows processed")
        self.parse_errors = Counter("etcd_benchmark_jsonl_parse_errors_total", "JSONL parse errors")
        self.exporter_up = Gauge("etcd_benchmark_exporter_up", "Exporter health")

        self.exporter_up.set(1)


class JsonlTailer:
    def __init__(self, path: Path, metrics: BenchmarkMetrics):
        self.path = path
        self.metrics = metrics

        self._position = 0
        self._inode = None
        self._latest_id = -1

    def run(self):
        while True:
            self._process_new_data()
            time.sleep(2)

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
                    self.metrics.rows_processed.inc()
                except Exception:
                    self.metrics.parse_errors.inc()

            self._position = f.tell()

    def _handle_record(self, obj: dict):
        sample_id = int(obj["id"])

        # Only process strictly newer samples
        if sample_id <= self._latest_id:
            return

        self._latest_id = sample_id

        self._publish(obj)

    def _publish(self, obj: dict):
        # iteration
        self.metrics.iteration.set(obj["id"])

        # timestamp
        ts = obj["ts"]
        ts_epoch = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
        self.metrics.last_ts.set(ts_epoch)

        for op_type in ["read", "write"]:
            data = obj[op_type]

            self.metrics.total_ops.labels(op_type).set(float(data["ops"]))
            self.metrics.avg_latency.labels(op_type).set(float(data["avg"]))
            self.metrics.stddev_latency.labels(op_type).set(float(data["stddev"]))
            self.metrics.throughput.labels(op_type).set(float(data["rps"]))

            self.metrics.latency_quantile.labels(op_type, "0.50").set(float(data["p50"]))
            self.metrics.latency_quantile.labels(op_type, "0.90").set(float(data["p90"]))
            self.metrics.latency_quantile.labels(op_type, "0.99").set(float(data["p99"]))


def main():
    # --- ENV CONFIG ---
    jsonl_path = os.environ.get("ETCD_BENCHMARK_JSONL_PATH")
    port = int(os.environ.get("ETCD_BENCHMARK_METRICS_PORT", "9645"))

    if not jsonl_path:
        raise RuntimeError("ETCD_BENCHMARK_JSONL_PATH must be set")

    metrics = BenchmarkMetrics()

    start_http_server(port)

    tailer = JsonlTailer(Path(jsonl_path), metrics)

    t = Thread(target=tailer.run, daemon=True)
    t.start()

    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()