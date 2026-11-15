"""A DEVELOPMENT machine is declared like a server, and its machine file is a RENDER of the declaration.

The config-source repository (``[ops.config] source``) holds the family file and one host file per machine. Three
layers, one way, each fact in one place:

1. FAMILY (``family.toml``): every fact all machines share -- machine-file tables as they are read
   (``[hpc]``, ``[ai_lab]``, ``[consent]``, ``[breakglass]``, ``[ssh]`` ...) and the shared ``[dev]`` keys;
2. HOST (``hosts/<name>.toml``): one machine's facts -- ``[dev]`` and the :data:`MACHINE_TABLES` it reads;
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

:func:`render` = family ⊕ host ⊕ local, with a header naming the sources and their digests and a ``[devhost]``
table naming the host and the clone. :func:`drift` compares the live file with that render, and its ``[repos]
dev-lab`` checkout's branch with ``ref``; the ``SessionStart`` notice (:func:`notice`) runs it with no network.

``python -m dev_lab.dev.devhost drift`` -- read only, exit 1 on drift: each drifted KEY with the layer owning it and
that layer's door, then the family-repo census (:func:`dev_lab.dev.familyrepos.census`);
``python -m dev_lab.dev.devhost local set|unset <table>.<key> [value]`` -- the ONE door into the local layer
(``[repos]``, ``[user]``): it refuses a rendered table, backs the file up, re-renders and prints what changed. Every
other write is refused by MACHINE-FILE-IS-RENDERED (:mod:`dev_lab.dev.machineguard`);
``python -m dev_lab.dev.devhost render --host NAME --from CLONE [--write]`` -- prints the render; ``--write``
refuses a render that does not parse, else backs the live file up under the output tree and replaces it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tomllib
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from lab_commons import config as machineconfig
from lab_commons.log import emit

from dev_lab.dev import familyrepos
from dev_lab.dev._machinefile import dumps, merged, render_value
from dev_lab.dev.checkout import git_out
from dev_lab.dev.devschema import CHANNELS_TABLE, channel_defects, fill_remedy, hpc_reach, unfilled
from dev_lab.dev.venvpath import running_interpreter

__all__ = [
    'LOCAL_DOOR', 'OWN_TABLE', 'RENDER_DOOR', 'config_source', 'declared', 'declared_channels', 'detect', 'drift',
    'host_file', 'local_set', 'main', 'notice', 'render', 'stop_block',
]  # fmt: skip

#: The render's own table: which host and clone it came from.
OWN_TABLE: Final = 'devhost'
#: A key one side lacks (``None`` is not a TOML value, but a sentinel says so outright).
_ABSENT: Final = object()


def _read(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_text(encoding='utf-8'))


def declared(host_file: Path, family_file: Path) -> dict[str, Any]:
    """The effective ``[dev]``: the family's under the host's."""
    shared = _read(family_file).get('dev', {}) if family_file.is_file() else {}
    return _merge(shared, _read(host_file).get('dev', {}))


def _merge(under: Mapping[str, Any], over: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(under)
    for key, value in over.items():
        both = isinstance(value, Mapping) and isinstance(out.get(key), Mapping)
        out[key] = _merge(out[key], value) if both else value
    return out


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def host_file(host: str) -> str:
    """Where *host*'s declaration lives in the config source, relative to its root."""
    return f'hosts/{host}.toml'


def _sources(clone: Path, host: str) -> tuple[Path, Path]:
    return clone / 'family.toml', clone / host_file(host)


def config_source(live: Mapping[str, Any] | None = None) -> str:
    """The config source's forge URL: the ``origin`` of the clone the machine file's ``[devhost]`` names.

    Raises:
        ValueError: the machine file is not a render (no ``[devhost] source``), the source is relative (it would
            follow the CWD to another clone, #556), or that clone has no ``origin``.

    """
    own = (machineconfig.machine() if live is None else live).get(OWN_TABLE, {})
    if not own.get('source'):
        msg = f'the machine file has no [{OWN_TABLE}] source: render it (devhost render --host NAME --from CLONE)'
        raise ValueError(msg)
    if not Path(own['source']).is_absolute():
        msg = (f"the machine file's [{OWN_TABLE}] source {own['source']!r} is relative, so it would resolve against "
               f"the current directory and read another clone's origin: re-render it with an absolute clone -- "
               f"devhost render --host {own.get('host') or 'NAME'} --from <absolute clone> --write")  # fmt: skip
        raise ValueError(msg)
    url = git_out(Path(own['source']), 'remote', 'get-url', 'origin')
    if not url:
        msg = f'{own["source"]} has no origin remote: the config source is unknown here'
        raise ValueError(msg)
    return url.strip()


def render(clone: Path, host: str, live: Mapping[str, Any]) -> str:
    """The machine file for *host*: family ⊕ host (``[dev]`` aside) ⊕ the *live* file's local-only tables."""
    family_file, host_file = _sources(clone, host)
    family, declared = _read(family_file), _read(host_file)
    layered = _merge({k: v for k, v in family.items() if k != 'dev'}, {k: v for k, v in declared.items() if k != 'dev'})
    vendors = declared.get('dev', {}).get('vendors', {})
    seats = {name: {'seats': vendor['seats']} for name, vendor in vendors.items() if vendor.get('seats')}
    layered = _merge(layered, {'capabilities': seats} if seats else {})
    layered = _merge(layered, {'hpc': {'reach': hpc_reach(declared.get('dev', {}))}} if 'hpc' in layered else {})
    if channels := declared.get('dev', {}).get('channels'):
        layered = _merge(layered, {CHANNELS_TABLE: {'channels': channels}})
    local = {k: v for k, v in live.items() if k not in layered and k != OWN_TABLE}
    own = {OWN_TABLE: {'host': host, 'source': clone.resolve().as_posix()}}  # absolute: never the reader's CWD (#556)
    header = (
        f'# RENDERED by python -m dev_lab.dev.devhost render --host {host}: edit the sources, not this file.\n'
        f'# family.toml sha256:{_digest(family_file)}; hosts/{host}.toml sha256:{_digest(host_file)}; '
        f'this machine keeps {sorted(local)}.\n\n'
    )
    return header + dumps({**layered, **local, **own})


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


def drift(live: Mapping[str, Any]) -> list[str]:
    """Where the *live* machine file departs from its render, and its dev-lab checkout from the declared ref."""
    own = live.get(OWN_TABLE, {})
    if not own.get('host') or not own.get('source'):
        return []
    clone, host = Path(own['source']), own['host']
    rendered, have = _leaves(tomllib.loads(render(clone, host, live))), _leaves(live)
    found = [
        f'{_dotted(path)} is {"absent" if path not in have else "not the render"} -- {_owner(path, clone, host)}'
        for path in sorted(set(rendered) | set(have))
        if rendered.get(path, _ABSENT) != have.get(path, _ABSENT)
    ]
    family_file, own_file = _sources(clone, host)
    dev = declared(own_file, family_file)
    if names := unfilled(dev):
        found.insert(0, fill_remedy(names))
    found += familyrepos.census(live)
    checkout = live.get('repos', {}).get('dev-lab')
    if (want := dev.get('ref')) and checkout and (on := _branch(checkout)) not in {want, None}:
        found.append(f'the dev-lab checkout is on {on!r}, declared ref {want!r}')
    return found


def _leaves(table: Mapping[str, Any], prefix: tuple[str, ...] = ()) -> dict[tuple[str, ...], Any]:
    """Every leaf key of *table* by its path; a list, a scalar or an empty table is a leaf."""
    out: dict[tuple[str, ...], Any] = {}
    for key, value in table.items():
        if isinstance(value, Mapping) and value:
            out.update(_leaves(value, (*prefix, key)))
        else:
            out[(*prefix, key)] = value
    return out


def _dotted(path: tuple[str, ...]) -> str:
    return f'[{path[0]}]' + ''.join(f'.{part}' for part in path[1:])


def _owner(path: tuple[str, ...], clone: Path, host: str) -> str:
    """The layer owning the key at *path*, and that layer's door."""
    if path[0] == OWN_TABLE:
        return f'the render itself: {RENDER_DOOR}'
    edit = f'change it there through its pull request, then {RENDER_DOOR}'
    family_file, own_file = _sources(clone, host)
    for layer, source in (('host', own_file), ('family', family_file)):
        tables = {k: v for k, v in (_read(source) if source.is_file() else {}).items() if k != 'dev'}
        if any(path[: len(key)] == key or key[: len(path)] == path for key in _leaves(tables)):
            return f'{layer} layer ({source.relative_to(clone).as_posix()}): {edit}'
    if path[0] in _layered(clone, host):
        return f'host layer ({host_file(host)} [dev], rendered): {edit}'
    return f'local layer: {LOCAL_DOOR}'


def _layered(clone: Path, host: str) -> set[str]:
    """The tables the family and host layers render; every other table is local."""
    return set(tomllib.loads(render(clone, host, {}))) - {OWN_TABLE}


def notice(live: Mapping[str, Any] | None = None) -> str | None:
    """One SessionStart line when the machine file drifted from its render; else ``None`` (or not a render)."""
    try:
        found = drift(machineconfig.machine() if live is None else live)
    except (OSError, tomllib.TOMLDecodeError):
        return None
    first = [line for line in found if line.startswith('install home not filled')]
    rest = [line for line in found if line not in first]
    lines = [f'HOST-CONFIG FIRST: {line}' for line in first]
    if rest:
        drifted = '; '.join(rest)
        lines.append(f'HOST-CONFIG: the machine file drifted from its render: {drifted}. Re-render: {RENDER_DOOR}')
    return '\n'.join(lines) or None


def _own_dev(live: Mapping[str, Any]) -> dict[str, Any]:
    own = live.get(OWN_TABLE, {})
    if not own.get('host') or not own.get('source'):
        return {}
    family_file, host_file = _sources(Path(own['source']), own['host'])
    return declared(host_file, family_file)


def stop_block(payload: Mapping[str, Any], live: Mapping[str, Any], marks: Path) -> str | None:
    """The ``Stop`` hook's reason to block, ONCE per session, while this machine's host file holds an unfilled home."""
    session = str(payload.get('session_id') or '')
    try:
        names = unfilled(_own_dev(live))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    mark = marks / session
    if not names or not session or mark.exists() or payload.get('stop_hook_active'):
        return None
    marks.mkdir(parents=True, exist_ok=True)
    mark.touch()
    return f'Before you stop: {fill_remedy(names)}.'


def _matches(pattern: str) -> list[Path]:
    anchored = Path(pattern)
    return list(Path(anchored.anchor).glob(str(anchored.relative_to(anchored.anchor))))


def detect(patterns: Mapping[str, list[str]]) -> dict[str, str]:
    """Each vendor's install home on THIS machine: the last (newest-named) directory its patterns match."""
    found = {}
    for name, globs in patterns.items():
        hits = sorted({hit for pattern in globs for hit in _matches(pattern) if hit.is_dir()})
        if hits:
            found[name] = hits[-1].as_posix()
    return found


#: The door that re-renders this machine's file from its recorded host and clone.
RENDER_DOOR: Final = f'{running_interpreter()} -m dev_lab.dev.devhost render --write'
#: The door that sets one key of the machine's own (local) layer.
LOCAL_DOOR: Final = f'{running_interpreter()} -m dev_lab.dev.devhost local set <table>.<key> <value>'


def _replace(path: Path, text: str, backups: Path) -> Path:
    backups.mkdir(parents=True, exist_ok=True)
    backup = backups / f'{path.name}.{datetime.now(UTC):%Y%m%dT%H%M%SZ}'
    if path.is_file():
        backup.write_bytes(path.read_bytes())
    staged = path.with_name(f'{path.name}.{os.getpid()}.tmp')
    staged.write_text(text, encoding='utf-8')
    staged.replace(path)
    return backup


def _source(clone: Path | None, own: Mapping[str, Any]) -> Path | None:
    return clone or (Path(own['source']) if own.get('source') else None)


def _stop(path: Path, live: Mapping[str, Any]) -> int:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    marks = path.parent.parent / 'state' / 'devhost-stop'
    if isinstance(payload, dict) and (reason := stop_block(payload, live, marks)):
        emit(json.dumps({'decision': 'block', 'reason': reason}))
    return 0


def _drift(path: Path, live: Mapping[str, Any]) -> int:
    found = drift(live)
    for line in found:
        emit(f'drift: {line}')
    if not found:
        emit(f'agrees: {path} is its render' if live.get(OWN_TABLE) else f'{path} is not a render')
    return 1 if found else 0


def _detect(source: Path | None) -> int:
    if source is None:
        emit('refused: detect needs --from (no [devhost] in the machine file)', err=True)
        return 2
    homes = detect(_read(source / 'family.toml').get('dev', {}).get('detect', {}))
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
    host, clone = args.host or own.get('host'), _source(args.clone, own)
    if not host or clone is None:
        emit('refused: render needs --host and --from (no [devhost] in the machine file)', err=True)
        return 2
    text = render(clone, host, live)
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
    emit(f'rendered {path}; the previous file is {_replace(path, text, backups)}')
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
    backup = _replace(path, text, backups)
    emit(f'local: [{table}].{key}: {before!r} -> {value!r} in {path}; the previous file is {backup}')
    return 0


def main(argv: list[str] | None = None) -> int:
    """``drift`` (read only; exit 1 on drift), ``render`` (``--write`` backs up), ``detect``, ``stop``, ``channels``."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.devhost', description=main.__doc__)
    parser.add_argument('--machine', type=Path, default=None, help='the machine file (default: this machine)')
    verbs = parser.add_subparsers(dest='verb', required=True)
    verbs.add_parser('drift', help='report where the machine file departs from its render')
    verbs.add_parser('stop', help='the Stop hook: block once per session while an install home is unfilled')
    telling = verbs.add_parser('channels', help="print this machine's declared session channels (source -> user)")
    telling.add_argument('--json', action='store_true', required=True, help='as one JSON object ({} when undeclared)')
    finding = verbs.add_parser('detect', help="print the host-file lines for this machine's vendor install homes")
    finding.add_argument('--from', dest='clone', type=Path, default=None, help='the config-source clone')
    making = verbs.add_parser('render', help='render the machine file from the family and host files')
    making.add_argument('--host', default=None, help='the host name (default: the live [devhost] host)')
    making.add_argument('--from', dest='clone', type=Path, default=None, help='the config-source clone')
    making.add_argument('--write', action='store_true', help='back the live file up, then replace it')
    making.add_argument('--backups', type=Path, default=None, help='where the backup goes (default: the output tree)')
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
    live = _read(path) if path.is_file() else {}
    if args.verb == 'stop':
        return _stop(path, live)
    if args.verb == 'channels':
        return _channels(live)
    if args.verb == 'drift':
        return _drift(path, live)
    if args.verb == 'local':
        return _local_verb(args, path, live)
    if args.verb == 'detect':
        return _detect(_source(args.clone, live.get(OWN_TABLE, {})))
    return _render_verb(args, path, live)


if __name__ == '__main__':
    raise SystemExit(main())
