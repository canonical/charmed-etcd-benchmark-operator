#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper functions for the integration tests."""

from datetime import datetime, timedelta

import yaml
from dateutil.parser import parse
from jubilant import Juju, Status, all_active, all_agents_idle


def apps_active_and_agents_idle(status: Status, *apps: str, idle_period: int = 0) -> bool:
    """Check that all given apps are active, their agents idle.

     Optionally, specify idle interval for agents as well.

    Args:
        status: represents the jubilant model's current status
        apps: A list of applications whose statuses to test against
        idle_period: Seconds to wait for the agents of each application unit to be idle.
    """
    return (
        all_active(status, *apps)
        and all_agents_idle(status, *apps)
        and check_apps_idle_period(status, *apps, idle_period=idle_period)
    )


def check_apps_idle_period(status: Status, *apps: str, idle_period: int) -> bool:
    """Check that all agents for given apps have been idle for at least given period.

    Args:
        status: represents the jubilant model's current status
        apps: A list of applications whose agents to test
        idle_period: Seconds to wait for the agents of each application unit to be idle.
    """
    return all(
        parse(unit.juju_status.since, ignoretz=True) + timedelta(seconds=idle_period)
        < datetime.now()
        for app in apps
        for unit in status.get_units(app).values()
    )


def get_leader_unit_name(juju: Juju, app: str) -> str:
    """Retrieve the leader unit's name.

    Raises:
        RuntimeError: if no leader unit is found.
    """
    for name, unit in juju.status().get_units(app).items():
        if unit.leader:
            return name

    raise RuntimeError(f"No leader unit found for app {app}")


def get_unit_relation_data(
    juju: Juju,
    unit_name: str,
    target_unit_name: str,
    relation_name: str,
    key: str,
) -> str | None:
    """Get relation data for a unit.

    Args:
        juju: An instance of Jubilant's Juju class on which to run Juju commands
        unit_name: The name of provider's unit
        target_unit_name: The name of requirer's unit
        relation_name: name of the relation to get connection data from
        key: key of data to be retrieved

    Returns:
        the data that was requested or None
            if no data in the relation

    Raises:
        ValueError if it's not possible to get application unit data
            or if there is no data for the particular relation endpoint
            and/or alias.
    """
    raw_data = juju.cli("show-unit", unit_name)
    if not raw_data:
        raise ValueError(f"no unit info could be grabbed for {unit_name}")
    data = yaml.safe_load(raw_data)
    # Filter the data based on the relation name.
    relation_data = [v for v in data[unit_name]["relation-info"] if v["endpoint"] == relation_name]
    if not relation_data:
        raise ValueError(
            f"no relation data could be grabbed on relation with endpoint {relation_name}"
        )
    # Consider the case we are dealing with subordinate charms, e.g. grafana-agent
    # The field "relation-units" is structured slightly different.
    for idx in range(len(relation_data)):
        if target_unit_name in relation_data[idx]["related-units"]:
            break
    else:
        return None
    return (
        relation_data[idx]["related-units"].get(target_unit_name, {}).get("data", {}).get(key, {})
    )
