#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Handle all TLS related events."""

import logging
from typing import TYPE_CHECKING

import ops
from charmlibs.interfaces.tls_certificates import (
    CertificateAvailableEvent,
    TLSCertificatesRequiresV4,
)
from ops import Object

from literals import CLIENT_CERT_PATH, CLIENT_KEY_PATH

if TYPE_CHECKING:
    from charm import CharmedEtcdBenchmarkOperatorCharm

logger = logging.getLogger(__name__)


class RefreshTLSCertificatesEvent(ops.EventBase):
    """Event for refreshing peer TLS certificates."""


class TLSEvents(Object):
    """Event handler class for TLS related events."""

    refresh_tls_certificates_event = ops.EventSource(RefreshTLSCertificatesEvent)

    def __init__(self, charm: "CharmedEtcdBenchmarkOperatorCharm"):
        super().__init__(charm, key="tls-events")
        self.charm = charm
        self.certificates = TLSCertificatesRequiresV4(
            self.charm,
            "certificates",
            certificate_requests=self.charm.tls_manager.client_requests,
            refresh_events=[self.refresh_tls_certificates_event],
        )

        self.framework.observe(
            self.certificates.on.certificate_available, self._on_certificate_available
        )

    def _on_certificate_available(self, event: CertificateAvailableEvent) -> None:
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
