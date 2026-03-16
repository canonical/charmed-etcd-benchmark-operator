# Copyright 2026 Canonical
# See LICENSE file for licensing details.
#
# The integration tests use the Jubilant library. See https://documentation.ubuntu.com/jubilant/
# To learn more about testing, see https://documentation.ubuntu.com/ops/latest/explanation/testing/

"""A basic set of integration tests to verify charm functionality."""

import logging
import pathlib

from helpers import apps_active_and_agents_idle
from jubilant import Juju

logger = logging.getLogger(__name__)

ETCD_APP_NAME = "charmed-etcd"
TLS_NAME = "self-signed-certificates"
CHARMED_ETCD_BENCHMARK_OPERATOR = "charmed-etcd-benchmark-operator"


def test_deploy(benchmark_charm: pathlib.Path, etcd_charm: pathlib.Path, juju_vm_model: Juju):
    """Deploy the charm under test, and other charms necessary."""
    juju_vm_model.deploy(benchmark_charm.resolve(), app=CHARMED_ETCD_BENCHMARK_OPERATOR)
    juju_vm_model.deploy(etcd_charm, app=ETCD_APP_NAME, num_units=2)
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


def test_integrate_benchmark_and_etcd_charms(juju_vm_model: Juju) -> None:
    """Test normal client charm relation."""
    juju_vm_model.integrate(CHARMED_ETCD_BENCHMARK_OPERATOR, ETCD_APP_NAME)
    juju_vm_model.wait(
        lambda status: apps_active_and_agents_idle(
            status, CHARMED_ETCD_BENCHMARK_OPERATOR, ETCD_APP_NAME, idle_period=10
        )
    )

    run_action = juju_vm_model.run(f"{CHARMED_ETCD_BENCHMARK_OPERATOR}/0", "run")
    assert run_action.status == "completed", "Action should succeed"
    logger.info(f"Results of run: {run_action.results}")
