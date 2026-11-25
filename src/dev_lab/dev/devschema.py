"""The ``[dev]`` table of a development machine's host file: its keys, its checks, and what they derive.

:mod:`dev_lab.dev.devhost` renders and compares with it; :mod:`dev_lab.ops.configcheck` checks with it.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, Final

from lab_commons import config as machineconfig

from dev_lab.dev import devservers, remote
from dev_lab.dev.venvpath import running_interpreter
from dev_lab.ops import clientkeys

__all__ = [
    'BRIDGE',
    'BRIDGE_HPC',
    'CADENCE_HOURS',
    'CHANNELS_TABLE',
    'CPU_SHARES',
    'DETECT_DOOR',
    'FAMILY_ONLY',
    'FORGE_REACH',
    'HELPERS',
    'HOOK_MODES',
    'HOST_ONLY',
    'MACHINE_TABLES',
    'RESOURCES',
    'RETIRED_KEYS',
    'SCHEMA',
    'SSH',
    'SSH_HOLD',
    'UNFILLED',
    'VENDOR',
    'HomeUnfilled',
    'app_tables',
    'channel_defects',
    'check',
    'check_family',
    'declared_channels',
    'fill_remedy',
    'home_of',
    'hpc_reach',
    'key_comment_defects',
    'ssh_defects',
    'unfilled',
    'usable',
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
VENDOR: Final = {'seats': int, 'version': str, 'home': str, 'license_server': str, 'license_feature': str}
#: Every ``[dev]`` key and its type; ``vendors`` and ``forges`` are tables of named entries.
SCHEMA: Final = {
    'hpc': list, 'ref': str, 'os': str, 'forges': dict, 'vendors': dict, 'resources': dict, 'detect': dict,
    'helpers': dict, 'channels': dict, 'bridge': dict, 'hooks': str, 'default': dict, 'apps': list,
    'client_keys': list, 'hostname': str, 'key_account': str, 'forge_reach': list, 'servers': dict,
}  # fmt: skip
#: ``[dev] forge_reach``: the transports this machine reaches the forge's approval doors (consent, break-glass) by,
#: in its order of preference -- ``ssh`` (port 22) and/or ``https`` (443, :mod:`dev_lab.ops.httpsdoor`). Undeclared
#: is ``["ssh"]``. Rendered as the machine file's ``[devhost] forge_reach``; read by
#: :func:`dev_lab.ops.consent.door.endpoint_send`.
FORGE_REACH: Final = ('ssh', 'https')
#: ``[dev] bridge``: what the session bridge runs on this machine -- ``hpc`` (:data:`BRIDGE_HPC`), the HPC usage
#: collector for the agents dashboard, rendered as the machine file's ``[bridge.hpc]``.
BRIDGE: Final = {'hpc': dict}
#: ``[dev] bridge.hpc``: ``cadence_hours`` -- the read cadence (1..168; default 6).
BRIDGE_HPC: Final = {'cadence_hours': int}
#: ``cadence_hours`` bounds: an hourly read at most, a weekly one at least.
CADENCE_HOURS: Final = (1, 168)
#: ``[dev] hooks``: ``enforce`` -- a firing hook row refuses; ``warn`` -- it only warns (an unmanaged machine).
HOOK_MODES: Final = ('enforce', 'warn')
#: ``[dev]`` keys only the family declares: ``default`` -- the profile an undeclared machine renders
#: (:mod:`dev_lab.dev.devprofile`); ``servers`` -- the servers every workstation operates, by address
#: (:mod:`dev_lab.dev.devservers`).
FAMILY_ONLY: Final = ('default', 'apps', 'servers')
#: ``[dev]`` keys that are one machine's facts and never the family's: ``channels`` -- session channel source ->
#: the user whose messages through it ARE the machine's user (an undeclared channel or user carries no authority);
#: ``client_keys`` -- the machine's ssh client public keys, from which a server derives who may reach its approval
#: accounts (:mod:`dev_lab.ops.clientkeys`); ``hostname`` -- the machine's own host name, the part after ``@`` in
#: every one of its key comments (:func:`key_comment_defects`); ``forge_reach`` -- the transports its own network lets
#: it reach the forge by (:data:`FORGE_REACH`).
HOST_ONLY: Final = ('channels', 'client_keys', 'hostname', 'forge_reach')
#: ``[dev]`` keys the family declares for every machine and a host may OVERRIDE with a different value: ``forges`` --
#: the workstation login is one person's, so another person's machine names its own; ``key_account`` -- the account
#: named before ``@`` in every client key comment, likewise one person's. A host restating the family's value is still
#: refused: one fact, one place.
OVERRIDABLE: Final = ('forges', 'key_account')
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
MACHINE_TABLES: Final = ('capabilities', 'serve', 'reserve', 'workstation', 'storage')
#: The machine file's ``[ssh]`` table as a host file declares it (rendered by :func:`dev_lab.dev.devhost.render`,
#: read by :mod:`dev_lab.dev.sshhold`): ``jump`` -- destination -> bastion, the declared per-host route; ``hold`` --
#: :data:`SSH_HOLD`; ``host_keys`` -- endpoint host -> its ``"<type> <base64>"`` host key, the one key a declared
#: endpoint (``[consent]``, ``[breakglass]``) is checked against (:data:`dev_lab.dev.remote.HOST_KEY_RULE`).
SSH: Final = {'jump': dict, 'hold': dict, 'host_keys': dict}
#: ``[ssh.hold]``: the session ceiling and the idle limit.
SSH_HOLD: Final = {'max_hours': (int, float), 'idle_minutes': (int, float)}
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


def ssh_defects(ssh: object, where: str = 'ssh') -> list[str]:
    """Defects of an ``[ssh]`` table: only :data:`SSH` keys; ``jump`` maps destinations to bastions, both non-empty."""
    if not isinstance(ssh, Mapping):
        return [f'{where} must be a table']
    found = _typed(ssh, SSH, where)
    jump = ssh.get('jump')
    if isinstance(jump, dict):
        found += [
            f'{where}.jump.{dest!r} = {bastion!r}: destination and bastion must be non-empty strings'
            for dest, bastion in jump.items()
            if not (isinstance(dest, str) and dest and isinstance(bastion, str) and bastion)
        ]
    hold = ssh.get('hold')
    if isinstance(hold, dict):
        found += _typed(hold, SSH_HOLD, f'{where}.hold')
    keys = ssh.get('host_keys')
    if isinstance(keys, dict):
        found += [f'{where}.host_keys.{host!r}: {why}' for host in keys if (why := _host_key_defect(host, keys))]
    return found


def _host_key_defect(host: str, keys: Mapping[str, Any]) -> str | None:
    """Why *host*'s declared key is malformed; ``None`` for a key line or the not-yet-filled placeholder."""
    if keys.get(host) == remote.HOST_KEY_UNFILLED:
        return None  # accepted here, refused by name where it is used
    try:
        remote.host_key_line(f'check@{host}', keys)
    except remote.HostKeyUndeclared as refused:
        return str(refused)
    return None


def _bridge(table: Mapping[str, Any], where: str) -> list[str]:
    bridge = table.get('bridge')
    if not isinstance(bridge, dict):
        return []
    found = _typed(bridge, BRIDGE, f'{where}.bridge')
    hpc = bridge.get('hpc')
    if isinstance(hpc, dict):
        found += _typed(hpc, BRIDGE_HPC, f'{where}.bridge.hpc')
        hours = hpc.get('cadence_hours', 6)
        if isinstance(hours, int) and not CADENCE_HOURS[0] <= hours <= CADENCE_HOURS[1]:
            found.append(
                f'{where}.bridge.hpc.cadence_hours must be {CADENCE_HOURS[0]}..{CADENCE_HOURS[1]}, not {hours}'
            )
    return found


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
    found += _bridge(table, where)
    if 'hooks' in table and table['hooks'] not in HOOK_MODES:
        found.append(f'{where}.hooks {table["hooks"]!r} is not one of {list(HOOK_MODES)}')
    if 'channels' in table:
        found += channel_defects(table['channels'], f'{where}.channels')
    if 'client_keys' in table:
        found += clientkeys.defects(table['client_keys'], f'{where}.client_keys')
    if isinstance(table.get('servers'), dict):
        found += devservers.defects(table['servers'], f'{where}.servers')
    reach = table.get('forge_reach', list(FORGE_REACH[:1]))
    if not (isinstance(reach, list) and reach and len(set(reach)) == len(reach) and set(reach) <= set(FORGE_REACH)):
        found.append(f'{where}.forge_reach must list, once each and in preference order, some of {list(FORGE_REACH)}')
    found += [f'{where}.{key} must be a non-empty name with no "@" or space' for key in ('hostname', 'key_account')
              if isinstance(table.get(key), str) and not _NAME.fullmatch(table[key])]  # fmt: skip
    found += _named_lists(table, 'detect', where, 'glob patterns')
    found += _resources(table, where)
    vendors = table.get('vendors') if isinstance(table.get('vendors'), dict) else {}
    for name, vendor in vendors.items():
        if isinstance(vendor, dict):
            found += _typed(vendor, VENDOR, f'{where}.vendors.{name}')
        else:
            found.append(f'{where}.vendors.{name} must be a table')
    return found


_NAME: Final = re.compile(r'[^@\s]+')


def key_comment_defects(dev: Mapping[str, Any], where: str = '[dev]') -> list[str]:
    """Why a client key's comment is not ``<key_account>@<hostname>`` of *dev* (a host's merged ``[dev]``).

    A machine's key names who holds it and where: the comment is DERIVED from the declared account and host name,
    so a key copied from another machine, or labeled by hand, is refused by name.
    """
    keys, host, account = dev.get('client_keys'), dev.get('hostname'), dev.get('key_account')
    if not isinstance(keys, list) or clientkeys.defects(keys, f'{where}.client_keys'):
        return []  # absent, or already refused by its shape
    door = ('declare [dev] hostname (the machine host name, in this host file) and [dev] key_account (the key '
            "holder's account, in the family file or this host file)")  # fmt: skip
    if not (isinstance(host, str) and isinstance(account, str)):
        return [f'{where}.client_keys needs a declared <key_account>@<hostname> to check its comments against: {door}']
    expected = f'{account}@{host}'
    return [
        f'{where}.client_keys[{index}] comment is {actual!r}, expected {expected!r} (<key_account>@<hostname>): '
        f'relabel the key (ssh-keygen -c -C {expected} -f <its private key>) and its line in this host file, '
        f'or correct [dev] hostname / key_account'
        for index, key in enumerate(keys)
        if (actual := ' '.join(key.split()[2:])) != expected
    ]


def _leaves(table: Mapping[str, Any], prefix: str = '') -> Iterator[tuple[str, Any]]:
    for key, value in table.items():
        if isinstance(value, Mapping):
            yield from _leaves(value, f'{prefix}{key}.')
        else:
            yield f'{prefix}{key}', value


def _restated(host: Mapping[str, Any], family: Mapping[str, Any]) -> list[str]:
    """Leaves *host* shares with *family*: any of them, but an :data:`OVERRIDABLE` one only when its value is equal."""
    ours, theirs = dict(_leaves(host)), dict(_leaves(family))
    overridable = tuple(f'dev.{key}.' for key in OVERRIDABLE)
    scalars = {f'dev.{key}' for key in OVERRIDABLE}
    return sorted(key for key in ours.keys() & theirs.keys()
                  if not (key.startswith(overridable) or key in scalars) or ours[key] == theirs[key])  # fmt: skip


def check(host: Mapping[str, Any], family: Mapping[str, Any] | None = None) -> list[str]:
    """Defects of a development host file against the family: ``[dev]`` shape, a restated family key, a gap."""
    shared = family or {}
    found = _shape(host.get('dev', {}), '[dev]')
    found += [f'[dev].{key} is the family default profile; it lives in family.toml' for key in FAMILY_ONLY
              if key in host.get('dev', {})]  # fmt: skip
    restated = _restated(host, shared)
    found += [f'{key} restates the family file; it lives there once' for key in restated]
    merged = {**shared.get('dev', {}), **host.get('dev', {})}
    found += key_comment_defects(merged)
    found += [f'[dev].{key} is required (host or family file)' for key in REQUIRED if key not in merged]
    return found


def check_family(family: Mapping[str, Any]) -> list[str]:
    """Defects of the family file's ``[dev]`` by itself, and a key only a host may declare."""
    dev = family.get('dev', {})
    host_only = [f'[dev].{key} is one machine fact; it lives in that host file' for key in HOST_ONLY if key in dev]
    found = host_only + _shape(dev, '[dev]')
    default = dev.get('default')
    if isinstance(default, dict):
        nested = [key for key in (*FAMILY_ONLY, *HOST_ONLY) if key in default]
        found += [f'[dev].default.{key} may not be declared in the default profile' for key in nested]
        found += _shape({k: v for k, v in default.items() if k not in nested}, '[dev].default')
    return found


def app_tables(family: Mapping[str, Any]) -> tuple[str, ...]:
    """The consumer tables the family opens in every host and account file (``[dev] apps``, family-only).

    A consumer application reads its own machine facts from a table named after it (e.g. ``[<app>.core]``); the
    family names those applications ONCE, so a host file may carry ``[<app>]`` without this kit knowing the app.
    """
    apps = family.get('dev', {}).get('apps', [])
    return tuple(name for name in apps if isinstance(name, str))


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


def declared_channels(live: Mapping[str, Any] | None = None) -> dict[str, str]:
    """Return this machine's session channels: source -> the user whose messages through it ARE the machine's user.

    Read from the machine file's ``[agent] channels`` (the render of the host file's ``[dev] channels``). Empty when
    none is declared: an undeclared channel or user carries no authority.

    Raises:
        ValueError: the table is not non-empty source strings to non-empty user strings -- never read past.

    """
    channels = (machineconfig.machine() if live is None else live).get(CHANNELS_TABLE, {}).get('channels', {})
    if defects := channel_defects(channels, f'[{CHANNELS_TABLE}].channels'):
        raise ValueError('; '.join(defects))
    return dict(channels)
