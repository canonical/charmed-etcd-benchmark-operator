#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for etcd interface related state wrappers."""

from unittest.mock import MagicMock, patch

from core.interfaces import EtcdInterfaceState


def _make_etcd_interface_state():
    """Create an EtcdInterfaceState with a mocked charm."""
    charm = MagicMock()
    charm.etcd_interface_events = MagicMock()
    return EtcdInterfaceState(charm), charm


def test_relation_returns_none_if_etcd_interface_missing():
    """relation should return None if the etcd interface handler is unavailable."""
    etcd_interface_state, charm = _make_etcd_interface_state()

    del charm.etcd_interface_events.etcd_interface

    assert etcd_interface_state.relation is None


def test_relation_returns_none_if_no_relations():
    """relation should return None if no relations are present."""
    etcd_interface_state, charm = _make_etcd_interface_state()

    charm.etcd_interface_events.etcd_interface.relations = []

    assert etcd_interface_state.relation is None


def test_relation_returns_first_relation():
    """relation should return the first etcd-client relation."""
    etcd_interface_state, charm = _make_etcd_interface_state()

    relation = MagicMock()
    charm.etcd_interface_events.etcd_interface.relations = [relation]

    assert etcd_interface_state.relation is relation


def test_local_model_returns_none_if_no_relation():
    """local_model should return None if no relation is available."""
    etcd_interface_state, charm = _make_etcd_interface_state()

    charm.etcd_interface_events.etcd_interface.relations = []

    assert etcd_interface_state.local_model is None


def test_local_model_builds_local_requirer_model():
    """local_model should build the local requirer data contract."""
    etcd_interface_state, charm = _make_etcd_interface_state()

    relation = MagicMock()
    relation.id = 1
    charm.etcd_interface_events.etcd_interface.relations = [relation]

    repository_data = {"requests": []}
    charm.etcd_interface_events.etcd_interface.interface.repository.return_value = repository_data

    built_model = MagicMock()

    with patch("core.interfaces.build_model", return_value=built_model) as mock_build_model:
        result = etcd_interface_state.local_model

    charm.etcd_interface_events.etcd_interface.interface.repository.assert_called_once_with(1)
    mock_build_model.assert_called_once()
    assert result is built_model


def test_remote_responses_returns_none_if_no_relation(caplog):
    """remote_responses should return None if no relation is available."""
    etcd_interface_state, charm = _make_etcd_interface_state()

    charm.etcd_interface_events.etcd_interface.relations = []

    with caplog.at_level("WARNING"):
        result = etcd_interface_state.remote_responses

    assert result is None
    assert "Relation isn't available yet" in caplog.text


def test_remote_responses_returns_provider_requests():
    """remote_responses should return remote provider responses."""
    etcd_interface_state, charm = _make_etcd_interface_state()

    relation = MagicMock()
    relation.id = 1
    relation.app = MagicMock()
    charm.etcd_interface_events.etcd_interface.relations = [relation]

    repository_data = {"requests": []}
    charm.etcd_interface_events.etcd_interface.interface.repository.return_value = repository_data

    built_model = MagicMock()
    built_model.requests = ["response-1"]

    with patch("core.interfaces.build_model", return_value=built_model) as mock_build_model:
        result = etcd_interface_state.remote_responses

    charm.etcd_interface_events.etcd_interface.interface.repository.assert_called_once_with(
        1, relation.app
    )
    mock_build_model.assert_called_once()
    assert result == ["response-1"]


def test_uris_returns_none_if_no_remote_responses():
    """uris should return None if no remote responses are available."""
    etcd_interface_state, charm = _make_etcd_interface_state()

    charm.etcd_interface_events.etcd_interface.relations = []

    assert etcd_interface_state.uris is None


def test_uris_returns_first_remote_response_uri():
    """uris should return the URI from the first remote response."""
    etcd_interface_state, charm = _make_etcd_interface_state()

    relation = MagicMock()
    relation.id = 1
    relation.app = MagicMock()
    charm.etcd_interface_events.etcd_interface.relations = [relation]

    repository_data = {"requests": []}
    charm.etcd_interface_events.etcd_interface.interface.repository.return_value = repository_data

    response = MagicMock()
    response.uris = "https://10.1.2.3:2379"

    built_model = MagicMock()
    built_model.requests = [response]

    with patch("core.interfaces.build_model", return_value=built_model):
        assert etcd_interface_state.uris == "https://10.1.2.3:2379"


def test_write_local_model_returns_if_no_relation():
    """write_local_model should return early if no relation is available."""
    etcd_interface_state, charm = _make_etcd_interface_state()
    model = MagicMock()

    charm.etcd_interface_events.etcd_interface.relations = []

    etcd_interface_state.write_local_model(model)

    charm.etcd_interface_events.etcd_interface.interface.write_model.assert_not_called()


def test_write_local_model_writes_model_to_relation():
    """write_local_model should persist the local model to relation data."""
    etcd_interface_state, charm = _make_etcd_interface_state()
    model = MagicMock()

    relation = MagicMock()
    relation.id = 1
    charm.etcd_interface_events.etcd_interface.relations = [relation]

    etcd_interface_state.write_local_model(model)

    charm.etcd_interface_events.etcd_interface.interface.write_model.assert_called_once_with(
        1, model
    )