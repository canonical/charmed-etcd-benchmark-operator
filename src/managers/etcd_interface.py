#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manage all things etcd_client interface related."""

import logging
from typing import TYPE_CHECKING

from charmlibs.interfaces.tls_certificates import Certificate
from charms.data_platform_libs.v1.data_interfaces import (
    RequirerCommonModel,
)
from ops import Object

from utils.utils import get_common_name_from_chain

if TYPE_CHECKING:
    from charm import CharmedEtcdBenchmarkOperatorCharm

logger = logging.getLogger(__name__)


class EtcdInterfaceManager(Object):
    """Manager class for etcd interface related events."""

    def __init__(self, charm: "CharmedEtcdBenchmarkOperatorCharm"):
        super().__init__(charm, key="etcd-interface-manager")
        self.charm = charm

    @property
    def client_requests(self) -> list[RequirerCommonModel]:
        """Return the client requests for the etcd requirer interface."""
        return [
            RequirerCommonModel(
                resource="",
                mtls_cert=self.charm.tls_state.get_stored_certificate_of_common_name(
                    self.charm.tls_state.common_name
                )
                or "",
            )
        ]

    def update_request_from_cert(self, cert: Certificate) -> None:
        """Update the requests in the relation data bag from the assigned certificates."""
        local_model = self.charm.etcd_interface_state.local_model
        if not local_model:
            return

        request_common_names = {
            get_common_name_from_chain(request.mtls_cert): request
            for request in local_model.requests
            if request.mtls_cert
        }

        cur_request = request_common_names.get(
            cert.common_name,
            RequirerCommonModel(resource=f"/{cert.common_name}/"),
        )
        cur_request.mtls_cert = cert.raw

        local_model.requests = [cur_request]
        self.charm.etcd_interface_state.write_local_model(local_model)
