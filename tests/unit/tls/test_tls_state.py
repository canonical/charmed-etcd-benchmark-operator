#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for TLS-related state."""

from unittest.mock import MagicMock, patch

from core.tls import TLSState
from literals import CLIENT_CERT_PATH


def test_common_name_builds_expected_value():
    """common_name should be derived from unit name and first UUID segment."""
    charm = MagicMock()
    charm.unit.name = "charmed-etcd-benchmark-operator/0"
    charm.model.uuid = "12345678-abcd-efgh-ijkl-1234567890ab"

    tls_state = TLSState(charm)

    assert tls_state.common_name == "charmed-etcd-benchmark-operator0-12345678"


def test_assigned_certificates_returns_values_when_present():
    """assigned_certificates should return certs and key when available."""
    charm = MagicMock()
    certs = [MagicMock()]
    private_key = MagicMock()
    charm.tls_events.certificates.get_assigned_certificates.return_value = (certs, private_key)

    tls_state = TLSState(charm)

    result_certs, result_key = tls_state.assigned_certificates

    assert result_certs == certs
    assert result_key == private_key


def test_assigned_certificates_returns_none_tuple_when_missing():
    """assigned_certificates should normalize missing values to (None, None)."""
    charm = MagicMock()
    charm.tls_events.certificates.get_assigned_certificates.return_value = ([], None)

    tls_state = TLSState(charm)

    result_certs, result_key = tls_state.assigned_certificates

    assert result_certs is None
    assert result_key is None


def test_stored_certificate_raw_reads_file_from_workload():
    """stored_certificate_raw should read the stored client certificate from disk."""
    charm = MagicMock()
    charm.workload.read_file.return_value = "RAW CERT"

    tls_state = TLSState(charm)

    result = tls_state.stored_certificate_raw

    assert result == "RAW CERT"
    charm.workload.read_file.assert_called_once_with(CLIENT_CERT_PATH)


def test_get_stored_certificate_of_common_name_returns_none_if_missing():
    """get_stored_certificate_of_common_name should return None if no cert file exists."""
    charm = MagicMock()
    charm.workload.read_file.return_value = None

    tls_state = TLSState(charm)

    result = tls_state.get_stored_certificate_of_common_name("expected-cn")

    assert result is None
    charm.workload.read_file.assert_called_once_with(CLIENT_CERT_PATH)


def test_get_stored_certificate_of_common_name_returns_cert_if_cn_matches():
    """get_stored_certificate_of_common_name should return raw cert if CN matches."""
    raw_cert = "RAW CERT"

    charm = MagicMock()
    charm.workload.read_file.return_value = raw_cert

    tls_state = TLSState(charm)

    with patch("core.tls.Certificate") as mock_certificate:
        mock_certificate.return_value.common_name = "expected-cn"

        result = tls_state.get_stored_certificate_of_common_name("expected-cn")

    assert result == raw_cert
    mock_certificate.assert_called_once_with(raw=raw_cert)


def test_get_stored_certificate_of_common_name_returns_none_if_cn_mismatch():
    """get_stored_certificate_of_common_name should return None if CN does not match."""
    raw_cert = "RAW CERT"

    charm = MagicMock()
    charm.workload.read_file.return_value = raw_cert

    tls_state = TLSState(charm)

    with patch("core.tls.Certificate") as mock_certificate:
        mock_certificate.return_value.common_name = "different-cn"

        result = tls_state.get_stored_certificate_of_common_name("expected-cn")

    assert result is None
    mock_certificate.assert_called_once_with(raw=raw_cert)
