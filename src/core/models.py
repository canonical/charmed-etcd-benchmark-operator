#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Typed models for benchmark state and metadata."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class BenchmarkMetadata:
    """Immutable metadata describing a benchmark test."""

    test_id: str
    test_name: str
    started_at: datetime
    test_config: dict[str, Any] = field(default_factory=dict)
    is_active: bool = True

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
            is_active=bool(data.get("is_active", True)),
        )
