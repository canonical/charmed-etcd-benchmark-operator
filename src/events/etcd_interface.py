#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Handle all etcd_client interface related events."""

import logging
from typing import TYPE_CHECKING

from ops import Object

from literals import CA_CERT_PATH

if TYPE_CHECKING:
    from charm import CharmedEtcdBenchmarkOperatorCharm
from charms.data_platform_libs.v1.data_interfaces import (
    ResourceCreatedEvent,
    ResourceEndpointsChangedEvent,
    ResourceProviderModel,
    ResourceRequirerEventHandler,
)

logger = logging.getLogger(__name__)


class EtcdInterfaceEvents(Object):
    """Event handler class for etcd interface related events."""

    def __init__(self, charm: "CharmedEtcdBenchmarkOperatorCharm"):
        super().__init__(charm, "etcd_requirer_events")
        self.charm = charm
        self.etcd_interface = ResourceRequirerEventHandler(
            self.charm,
            relation_name="etcd-client",
            requests=self.charm.etcd_interface_manager.client_requests,
            response_model=ResourceProviderModel,
        )

        # Events pertaining to integration with etcd charm

        self.framework.observe(
            self.etcd_interface.on.endpoints_changed, self._on_endpoints_changed
        )
        self.framework.observe(self.etcd_interface.on.resource_created, self._on_resource_created)

    def _on_endpoints_changed(
        self, event: ResourceEndpointsChangedEvent[ResourceProviderModel]
    ) -> None:
        """Handle etcd client relation data changed event."""
        response = event.response
        logger.info("Endpoints changed: %s", response.endpoints)
        if not response.endpoints:
            logger.error("No endpoints available")

    def _on_resource_created(self, event: ResourceCreatedEvent[ResourceProviderModel]) -> None:
        """Handle resource created event."""
        logger.info("Resource created")
        response = event.response
        if not response.tls_ca:
            logger.error("No server CA chain available")
            return
        if not response.username:
            logger.error("No username available")
            return

        self.charm.workload.write_file(response.tls_ca, CA_CERT_PATH)
