#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for TLS-related event handlers."""

from unittest.mock import ANY, patch, MagicMock

import pytest
from ops import testing

from charm import CharmedEtcdBenchmarkOperatorCharm


@pytest.fixture(autouse=True)
def patch_snap_cache():
    """Patch SnapCache so the charm/workload can be constructed safely."""
    with patch("workload.snap.SnapCache") as mock_snap_cache:
        mock_snap = mock_snap_cache.return_value.__getitem__.return_value
        yield mock_snap


def test_tls_events_init_constructs_tls_requires():
    """Charm construction should initialize TLSCertificatesRequiresV4."""
    ctx = testing.Context(CharmedEtcdBenchmarkOperatorCharm)
    state_in = testing.State()

    with (
        patch("events.tls.TLSCertificatesRequiresV4") as mock_tls_requires,
        patch("events.tls.socket.gethostname", return_value="test-host"),
        patch("events.tls.socket.gethostbyname", return_value="10.1.2.3"),
        patch("ops.framework.Framework.observe") as mock_observe,
        patch("workload.subprocess.run") as mock_run,
    ):
        mock_run.return_value.stdout = b"help output"

        ctx.run(ctx.on.start(), state_in)

    mock_tls_requires.assert_called_once()

    args, kwargs = mock_tls_requires.call_args
    assert args[1] == "certificates"

    assert "certificate_requests" in kwargs
    assert len(kwargs["certificate_requests"]) == 1

    request = kwargs["certificate_requests"][0]
    assert request.common_name.startswith("charmed-etcd-benchmark-operator0-")
    assert request.sans_ip == frozenset({"10.1.2.3"})
    assert request.sans_dns == frozenset({"charmed-etcd-benchmark-operator/0", "test-host"})

    assert "refresh_events" in kwargs
    assert len(kwargs["refresh_events"]) == 1

    mock_observe.assert_any_call(
        mock_tls_requires.return_value.on.certificate_available,
        ANY,
    )

def test_certificate_available_invokes_tls_manager():
    """certificate_available should delegate to TLSManager."""
    ctx = testing.Context(CharmedEtcdBenchmarkOperatorCharm)
    state_in = testing.State()

    with (
        patch("events.tls.socket.gethostname", return_value="test-host"),
        patch("events.tls.socket.gethostbyname", return_value="10.1.2.3"),
        patch("workload.subprocess.run") as mock_run,
        patch("managers.tls.TLSManager.handle_certificate_available") as mock_handle,
    ):
        mock_run.return_value.stdout = b"help output"

        with ctx(ctx.on.start(), state_in) as manager:
            charm = manager.charm
            event = MagicMock()

            charm.tls_events._on_certificate_available(event)

    mock_handle.assert_called_once_with(event)