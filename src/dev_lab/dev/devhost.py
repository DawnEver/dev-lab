"""A DEVELOPMENT machine is declared like a server, and its machine file is a RENDER of the declaration.

The config-source repository (``[ops.config] source``) holds the family file and one host file per machine. Three
layers, one way, each fact in one place:

1. FAMILY (``family.toml``): every fact all machines share -- machine-file tables as they are read
   (``[hpc]``, ``[ai_lab]``, ``[consent]``, ``[breakglass]``, ``[ssh]`` ...) and the shared ``[dev]`` keys;
2. HOST (``hosts/<name>.toml``): one machine's facts -- ``[dev]`` and the :data:`MACHINE_TABLES` it reads; for an
   HPC ACCOUNT (``hosts/<cluster>-<user>.toml``, :mod:`dev_lab.dev.accounthost`) its own ``[deploy]``,
   ``[schedule]``, ``[hpc.paging]`` and ``[capabilities]``, with ``[deploy] role`` derived from its family grant;
3. LOCAL: what stays on the machine -- every table of the live file neither layer declares (``[repos]`` paths,
   personal ``[user]`` preferences), preserved by the render, never invented. Credentials are in no layer: a path
   may be declared, a value never.

A host file restating a family key is refused (:func:`check`). ``[dev]`` (:data:`SCHEMA`): ``hpc``
(the account roles the machine may reach, rendered as ``[hpc] reach``), ``ref`` (the dev-lab ref followed),
``forges`` (forge host -> account names), ``os``,
``resources`` (:data:`RESOURCES`; :func:`usable` is the part this user holds), ``vendors.<name>`` (:data:`VENDOR`),
``detect`` (vendor -> install-home glob patterns, family-wide),
``channels`` (session channel source -> user, host-only; rendered as ``[agent] channels``, read by
:func:`declared_channels`). ``[dev]`` is not rendered itself; a vendor's ``seats > 0`` renders as
``[capabilities.<vendor>] seats``, its one consumer-facing copy.

Install homes are found ON each machine: ``detect`` globs the family's patterns locally and prints the host-file
lines to propose through a pull request; a vendor with seats and no ``home`` is named by the drift notice.

A machine with no host file renders the family's ``[dev.default]`` instead, stamped ``[devhost] unmanaged``
(:mod:`dev_lab.dev.devprofile`); ``[dev] bridge.hpc`` renders as ``[bridge.hpc]``, ``[dev] hooks`` as
``[devhost] hooks``.

:func:`render` = family ⊕ host ⊕ local, with a header naming the sources and their digests and a ``[devhost]``
table naming the host and the clone. :func:`drift` compares the live file with that render, and its ``[repos]
dev-lab`` checkout's branch with ``ref``; the ``SessionStart`` notice (:func:`notice`) runs it with no network.
``session-start`` is that notice's ONE trigger, wired once per session (:data:`dev_lab.dev.agent_wiring.WIRING`):
machine-file drift and an unfilled install home cannot change within a turn, so no ``Stop`` re-reads them.

``python -m dev_lab.dev.devhost bringup --check`` -- the ONE preflight of a new or migrated workstation
(:mod:`dev_lab.dev.bringup`): every wall with its door, and which doors then spend a code;
``python -m dev_lab.dev.devhost drift [--from CLONE]`` -- read only, exit 1 on drift: each drifted KEY with the layer
owning it and that layer's door, then the family-repo census (:func:`dev_lab.dev.familyrepos.census`);
``python -m dev_lab.dev.devhost local set|unset <table>.<key> [value]`` -- the ONE door into the local layer
(``[repos]``, ``[user]``): it refuses a rendered table, backs the file up, re-renders and prints what changed. Every
other write is refused by MACHINE-FILE-IS-RENDERED (:mod:`dev_lab.dev.machineguard`);
``python -m dev_lab.dev.devhost render --host NAME --from CLONE [--write]`` -- prints the render; ``--write``
refuses a render that does not parse, else backs the live file up under the output tree and replaces it.
"""

from __future__ import annotations

import argparse
import json
import platform
import tomllib
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from lab_commons import config as machineconfig
from lab_commons.log import emit

from dev_lab.dev import (
    bringup,
    devprofile,
    familyrepos,
    forgecredential,
    forgeenrol,
    tomlleaves,
    vendordetect,
)
from dev_lab.dev._machinefile import merged, render_value
from dev_lab.dev.backedup import replace_backed_up
from dev_lab.dev.checkout import git_out
from dev_lab.dev.devdeclared import OWN_TABLE, declared, declared_by, layered
from dev_lab.dev.devrender import RENDER_DOOR, host_file, read_toml, render, sources
from dev_lab.dev.devschema import CHANNELS_TABLE, channel_defects, fill_remedy, unfilled
from dev_lab.dev.venvpath import running_interpreter

__all__ = [
    'LOCAL_DOOR', 'declared_channels', 'drift', 'local_set', 'main', 'notice',
]  # fmt: skip

#: A key one side lacks (``None`` is not a TOML value, but a sentinel says so outright).
_ABSENT: Final = object()


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


def _branch(checkout: str) -> str | None:
    return (git_out(Path(checkout), 'symbolic-ref', '--short', 'HEAD') or '').strip() or None


def drift(live: Mapping[str, Any], clone: Path | None = None) -> list[str]:
    """Where the *live* machine file departs from its render, and its dev-lab checkout from the declared ref.

    Rendered from *clone* when given, else from the live ``[devhost] source`` -- which may name a path of another
    machine: a source that is not a clone here is one drift line naming ``--from``, never a crash.
    """
    own = live.get(OWN_TABLE, {})
    if not own.get('host') or not (clone or own.get('source')):
        return []
    clone, host = clone or Path(own['source']), own['host']
    if not (clone / 'family.toml').is_file():
        return [f'the config source {clone.as_posix()} is not a clone here: name one with drift --from <clone>']
    try:
        text = render(clone, host, live)
    except (
        LookupError,
        TypeError,
        ValueError,
    ) as unrenderable:  # a wall is a drift line naming its door, never a crash
        return [f'the machine file cannot be rendered: {unrenderable}']
    rendered, have = tomlleaves.leaves(tomllib.loads(text)), tomlleaves.leaves(live)
    found = [
        f'{tomlleaves.dotted(path)} is {"absent" if path not in have else "not the render"} -- '
        f'{_owner(path, clone, host)}'
        for path in sorted(set(rendered) | set(have))
        if rendered.get(path, _ABSENT) != have.get(path, _ABSENT)
    ]
    family_file, own_file = sources(clone, host)
    dev = declared(own_file, family_file)
    if names := unfilled(dev):
        found.insert(0, fill_remedy(names))
    found += familyrepos.census(layered(live))
    found += forgecredential.drift(dev)
    checkout = live.get('repos', {}).get('dev-lab')
    if (want := dev.get('ref')) and checkout and (on := _branch(checkout)) not in {want, None}:
        found.append(f'the dev-lab checkout is on {on!r}, declared ref {want!r}')
    return found


def _owner(path: tuple[str, ...], clone: Path, host: str) -> str:
    """The layer owning the key at *path*, and that layer's door."""
    if path[0] == OWN_TABLE:
        return f'the render itself: {RENDER_DOOR}'
    edit = f'change it there through its pull request, then {RENDER_DOOR}'
    family_file, own_file = sources(clone, host)
    for layer, source in (('host', own_file), ('family', family_file)):
        tables = {k: v for k, v in (read_toml(source) if source.is_file() else {}).items() if k != 'dev'}
        if any(path[: len(key)] == key or key[: len(path)] == path for key in tomlleaves.leaves(tables)):
            return f'{layer} layer ({source.relative_to(clone).as_posix()}): {edit}'
    if path[0] in _layered(clone, host):
        return f'host layer ({host_file(host)} [dev], rendered): {edit}'
    return f'local layer: {LOCAL_DOOR}'


def _layered(clone: Path, host: str) -> set[str]:
    """The tables the family and host layers render; every other table is local.

    Asked of the LAYERS alone: a local value a layer reads (the bridge's ``[repos] dev-lab``) is stood in for, so the
    question never refuses for the very local key ``local set`` is about to supply (2026-11-20).
    """
    stand_in = {familyrepos.LOCAL_TABLE: {devprofile.BRIDGE_CHECKOUT: '/dev-lab'}}
    family = {k for k in read_toml(sources(clone, host)[0]) if k != 'dev'}
    return (set(tomllib.loads(render(clone, host, stand_in))) | family) - {OWN_TABLE, familyrepos.LOCAL_TABLE}


def notice(live: Mapping[str, Any] | None = None) -> str | None:
    """One SessionStart line when the machine file drifted from its render; else ``None`` (or not a render)."""
    try:
        found = drift(machineconfig.machine() if live is None else live)
    except (OSError, tomllib.TOMLDecodeError):
        return None
    first = [line for line in found if line.startswith('install home not filled')]
    rest = [line for line in found if line not in first]
    lines = [f'HOST-CONFIG FIRST: {line}' for line in first]
    if host := devprofile.unmanaged(machineconfig.machine() if live is None else live):
        lines.insert(0, f'HOST-CONFIG FIRST: {devprofile.enrolment(host)}')
    if rest:
        drifted = '; '.join(rest)
        lines.append(f'HOST-CONFIG: the machine file drifted from its render: {drifted}. Re-render: {RENDER_DOOR}')
    return '\n'.join(lines) or None


#: The door that sets one key of the machine's own (local) layer.
LOCAL_DOOR: Final = f'{running_interpreter()} -m dev_lab.dev.devhost local set <table>.<key> <value>'


def _source(clone: Path | None, own: Mapping[str, Any]) -> Path | None:
    return clone or (Path(own['source']) if own.get('source') else None)


def _drift(path: Path, live: Mapping[str, Any], clone: Path | None) -> int:
    found = drift(live, clone)
    for line in found:
        emit(f'drift: {line}')
    if not found:
        emit(f'agrees: {path} is its render' if live.get(OWN_TABLE) else f'{path} is not a render')
    return 1 if found else 0


def _detect(source: Path | None) -> int:
    if source is None:
        emit(
            "refused: detect needs --from <the config source's checkout> (no [devhost] in the machine file): "
            'clone the config source as a family repo and set its path -- ' + familyrepos.SET_DOOR,
            err=True,
        )
        return 2
    homes = vendordetect.detect(read_toml(source / 'family.toml').get('dev', {}).get('detect', {}))
    for name, home in homes.items():
        emit(f'[dev.vendors.{name}]\nhome = {render_value(home)}\n')
    if not homes:
        emit('no declared vendor pattern matched on this machine')
    return 0


def _channels(live: Mapping[str, Any]) -> int:
    try:
        channels = declared_channels(live)
    except ValueError as malformed:
        emit(f'refused: {malformed}', err=True)
        return 2
    emit(json.dumps(channels, sort_keys=True))
    return 0


def _render_verb(args: argparse.Namespace, path: Path, live: Mapping[str, Any]) -> int:
    own = live.get(OWN_TABLE, {})
    host, clone = args.host or own.get('host') or platform.node(), _source(args.clone, own)
    if not host or clone is None:
        emit(
            "refused: render needs --from <the config source's checkout> (no [devhost] in the machine file): "
            'clone the config source as a family repo and set its path -- ' + familyrepos.SET_DOOR,
            err=True,
        )
        return 2
    try:
        text = render(clone, host, live)
    except (LookupError, TypeError) as undeclared:
        emit(f'refused: {undeclared}; declare it in the config source', err=True)
        return 2
    except ValueError as local:  # a local key the layers read is unset: its door is named, nothing is written
        emit(f'refused: {local}; {path} is unchanged', err=True)
        return 2
    if not (clone / host_file(host)).is_file():
        emit(f'render: {devprofile.enrolment(host)}', err=True)
    if names := unfilled(declared(clone / 'hosts' / f'{host}.toml', clone / 'family.toml')):
        emit(f'render: {fill_remedy(names)}', err=True)
    if not args.write:
        emit(text)
        return 0
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as broken:
        emit(f'refused: the render of {host} is not TOML ({broken}); {path} is unchanged', err=True)
        return 2
    backups = args.backups or Path('output/logs') / f'{datetime.now(UTC):%y/%m/%d}' / 'devhost'
    emit(f'rendered {path}; the previous file is {replace_backed_up(path, text, backups)}')
    return 0


def local_set(live: Mapping[str, Any], dotted: str, value: str | None) -> dict[str, Any]:
    """*live* with the LOCAL key ``<table>.<key>`` set to *value*; ``None`` removes it.

    Raises:
        ValueError: *dotted* is not ``<table>.<key>``; its table is rendered from the config source (a family or
            host table: change it there); or a ``[repos]`` value is not an absolute path.

    """
    table, _, key = dotted.partition('.')
    if not table or not key or '.' in key:
        msg = f'{dotted!r} is not <table>.<key>'
        raise ValueError(msg)
    own = live.get(OWN_TABLE, {})
    rendered = own.get('host') and own.get('source') and table in _layered(Path(own['source']), own['host'])
    if table == OWN_TABLE or rendered:
        msg = (f'[{table}] is rendered from the config source, not a local table: change it there (family.toml or '
               f'hosts/<machine>.toml) through its pull request, then {RENDER_DOOR}')  # fmt: skip
        raise ValueError(msg)
    if table == familyrepos.LOCAL_TABLE and value is not None and not Path(value).is_absolute():
        msg = f'[{table}] {key} = {value!r} must be an absolute path'
        raise ValueError(msg)
    changed = {name: dict(rows) if isinstance(rows, Mapping) else rows for name, rows in live.items()}
    rows = changed.setdefault(table, {})
    if value is None:
        rows.pop(key, None)
    else:
        rows[key] = value
    return changed


def _local_verb(args: argparse.Namespace, path: Path, live: Mapping[str, Any]) -> int:
    value = None if args.local_verb == 'unset' else args.value
    try:
        changed = local_set(live, args.key, value)
    except ValueError as refused:
        emit(f'refused: {refused}; {path} is unchanged', err=True)
        return 2
    table, _, key = args.key.partition('.')
    before = live.get(table, {}).get(key) if isinstance(live.get(table), Mapping) else None
    own = live.get(OWN_TABLE, {})
    if own.get('host') and own.get('source'):
        text = render(Path(own['source']), own['host'], changed)
    else:  # not a render: set the one key in the text, every other line kept
        text = merged(path.read_text(encoding='utf-8') if path.is_file() else '', {table: {key: value}})
    backups = args.backups or Path('output/logs') / f'{datetime.now(UTC):%y/%m/%d}' / 'devhost'
    backup = replace_backed_up(path, text, backups)
    emit(f'local: [{table}].{key}: {before!r} -> {value!r} in {path}; the previous file is {backup}')
    return 0


def main(argv: list[str] | None = None) -> int:
    """The verbs: drift, render, detect, session-start, channels, use-store, enrol, bringup (each its help)."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.devhost', description=main.__doc__)
    parser.add_argument('--machine', type=Path, default=None, help='the machine file (default: this machine)')
    verbs = parser.add_subparsers(dest='verb', required=True)
    drifting = verbs.add_parser('drift', help='report where the machine file departs from its render')
    drifting.add_argument('--from', dest='clone', type=Path, default=None, help='the config-source clone')
    verbs.add_parser('session-start', help='the SessionStart hook: the machine-file notice, if any; always 0')
    telling = verbs.add_parser('channels', help="print this machine's declared session channels (source -> user)")
    telling.add_argument('--json', action='store_true', required=True, help='as one JSON object ({} when undeclared)')
    finding = verbs.add_parser('detect', help="print the host-file lines for this machine's vendor install homes")
    finding.add_argument('--from', dest='clone', type=Path, default=None, help='the config-source clone')
    making = verbs.add_parser('render', help='render the machine file from the family and host files')
    making.add_argument('--host', default=None, help='the host name (default: the live [devhost] host, else this one)')
    making.add_argument('--from', dest='clone', type=Path, default=None, help='the config-source clone')
    making.add_argument('--write', action='store_true', help='back the live file up, then replace it')
    making.add_argument('--backups', type=Path, default=None, help='where the backup goes (default: the output tree)')
    forgecredential.add_use_store(verbs)
    forgeenrol.add_enrol(verbs)
    checking = verbs.add_parser(
        'bringup', help='list every wall a new or migrated workstation hits, each with its door'
    )
    checking.add_argument('--check', action='store_true', required=True, help='read only; exit 1 while a wall stands')
    setting = verbs.add_parser('local', help='set or unset ONE local-layer key ([repos], [user]) and re-render')
    local_verbs = setting.add_subparsers(dest='local_verb', required=True)
    one = local_verbs.add_parser('set', help='set <table>.<key> to <value>')
    one.add_argument('key', help='<table>.<key>, e.g. repos.dev-lab')
    one.add_argument('value', help='the value; a [repos] path must be absolute')
    gone = local_verbs.add_parser('unset', help='remove <table>.<key>')
    gone.add_argument('key', help='<table>.<key>')
    for sub in (one, gone):
        sub.add_argument('--backups', type=Path, default=None, help='where the backup goes (default: the output tree)')
    args = parser.parse_args(argv)
    path = args.machine or machineconfig.config_path()
    live = read_toml(path) if path.is_file() else {}
    if args.verb == 'session-start':
        if where := familyrepos.notice():
            emit(where)  # every session starts knowing where the family's checkouts live
        if said := notice(live):
            emit(said)
        return 0
    plain = {
        'channels': lambda: _channels(live),
        'drift': lambda: _drift(path, live, args.clone),
        'use-store': lambda: forgecredential.use_declared(declared_by(live.get(OWN_TABLE, {})), args.host),
        'bringup': lambda: bringup.main(live),
        'enrol': lambda: forgeenrol.run(args, live.get(OWN_TABLE, {}), declared_by(live.get(OWN_TABLE, {}))),
    }
    if args.verb in plain:
        return plain[args.verb]()
    if args.verb == 'local':
        return _local_verb(args, path, live)
    if args.verb == 'detect':
        return _detect(_source(args.clone, live.get(OWN_TABLE, {})))
    return _render_verb(args, path, live)


if __name__ == '__main__':
    raise SystemExit(main())
