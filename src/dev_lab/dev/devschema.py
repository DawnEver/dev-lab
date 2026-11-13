"""The ``[dev]`` table of a development machine's host file: its keys, its checks, and what they derive.

:mod:`dev_lab.dev.devhost` renders and compares with it; :mod:`dev_lab.ops.configcheck` checks with it.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, Final

from dev_lab.dev.venvpath import running_interpreter

__all__ = [
    'CHANNELS_TABLE', 'CPU_SHARES', 'DETECT_DOOR', 'HELPERS', 'HOST_ONLY', 'MACHINE_TABLES', 'RESOURCES',
    'RETIRED_KEYS', 'SCHEMA', 'UNFILLED', 'VENDOR', 'HomeUnfilled', 'channel_defects', 'check', 'check_family',
    'fill_remedy', 'home_of', 'hpc_reach', 'unfilled', 'usable',
]  # fmt: skip

#: Retired ``[dev]`` keys, each with its remedy (refused by name, never read).
RETIRED_KEYS: Final = {
    'role': (
        'retired (user correction 2026-11-12): the integrator is a SESSION identity, never a host one -- a host '
        'declares only what the machine may reach, [dev] hpc; a session proves the integrator role with a consent '
        'credential (dev_lab.dev.hpcaccount.session)'
    ),
}
#: One vendor install's keys.
VENDOR: Final = {'seats': int, 'version': str, 'home': str, 'licence_server': str, 'licence_feature': str}
#: Every ``[dev]`` key and its type; ``vendors`` and ``forges`` are tables of named entries.
SCHEMA: Final = {
    'hpc': list, 'ref': str, 'os': str, 'forges': dict, 'vendors': dict, 'resources': dict, 'detect': dict,
    'helpers': dict, 'channels': dict,
}  # fmt: skip
#: ``[dev]`` keys that are one machine's facts and never the family's: ``channels`` -- session channel source ->
#: the user whose messages through it ARE the machine's user (an undeclared channel or user carries no authority).
HOST_ONLY: Final = ('channels',)
#: The machine-file table ``[dev] channels`` renders into, as ``[agent] channels``: its consumer is the agent session
#: (the harness and its channel plugins), not the dev tooling, so the table is named for who reads it.
CHANNELS_TABLE: Final = 'agent'
#: The git credential helpers a ``[dev] helpers.<forge host>`` may declare: ``store`` -- that host reads ONLY
#: ``~/.git-credentials`` (a narrowly scoped bot token), every other host keeps the machine's own helper.
HELPERS: Final = ('store',)
#: The box's hardware; a SHARED box also declares the part this user holds (``allotted_*``), read before the total.
RESOURCES: Final = {
    'cpu': str, 'cores': int, 'logical_cores': int, 'memory_gb': (int, float), 'gpu': str, 'shared': bool,
    'allotted_cores': int, 'allotted_memory_gb': (int, float), 'cpu_share': str,
}  # fmt: skip
#: How a shared box splits its CPU: ``session-fair`` -- evenly among the ACTIVE login sessions (all of it when alone).
CPU_SHARES: Final = ('session-fair',)
#: The ONE placeholder for an install home not yet found on its machine: never a plausible path. configcheck accepts
#: it; the session start names it first, the stop blocks once on it, and :func:`home_of` refuses it.
UNFILLED: Final = 'FILL-ON-THIS-MACHINE'
#: Keys the family and host ``[dev]`` must hold between them.
REQUIRED: Final = ('ref',)
#: The machine-file tables a host file may declare for its machine (each open: its consumer owns its keys).
MACHINE_TABLES: Final = ('capabilities', 'serve', 'reserve', 'workstation')
#: The door that finds this machine's vendor install homes.
DETECT_DOOR: Final = f'{running_interpreter()} -m dev_lab.dev.devhost detect'


def _typed(table: Mapping[str, Any], schema: Mapping[str, Any], where: str) -> list[str]:
    found = []
    for key, value in table.items():
        if key not in schema:
            found.append(f'{where}.{key} is not a declared key')
        elif not isinstance(value, schema[key]) or (isinstance(value, bool) and schema[key] is not bool):
            found.append(
                f'{where}.{key} must be {schema[key].__name__ if isinstance(schema[key], type) else "a number"}'
            )
    return found


def _named_lists(table: Mapping[str, Any], key: str, where: str, what: str) -> list[str]:
    entries = table.get(key) if isinstance(table.get(key), dict) else {}
    return [
        f'{where}.{key}.{name} must be a non-empty list of {what}'
        for name, items in entries.items()
        if not (isinstance(items, list) and items and all(isinstance(item, str) for item in items))
    ]


def _resources(table: Mapping[str, Any], where: str) -> list[str]:
    if 'resources' not in table:
        return []
    resources = table['resources']
    if not isinstance(resources, dict):
        return [f'{where}.resources must be a table']
    found = _typed(resources, RESOURCES, f'{where}.resources')
    if 'cpu_share' in resources and resources['cpu_share'] not in CPU_SHARES:
        found.append(f'{where}.resources.cpu_share {resources["cpu_share"]!r} is not one of {list(CPU_SHARES)}')
    return found


def channel_defects(channels: object, where: str) -> list[str]:
    """Defects of a channel declaration: it must map non-empty source strings to non-empty user strings."""
    if not isinstance(channels, Mapping):
        return [f'{where} must be a table of channel source -> user name']
    return [
        f'{where}.{source!r} = {user!r}: source and user must be non-empty strings'
        for source, user in channels.items()
        if not (isinstance(source, str) and source and isinstance(user, str) and user)
    ]


def _shape(table: Mapping[str, Any], where: str) -> list[str]:
    """Defects of one ``[dev]`` table (host or family) by itself."""
    found = [f'{where}.{key} is {remedy}' for key, remedy in RETIRED_KEYS.items() if key in table]
    found += _typed({k: v for k, v in table.items() if k not in RETIRED_KEYS}, SCHEMA, where)
    hpc = table.get('hpc', [])
    if not (isinstance(hpc, list) and all(isinstance(role, str) and role for role in hpc)):
        found.append(f'{where}.hpc must list account role names (e.g. ["research"]), or be [] for none')
    found += _named_lists(table, 'forges', where, 'account names')
    helpers = table.get('helpers') if isinstance(table.get('helpers'), dict) else {}
    found += [
        f'{where}.helpers.{host} {helper!r} is not one of {list(HELPERS)}'
        for host, helper in helpers.items()
        if helper not in HELPERS
    ]
    if 'channels' in table:
        found += channel_defects(table['channels'], f'{where}.channels')
    found += _named_lists(table, 'detect', where, 'glob patterns')
    found += _resources(table, where)
    vendors = table.get('vendors') if isinstance(table.get('vendors'), dict) else {}
    for name, vendor in vendors.items():
        if isinstance(vendor, dict):
            found += _typed(vendor, VENDOR, f'{where}.vendors.{name}')
        else:
            found.append(f'{where}.vendors.{name} must be a table')
    return found


def _leaves(table: Mapping[str, Any], prefix: str = '') -> Iterator[str]:
    for key, value in table.items():
        if isinstance(value, Mapping):
            yield from _leaves(value, f'{prefix}{key}.')
        else:
            yield f'{prefix}{key}'


def check(host: Mapping[str, Any], family: Mapping[str, Any] | None = None) -> list[str]:
    """Defects of a development host file against the family: ``[dev]`` shape, a restated family key, a gap."""
    shared = family or {}
    found = _shape(host.get('dev', {}), '[dev]')
    restated = sorted(set(_leaves(host)) & set(_leaves(shared)))
    found += [f'{key} restates the family file; it lives there once' for key in restated]
    merged = {**shared.get('dev', {}), **host.get('dev', {})}
    found += [f'[dev].{key} is required (host or family file)' for key in REQUIRED if key not in merged]
    return found


def check_family(family: Mapping[str, Any]) -> list[str]:
    """Defects of the family file's ``[dev]`` by itself, and a key only a host may declare."""
    dev = family.get('dev', {})
    host_only = [f'[dev].{key} is one machine fact; it lives in that host file' for key in HOST_ONLY if key in dev]
    return host_only + _shape(dev, '[dev]')


def hpc_reach(dev: Mapping[str, Any]) -> list[str]:
    """The account roles this machine may reach -- rendered as the machine file's ``[hpc] reach``; none undeclared."""
    return list(dev.get('hpc', []))


def usable(dev: Mapping[str, Any]) -> tuple[int | None, float | None]:
    """The cores and memory (GB) this user may use: a shared box's fixed allotment, else the box's own.

    ``None`` means SIZE FROM THE LIVE FIGURES at run time: a shared box with no fixed allotment (``cpu_share =
    "session-fair"``, memory shared without a cap) is never sized from its declared total.
    """
    resources = dev.get('resources', {})
    if resources.get('shared'):
        return resources.get('allotted_cores'), resources.get('allotted_memory_gb')
    return resources.get('cores'), resources.get('memory_gb')


def unfilled(dev: Mapping[str, Any]) -> list[str]:
    """The vendors whose install home this machine has yet to fill: the placeholder, or seats with no home."""
    return [
        name
        for name, vendor in dev.get('vendors', {}).items()
        if vendor.get('home') == UNFILLED or (vendor.get('seats') and not vendor.get('home'))
    ]


def fill_remedy(names: list[str]) -> str:
    """What a machine does about *names*: detect here, then propose the lines through a config-source PR."""
    return (
        f'install home not filled for {", ".join(names)} ({UNFILLED}): run {DETECT_DOOR} on this machine and open a '
        "pull request on the config source replacing the placeholder in this machine's host file"
    )


class HomeUnfilled(LookupError):
    """A code path needs a vendor's install home this machine has not filled."""


def home_of(dev: Mapping[str, Any], vendor: str) -> Path:
    """*vendor*'s declared install home.

    Raises:
        HomeUnfilled: it is the placeholder or absent -- never a fallback guess.

    """
    home = dev.get('vendors', {}).get(vendor, {}).get('home')
    if not home or home == UNFILLED:
        raise HomeUnfilled(fill_remedy([vendor]))
    return Path(home)
