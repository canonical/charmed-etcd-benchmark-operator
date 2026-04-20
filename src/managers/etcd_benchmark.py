#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manage the benchmarking activity."""

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import ops
from ops import Object

from core.models import BenchmarkMetadata
from literals import (
    BENCHMARK_TESTS_ROOT_DIR,
    CA_CERT_PATH,
    CLIENT_CERT_PATH,
    CLIENT_KEY_PATH,
    METADATA_JSON_FILE_NAME,
    RESULT_CSV_HEADERS,
    RESULTS_CSV_FILE_NAME,
)
from utils.utils import generate_test_id

if TYPE_CHECKING:
    from charm import CharmedEtcdBenchmarkOperatorCharm

logger = logging.getLogger(__name__)


class EtcdBenchmarkManager(Object):
    """Manager class for etcd benchmark activity."""

    def __init__(self, charm: "CharmedEtcdBenchmarkOperatorCharm"):
        super().__init__(charm, key="etcd-benchmark-manager")
        self.charm = charm

    def initiate_run(self, event: ops.ActionEvent):
        """Handle run action."""
        # Create unique test folder in the unit and create initial artifacts:
        # e.g: metadata file and a CSV in which to write benchmarking results.
        # Fire workload's start_service method, with charm configs, endpoints and CSV path.
        # Return success to console.

        uris = self.charm.etcd_interface_state.uris
        logger.debug(f"Endpoints available for txn-mixed: {uris}")

        started_at = datetime.now(UTC)
        test_id = generate_test_id(started_at)

        config = self.charm.config_manager.get_charm_config()

        if config.get("duration", 0) != 0 and config.get("total-transactions", 0) != 0:
            error_str = (
                "Both duration and total-transactions configs are set to non-zero values, which is invalid. "
                "Only ONE of the two can be specified. "
                "Please re-check, set valid config values and try again."
            )
            event.set_results({"error": error_str})
            event.fail(error_str)
            return

        results_csv_path = self._create_initial_test_artifacts(
            BenchmarkMetadata(
                test_name=str(self.charm.config.get("test-name")),
                test_id=test_id,
                started_at=started_at,
                test_config=config,
            )
        )

        config["current_test_id"] = test_id
        config["current_test_name"] = self.charm.config.get("test-name")
        config["results_csv_path"] = results_csv_path
        config["endpoints"] = uris
        config["client_cert_path"] = CLIENT_CERT_PATH
        config["client_key_path"] = CLIENT_KEY_PATH
        config["ca_cert_path"] = CA_CERT_PATH

        # TODO cleaner separation of concerns: have this manager only return config/throw error,
        # have the event handler set results
        self.charm.workload.start_service(f"{os.environ.get('CHARM_DIR', '')}/templates", config)

        event.set_results(
            {
                "results": (
                    "Benchmark started successfully.\n"
                    "If duration or total-transactions config options have been set, "
                    "test will auto terminate accordingly. "
                    "Alternatively, the `stop` action can be used."
                )
            }
        )

    def _create_initial_test_artifacts(self, benchmark_metadata: BenchmarkMetadata) -> str:
        """Create filesystem artifacts for a newly started benchmark.

        Returns:
             path to the created results CSV.
        """
        # This test's metadata: Create the test directory for this benchmark test
        test_dir = Path(BENCHMARK_TESTS_ROOT_DIR) / benchmark_metadata.test_id
        Path(str(test_dir)).mkdir(parents=True, exist_ok=True)

        self.charm.workload.write_file(
            file=Path(str(test_dir / METADATA_JSON_FILE_NAME)),
            content=json.dumps(benchmark_metadata.to_dict(), indent=2) + "\n",
        )
        self.charm.workload.write_file(
            file=Path(str(test_dir / RESULTS_CSV_FILE_NAME)),
            content=(",".join(RESULT_CSV_HEADERS)) + "\n",
        )
        return str(test_dir / RESULTS_CSV_FILE_NAME)
