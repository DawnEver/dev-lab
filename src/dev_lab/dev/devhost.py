"""A DEVELOPMENT machine is declared like a server, and its machine file is a RENDER of the declaration.

The config-source repository (``[ops.config] source``) holds the family file and one host file per machine. Three
layers, one way, each fact in one place:

1. FAMILY (``family.toml``): every fact all machines share -- machine-file tables as they are read
   (``[hpc]``, ``[ai_lab]``, ``[consent]``, ``[breakglass]``, ``[ssh]`` ...) and the shared ``[dev]`` keys;
2. HOST (``hosts/<name>.toml``): one machine's facts -- ``[dev]`` and the :data:`MACHINE_TABLES` it reads;
3. LOCAL: what stays on the machine -- every table of the live file neither layer declares (``[repos]`` paths,
   personal ``[user]`` preferences), preserved by the render, never invented. Credentials are in no layer: a path
   may be declared, a value never.

A host file restating a family key is refused (:func:`check`). ``[dev]`` (:data:`SCHEMA`): ``role``
(:data:`ROLES`), ``ref`` (the dev-lab ref followed), ``forges`` (forge host -> account names), ``os``,
``resources`` (:data:`RESOURCES`; :func:`usable` is the part this user holds), ``vendors.<name>`` (:data:`VENDOR`),
``detect`` (vendor -> install-home glob patterns, family-wide). ``[dev]`` is not rendered itself; a vendor's
``seats > 0`` renders as ``[capabilities.<vendor>] seats``, its one consumer-facing copy.

Install homes are found ON each machine: ``detect`` globs the family's patterns locally and prints the host-file
lines to propose through a pull request; a vendor with seats and no ``home`` is named by the drift notice.

:func:`render` = family ⊕ host ⊕ local, with a header naming the sources and their digests and a ``[devhost]``
table naming the host and the clone. :func:`drift` compares the live file with that render, and its ``[repos]
dev-lab`` checkout's branch with ``ref``; the ``SessionStart`` notice (:func:`notice`) runs it with no network.

``python -m dev_lab.dev.devhost drift`` -- read only, exit 1 on drift;
``python -m dev_lab.dev.devhost render --host NAME --from CLONE [--write]`` -- prints the render; ``--write``
backs the live file up under the output tree, then replaces it.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import os
import subprocess
import tomllib
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from lab_commons import config as machineconfig
from lab_commons.log import emit

from dev_lab.dev._machinefile import render_value

__all__ = [
    'MACHINE_TABLES', 'RESOURCES', 'ROLES', 'SCHEMA', 'VENDOR', 'check', 'check_family', 'detect', 'drift', 'dumps',
    'main', 'notice', 'render', 'usable',
]  # fmt: skip

#: What a development machine does.
ROLES: Final = ('integrator', 'workstation')
#: One vendor install's keys.
VENDOR: Final = {'seats': int, 'version': str, 'home': str, 'licence_server': str, 'licence_feature': str}
#: Every ``[dev]`` key and its type; ``vendors`` and ``forges`` are tables of named entries.
SCHEMA: Final = {
    'role': str, 'ref': str, 'os': str, 'forges': dict, 'vendors': dict, 'resources': dict, 'detect': dict,
}  # fmt: skip
#: The box's hardware; a SHARED box also declares the part this user holds (``allotted_*``), read before the total.
RESOURCES: Final = {
    'cpu': str, 'cores': int, 'logical_cores': int, 'memory_gb': (int, float), 'gpu': str, 'shared': bool,
    'allotted_cores': int, 'allotted_memory_gb': (int, float),
}  # fmt: skip
#: Keys the family and host ``[dev]`` must hold between them.
REQUIRED: Final = ('ref',)
#: The machine-file tables a host file may declare for its machine (each open: its consumer owns its keys).
MACHINE_TABLES: Final = ('capabilities', 'serve', 'reserve', 'workstation')
#: The render's own table: which host and clone it came from.
OWN_TABLE: Final = 'devhost'


def _read(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_text(encoding='utf-8'))


def _typed(table: Mapping[str, Any], schema: Mapping[str, Any], where: str) -> list[str]:
    found = []
    for key, value in table.items():
        if key not in schema:
            found.append(f'{where}.{key} is not a declared key')
        elif not isinstance(value, schema[key]) or (isinstance(value, bool) and schema[key] is not bool):
            found.append(f'{where}.{key} must be {getattr(schema[key], "__name__", "a number")}')
    return found


def _shape(table: Mapping[str, Any], where: str) -> list[str]:
    """Defects of one ``[dev]`` table (host or family) by itself."""
    found = _typed(table, SCHEMA, where)
    if 'role' in table and table['role'] not in ROLES:
        found.append(f'{where}.role {table["role"]!r} is not one of {list(ROLES)}')
    forges = table.get('forges') if isinstance(table.get('forges'), dict) else {}
    for forge, accounts in forges.items():
        if not (isinstance(accounts, list) and accounts and all(isinstance(a, str) for a in accounts)):
            found.append(f'{where}.forges.{forge} must be a non-empty list of account names')
    if isinstance(resources := table.get('resources'), dict):
        found += _typed(resources, RESOURCES, f'{where}.resources')
    elif 'resources' in table:
        found.append(f'{where}.resources must be a table')
    detects = table.get('detect') if isinstance(table.get('detect'), dict) else {}
    for name, patterns in detects.items():
        if not (isinstance(patterns, list) and patterns and all(isinstance(p, str) for p in patterns)):
            found.append(f'{where}.detect.{name} must be a non-empty list of glob patterns')
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
    """Defects of the family file's ``[dev]`` by itself."""
    return _shape(family.get('dev', {}), '[dev]')


def usable(dev: Mapping[str, Any]) -> tuple[int | None, float | None]:
    """The cores and memory (GB) this user may use: a shared box's allotment, else the box's own; ``None`` unknown.

    A shared box with no declared allotment is unknown, never its total.
    """
    resources = dev.get('resources', {})
    if resources.get('shared'):
        return resources.get('allotted_cores'), resources.get('allotted_memory_gb')
    return resources.get('cores'), resources.get('memory_gb')


def _merge(under: Mapping[str, Any], over: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(under)
    for key, value in over.items():
        both = isinstance(value, Mapping) and isinstance(out.get(key), Mapping)
        out[key] = _merge(out[key], value) if both else value
    return out


def _is_tables(value: object) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(v, Mapping) for v in value)


def _key(key: str) -> str:
    return key if key.replace('_', '').replace('-', '').isalnum() else render_value(key)


def _table(lines: list[str], name: str, table: Mapping[str, Any]) -> None:
    scalars = {k: v for k, v in table.items() if not isinstance(v, Mapping) and not _is_tables(v)}
    if name and (scalars or not table):
        lines += ['', f'[{name}]']
    lines += [f'{_key(k)} = {render_value(v)}' for k, v in scalars.items()]
    for key, value in table.items():
        dotted = f'{name}.{_key(key)}' if name else _key(key)
        if isinstance(value, Mapping):
            _table(lines, dotted, value)
        elif _is_tables(value):
            for item in value:
                lines += ['', f'[[{dotted}]]']
                lines += [f'{_key(k)} = {render_value(v)}' for k, v in item.items()]


def dumps(table: Mapping[str, Any]) -> str:
    """*table* as TOML (the machine file's value shapes: scalars, lists, tables, arrays of tables)."""
    lines: list[str] = []
    _table(lines, '', table)
    return '\n'.join(lines).lstrip('\n') + '\n'


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def _sources(clone: Path, host: str) -> tuple[Path, Path]:
    return clone / 'family.toml', clone / 'hosts' / f'{host}.toml'


def render(clone: Path, host: str, live: Mapping[str, Any]) -> str:
    """The machine file for *host*: family ⊕ host (``[dev]`` aside) ⊕ the *live* file's local-only tables."""
    family_file, host_file = _sources(clone, host)
    family, declared = _read(family_file), _read(host_file)
    layered = _merge({k: v for k, v in family.items() if k != 'dev'}, {k: v for k, v in declared.items() if k != 'dev'})
    vendors = declared.get('dev', {}).get('vendors', {})
    seats = {name: {'seats': vendor['seats']} for name, vendor in vendors.items() if vendor.get('seats')}
    layered = _merge(layered, {'capabilities': seats} if seats else {})
    local = {k: v for k, v in live.items() if k not in layered and k != OWN_TABLE}
    own = {OWN_TABLE: {'host': host, 'source': clone.as_posix()}}
    header = (
        f'# RENDERED by python -m dev_lab.dev.devhost render --host {host}: edit the sources, not this file.\n'
        f'# family.toml sha256:{_digest(family_file)}; hosts/{host}.toml sha256:{_digest(host_file)}; '
        f'this machine keeps {sorted(local)}.\n\n'
    )
    return header + dumps({**layered, **local, **own})


def _branch(checkout: str) -> str | None:
    done = subprocess.run(
        ['git', '-C', checkout, 'symbolic-ref', '--short', 'HEAD'],  # noqa: S607
        capture_output=True, text=True, encoding='utf-8', check=False,
    )  # fmt: skip
    return (done.stdout.strip() or None) if done.returncode == 0 else None


def drift(live: Mapping[str, Any]) -> list[str]:
    """Where the *live* machine file departs from its render, and its dev-lab checkout from the declared ref."""
    own = live.get(OWN_TABLE, {})
    if not own.get('host') or not own.get('source'):
        return []
    clone, host = Path(own['source']), own['host']
    rendered = tomllib.loads(render(clone, host, live))
    found = [
        f'[{key}] is {"absent" if key not in live else "not the render"}'
        for key in sorted(set(rendered) | set(live))
        if rendered.get(key) != live.get(key)
    ]
    family_file, host_file = _sources(clone, host)
    dev = _merge(_read(family_file).get('dev', {}), _read(host_file).get('dev', {}))
    found += [
        f'home not declared for {name}; run {DETECT_DOOR}'
        for name, vendor in dev.get('vendors', {}).items()
        if vendor.get('seats') and not vendor.get('home')
    ]
    checkout = live.get('repos', {}).get('dev-lab')
    if (want := dev.get('ref')) and checkout and (have := _branch(checkout)) not in {want, None}:
        found.append(f'the dev-lab checkout is on {have!r}, declared ref {want!r}')
    return found


def notice(live: Mapping[str, Any] | None = None) -> str | None:
    """One SessionStart line when the machine file drifted from its render; else ``None`` (or not a render)."""
    try:
        found = drift(machineconfig.machine() if live is None else live)
    except (OSError, tomllib.TOMLDecodeError):
        return None
    if not found:
        return None
    return f'HOST-CONFIG: the machine file drifted from its render: {"; ".join(found)}. Re-render: {RENDER_DOOR}'


#: The door that finds this machine's vendor install homes.
DETECT_DOOR: Final = 'python -m dev_lab.dev.devhost detect'


def detect(patterns: Mapping[str, list[str]]) -> dict[str, str]:
    """Each vendor's install home on THIS machine: the last (newest-named) directory its patterns match."""
    found = {}
    for name, globs in patterns.items():
        hits = sorted({hit for pattern in globs for hit in glob.glob(pattern) if Path(hit).is_dir()})  # noqa: PTH207 -- absolute patterns
        if hits:
            found[name] = Path(hits[-1]).as_posix()
    return found


#: The door that re-renders this machine's file from its recorded host and clone.
RENDER_DOOR: Final = 'python -m dev_lab.dev.devhost render --write'


def _replace(path: Path, text: str, backups: Path) -> Path:
    backups.mkdir(parents=True, exist_ok=True)
    backup = backups / f'{path.name}.{datetime.now(UTC):%Y%m%dT%H%M%SZ}'
    if path.is_file():
        backup.write_bytes(path.read_bytes())
    staged = path.with_name(f'{path.name}.{os.getpid()}.tmp')
    staged.write_text(text, encoding='utf-8')
    staged.replace(path)
    return backup


def main(argv: list[str] | None = None) -> int:
    """``drift`` (read only; exit 1 on drift) or ``render`` (prints; ``--write`` backs up, then replaces)."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.devhost', description=main.__doc__)
    parser.add_argument('--machine', type=Path, default=None, help='the machine file (default: this machine)')
    verbs = parser.add_subparsers(dest='verb', required=True)
    verbs.add_parser('drift', help='report where the machine file departs from its render')
    making = verbs.add_parser('render', help='render the machine file from the family and host files')
    finding = verbs.add_parser('detect', help="print the host-file lines for this machine's vendor install homes")
    finding.add_argument('--from', dest='clone', type=Path, default=None, help='the config-source clone')
    making.add_argument('--host', default=None, help='the host name (default: the live [devhost] host)')
    making.add_argument('--from', dest='clone', type=Path, default=None, help='the config-source clone')
    making.add_argument('--write', action='store_true', help='back the live file up, then replace it')
    making.add_argument('--backups', type=Path, default=None, help='where the backup goes (default: the output tree)')
    args = parser.parse_args(argv)
    path = args.machine or machineconfig.config_path()
    live = _read(path) if path.is_file() else {}
    if args.verb == 'drift':
        found = drift(live)
        for line in found:
            emit(f'drift: {line}')
        if not found:
            emit(f'agrees: {path} is its render' if live.get(OWN_TABLE) else f'{path} is not a render')
        return 1 if found else 0
    own = live.get(OWN_TABLE, {})
    if args.verb == 'detect':
        source = args.clone or (Path(own['source']) if own.get('source') else None)
        if source is None:
            emit('refused: detect needs --from (no [devhost] in the machine file)', err=True)
            return 2
        homes = detect(_read(source / 'family.toml').get('dev', {}).get('detect', {}))
        for name, home in homes.items():
            emit(f'[dev.vendors.{name}]\nhome = {render_value(home)}\n')
        if not homes:
            emit('no declared vendor pattern matched on this machine')
        return 0
    host, clone = args.host or own.get('host'), args.clone or (Path(own['source']) if own.get('source') else None)
    if not host or clone is None:
        emit('refused: render needs --host and --from (no [devhost] in the machine file)', err=True)
        return 2
    text = render(clone, host, live)
    if not args.write:
        emit(text)
        return 0
    backups = args.backups or Path('output/logs') / f'{datetime.now(UTC):%y/%m/%d}' / 'devhost'
    emit(f'rendered {path}; the previous file is {_replace(path, text, backups)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
