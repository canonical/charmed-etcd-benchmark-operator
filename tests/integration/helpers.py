#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper functions for the integration tests."""

from datetime import datetime, timedelta

import jubilant
from dateutil.parser import parse


def apps_active_and_agents_idle(status: jubilant.Status, *apps: str, idle_period: int = 0) -> bool:
    """Check that all given apps are active, their agents idle.

     Optionally, specify idle interval for agents as well.

    Args:
        status: represents the jubilant model's current status
        apps: A list of applications whose statuses to test against
        idle_period: Seconds to wait for the agents of each application unit to be idle.
    """
    return (
        jubilant.all_active(status, *apps)
        and jubilant.all_agents_idle(status, *apps)
        and check_apps_idle_period(status, *apps, idle_period=idle_period)
    )


def check_apps_idle_period(status: jubilant.Status, *apps: str, idle_period: int) -> bool:
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
