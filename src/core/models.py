#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Typed models for benchmark state and metadata."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, final

from charms.data_platform_libs.v1.data_interfaces import OpsPeerRepositoryInterface, PeerModel
from ops import Application, Relation
from pydantic import Field

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BenchmarkMetadata:
    """Immutable metadata describing a benchmark test."""

    test_id: str
    test_name: str
    started_at: datetime
    test_config: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert model to a JSON-serializable dict."""
        data = asdict(self)
        data["started_at"] = self.started_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BenchmarkMetadata":
        """Create model from a dict."""
        raw_test_config = data.get("test_config", {})
        test_config: dict[str, Any] = {}

        if isinstance(raw_test_config, dict):
            test_config = {str(key): value for key, value in raw_test_config.items()}

        return cls(
            test_id=data["test_id"],
            test_name=data["test_name"],
            started_at=datetime.fromisoformat(data["started_at"]),
            test_config=test_config,
        )


class PeerAppModel(PeerModel):
    """Model for the peer application data."""

    current_test_id: str | None = Field(default=None)
    current_test_name: str | None = Field(default=None)
    current_test_started_at: str | None = Field(default=None)
    current_test_config: dict[str, Any] | None = Field(default=None)


class RelationState:
    """Relation state object."""

    def __init__(
        self,
        relation: Relation | None,
        data_interface: OpsPeerRepositoryInterface[PeerAppModel],
        component: Application,
    ):
        self.relation = relation
        self.data_interface = data_interface
        self.component = component

    def update(self, items: dict[str, Any]) -> None:
        """Write to relation data."""
        if not self.relation:
            logger.warning(
                f"Fields {list(items.keys())} were attempted to be written on the relation "
                f"before it exists."
            )
            return

        delete_fields = [key for key in items if not items[key]]
        update_content = {k: items[k] for k in items if k not in delete_fields}

        model = self.data_interface.build_model(self.relation.id)
        for field_name, value in update_content.items():
            setattr(model, field_name.replace("-", "_"), value)

        for field_name in delete_fields:
            setattr(model, field_name.replace("-", "_"), None)

        self.data_interface.write_model(self.relation.id, model)


@final
class EtcdBenchmarkCluster(RelationState):
    """Model representing the etcd benchmark cluster state."""

    def __init__(
        self,
        relation: Relation | None,
        data_interface: OpsPeerRepositoryInterface[PeerAppModel],
        component: Application,
    ):
        super().__init__(relation, data_interface, component)

    @property
    def model(self) -> PeerAppModel | None:
        """The peer relation model for this application."""
        return self.data_interface.build_model(self.relation.id) if self.relation else None

    @property
    def is_test_active(self) -> bool:
        """Whether there is an active test in peer relation state."""
        return self.model.current_test_id is not None if self.model else False

    @property
    def current_test_id(self) -> str | None:
        """Return the current test id from peer relation state."""
        return self.model.current_test_id if self.model else None

    @property
    def current_test_name(self) -> str | None:
        """Return the current test name from peer relation state."""
        return self.model.current_test_name if self.model else None

    @property
    def current_test_started_at(self) -> datetime | None:
        """Return current test start time parsed from peer relation state."""
        return (
            datetime.fromisoformat(self.model.current_test_started_at)
            if self.model and self.model.current_test_started_at
            else None
        )

    @property
    def current_test_config(self) -> dict[str, Any] | None:
        """Return the current test configuration from peer relation state."""
        return self.model.current_test_config if self.model else None

    def clear_current_test_metadata(self) -> None:
        """Clear current test fields from peer relation state."""
        self.update(
            {
                "current_test_id": None,
                "current_test_name": None,
                "current_test_started_at": None,
                "current_test_config": None,
            }
        )
