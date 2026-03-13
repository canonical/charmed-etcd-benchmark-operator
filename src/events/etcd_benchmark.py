#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from subprocess import CalledProcessError
from typing import TYPE_CHECKING

import ops
from ops import Object

if TYPE_CHECKING:
    from charm import CharmedEtcdBenchmarkOperatorCharm

logger = logging.getLogger(__name__)


class EtcdBenchmarkEvents(Object):
    """Handle all base and etcd benchmark tool related events."""

    def __init__(self, charm: "CharmedEtcdBenchmarkOperatorCharm"):
        super().__init__(charm, key="etcd_benchmark_events")
        self.charm = charm

        # Core etcd benchmark charm events

        self.framework.observe(self.charm.on.start, self._on_start)
        self.framework.observe(self.charm.on.run_action, self._on_run_action)

    def _on_start(self, event: ops.StartEvent) -> None:
        """Handle start event."""
        self.charm.unit.status = ops.MaintenanceStatus("starting workload")
        self.charm.workload.start()
        self.charm.unit.status = ops.ActiveStatus()

    def _on_run_action(self, event: ops.ActionEvent):
        """Handle run action event."""
        if not self.charm.etcd_interface_manager.etcd_relation:
            event.set_results({"ok": False, "stderr": "The etcd relation is needed in order to run this action"})
            return

        uris = self.charm.etcd_interface_manager.etcd_uris

        if not uris:
            event.fail("No uris available")
            event.set_results({"ok": False})
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
