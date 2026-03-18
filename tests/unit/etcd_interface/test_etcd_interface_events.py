#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for etcd interface related event handlers."""

from unittest.mock import ANY, MagicMock, patch

import pytest
from ops import testing

from charm import CharmedEtcdBenchmarkOperatorCharm


@pytest.fixture(autouse=True)
def patch_snap_cache():
    """Patch SnapCache so the charm/workload can be constructed safely."""
    with patch("workload.snap.SnapCache") as mock_snap_cache:
        mock_snap = mock_snap_cache.return_value.__getitem__.return_value
        yield mock_snap


def test_etcd_interface_events_init_constructs_requirer_handler():
    """Charm construction should initialize ResourceRequirerEventHandler."""
    ctx = testing.Context(CharmedEtcdBenchmarkOperatorCharm)
    state_in = testing.State()

    with (
        patch("events.etcd_interface.ResourceRequirerEventHandler") as mock_handler,
        patch("ops.framework.Framework.observe") as mock_observe,
        patch("workload.subprocess.run") as mock_run,
    ):
        mock_run.return_value.stdout = b"help output"

        ctx.run(ctx.on.start(), state_in)

    mock_handler.assert_called_once_with(
        ANY,
        relation_name="etcd-client",
        requests=ANY,
        response_model=ANY,
    )

    mock_observe.assert_any_call(
        mock_handler.return_value.on.endpoints_changed,
        ANY,
    )
    mock_observe.assert_any_call(
        mock_handler.return_value.on.resource_created,
        ANY,
    )


def test_endpoints_changed_event_invokes_etcd_interface_manager():
    """endpoints_changed should delegate to EtcdInterfaceManager."""
    ctx = testing.Context(CharmedEtcdBenchmarkOperatorCharm)
    state_in = testing.State()

    with (
        patch("workload.subprocess.run") as mock_run,
        patch(
            "managers.etcd_interface.EtcdInterfaceManager.handle_endpoints_changed"
        ) as mock_handle,
    ):
        mock_run.return_value.stdout = b"help output"

        with ctx(ctx.on.start(), state_in) as manager:
            charm = manager.charm
            event = MagicMock()

            charm.etcd_interface_events._on_endpoints_changed(event)

    mock_handle.assert_called_once_with(event)


def test_resource_created_event_invokes_etcd_interface_manager():
    """resource_created should delegate to EtcdInterfaceManager."""
    ctx = testing.Context(CharmedEtcdBenchmarkOperatorCharm)
    state_in = testing.State()

    with (
        patch("workload.subprocess.run") as mock_run,
        patch(
            "managers.etcd_interface.EtcdInterfaceManager.handle_resource_created"
        ) as mock_handle,
    ):
        mock_run.return_value.stdout = b"help output"

        with ctx(ctx.on.start(), state_in) as manager:
            charm = manager.charm
            event = MagicMock()

            charm.etcd_interface_events._on_resource_created(event)

    mock_handle.assert_called_once_with(event)