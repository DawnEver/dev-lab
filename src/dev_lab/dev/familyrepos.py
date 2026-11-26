"""FAMILY-REPO-IS-CHECKED-OUT: where every family repo lives on this machine, said at session start and enforced.

THE INCIDENT (2026-11-15). An agent did not find the agent-config checkout and cloned a SECOND copy of a family
repo beside the first, although the machine file's ``[repos]`` already named its path: nothing put ``[repos]`` in
front of the agent, and nothing refused the duplicate.

TWO FACTS, EACH IN ONE PLACE. The family's repo LIST -- each name, its remote and its integration branch -- is the
config source's family layer, ``[family_repos]`` (rendered into the machine file by :mod:`dev_lab.dev.devhost`).
Where each one is checked out is the machine's local layer, ``[repos]`` (:func:`lab_commons.home.repos`). This
module holds no list; it only compares the two:

* :func:`listing` -- one ``name -> path`` line per ``[repos]`` row, ``MISSING`` when the path is absent, printed by
  the ``SessionStart`` hook (:mod:`dev_lab.dev.venvfollow`);
* :func:`census` -- a family repo with no path and a path naming no family repo, each with its door; read by
  :func:`dev_lab.dev.devhost.drift`, so the drift notice and ``devhost drift`` both say it;
* :func:`stale_origins` -- a checkout whose ``origin`` is not the remote the family declares for it (dev-lab#46: two
  clones still pointed at a retired forge for 9 days, and the forge door blamed a missing credential), named with
  the ``remote set-url`` door; said at session start beside the listing;
* :func:`clone_refusal` -- the agent guard's ``when: 'declared-repo'`` row asks ``python -m dev_lab.dev.familyrepos
  clone-check`` (the command on stdin): a clone whose url is a family repo's remote and whose name ``[repos]``
  already maps is refused, naming the registered path. A url no family repo declares passes.

* :func:`clone_missing` -- ``python -m dev_lab.dev.familyrepos clone``: every family repo whose ``[repos]`` path holds
  no checkout is cloned THERE (its remote, its branch, with submodules, through the retry door) and given its own
  environment through ``dep --bootstrap``. A family repo with no ``[repos]`` path is named with its door, never
  placed by guess; a path holding anything is never touched.

``python -m dev_lab.dev.familyrepos [list | clone-check | clone]``; ``clone-check`` exits 1 with the refusal, ``clone``
exits 1 when any repo could not be cloned or placed, else 0.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Final, TextIO

import lab_commons.launch as _door
from lab_commons import config as machineconfig
from lab_commons.log import emit

from dev_lab.dev.disclosure import details_for
from dev_lab.dev.netverb import run_network_verb
from dev_lab.dev.venvpath import running_interpreter

__all__ = [
    'FAMILY_TABLE',
    'HAZARD',
    'LOCAL_TABLE',
    'REMEDY',
    'RULE_ID',
    'SET_DOOR',
    'census',
    'clone_missing',
    'clone_refusal',
    'listing',
    'main',
    'notice',
    'stale_origins',
]

RULE_ID: Final = 'FAMILY-REPO-IS-CHECKED-OUT'
#: The family layer's table: name -> ``{remote, branch}``.
FAMILY_TABLE: Final = 'family_repos'
#: The local layer's table: name -> absolute checkout path.
LOCAL_TABLE: Final = 'repos'
HAZARD: Final = 'a second clone of a family repo this machine already checks out splits its work between two trees.'
REMEDY: Final = (
    'Work in the registered checkout: add a worktree there (git -C <path> worktree add -b pr/<slug> '
    '.claude/worktrees/<slug> origin/<branch>). Its path is wrong? '
    '{python} -m dev_lab.dev.devhost local set repos.<name> <absolute path>.'
)
SET_DOOR: Final = f'{running_interpreter()} -m dev_lab.dev.devhost local set {LOCAL_TABLE}.<name> <absolute path>'
_UNSET_DOOR: Final = f'{running_interpreter()} -m dev_lab.dev.devhost local unset {LOCAL_TABLE}.'
_CLONE_TIMEOUT_S: Final = 1800.0
_BOOTSTRAP_TIMEOUT_S: Final = 3600
_URL: Final = re.compile(r'(?:[a-z][a-z0-9+.-]*://|[\w.-]+@[\w.-]+:)[^\s"\';&|()]+', re.IGNORECASE)


def _key(url: str) -> str:
    """A remote url as ``host/owner/name``, lower case: scheme, user, ``.git`` and a trailing slash dropped."""
    text = url.strip().lower()
    text = re.sub(r'^[a-z][a-z0-9+.-]*://', '', text)
    text = re.sub(r'^[^/@]+@', '', text).replace(':', '/', 1) if '@' in text.split('/', 1)[0] else text
    return re.sub(r'(?:\.git)?/*$', '', text)


def _family(live: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    table = live.get(FAMILY_TABLE, {})
    return {name: row for name, row in table.items() if isinstance(row, Mapping)} if isinstance(table, Mapping) else {}


def _local(live: Mapping[str, Any]) -> dict[str, str]:
    table = live.get(LOCAL_TABLE, {})
    return {name: str(path) for name, path in table.items()} if isinstance(table, Mapping) else {}


def listing(live: Mapping[str, Any]) -> list[str]:
    """One line per ``[repos]`` row: ``repo <name> -> <path>``, `` MISSING`` when nothing is there."""
    return [
        f'repo {name} -> {path}{"" if Path(path).is_dir() else " MISSING"}'
        for name, path in sorted(_local(live).items())
    ]


def census(live: Mapping[str, Any]) -> list[str]:
    """Each family repo ``[repos]`` lacks and each ``[repos]`` name no family repo is; ``[]`` with no family table."""
    family, local = _family(live), _local(live)
    if not family:
        return []
    found = [
        f'family repo {name} has no [{LOCAL_TABLE}] path: set its checkout with {SET_DOOR}, or clone '
        f'{family[name].get("remote", "<remote>")} at {family[name].get("branch", "<branch>")} first'
        for name in sorted(set(family) - set(local))
    ]
    found += [
        f'[{LOCAL_TABLE}] {name} is not a family repo ([{FAMILY_TABLE}] in the config source): declare it there '
        f'through a hosts-config pull request, or drop the row with {_UNSET_DOOR}{name}'
        for name in sorted(set(local) - set(family))
    ]
    return found


def _origin(path: Path) -> str | None:
    """The ``origin`` url of the checkout at *path*; ``None`` when it is no checkout or has no origin."""
    if not path.is_dir():
        return None
    answer = _door.run(['git', '-C', str(path), 'remote', 'get-url', 'origin'],
                       capture_output=True, text=True, check=False, timeout=30)  # fmt: skip
    return answer.stdout.strip() or None if answer.returncode == 0 else None


def stale_origins(live: Mapping[str, Any], *, origin_of: Callable[[Path], str | None] = _origin) -> list[str]:
    """Each ``[repos]`` checkout whose ``origin`` is not its family remote, with the door re-pointing it."""
    family, found = _family(live), []
    for name, path in sorted(_local(live).items()):
        declared = str(family.get(name, {}).get('remote', ''))
        origin = origin_of(Path(path)) if declared else None
        if origin is not None and _key(origin) != _key(declared):
            found.append(
                f'family repo {name} at {path}: its origin is {origin}, but the family declares {declared} -- a '
                f'forge call there reaches the wrong forge, not a missing credential; re-point it: '
                f'git -C {path} remote set-url origin {declared}'
            )
    return found


def clone_refusal(command: str, live: Mapping[str, Any]) -> str | None:
    """The refusal for *command* cloning a family repo ``[repos]`` already maps; ``None`` otherwise."""
    remotes = {_key(str(row.get('remote', ''))): name for name, row in _family(live).items()}
    local = _local(live)
    for url in _URL.findall(command):
        name = remotes.get(_key(url))
        if name is not None and name in local:
            branch = _family(live)[name].get('branch', '<branch>')
            remedy = REMEDY.replace('{python}', running_interpreter())
            where = f'{name} is already checked out at {local[name]} (branch {branch})'
            return f'{RULE_ID}: {HAZARD}\n{where}. {remedy}\n{details_for(RULE_ID)}'
    return None


def clone_missing(
    live: Mapping[str, Any],
    *,
    net: Callable[[str, str, Path], bool] | None = None,
    bootstrap: Callable[[Path], bool] | None = None,
) -> tuple[list[str], bool]:
    """Clone each family repo whose declared ``[repos]`` path is absent; ``(one line per repo acted on, all ok)``."""
    net = net or _clone
    bootstrap = bootstrap or _bootstrap
    family, local = _family(live), _local(live)
    lines: list[str] = []
    ok = True
    for name in sorted(family):
        row = family[name]
        if name not in local:
            lines.append(f'family repo {name}: no [{LOCAL_TABLE}] path declares where it goes -- {SET_DOOR}')
            ok = False
            continue
        dest = Path(local[name])
        if dest.exists():
            continue
        remote, branch = str(row.get('remote', '')), str(row.get('branch', ''))
        if not remote or not net(remote, branch, dest):
            lines.append(f'family repo {name}: clone of {remote or "<no remote>"} into {dest} failed')
            ok = False
            continue
        booted = bootstrap(dest)
        ok = ok and booted
        lines.append(f'family repo {name}: cloned into {dest}{"" if booted else "; dep --bootstrap FAILED"}')
    return lines, ok


def _clone(remote: str, branch: str, dest: Path) -> bool:
    argv = ['git', 'clone', '--recurse-submodules', *(['-b', branch] if branch else []), remote, str(dest)]
    return run_network_verb(argv, timeout=_CLONE_TIMEOUT_S).ok


def _bootstrap(dest: Path) -> bool:
    argv = [running_interpreter(), '-m', 'dev_lab.dev.dep', '--bootstrap', str(dest)]
    return _door.run(argv, cwd=dest, check=False, timeout=_BOOTSTRAP_TIMEOUT_S).returncode == 0


def notice(live: Mapping[str, Any] | None = None) -> str | None:
    """The ``SessionStart`` lines: :func:`listing` and :func:`stale_origins` of this machine's file, or ``None``."""
    try:
        read = _live(None) if live is None else live
        lines = listing(read) + stale_origins(read)
    except (OSError, ValueError):
        return None
    return '\n'.join(lines) or None


def _live(machine: Path | None) -> dict[str, Any]:
    path = machine or machineconfig.config_path()
    return tomllib.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}


def main(argv: list[str] | None = None, *, stdin: TextIO | None = None) -> int:
    """``list`` (default): the ``[repos]`` lines and the census; ``clone-check``: exit 1 with the refusal."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.familyrepos', description=main.__doc__)
    parser.add_argument('--machine', type=Path, default=None, help='the machine file (default: this machine)')
    parser.add_argument('verb', nargs='?', choices=('list', 'clone-check', 'clone'), default='list')
    args = parser.parse_args(argv)
    try:
        live = _live(args.machine)
    except (OSError, ValueError) as unreadable:  # a guard that cannot read the file refuses nothing
        emit(f'family repos unread: {unreadable}', err=True)
        return 0
    if args.verb == 'clone':
        lines, ok = clone_missing(live)
        for line in lines:
            emit(line)
        return 0 if ok else 1
    if args.verb == 'clone-check':
        refused = clone_refusal((stdin or sys.stdin).read(), live)
        if refused is not None:
            emit(refused)
        return 1 if refused is not None else 0
    for line in [*listing(live), *census(live)]:
        emit(line)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
