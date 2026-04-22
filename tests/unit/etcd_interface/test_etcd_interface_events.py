#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for etcd interface related event handlers."""

from unittest.mock import ANY, MagicMock, patch

import pytest
from ops import testing

from charm import CharmedEtcdBenchmarkOperatorCharm
from literals import CA_CERT_PATH


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


def test_endpoints_changed_event_logs_error_if_no_endpoints(caplog):
    """endpoints_changed should log an error if no endpoint is available."""
    ctx = testing.Context(CharmedEtcdBenchmarkOperatorCharm)
    state_in = testing.State()

    with patch("workload.subprocess.run") as mock_run:
        mock_run.return_value.stdout = b"help output"

        with ctx(ctx.on.start(), state_in) as manager:
            charm = manager.charm
            event = MagicMock()
            event.response.endpoints = None

            with caplog.at_level("ERROR"):
                charm.etcd_interface_events._on_endpoints_changed(event)

    assert "No endpoints available" in caplog.text


def test_resource_created_event_returns_if_no_tls_ca(caplog):
    """resource_created should return early when no CA chain is provided."""
    ctx = testing.Context(CharmedEtcdBenchmarkOperatorCharm)
    state_in = testing.State()

    with patch("workload.subprocess.run") as mock_run:
        mock_run.return_value.stdout = b"help output"

        with ctx(ctx.on.start(), state_in) as manager:
            charm = manager.charm
            event = MagicMock()
            event.response.tls_ca = None
            event.response.username = "test-user"

            with patch.object(charm.workload, "write_file") as mock_write_file:
                with caplog.at_level("ERROR"):
                    charm.etcd_interface_events._on_resource_created(event)

                mock_write_file.assert_not_called()

    assert "No server CA chain available" in caplog.text


def test_resource_created_event_returns_if_no_username(caplog):
    """resource_created should return early when no username is provided."""
    ctx = testing.Context(CharmedEtcdBenchmarkOperatorCharm)
    state_in = testing.State()

    with patch("workload.subprocess.run") as mock_run:
        mock_run.return_value.stdout = b"help output"

        with ctx(ctx.on.start(), state_in) as manager:
            charm = manager.charm
            event = MagicMock()
            event.response.tls_ca = "CA DATA"
            event.response.username = None

            with patch.object(charm.workload, "write_file") as mock_write_file:
                with caplog.at_level("ERROR"):
                    charm.etcd_interface_events._on_resource_created(event)

                mock_write_file.assert_not_called()

    assert "No username available" in caplog.text


def test_resource_created_event_writes_ca_file():
    """resource_created should write the server CA chain to disk."""
    ctx = testing.Context(CharmedEtcdBenchmarkOperatorCharm)
    state_in = testing.State()

    with patch("workload.subprocess.run") as mock_run:
        mock_run.return_value.stdout = b"help output"

        with ctx(ctx.on.start(), state_in) as manager:
            charm = manager.charm
            event = MagicMock()
            event.response.tls_ca = "CA DATA"
            event.response.username = "test-user"

            with patch.object(charm.workload, "write_file") as mock_write_file:
                charm.etcd_interface_events._on_resource_created(event)

                mock_write_file.assert_called_once_with("CA DATA", CA_CERT_PATH)
