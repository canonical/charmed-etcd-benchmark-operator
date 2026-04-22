#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""State for relations this charm supports."""

import logging
from typing import TYPE_CHECKING

import ops
from charms.data_platform_libs.v1.data_interfaces import (
    DataContractV1,
    RequirerCommonModel,
    RequirerDataContractV1,
    ResourceProviderModel,
    build_model,
)
from ops import Object

if TYPE_CHECKING:
    from charm import CharmedEtcdBenchmarkOperatorCharm

logger = logging.getLogger(__name__)


class EtcdInterfaceState(Object):
    """State wrapper for etcd-client relation data."""

    def __init__(self, charm: "CharmedEtcdBenchmarkOperatorCharm"):
        super().__init__(charm, key="etcd-interface-state")
        self.charm = charm

    @property
    def relation(self) -> ops.Relation | None:
        """Return the etcd-client relation if present."""
        if not hasattr(self.charm.etcd_interface_events, "etcd_interface"):
            return None

        relations = self.charm.etcd_interface_events.etcd_interface.relations
        return relations[0] if relations else None

    @property
    def local_model(self) -> RequirerDataContractV1[RequirerCommonModel] | None:
        """Return the local requirer model."""
        if not self.relation:
            return None

        return build_model(
            self.charm.etcd_interface_events.etcd_interface.interface.repository(self.relation.id),
            RequirerDataContractV1[RequirerCommonModel],
        )

    @property
    def remote_responses(self) -> list[ResourceProviderModel] | None:
        """Return remote provider responses."""
        if not self.relation:
            logger.warning("Relation isn't available yet")
            return None

        return build_model(
            self.charm.etcd_interface_events.etcd_interface.interface.repository(
                self.relation.id, self.relation.app
            ),
            DataContractV1[ResourceProviderModel],
        ).requests

    @property
    def uris(self) -> str | None:
        """Return etcd URIs from remote responses."""
        remote_responses = self.remote_responses
        if not remote_responses:
            return None
        return remote_responses[0].uris

    def write_local_model(self, model: RequirerDataContractV1[RequirerCommonModel]) -> None:
        """Persist the local requirer model."""
        if not self.relation:
            logger.warning("Relation isn't available yet")
            return

        self.charm.etcd_interface_events.etcd_interface.interface.write_model(
            self.relation.id, model
        )
