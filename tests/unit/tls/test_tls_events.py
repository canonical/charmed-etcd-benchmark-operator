#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for TLS-related event handlers."""

from unittest.mock import ANY, MagicMock, patch

import ops
import pytest
from ops import testing

from charm import CharmedEtcdBenchmarkOperatorCharm
from literals import CLIENT_CERT_PATH, CLIENT_KEY_PATH


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


def test_certificate_available_returns_if_no_assigned_certificates():
    """certificate_available should return early if no assigned certificates exist."""
    ctx = testing.Context(CharmedEtcdBenchmarkOperatorCharm)
    state_in = testing.State()

    with (
        patch("events.tls.socket.gethostname", return_value="test-host"),
        patch("events.tls.socket.gethostbyname", return_value="10.1.2.3"),
        patch("workload.subprocess.run") as mock_run,
    ):
        mock_run.return_value.stdout = b"help output"

        with ctx(ctx.on.start(), state_in) as manager:
            charm = manager.charm
            event = MagicMock()
            with (
                patch.object(charm.workload, "write_file") as mock_write_file,
                patch.object(
                    charm.etcd_interface_manager, "update_request_from_cert"
                ) as mock_update_request,
                patch.object(
                    charm.tls_events.certificates,
                    "get_assigned_certificates",
                    return_value=(None, None),
                ),
            ):
                charm.tls_events._on_certificate_available(event)

            mock_write_file.assert_not_called()
            mock_update_request.assert_not_called()


def test_certificate_available_returns_if_certificate_mismatch():
    """certificate_available should ignore events for non-assigned certificates."""
    ctx = testing.Context(CharmedEtcdBenchmarkOperatorCharm)
    state_in = testing.State()

    with (
        patch("events.tls.socket.gethostname", return_value="test-host"),
        patch("events.tls.socket.gethostbyname", return_value="10.1.2.3"),
        patch("workload.subprocess.run") as mock_run,
    ):
        mock_run.return_value.stdout = b"help output"

        with ctx(ctx.on.start(), state_in) as manager:
            charm = manager.charm
            event = MagicMock()

            assigned_certificate = MagicMock(name="assigned_certificate")
            event_certificate = MagicMock(name="event_certificate")

            cert = MagicMock()
            cert.certificate = assigned_certificate

            private_key = MagicMock()

            event.certificate = event_certificate

            with (
                patch.object(charm.workload, "write_file") as mock_write_file,
                patch.object(
                    charm.etcd_interface_manager, "update_request_from_cert"
                ) as mock_update_request,
                patch.object(
                    charm.tls_events.certificates,
                    "get_assigned_certificates",
                    return_value=([cert], private_key),
                ),
            ):
                charm.tls_events._on_certificate_available(event)

            mock_write_file.assert_not_called()
            mock_update_request.assert_not_called()


def test_certificate_available_writes_cert_and_key_and_updates_request():
    """certificate_available should write cert/key and update etcd request."""
    ctx = testing.Context(CharmedEtcdBenchmarkOperatorCharm)
    state_in = testing.State()

    with (
        patch("events.tls.socket.gethostname", return_value="test-host"),
        patch("events.tls.socket.gethostbyname", return_value="10.1.2.3"),
        patch("workload.subprocess.run") as mock_run,
    ):
        mock_run.return_value.stdout = b"help output"

        with ctx(ctx.on.start(), state_in) as manager:
            charm = manager.charm
            event = MagicMock()

            certificate = MagicMock()
            certificate.raw = "CERT DATA"

            cert = MagicMock()
            cert.certificate = certificate

            private_key = MagicMock()
            private_key.raw = "KEY DATA"

            event.certificate = certificate

            with (
                patch.object(charm.workload, "write_file") as mock_write_file,
                patch.object(
                    charm.etcd_interface_manager, "update_request_from_cert"
                ) as mock_update_request,
                patch.object(
                    charm.tls_events.certificates,
                    "get_assigned_certificates",
                    return_value=([cert], private_key),
                ),
            ):
                charm.tls_events._on_certificate_available(event)

            mock_write_file.assert_any_call("CERT DATA", CLIENT_CERT_PATH)
            mock_write_file.assert_any_call("KEY DATA", CLIENT_KEY_PATH)
            assert mock_write_file.call_count == 2

            mock_update_request.assert_called_once_with(certificate)


def test_certificate_available_sets_blocked_status_if_write_fails():
    """certificate_available should block the unit if writing TLS files fails."""
    ctx = testing.Context(CharmedEtcdBenchmarkOperatorCharm)
    state_in = testing.State()

    with (
        patch("events.tls.socket.gethostname", return_value="test-host"),
        patch("events.tls.socket.gethostbyname", return_value="10.1.2.3"),
        patch("workload.subprocess.run") as mock_run,
    ):
        mock_run.return_value.stdout = b"help output"

        with ctx(ctx.on.start(), state_in) as manager:
            charm = manager.charm
            event = MagicMock()

            certificate = MagicMock()
            certificate.raw = "CERT DATA"

            cert = MagicMock()
            cert.certificate = certificate

            private_key = MagicMock()
            private_key.raw = "KEY DATA"

            event.certificate = certificate
            with (
                patch.object(charm.workload, "write_file") as mock_write_file,
                patch.object(
                    charm.etcd_interface_manager, "update_request_from_cert"
                ) as mock_update_request,
                patch.object(
                    charm.tls_events.certificates,
                    "get_assigned_certificates",
                    return_value=([cert], private_key),
                ),
            ):
                mock_write_file.side_effect = OSError("disk full")
                charm.tls_events._on_certificate_available(event)

            assert charm.unit.status == ops.BlockedStatus("Error writing TLS certificates to disk")
            mock_update_request.assert_not_called()
