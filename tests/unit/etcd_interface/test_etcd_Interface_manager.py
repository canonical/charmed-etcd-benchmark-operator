#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for etcd interface related managers."""

from unittest.mock import MagicMock, patch

from managers.etcd_interface import EtcdInterfaceManager


def _make_etcd_interface_manager():
    """Create an EtcdInterfaceManager with a mocked charm."""
    charm = MagicMock()
    charm.tls_state = MagicMock()
    charm.etcd_interface_state = MagicMock()
    return EtcdInterfaceManager(charm), charm


def test_client_requests_returns_request_with_stored_cert():
    """client_requests should include the stored certificate."""
    etcd_interface_manager, charm = _make_etcd_interface_manager()

    charm.tls_state.common_name = "test-common-name"
    charm.tls_state.get_stored_certificate_of_common_name.return_value = "CERT DATA"

    requests = etcd_interface_manager.client_requests

    assert len(requests) == 1
    assert requests[0].resource == ""
    assert requests[0].mtls_cert == "CERT DATA"
    charm.tls_state.get_stored_certificate_of_common_name.assert_called_once_with(
        "test-common-name"
    )


def test_client_requests_returns_empty_cert_if_no_stored_cert():
    """client_requests should use empty string when no stored certificate exists."""
    etcd_interface_manager, charm = _make_etcd_interface_manager()

    charm.tls_state.common_name = "test-common-name"
    charm.tls_state.get_stored_certificate_of_common_name.return_value = None

    requests = etcd_interface_manager.client_requests

    assert len(requests) == 1
    assert requests[0].resource == ""
    assert requests[0].mtls_cert == ""


def test_update_request_from_cert_returns_if_no_local_model():
    """update_request_from_cert should return early if no local model exists."""
    etcd_interface_manager, charm = _make_etcd_interface_manager()
    cert = MagicMock()

    charm.etcd_interface_state.local_model = None

    etcd_interface_manager.update_request_from_cert(cert)

    charm.etcd_interface_state.write_local_model.assert_not_called()


def test_update_request_from_cert_updates_existing_request():
    """update_request_from_cert should update an existing matching request."""
    etcd_interface_manager, charm = _make_etcd_interface_manager()

    cert = MagicMock()
    cert.common_name = "test-common-name"
    cert.raw = "NEW CERT DATA"

    existing_request = MagicMock()
    existing_request.mtls_cert = "OLD CERT DATA"

    local_model = MagicMock()
    local_model.requests = [existing_request]

    charm.etcd_interface_state.local_model = local_model

    with patch(
        "managers.etcd_interface.get_common_name_from_chain", return_value="test-common-name"
    ):
        etcd_interface_manager.update_request_from_cert(cert)

    assert existing_request.mtls_cert == "NEW CERT DATA"
    assert local_model.requests == [existing_request]
    charm.etcd_interface_state.write_local_model.assert_called_once_with(local_model)


def test_update_request_from_cert_creates_new_request_when_no_match():
    """update_request_from_cert should create a new request if no matching request exists."""
    etcd_interface_manager, charm = _make_etcd_interface_manager()

    cert = MagicMock()
    cert.common_name = "test-common-name"
    cert.raw = "NEW CERT DATA"

    local_model = MagicMock()
    local_model.requests = []

    charm.etcd_interface_state.local_model = local_model

    etcd_interface_manager.update_request_from_cert(cert)

    assert len(local_model.requests) == 1
    assert local_model.requests[0].resource == "/test-common-name/"
    assert local_model.requests[0].mtls_cert == "NEW CERT DATA"
    charm.etcd_interface_state.write_local_model.assert_called_once_with(local_model)
