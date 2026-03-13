#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manage all things etcd_client interface related."""

import logging
from typing import TYPE_CHECKING

import ops
from charmlibs.interfaces.tls_certificates import Certificate
from charms.data_platform_libs.v1.data_interfaces import (
    DataContractV1,
    RequirerCommonModel,
    RequirerDataContractV1,
    ResourceProviderModel,
    build_model,
)
from ops import Object

from managers.tls import get_common_name_from_chain

if TYPE_CHECKING:
    from charm import CharmedEtcdBenchmarkOperatorCharm

logger = logging.getLogger(__name__)


class EtcdInterfaceManager(Object):
    """Manager class for etcd interface related events."""

    def __init__(self, charm: "CharmedEtcdBenchmarkOperatorCharm"):
        super().__init__(charm, key="tls-manager")
        self.charm = charm

    @property
    def etcd_relation(self) -> ops.Relation | None:
        """Return the etcd relation if present."""
        if not hasattr(self.charm.etcd_interface_events, "etcd_interface"):
            return None
        return (
            self.charm.etcd_interface_events.etcd_interface.relations[0]
            if len(self.charm.etcd_interface_events.etcd_interface.relations)
            else None
        )

    @property
    def client_requests(self) -> list:
        """Return the client requests for the etcd requirer interface."""
        return [
            RequirerCommonModel(
                resource="",
                mtls_cert=self.charm.tls_manager.get_certificate_of_common_name(
                    self.charm.tls_manager.common_name
                )
                or "",
            )
        ]

    @property
    def etcd_relation_local_model(self) -> RequirerDataContractV1[RequirerCommonModel]:
        """Return the etcd relation local model."""
        if not self.etcd_relation:
            raise RuntimeError("etcd relation not found")
        return build_model(
            self.charm.etcd_interface_events.etcd_interface.interface.repository(
                self.etcd_relation.id
            ),
            RequirerDataContractV1[RequirerCommonModel],
        )

    @property
    def etcd_uris(self) -> str | None:
        """Return the etcd uris."""
        remote_responses = self.remote_responses
        if not remote_responses:
            return None
        remote_response = remote_responses[0]
        return remote_response.uris

    @property
    def remote_responses(self) -> list[ResourceProviderModel] | None:
        """Return the remote response model."""
        if not self.etcd_relation:
            logger.warning("Relation isn't available yet")
            return None

        return build_model(
            self.charm.etcd_interface_events.etcd_interface.interface.repository(
                self.etcd_relation.id, self.etcd_relation.app
            ),
            DataContractV1[ResourceProviderModel],
        ).requests

    def update_request_from_cert(self, cert: Certificate) -> None:
        """Update the requests in the relation data bag from the assigned certificates."""
        if not self.etcd_relation:
            logger.warning("Relation isn't available yet")
            return
        local_model = self.etcd_relation_local_model

        request_common_names = {
            get_common_name_from_chain(request.mtls_cert): request
            for request in local_model.requests
            if request.mtls_cert
        }

        requests_to_send = []
        cur_request = request_common_names.get(
            cert.common_name,
            RequirerCommonModel(resource=f"/{cert.common_name}/"),
        )

        cur_request.mtls_cert = cert.raw
        requests_to_send.append(cur_request)

        local_model.requests = requests_to_send
        self.charm.etcd_interface_events.etcd_interface.interface.write_model(
            self.etcd_relation.id, local_model
        )
