#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for TLS-related managers."""

from unittest.mock import MagicMock, patch

from managers.tls import TLSManager


def _make_tls_manager():
    """Create a TLSManager with a mocked charm."""
    charm = MagicMock()
    charm.tls_state = MagicMock()
    charm.unit = MagicMock()
    return TLSManager(charm), charm


def test_client_requests_returns_expected_request_attributes():
    """client_requests should return one request with expected core fields."""
    tls_manager, charm = _make_tls_manager()
    charm.tls_state.common_name = "charmed-etcd-benchmark-operator0-1234abcd"
    charm.unit.name = "charmed-etcd-benchmark-operator/0"

    with (
        patch("managers.tls.socket.gethostname", return_value="test-host"),
        patch("managers.tls.socket.gethostbyname", return_value="10.1.2.3"),
    ):
        requests = tls_manager.client_requests

    assert len(requests) == 1
    request = requests[0]

    assert request.common_name == "charmed-etcd-benchmark-operator0-1234abcd"
    assert request.sans_ip is not None
    assert request.sans_dns is not None
    assert "10.1.2.3" in request.sans_ip
    assert "charmed-etcd-benchmark-operator/0" in request.sans_dns
    assert "test-host" in request.sans_dns
