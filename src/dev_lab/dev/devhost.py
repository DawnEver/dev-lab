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

from dev_lab.dev._machinefile import dumps, render_value
from dev_lab.dev.checkout import git_out
from dev_lab.dev.devschema import fill_remedy, unfilled
from dev_lab.dev.venvpath import running_interpreter

__all__ = ['OWN_TABLE', 'RENDER_DOOR', 'declared', 'detect', 'drift', 'main', 'notice', 'render', 'stop_block']

#: The render's own table: which host and clone it came from.
OWN_TABLE: Final = 'devhost'


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
    return (git_out(Path(checkout), 'symbolic-ref', '--short', 'HEAD') or '').strip() or None


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
    dev = declared(host_file, family_file)
    if names := unfilled(dev):
        found.insert(0, fill_remedy(names))
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
    backups = args.backups or Path('output/logs') / f'{datetime.now(UTC):%y/%m/%d}' / 'devhost'
    emit(f'rendered {path}; the previous file is {_replace(path, text, backups)}')
    return 0


def main(argv: list[str] | None = None) -> int:
    """``drift`` (read only; exit 1 on drift), ``render`` (``--write`` backs up first), ``detect``, ``stop``."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.devhost', description=main.__doc__)
    parser.add_argument('--machine', type=Path, default=None, help='the machine file (default: this machine)')
    verbs = parser.add_subparsers(dest='verb', required=True)
    verbs.add_parser('drift', help='report where the machine file departs from its render')
    verbs.add_parser('stop', help='the Stop hook: block once per session while an install home is unfilled')
    finding = verbs.add_parser('detect', help="print the host-file lines for this machine's vendor install homes")
    finding.add_argument('--from', dest='clone', type=Path, default=None, help='the config-source clone')
    making = verbs.add_parser('render', help='render the machine file from the family and host files')
    making.add_argument('--host', default=None, help='the host name (default: the live [devhost] host)')
    making.add_argument('--from', dest='clone', type=Path, default=None, help='the config-source clone')
    making.add_argument('--write', action='store_true', help='back the live file up, then replace it')
    making.add_argument('--backups', type=Path, default=None, help='where the backup goes (default: the output tree)')
    args = parser.parse_args(argv)
    path = args.machine or machineconfig.config_path()
    live = _read(path) if path.is_file() else {}
    if args.verb == 'stop':
        return _stop(path, live)
    if args.verb == 'drift':
        return _drift(path, live)
    if args.verb == 'detect':
        return _detect(_source(args.clone, live.get(OWN_TABLE, {})))
    return _render_verb(args, path, live)


if __name__ == '__main__':
    raise SystemExit(main())
