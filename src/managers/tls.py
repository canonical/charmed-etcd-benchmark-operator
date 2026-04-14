#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manage all things TLS related."""

import logging
import socket
from typing import TYPE_CHECKING

from charmlibs.interfaces.tls_certificates import (
    CertificateRequestAttributes,
)
from ops import Object

if TYPE_CHECKING:
    from charm import CharmedEtcdBenchmarkOperatorCharm

logger = logging.getLogger(__name__)


class TLSManager(Object):
    """Manager class for TLS related events."""

    def __init__(self, charm: "CharmedEtcdBenchmarkOperatorCharm"):
        super().__init__(charm, key="tls-manager")
        self.charm = charm

    @property
    def client_requests(self) -> list[CertificateRequestAttributes]:
        """Return the client requests for the etcd requirer interface."""
        return [
            CertificateRequestAttributes(
                common_name=self.charm.tls_state.common_name,
                sans_ip=frozenset({socket.gethostbyname(socket.gethostname())}),
                sans_dns=frozenset({self.charm.unit.name, socket.gethostname()}),
            )
        ]
