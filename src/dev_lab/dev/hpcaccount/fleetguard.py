"""``deploy-fleet``'s run-wide refusals: checked once, before any account is reached.

Split from :mod:`dev_lab.dev.hpcaccount.fleet`: a stale machine-file render (:func:`stale_render`) and a serving
account holding two grants (:func:`serving_twice_refusal`) refuse the whole run;
an account's own refusal skips only it.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from lab_commons.hpc.grants import Grant

from dev_lab.dev import devhost, tomlleaves
from dev_lab.dev.devdeclared import OWN_TABLE
from dev_lab.dev.hpcaccount.division import DEFAULT_ROLES, Division

__all__ = ['serving_twice_refusal', 'stale_render']


def serving_twice_refusal(grants: Sequence[Grant], accounts: Sequence[str], division: Division | None) -> str:
    """Why this run is refused when an account it DEPLOYS serves under two grants (two tick hosts); ``''`` when none.

    A research account's several grants are several allocations (no tick), and an account outside *accounts* is not
    deployed by this run, so neither is refused. A role no table names counts as serving: the guard stays on.
    """
    roles = division.roles if division is not None else DEFAULT_ROLES
    selected = set(accounts) or {grant.user for grant in grants}
    users = [grant.user for grant in grants if grant.user in selected]

    def serves(user: str) -> bool:
        return any(bool(roles.get(grant.role, {}).get('serves', True)) for grant in grants if grant.user == user)

    if not (twice := sorted({user for user in users if users.count(user) > 1 and serves(user)})):
        return ''
    return (
        f'{twice} serve under more than one [[hpc.grant]]: a serving account ticks from ONE login host. Keep one '
        f'grant per serving account in the machine file, or deploy the others alone (--account <user>)'
    )


def stale_render(live: Mapping[str, Any]) -> str:
    """Why *live* (this machine's file) is not the render of its config source; ``''`` when it is.

    The deploy line is built from THIS machine's grants, so a stale render deploys stale family facts (measured
    2026-11-20: a cluster ``setup`` landed in the source, the machine file was never re-rendered, and every deploy ran
    without it).
    """
    own = live.get(OWN_TABLE, {})
    if not own.get('host') or not own.get('source'):
        return ''  # not a render at all: config_source_of refuses it by name
    clone = Path(own['source'])
    rendered = tomlleaves.leaves(tomllib.loads(devhost.render(clone, own['host'], live)))
    have = tomlleaves.leaves(live)
    differ = sorted(path for path in set(rendered) | set(have) if rendered.get(path) != have.get(path))
    if not differ:
        return ''
    first = ', '.join(f'{tomlleaves.dotted(path)} ({"absent" if path not in have else "not the render"})'
                      for path in differ[:3])  # fmt: skip
    return (
        f'the machine file is not the render of {clone.as_posix()} ({len(differ)} key(s): {first}); re-render it '
        f'first: python -m dev_lab.dev.devhost render --host {own["host"]} --write'
    )
