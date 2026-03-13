#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manage all things TLS related."""

import logging
from typing import TYPE_CHECKING

from charmlibs.interfaces.tls_certificates import Certificate, PrivateKey
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

    @property
    def common_name(self) -> str:
        """Return the common names for the client certificates."""
        return "client1.etcd-benchmark-charm"

    def write_certificate(self, certificate: Certificate, private_key: PrivateKey):
        """Write certificate to disk."""
        logger.debug("Writing certificates to disk")
        self.charm.workload.write_file(certificate.raw, CLIENT_CERT_PATH)
        self.charm.workload.write_file(private_key.raw, CLIENT_KEY_PATH)

    def get_certificate_of_common_name(self, common_name: str) -> str | None:
        """Return the certificate for a given common name."""
        raw_cert = self.charm.workload.read_file(CLIENT_CERT_PATH)
        if not raw_cert:
            return None
        if Certificate(raw=raw_cert).common_name == common_name:
            return raw_cert
        return None


def get_common_name_from_chain(mtls_cert: str) -> str:
    """Get common name from chain."""
    raw_cas = [
        cert.strip() for cert in mtls_cert.split("-----END CERTIFICATE-----") if cert.strip()
    ]
    cert = raw_cas[0] + "\n-----END CERTIFICATE-----"
    return Certificate.from_string(cert).common_name
