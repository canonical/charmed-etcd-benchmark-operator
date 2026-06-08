#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Handle etcd benchmark tool related events."""

import logging
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import ops
from charmlibs import snap
from ops import Object

from common.exceptions import (
    BenchmarkConfigurationError,
    BenchmarkResultsParseError,
    BenchmarkServiceError,
    BenchmarkWorkloadError,
    MetricsExporterServiceError,
)
from literals import (
    BENCHMARK_RUNNER_FILE_NAME,
    BENCHMARK_RUNNER_FILE_PATH,
    BENCHMARK_TESTS_ROOT_DIR,
    METRICS_EXPORTER_RUNNER_FILE_NAME,
    METRICS_EXPORTER_RUNNER_FILE_PATH,
)

if TYPE_CHECKING:
    from charm import CharmedEtcdBenchmarkOperatorCharm

logger = logging.getLogger(__name__)


class EtcdBenchmarkEvents(Object):
    """Event handler class for etcd benchmark tool related events."""

    def __init__(self, charm: "CharmedEtcdBenchmarkOperatorCharm"):
        super().__init__(charm, key="etcd_benchmark_events")
        self.charm = charm

        # Core etcd benchmark charm events

        self.framework.observe(self.charm.on.install, self._on_install)
        self.framework.observe(self.charm.on.start, self._on_start)
        self.framework.observe(self.charm.on.run_action, self._on_run_action)
        self.framework.observe(self.charm.on.stop_action, self._on_stop_action)
        self.framework.observe(self.charm.on.list_tests_action, self._on_list_tests_action)
        self.framework.observe(self.charm.on.get_summary_action, self._on_get_summary_action)

    def _on_install(self, event: ops.InstallEvent) -> None:
        """Handle install event."""
        self.charm.unit.status = ops.MaintenanceStatus("installing workload")

        try:
            self.charm.workload.install()
            runner_files = (
                (BENCHMARK_RUNNER_FILE_NAME, BENCHMARK_RUNNER_FILE_PATH),
                (METRICS_EXPORTER_RUNNER_FILE_NAME, METRICS_EXPORTER_RUNNER_FILE_PATH),
            )
            for runner_file_name, runner_file_path in runner_files:
                shutil.copyfile(
                    f"{self.charm.charm_dir}/templates/{runner_file_name}",
                    runner_file_path,
                )
                Path(runner_file_path).chmod(0o755)
        except snap.SnapError as e:
            logger.error(f"Error installing workload: {e.message}")
            self.charm.unit.status = ops.BlockedStatus("Error installing the workload")
            return
        except OSError as e:
            logger.error(f"Error setting up runner file: {e}")
            self.charm.unit.status = ops.BlockedStatus("Error setting up runner file")
            return

        self.charm.unit.status = ops.MaintenanceStatus("installed workload")

    def _on_start(self, event: ops.StartEvent) -> None:
        """Handle start event."""
        self.charm.unit.status = ops.MaintenanceStatus("running workload smoke-test")

        try:
            self.charm.workload.verify_workload_ready()

        except BenchmarkWorkloadError:
            self.charm.unit.status = ops.BlockedStatus("Error with the workload")
            return

        self.charm.unit.status = ops.ActiveStatus()

    def _on_run_action(self, event: ops.ActionEvent) -> None:
        """Handle run action event."""
        # Verify that it's not already running, and that etcd uris available.

        if self.charm.workload.is_benchmark_running():
            event.set_results({"error": "A benchmark is already in progress"})
            detailed_error_str = (
                "There is already a benchmark in progress. "
                "Please stop the active benchmark before starting a new one."
            )
            event.fail(detailed_error_str)
            logger.error(detailed_error_str)
            return

        if (
            not self.charm.etcd_interface_state.relation
            or not self.charm.etcd_interface_state.uris
        ):
            event.set_results({"error": "etcd relation missing"})
            detailed_error_str = (
                "The etcd relation is needed in order to run this action. "
                "Please relate to an etcd charm and try again."
            )
            event.fail(detailed_error_str)
            logger.error(detailed_error_str)
            return

        # setup test folder, metadata and results files, and then kick off the run
        try:
            benchmark_config = self.charm.etcd_benchmark_manager.setup_test()

            metrics_config = self.charm.metrics_exporter_manager.setup_metrics_exporter(
                benchmark_config
            )
            self.charm.workload.start_metrics_exporter(
                f"{os.environ.get('CHARM_DIR', '')}/templates", metrics_config
            )

            self.charm.workload.start_benchmark(
                f"{os.environ.get('CHARM_DIR', '')}/templates", benchmark_config
            )

            event.set_results(
                {
                    "results": (
                        "Benchmark started successfully.\n"
                        "If duration or total-transactions config options have been set, "
                        "test will auto terminate accordingly. "
                        "Alternatively, the `stop` action can be used."
                    )
                }
            )

        except (
            BenchmarkConfigurationError,
            BenchmarkServiceError,
            MetricsExporterServiceError,
        ) as e:
            event.set_results({"error": e.message})
            event.fail(e.detailed_description)

    def _on_stop_action(self, event: ops.ActionEvent) -> None:
        """Handle stop action event."""
        if not self.charm.workload.is_benchmark_running():
            event.set_results({"error": "no active benchmark to stop"})
            detailed_error_str = (
                "There is no active benchmark to stop. Use the 'run' action to start a benchmark."
            )
            event.fail(detailed_error_str)
            logger.error(detailed_error_str)
            return

        try:
            self.charm.workload.stop_benchmark()

            self.charm.workload.stop_metrics_exporter()

            event.set_results(
                {
                    "results": (
                        "Successfully signalled stop of current run.\n"
                        "Final summary will be available shortly, "
                        "and can be viewed on the console using the 'get-summary' action."
                    )
                }
            )
        except (BenchmarkServiceError, MetricsExporterServiceError) as e:
            event.set_results({"error": e.message})
            event.fail(e.detailed_description)

    def _on_list_tests_action(self, event: ops.ActionEvent) -> None:
        """Handle list-tests action event."""
        if not (tests := self.charm.etcd_benchmark_manager.list_tests(BENCHMARK_TESTS_ROOT_DIR)):
            event.set_results({"tests": "No tests found."})
            return

        formatted = [f"{test_id} ({status})" for test_id, status in tests]
        event.set_results({"tests": "\n".join(formatted)})

    def _on_get_summary_action(self, event: ops.ActionEvent) -> None:
        """Handle get-summary action event."""
        if not (test_id := str(event.params.get("test-id", ""))):
            event.set_results({"error": "valid test-id not found"})
            detailed_error_str = "Please provide a valid, non-empty test-id parameter."
            event.fail(detailed_error_str)
            logger.error(detailed_error_str)
            return
        test_folder = f"{BENCHMARK_TESTS_ROOT_DIR}/{test_id}"
        if not self.charm.workload.file_exists(test_folder):
            detailed_error_str = f"{test_folder} does not exist."
            event.set_results({"error": detailed_error_str})
            event.fail(detailed_error_str)
            logger.error(detailed_error_str)
            return

        try:
            summary = self.charm.etcd_benchmark_manager.get_test_summary(test_folder)
            event.set_results({"results": summary})
        except BenchmarkResultsParseError as e:
            event.set_results({"error": e.message})
            event.fail(e.detailed_description)
            return
