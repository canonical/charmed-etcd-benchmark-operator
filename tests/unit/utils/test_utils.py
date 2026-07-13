#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for certificate utility helpers."""

from datetime import datetime
from unittest.mock import patch

import pytest
from jinja2 import UndefinedError

from utils.utils import generate_test_id, get_common_name_from_chain, render_template


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

    with patch("utils.utils.Certificate.from_string") as mock_from_string:
        mock_from_string.return_value.common_name = "first-cert-cn"

        result = get_common_name_from_chain(chain)

    assert result == "first-cert-cn"
    mock_from_string.assert_called_once_with(
        "-----BEGIN CERTIFICATE-----\nFIRST CERT DATA\n-----END CERTIFICATE-----"
    )


def test_generate_test_id_formats_timestamp_and_suffix():
    """generate_test_id should format timestamp and use an 8-char UUID suffix."""
    started_at = datetime(2026, 4, 30, 9, 8, 7)

    with patch("utils.utils.uuid4") as mock_uuid4:
        mock_uuid4.return_value.hex = "abcdef1234567890"

        test_id = generate_test_id(started_at)

    assert test_id == "20260430T090807Z-abcdef12"


def test_render_template_renders_with_context(tmp_path):
    """render_template should interpolate provided context into the template."""
    template_path = tmp_path / "demo.j2"
    template_path.write_text("hello {{ name }}")

    rendered = render_template(template_path, {"name": "etcd"})

    assert rendered == "hello etcd"


def test_render_template_raises_when_context_is_missing_value(tmp_path):
    """render_template should fail when required variables are missing from context."""
    template_path = tmp_path / "demo.j2"
    template_path.write_text("hello {{ name }}")

    with pytest.raises(UndefinedError) as e:
        render_template(template_path, {})

    assert "name" in str(e.value)
