#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""State for TLS-related data."""

import logging
from typing import TYPE_CHECKING

from charmlibs.interfaces.tls_certificates import Certificate
from ops import Object

from literals import CLIENT_CERT_PATH

if TYPE_CHECKING:
    from charm import CharmedEtcdBenchmarkOperatorCharm

logger = logging.getLogger(__name__)


class TLSState(Object):
    """State wrapper for TLS-related charm/library state."""

    def __init__(self, charm: "CharmedEtcdBenchmarkOperatorCharm"):
        super().__init__(charm, key="tls-state")
        self.charm = charm

    @property
    def common_name(self) -> str:
        """Build and return common name."""
        unit = self.charm.unit.name.replace("/", "")
        model_id = self.charm.model.uuid.split("-")[0]
        cn = f"{unit}-{model_id}"
        logger.debug(f"Computed common_name: {cn} (len={len(cn)})")
        return cn

    @property
    def stored_certificate_raw(self) -> str | None:
        """Return stored client certificate from disk."""
        return self.charm.workload.read_file(CLIENT_CERT_PATH)

    def get_stored_certificate_of_common_name(self, common_name: str) -> str | None:
        """Return the stored certificate if it matches the provided common name."""
        if not (raw_cert := self.stored_certificate_raw):
            return None
        if Certificate(raw=raw_cert).common_name == common_name:
            return raw_cert
        return None
