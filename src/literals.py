#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Collection of global literals for the etcd benchmark charm."""

SNAP_NAME = "charmed-etcd"
SNAP_CHANNEL = "3.6/edge"
TLS_ROOT_DIR = "/var/snap/charmed-etcd/current/tls"
CLIENT_CERT_PATH = f"{TLS_ROOT_DIR}/client.pem"
CLIENT_KEY_PATH = f"{TLS_ROOT_DIR}/client.key"
CA_CERT_PATH = f"{TLS_ROOT_DIR}/ca.pem"
