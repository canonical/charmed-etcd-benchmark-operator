#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for TLS-related managers."""

from unittest.mock import MagicMock

import ops

from literals import CLIENT_CERT_PATH, CLIENT_KEY_PATH
from managers.tls import TLSManager


def _make_tls_manager():
    """Create a TLSManager with a mocked charm."""
    charm = MagicMock()
    charm.workload = MagicMock()
    charm.tls_state = MagicMock()
    charm.etcd_interface_manager = MagicMock()
    charm.unit = MagicMock()
    return TLSManager(charm), charm


def test_handle_certificate_available_returns_if_no_assigned_certificates():
    """handle_certificate_available should return early if no assigned certificates exist."""
    tls_manager, charm = _make_tls_manager()
    event = MagicMock()

    charm.tls_state.assigned_certificates = (None, None)

    tls_manager.handle_certificate_available(event)

    charm.workload.write_file.assert_not_called()
    charm.etcd_interface_manager.update_request_from_cert.assert_not_called()


def test_handle_certificate_available_returns_if_certificate_mismatch():
    """handle_certificate_available should ignore events for non-assigned certificates."""
    tls_manager, charm = _make_tls_manager()
    event = MagicMock()

    assigned_certificate = MagicMock(name="assigned_certificate")
    event_certificate = MagicMock(name="event_certificate")

    cert = MagicMock()
    cert.certificate = assigned_certificate

    private_key = MagicMock()
    charm.tls_state.assigned_certificates = ([cert], private_key)

    event.certificate = event_certificate

    tls_manager.handle_certificate_available(event)

    charm.workload.write_file.assert_not_called()
    charm.etcd_interface_manager.update_request_from_cert.assert_not_called()


def test_handle_certificate_available_writes_cert_and_key_and_updates_request():
    """handle_certificate_available should write cert/key and update etcd request."""
    tls_manager, charm = _make_tls_manager()
    event = MagicMock()

    certificate = MagicMock()
    certificate.raw = "CERT DATA"

    cert = MagicMock()
    cert.certificate = certificate

    private_key = MagicMock()
    private_key.raw = "KEY DATA"

    charm.tls_state.assigned_certificates = ([cert], private_key)
    event.certificate = certificate

    tls_manager.handle_certificate_available(event)

    charm.workload.write_file.assert_any_call("CERT DATA", CLIENT_CERT_PATH)
    charm.workload.write_file.assert_any_call("KEY DATA", CLIENT_KEY_PATH)
    assert charm.workload.write_file.call_count == 2

    charm.etcd_interface_manager.update_request_from_cert.assert_called_once_with(certificate)


def test_handle_certificate_available_sets_blocked_status_if_write_fails():
    """handle_certificate_available should block the unit if writing TLS files fails."""
    tls_manager, charm = _make_tls_manager()
    event = MagicMock()

    certificate = MagicMock()
    certificate.raw = "CERT DATA"

    cert = MagicMock()
    cert.certificate = certificate

    private_key = MagicMock()
    private_key.raw = "KEY DATA"

    charm.tls_state.assigned_certificates = ([cert], private_key)
    event.certificate = certificate

    charm.workload.write_file.side_effect = OSError("disk full")

    tls_manager.handle_certificate_available(event)

    assert charm.unit.status == ops.BlockedStatus("Error writing TLS certificates to disk")
    charm.etcd_interface_manager.update_request_from_cert.assert_not_called()
