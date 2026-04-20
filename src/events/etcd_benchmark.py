#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Handle etcd benchmark tool related events."""

import logging
import shutil
from pathlib import Path
from subprocess import CalledProcessError
from typing import TYPE_CHECKING

import ops
from charmlibs import snap
from ops import Object

from literals import (
    BENCHMARK_TESTS_ROOT_DIR,
    RESULTS_CSV_FILE_NAME,
    RUNNER_FILE_NAME,
    RUNNER_FILE_PATH,
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
            shutil.copyfile(
                f"{self.charm.charm_dir}/templates/{RUNNER_FILE_NAME}", RUNNER_FILE_PATH
            )
            Path(RUNNER_FILE_PATH).chmod(0o755)
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
        self.charm.unit.status = ops.MaintenanceStatus("starting workload")

        try:
            self.charm.workload.start()
        except CalledProcessError as e:
            logger.error(f"Error starting workload: {e.stderr}")
            self.charm.unit.status = ops.BlockedStatus("Error starting the workload")
            return

        self.charm.unit.status = ops.ActiveStatus()

    def _on_run_action(self, event: ops.ActionEvent):
        """Handle run action event."""
        # Verify that it's not already running, and that etcd uris available.

        if self.charm.workload.is_running():
            error_str = (
                "There is already a benchmark in progress. "
                "Please stop the active benchmark before starting a new one."
            )
            event.set_results({"error": error_str})
            event.fail(error_str)
            return

        if (
            not self.charm.etcd_interface_state.relation
            or not self.charm.etcd_interface_state.uris
        ):
            error_str = (
                "The etcd relation is needed in order to run this action. "
                "Please relate to an etcd charm and try again."
            )
            event.set_results({"error": error_str})
            event.fail(error_str)
            return

        self.charm.etcd_benchmark_manager.initiate_run(event)

    def _on_stop_action(self, event: ops.ActionEvent):
        """Handle stop action event."""
        if not self.charm.workload.is_running():
            error_str = (
                "There is no active benchmark to stop. Use the 'run' action to start a benchmark."
            )
            event.set_results({"error": error_str})
            event.fail(error_str)
            return

        self.charm.workload.stop_service()

        event.set_results(
            {
                "results": (
                    "Successfully signalled stop of current run.\n"
                    "Final summary will be available shortly, "
                    "and can be viewed on the console using the 'get-summary' action."
                )
            }
        )

    def _on_list_tests_action(self, event: ops.ActionEvent):
        """Handle list-tests action event."""
        tests = self.charm.workload.list_tests(BENCHMARK_TESTS_ROOT_DIR)

        if not tests:
            event.set_results({"tests": "No tests found."})
            return

        formatted = [f"{test_id} ({status})" for test_id, status in tests]
        event.set_results({"tests": "\n".join(formatted)})

    def _on_get_summary_action(self, event: ops.ActionEvent):
        """Handle get-summary action event."""
        test_id = str(event.params.get("test-id", ""))
        if not test_id:
            event.set_results({"error": "Please provide a valid, non-empty test-id parameter."})
            event.fail("Please provide a valid, non-empty test-id parameter.")
            return
        test_folder = f"{BENCHMARK_TESTS_ROOT_DIR}/{test_id}"
        if not self.charm.workload.file_exists(test_folder):
            event.set_results({"error": f"{test_folder} does not exist."})
            event.fail(f"{test_folder} does not exist.")
            return

        error_str = "Error preparing/writing summary"

        try:
            summary = self.charm.workload.prepare_and_write_summary(
                f"{test_folder}/{RESULTS_CSV_FILE_NAME}"
            )
            event.set_results({"results": summary})
        except (OSError, ValueError) as e:
            logger.error(f"{error_str}: {e}")
            event.set_results({"error": f"{error_str}: {e}"})
            event.fail(f"{error_str}: {e}")
            return
