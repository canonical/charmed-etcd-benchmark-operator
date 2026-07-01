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

    # @property
    # def app_databag(self) -> ops.RelationDataContent | None:
    #     """Return the app-scoped databag for this charm app."""
    #     if not self.peer_relation:
    #         return None
    #     return self.peer_relation.data[self.charm.app]
    #
    # @property
    # def current_test_id(self) -> str | None:
    #     """Return currently active test id, if any."""
    #     if not self.app_databag:
    #         return None
    #     value = self.app_databag.get(PEER_CURRENT_TEST_ID_KEY, "")
    #     return value or None
    #
    # def set_current_test_id(self, test_id: str | None) -> None:
    #     """Persist current test id in app databag."""
    #     if not self.charm.unit.is_leader() or not self.app_databag:
    #         return
    #     self.app_databag[PEER_CURRENT_TEST_ID_KEY] = test_id or ""
    #
    # def get_all_test_metadata(self) -> dict[str, BenchmarkMetadata]:
    #     """Return all known tests keyed by test id."""
    #     if not self.app_databag:
    #         return {}
    #
    #     raw_payload = self.app_databag.get(PEER_TESTS_KEY, "{}")
    #     try:
    #         payload = json.loads(raw_payload)
    #     except json.JSONDecodeError:
    #         logger.warning("Malformed tests payload in peer relation databag")
    #         return {}
    #
    #     if not isinstance(payload, dict):
    #         logger.warning("Unexpected tests payload type in peer relation databag")
    #         return {}
    #
    #     result: dict[str, BenchmarkMetadata] = {}
    #     for test_id, raw_metadata in payload.items():
    #         if not isinstance(test_id, str) or not isinstance(raw_metadata, dict):
    #             continue
    #         try:
    #             result[test_id] = BenchmarkMetadata.from_dict(raw_metadata)
    #         except (KeyError, TypeError, ValueError) as e:
    #             logger.warning(f"Skipping malformed metadata for {test_id}: {e}")
    #
    #     return result
    #
    # def get_test_metadata(self, test_id: str) -> BenchmarkMetadata | None:
    #     """Return metadata for one test id, if present."""
    #     return self.get_all_test_metadata().get(test_id)
    #
    # def upsert_test_metadata(self, metadata: BenchmarkMetadata) -> None:
    #     """Create or update one test record in peer state."""
    #     if not self.charm.unit.is_leader() or not self.app_databag:
    #         return
    #
    #     all_tests = self.get_all_test_metadata()
    #     all_tests[metadata.test_id] = metadata
    #     self._write_all_tests(all_tests)
    #
    # def mark_test_completed(self, test_id: str) -> bool:
    #     """Mark a known test as completed; return True if state changed."""
    #     if not self.charm.unit.is_leader() or not self.app_databag:
    #         return False
    #
    #     all_tests = self.get_all_test_metadata()
    #     if test_id not in all_tests:
    #         return False
    #
    #     current = all_tests[test_id]
    #     if not current.is_active:
    #         return False
    #
    #     all_tests[test_id] = BenchmarkMetadata(
    #         test_id=current.test_id,
    #         test_name=current.test_name,
    #         started_at=current.started_at,
    #         test_config=current.test_config,
    #         is_active=False,
    #     )
    #     self._write_all_tests(all_tests)
    #
    #     if self.current_test_id == test_id:
    #         self.set_current_test_id(None)
    #
    #     return True
    #
    # def ensure_initialized(self) -> None:
    #     """Initialize peer databag schema keys if absent."""
    #     if not self.charm.unit.is_leader() or not self.app_databag:
    #         return
    #
    #     self.app_databag.setdefault(PEER_TESTS_KEY, "{}")
    #     self.app_databag.setdefault(PEER_CURRENT_TEST_ID_KEY, "")
    #
    # def _write_all_tests(self, tests: dict[str, BenchmarkMetadata]) -> None:
    #     """Serialize all test metadata back to relation databag."""
    #     if not self.app_databag:
    #         return
    #
    #     payload = {test_id: metadata.to_dict() for test_id, metadata in tests.items()}
    #     self.app_databag[PEER_TESTS_KEY] = json.dumps(payload, sort_keys=True)
