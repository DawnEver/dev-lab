"""Which node may run an account's ``deploy`` -- the host check :mod:`~dev_lab.dev.hpcaccount.deploy` runs first.

A serving account is pinned to the one node its cron runs on; an account that never serves may deploy from any of
its grant's login hosts (:func:`~dev_lab.dev.hpcaccount.spec.login_hosts`).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dev_lab.dev.hpcaccount.spec import Deployment, login_hosts

__all__ = ['host_refusal']


def host_refusal(spec: Deployment, path: Path, short: str, *, serves: bool, table: Mapping[str, Any] | None) -> str:
    """Why this node may not run *spec*'s deploy (``''``: it may).

    A serving account is pinned to ONE node, because cron is per node. An account that never serves installs no
    cron line, so any of its grant's login hosts -- an alias round-robining over several nodes too -- is its host.
    """
    if short == spec.host:
        return ''
    if not serves:
        hosts = login_hosts(path, table)
        if spec.host in hosts:
            return ''
        return (
            f'[deploy] host {spec.host} ({path}) is neither this node ({short}) nor a login host of the grant '
            f'{sorted(hosts)}; a {spec.role} account installs no cron, so declare --host as one of those'
        )
    return (
        f'this account serves from {spec.host} ([deploy] host in {path}); this is {short}. '
        f'cron is per node: ssh to {spec.host} and run it there.'
    )
