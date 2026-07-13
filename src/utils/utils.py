#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Utility functions."""

from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from charmlibs.interfaces.tls_certificates import Certificate
from jinja2 import Environment, FileSystemLoader, StrictUndefined


def get_common_name_from_chain(mtls_cert: str) -> str:
    """Get common name from cert chain."""
    raw_cas = [
        cert.strip() for cert in mtls_cert.split("-----END CERTIFICATE-----") if cert.strip()
    ]
    cert = raw_cas[0] + "\n-----END CERTIFICATE-----"
    return Certificate.from_string(cert).common_name


def generate_test_id(started_at: datetime) -> str:
    """Generate a unique, filesystem-safe test identifier for a benchmark run."""
    timestamp = started_at.strftime("%Y%m%dT%H%M%SZ")
    suffix = uuid4().hex[:8]
    return f"{timestamp}-{suffix}"


def render_template(template_file_path: Path, context: dict[str, Any]) -> str:
    """Render a Jinja2 template from the charm templates directory."""
    env = Environment(
        loader=FileSystemLoader(str(template_file_path.parent)),
        undefined=StrictUndefined,
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template(template_file_path.name)
    return template.render(**context)
