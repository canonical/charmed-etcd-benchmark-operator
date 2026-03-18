#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for certificate utility helpers."""

from unittest.mock import patch

from utils.certificates import get_common_name_from_chain


def test_get_common_name_from_chain_uses_first_certificate_only():
    """get_common_name_from_chain should parse the first cert in the chain."""
    chain = (
        "-----BEGIN CERTIFICATE-----\n"
        "FIRST CERT DATA\n"
        "-----END CERTIFICATE-----\n"
        "-----BEGIN CERTIFICATE-----\n"
        "SECOND CERT DATA\n"
        "-----END CERTIFICATE-----\n"
    )

    with patch("utils.certificates.Certificate.from_string") as mock_from_string:
        mock_from_string.return_value.common_name = "first-cert-cn"

        result = get_common_name_from_chain(chain)

    assert result == "first-cert-cn"
    mock_from_string.assert_called_once_with(
        "-----BEGIN CERTIFICATE-----\nFIRST CERT DATA\n-----END CERTIFICATE-----"
    )
