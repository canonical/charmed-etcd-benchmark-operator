#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manage all things TLS related."""

import logging
from typing import TYPE_CHECKING

import ops
from charmlibs.interfaces.tls_certificates import CertificateAvailableEvent
from ops import Object

from literals import CLIENT_CERT_PATH, CLIENT_KEY_PATH

if TYPE_CHECKING:
    from charm import CharmedEtcdBenchmarkOperatorCharm

logger = logging.getLogger(__name__)


class TLSManager(Object):
    """Manager class for TLS related events."""

    def __init__(self, charm: "CharmedEtcdBenchmarkOperatorCharm"):
        super().__init__(charm, key="tls-manager")
        self.charm = charm

    def handle_certificate_available(self, event: CertificateAvailableEvent) -> None:
        """Handle certificate available event."""
        logger.info("Certificate available")

        certs, private_key = self.charm.tls_state.assigned_certificates
        if not certs or not private_key:
            logger.error("No certificates available")
            return

        cert = certs[0]

        if cert.certificate != event.certificate:
            logger.error("Received certificate does not match assigned certificate: %s", cert)
            return

        try:
            self.charm.workload.write_file(cert.certificate.raw, CLIENT_CERT_PATH)
            self.charm.workload.write_file(private_key.raw, CLIENT_KEY_PATH)
        except Exception as e:
            logger.error("Error writing TLS certificates to disk: %s", e)
            self.charm.unit.status = ops.BlockedStatus("Error writing TLS certificates to disk")
            return

        self.charm.etcd_interface_manager.update_request_from_cert(cert.certificate)
