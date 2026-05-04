# Copyright 2026 Canonical
# See LICENSE file for licensing details.
#
# The integration tests use the Jubilant library. See https://documentation.ubuntu.com/jubilant/
# To learn more about testing, see https://documentation.ubuntu.com/ops/latest/explanation/testing/

"""A basic set of integration tests to verify charm functionality."""

import logging
import pathlib
from time import sleep

from helpers import apps_active_and_agents_idle
from jubilant import Juju

from literals import METRICS_PORT

logger = logging.getLogger(__name__)

ETCD_APP_NAME = "charmed-etcd"
TLS_NAME = "self-signed-certificates"
CHARMED_ETCD_BENCHMARK_OPERATOR = "charmed-etcd-benchmark-operator"


def test_deploy(benchmark_charm: pathlib.Path, juju_vm_model: Juju):
    """Deploy the charm under test, and other charms necessary."""
    juju_vm_model.deploy(benchmark_charm.resolve(), app=CHARMED_ETCD_BENCHMARK_OPERATOR)
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


def test_integrate_charms_and_trigger_run(juju_vm_model: Juju) -> None:
    """Test normal client charm relation."""
    juju_vm_model.integrate(CHARMED_ETCD_BENCHMARK_OPERATOR, ETCD_APP_NAME)
    juju_vm_model.wait(
        lambda status: apps_active_and_agents_idle(
            status, CHARMED_ETCD_BENCHMARK_OPERATOR, ETCD_APP_NAME, idle_period=10
        )
    )

    run_action = juju_vm_model.run(f"{CHARMED_ETCD_BENCHMARK_OPERATOR}/0", "run")
    assert run_action.status == "completed", "Action should succeed"
    assert "Benchmark started successfully." in str(run_action.results["results"])


def test_list_tests_action(juju_vm_model: Juju) -> None:
    """Test that list-tests action returns at least one completed test."""
    list_action = juju_vm_model.run(f"{CHARMED_ETCD_BENCHMARK_OPERATOR}/leader", "list-tests")

    assert list_action.status == "completed", "list-tests action should succeed"
    assert "tests" in list_action.results, "Result should contain 'tests' key"
    tests_output = list_action.results["tests"]
    assert tests_output, "Test output should exist"
    logger.info("list-tests output: %s", tests_output)

    output_lines = str(tests_output).strip().splitlines()
    assert len(output_lines) == 1, "There should be exactly one test listed"
    assert output_lines[0].split()[1] == "(in", "The test should be in progress"


def test_get_summary_action(juju_vm_model: Juju) -> None:
    """Test that get-summary action returns valid benchmark results for a listed test."""
    # First, wait for a minute for at least a few samples to be collected
    sleep(60)

    # Now, retrieve the list of tests to get a valid test ID
    test_id = _retrieve_test_id(juju_vm_model)

    summary_action = juju_vm_model.run(
        f"{CHARMED_ETCD_BENCHMARK_OPERATOR}/leader",
        "get-summary",
        params={"test-id": test_id},
    )
    assert summary_action.status == "completed", "get-summary action should succeed"
    assert "results" in summary_action.results, "Result should contain 'results' key"

    import json

    summary = json.loads(summary_action.results["results"])
    assert "metadata" in summary, "Summary should contain 'metadata'"
    assert "operations" in summary, "Summary should contain 'operations'"
    assert summary["metadata"]["test_id"] == test_id, (
        "test_id in summary should match requested ID"
    )
    assert summary["metadata"]["is_active"], "Tests should still be active"
    logger.info("get-summary output: %s", json.dumps(summary, indent=2))


def test_metrics_server(juju_vm_model: Juju) -> None:
    """Test that prometheus-friendly metrics are exposed at metrics port."""
    # TODO: add COS-lite integration tests here once COS integration is implemented.

    metrics = juju_vm_model.ssh(
        f"{CHARMED_ETCD_BENCHMARK_OPERATOR}/leader", f"curl http://localhost:{METRICS_PORT}"
    )
    logger.info(metrics)

    test_id = _retrieve_test_id(juju_vm_model)

    assert "# HELP etcd_benchmark_exporter_up Exporter health" in metrics
    assert "# TYPE etcd_benchmark_exporter_up gauge" in metrics
    assert f'etcd_benchmark_exporter_up{{test_id="{test_id}"}} 1.0' in metrics, (
        "Metrics exporter should be healthy"
    )
    assert f'etcd_benchmark_total_ops{{test_id="{test_id}",op_type="read"}}' in metrics
    assert f'etcd_benchmark_total_ops{{test_id="{test_id}",op_type="write"}}' in metrics
    assert (
        f'etcd_benchmark_average_latency_seconds{{test_id="{test_id}",op_type="read"}}' in metrics
    )
    assert (
        f'etcd_benchmark_average_latency_seconds{{test_id="{test_id}",op_type="write"}}' in metrics
    )
    assert (
        f'etcd_benchmark_stddev_latency_seconds{{test_id="{test_id}",op_type="read"}}' in metrics
    )
    assert (
        f'etcd_benchmark_stddev_latency_seconds{{test_id="{test_id}",op_type="write"}}' in metrics
    )
    assert f'etcd_benchmark_throughput_rps{{test_id="{test_id}",op_type="read"}}' in metrics
    assert f'etcd_benchmark_throughput_rps{{test_id="{test_id}",op_type="write"}}' in metrics


def test_stop_action(juju_vm_model: Juju) -> None:
    """Test that stop action terminates benchmark."""
    stop_action = juju_vm_model.run(f"{CHARMED_ETCD_BENCHMARK_OPERATOR}/leader", "stop")
    assert stop_action.status == "completed", "stop action should succeed"
    assert "Successfully signalled stop of current run." in str(stop_action.results["results"])

    sleep(10)

    test_id = _retrieve_test_id(juju_vm_model)

    summary_action = juju_vm_model.run(
        f"{CHARMED_ETCD_BENCHMARK_OPERATOR}/leader",
        "get-summary",
        params={"test-id": test_id},
    )
    assert summary_action.status == "completed", "get-summary action should succeed"
    assert "results" in summary_action.results, "Result should contain 'results' key"

    import json

    summary = json.loads(summary_action.results["results"])
    assert "metadata" in summary, "Summary should contain 'metadata'"
    assert "operations" in summary, "Summary should contain 'operations'"
    assert summary["metadata"]["test_id"] == test_id, (
        "test_id in summary should match requested ID"
    )
    assert not summary["metadata"]["is_active"], "Tests should still be active"
    logger.info("get-summary output after test completion: %s", json.dumps(summary, indent=2))


def _retrieve_test_id(juju_vm_model: Juju) -> str:
    # Now, retrieve the list of tests to get a valid test ID
    list_action = juju_vm_model.run(f"{CHARMED_ETCD_BENCHMARK_OPERATOR}/leader", "list-tests")
    assert list_action.status == "completed", "list-tests action should succeed"
    tests_output = list_action.results["tests"]
    assert tests_output, "There should be at least one test listed"

    # Parse the first test ID from the output
    first_line = str(tests_output).strip().splitlines()[0]
    # The test ID is the first whitespace-separated token; format "test-id (status)"
    test_id = first_line.split()[0]
    logger.info("Using test ID: %s", test_id)
    return test_id
