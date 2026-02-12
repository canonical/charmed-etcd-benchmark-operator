#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm the application."""

import logging

import ops

# A standalone module for workload-specific logic (no charming concerns):
import workload
from events.etcd_benchmark import EtcdBenchmarkEvents
from events.etcd_requires import EtcdRequires
from events.tls import TLSEvents

logger = logging.getLogger(__name__)


class CharmedEtcdBenchmarkOperatorCharm(ops.CharmBase):
    """Charm the application."""

    def __init__(self, *args):
        super().__init__(*args)
        self.workload = workload.EtcdBenchmarkWorkload()

        # --- EVENT HANDLERS ---
        self.etcd_benchmark_events = EtcdBenchmarkEvents(self)
        self.tls_events = TLSEvents(self)
        self.etcd_requires_events = EtcdRequires(self)


if __name__ == "__main__":  # pragma: nocover
    ops.main(CharmedEtcdBenchmarkOperatorCharm)
