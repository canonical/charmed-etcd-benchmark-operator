#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manage all config-adjacent activities."""

from typing import TYPE_CHECKING, Any

from ops import Object

if TYPE_CHECKING:
    from charm import CharmedEtcdBenchmarkOperatorCharm


class ConfigManager(Object):
    """Manager class for config."""

    def __init__(self, charm: "CharmedEtcdBenchmarkOperatorCharm"):
        super().__init__(charm, key="config_manager")
        self.charm = charm

    def get_charm_config(self) -> dict[str, Any]:
        """Render the systemd service file from current charm config."""
        config = self.charm.config

        return {
            "clients": config.get("clients"),
            "connections": config.get("connections"),
            "rate": config.get("rate"),
            "key_size": config.get("key-size"),
            "key_space_size": config.get("key-space-size"),
            "value_size": config.get("value-size"),
            "limit": config.get("limit"),
            "rw_ratio": config.get("rw-ratio"),
            "duration": config.get("duration"),
            "total_transactions": config.get("total-transactions"),
            "report_interval": config.get("report-interval"),
        }
