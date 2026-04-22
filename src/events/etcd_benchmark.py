#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Handle etcd benchmark tool related events."""

import logging
from subprocess import CalledProcessError
from typing import TYPE_CHECKING

import ops
from charmlibs import snap
from ops import Object

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

    def _on_install(self, event: ops.InstallEvent) -> None:
        """Handle install event."""
        self.charm.unit.status = ops.MaintenanceStatus("installing workload")

        try:
            self.charm.workload.install()
        except snap.SnapError as e:
            logger.error(f"Error installing workload: {e.message}")
            self.charm.unit.status = ops.BlockedStatus("Error installing the workload")
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
        if not self.charm.etcd_interface_state.relation:
            event.set_results({"error": "The etcd relation is needed in order to run this action"})
            event.fail("The etcd relation is needed in order to run this action")
            return

        if not (uris := self.charm.etcd_interface_state.uris):
            event.set_results({"error": "No etcd uris available"})
            event.fail("No etcd uris available")
            return

        logger.debug(f"Endpoints available for txn-mixed: {uris}")

        try:
            results = self.charm.workload.run(endpoints=uris)
            event.set_results({"results": results})
        except CalledProcessError as e:
            logger.error(e.stderr)
            event.set_results({"error": e.stderr})
            event.fail("Benchmark run failed. Check logs for more information.")
            return
