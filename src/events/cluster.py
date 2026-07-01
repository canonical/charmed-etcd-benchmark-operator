# #!/usr/bin/env python3
# # Copyright 2026 Canonical Ltd.
# # See LICENSE file for licensing details.
#
# """Cluster/peer-relation events for leader-managed behavior."""
#
# from __future__ import annotations
#
# from typing import TYPE_CHECKING
#
# from ops import Object, RelationChangedEvent, RelationCreatedEvent
#
# from literals import PEER_RELATION_NAME
#
# if TYPE_CHECKING:
#     from charm import CharmedEtcdBenchmarkOperatorCharm
#
#
# class ClusterEvents(Object):
#     """Handle peer relation lifecycle events."""
#
#     def __init__(self, charm: "CharmedEtcdBenchmarkOperatorCharm"):
#         super().__init__(charm, key="cluster-events")
#         self.charm = charm
#
#         self.framework.observe(
#             self.charm.on[PEER_RELATION_NAME].relation_created,
#             self._on_peer_relation_created,
#         )
#         self.framework.observe(
#             self.charm.on[PEER_RELATION_NAME].relation_changed,
#             self._on_peer_relation_changed,
#         )
#
#     def _on_peer_relation_created(self, event: RelationCreatedEvent) -> None:
#         """Ensure app-level peer state keys exist when relation is created."""
#         # del event
#         # self.charm.cluster_state.ensure_initialized()
#         return
#
#     def _on_peer_relation_changed(self, event: RelationChangedEvent) -> None:
#         """Ensure app-level peer state keys exist when relation data changes."""
#         # del event
#         # self.charm.cluster_state.ensure_initialized()
#         return
