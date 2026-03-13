# Copyright 2026 Canonical
# See LICENSE file for licensing details.
#
# The integration tests use the Jubilant library. See https://documentation.ubuntu.com/jubilant/
# To learn more about testing, see https://documentation.ubuntu.com/ops/latest/explanation/testing/

import logging
import pathlib

import jubilant
import pytest

from tests.integration.jubilant_helpers import apps_active_and_agents_idle

logger = logging.getLogger(__name__)

ETCD_APP_NAME = "charmed-etcd"
TLS_NAME = "self-signed-certificates"
CHARMED_ETCD_BENCHMARK_OPERATOR = "charmed-etcd-benchmark-operator";

def test_deploy(charm: pathlib.Path, juju_vm_model: jubilant.Juju):
    """Deploy the charm under test, and other charms necessary"""
    juju_vm_model.deploy(charm.resolve(), app=CHARMED_ETCD_BENCHMARK_OPERATOR)
    juju_vm_model.deploy(ETCD_APP_NAME, channel="3.6/edge", num_units=2)
    juju_vm_model.deploy(TLS_NAME, channel="1/edge")

    # enable TLS
    logger.info("Integrating peer-certificates and client-certificates relations")
    juju_vm_model.integrate(f"{ETCD_APP_NAME}:peer-certificates", TLS_NAME)
    juju_vm_model.integrate(f"{ETCD_APP_NAME}:client-certificates", TLS_NAME)
    juju_vm_model.integrate(CHARMED_ETCD_BENCHMARK_OPERATOR, TLS_NAME)
    juju_vm_model.wait(
        lambda status: apps_active_and_agents_idle(
            status, ETCD_APP_NAME, TLS_NAME, CHARMED_ETCD_BENCHMARK_OPERATOR, idle_period=10
        ),
        timeout=1200,
        successes=1,
    )
