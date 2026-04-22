#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Certificate-related utility functions."""

from charmlibs.interfaces.tls_certificates import Certificate


def get_common_name_from_chain(mtls_cert: str) -> str:
    """Get common name from chain."""
    raw_cas = [
        cert.strip() for cert in mtls_cert.split("-----END CERTIFICATE-----") if cert.strip()
    ]
    cert = raw_cas[0] + "\n-----END CERTIFICATE-----"
    return Certificate.from_string(cert).common_name
