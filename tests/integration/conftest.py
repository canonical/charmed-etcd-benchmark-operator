# Copyright 2026 Canonical
# See LICENSE file for licensing details.
#
# The integration tests use the Jubilant library. See https://documentation.ubuntu.com/jubilant/
# To learn more about testing, see https://documentation.ubuntu.com/ops/latest/explanation/testing/

import json
import logging
from platform import machine

import jubilant
import pytest
from jubilant import Juju

CONCIERGE_MODEL_NAME = "testing"

logger = logging.getLogger(__name__)

@pytest.fixture(scope="package")
def arch() -> str:
    """Fixture to provide the platform architecture for testing."""
    platforms = {
        "x86_64": "amd64",
        "aarch64": "arm64",
    }
    return platforms.get(machine(), "amd64")


@pytest.fixture
def charm(arch: str) -> str:
    """Path to the charm file to use for testing."""
    return f"./charmed-etcd-benchmark-operator_{arch}.charm"


@pytest.fixture(scope="module")
def juju(arch: str):
    with jubilant.temp_model() as juju:
        juju.wait_timeout = 1000
        juju.cli("set-model-constraints", f"arch={arch}")
        yield juju


@pytest.fixture(scope="module")
def lxd_cloud(juju: Juju):
    clouds = json.loads(juju.cli("clouds", "--format", "json", include_model=False))
    for cloud, details in clouds.items():
        if "lxd" == details.get("type"):
            logger.info(f"Identified LXD cloud: {cloud}")
            yield cloud


@pytest.fixture(scope="module")
def lxd_controller(lxd_cloud: str, juju: Juju):
    controllers = json.loads(juju.cli("controllers", "--format", "json", include_model=False))
    for controller, details in controllers.get("controllers").items():
        if lxd_cloud == details.get("cloud"):
            logger.info(f"Identified LXD controller: {controller}")
            yield controller


@pytest.fixture(scope="module")
def juju_vm_model(arch: str, lxd_cloud: str, lxd_controller: str, juju: Juju):
    # if concierge model ("testing") is found, such as on CI, continue with this. Else setup temp model.
    models = json.loads(juju.cli("models", "--format", "json", include_model=False))

    for model in models["models"]:
        if CONCIERGE_MODEL_NAME == model["short-name"]:
            juju_lxd = jubilant.Juju(
                model=f"{lxd_controller}:{CONCIERGE_MODEL_NAME}", wait_timeout=1000
            )
            juju_lxd.cli("set-model-constraints", f"arch={arch}")
            yield juju_lxd
            return

    with jubilant.temp_model(cloud=lxd_cloud, controller=lxd_controller, keep=True) as juju_lxd:
        juju_lxd.wait_timeout = 1000
        juju_lxd.cli("set-model-constraints", f"arch={arch}")
        yield juju_lxd
