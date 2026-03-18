#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm the application."""

import logging

import ops

import workload
from core.interfaces import EtcdInterfaceState
from core.tls import TLSState
from events.etcd_benchmark import EtcdBenchmarkEvents
from events.etcd_interface import EtcdInterfaceEvents
from events.tls import TLSEvents
from managers.etcd_interface import EtcdInterfaceManager
from managers.tls import TLSManager

logger = logging.getLogger(__name__)


class CharmedEtcdBenchmarkOperatorCharm(ops.CharmBase):
    """Charm the application."""

    def __init__(self, *args):
        super().__init__(*args)
        self.workload = workload.EtcdBenchmarkWorkload()

        # --- MANAGERS ---
        self.tls_manager = TLSManager(self)
        self.etcd_interface_manager = EtcdInterfaceManager(self)

        # --- STATE ---
        self.etcd_interface_state = EtcdInterfaceState(self)
        self.tls_state = TLSState(self)

        # --- EVENT HANDLERS ---
        self.etcd_benchmark_events = EtcdBenchmarkEvents(self)
        self.tls_events = TLSEvents(self)
        self.etcd_interface_events = EtcdInterfaceEvents(self)


if __name__ == "__main__":  # pragma: nocover
    ops.main(CharmedEtcdBenchmarkOperatorCharm)
