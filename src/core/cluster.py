#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""State management backed by the peer relation databag."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import ops
from charms.data_platform_libs.v1.data_interfaces import OpsPeerRepositoryInterface
from ops import Object

from core.models import EtcdBenchmarkCluster, PeerAppModel
from literals import PEER_RELATION_NAME

if TYPE_CHECKING:
    from charm import CharmedEtcdBenchmarkOperatorCharm

logger = logging.getLogger(__name__)


class ClusterState(Object):
    """State wrapper for app-level peer data."""

    def __init__(self, charm: "CharmedEtcdBenchmarkOperatorCharm"):
        super().__init__(charm, key="cluster-state")
        self.charm = charm
        self.peer_app_interface = OpsPeerRepositoryInterface(
            model=charm.model, relation_name=PEER_RELATION_NAME, data_model=PeerAppModel
        )

    @property
    def peer_relation(self) -> ops.Relation | None:
        """Return the peer relation if present."""
        return self.charm.model.get_relation(PEER_RELATION_NAME)

    @property
    def cluster(self) -> EtcdBenchmarkCluster:
        """Get the cluster state of the entire etcd benchmark application."""
        return EtcdBenchmarkCluster(
            relation=self.peer_relation,
            data_interface=self.peer_app_interface,
            component=self.model.app,
        )
