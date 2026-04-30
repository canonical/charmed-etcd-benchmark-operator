#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for config related manager."""

from unittest.mock import MagicMock

from managers.config import ConfigManager


def _make_config_manager(config: dict | None = None):
    """Create a ConfigManager with a mocked charm and config."""
    charm = MagicMock()
    charm.config = config or {}
    return ConfigManager(charm), charm


def test_get_charm_config_maps_all_expected_keys():
    """get_charm_config should map charm options to runner config keys."""
    config_manager, _ = _make_config_manager(
        {
            "clients": 10,
            "connections": 20,
            "rate": 30,
            "key-size": 40,
            "key-space-size": 50,
            "value-size": 60,
            "limit": 70,
            "rw-ratio": 2.5,
            "duration": 80,
            "total-transactions": 90,
            "report-interval": 15,
            "test-name": "ignored",
        }
    )

    assert config_manager.get_charm_config() == {
        "clients": 10,
        "connections": 20,
        "rate": 30,
        "key_size": 40,
        "key_space_size": 50,
        "value_size": 60,
        "limit": 70,
        "rw_ratio": 2.5,
        "duration": 80,
        "total_transactions": 90,
        "report_interval": 15,
    }


def test_get_charm_config_returns_none_for_missing_options():
    """get_charm_config should default missing options to None."""
    config_manager, _ = _make_config_manager({"clients": 3, "rw-ratio": 1.0})

    assert config_manager.get_charm_config() == {
        "clients": 3,
        "connections": None,
        "rate": None,
        "key_size": None,
        "key_space_size": None,
        "value_size": None,
        "limit": None,
        "rw_ratio": 1.0,
        "duration": None,
        "total_transactions": None,
        "report_interval": None,
    }
