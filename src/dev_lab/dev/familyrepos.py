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
* :func:`clone_refusal` -- the agent guard's ``when: 'declared-repo'`` row asks ``python -m dev_lab.dev.familyrepos
  clone-check`` (the command on stdin): a clone whose url is a family repo's remote and whose name ``[repos]``
  already maps is refused, naming the registered path. A url no family repo declares passes.

``python -m dev_lab.dev.familyrepos [list | clone-check]``; ``clone-check`` exits 1 with the refusal, else 0.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final, TextIO

from lab_commons import config as machineconfig
from lab_commons.log import emit

from dev_lab.dev.disclosure import details_for
from dev_lab.dev.venvpath import running_interpreter

__all__ = [
    'FAMILY_TABLE',
    'HAZARD',
    'LOCAL_TABLE',
    'REMEDY',
    'RULE_ID',
    'SET_DOOR',
    'census',
    'clone_refusal',
    'declaration',
    'listing',
    'main',
    'manifest_text',
    'notice',
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


def notice(live: Mapping[str, Any] | None = None) -> str | None:
    """The ``SessionStart`` lines: :func:`listing` of this machine's file; ``None`` when it maps no repo."""
    try:
        lines = listing(_live(None) if live is None else live)
    except (OSError, ValueError):
        return None
    return '\n'.join(lines) or None


def declaration(remote: str, live: Mapping[str, Any]) -> str:
    """The ``[tool.dev_lab.*]`` text the family row for *remote* implies (``''`` when no row names it).

    A repo with no manifest of its own (a data repo) is declared once, by its family row: its ``branch`` is both
    its trunk and its integration branch; the branch set's other keys keep their family defaults.
    """
    wanted = _key(remote)
    for row in _family(live).values():
        branch = str(row.get('branch', '')).strip()
        if branch and _key(str(row.get('remote', ''))) == wanted:
            return (
                f'[tool.dev_lab.branchset]\ntrunk = "{branch}"\nsessions = []\n\n'
                f'[tool.dev_lab.integrator]\nintegration = "{branch}"\n'
            )
    return ''


def manifest_text(root: Path) -> tuple[str, str]:
    """*root*'s ``pyproject.toml`` text and name; with none, its family row's :func:`declaration` and its source.

    No manifest and no row: ``''`` and a name pointing at both doors, so each reader refuses naming them.
    """
    manifest = root / 'pyproject.toml'
    if manifest.is_file():
        return manifest.read_text(encoding='utf-8'), str(manifest)
    from dev_lab.dev.checkout import git_out  # noqa: PLC0415 -- only a repo with no manifest asks git

    remote = (git_out(root, 'remote', 'get-url', 'origin') or '').strip()
    try:
        text = declaration(remote, _live(None)) if remote else ''
    except (OSError, ValueError):
        text = ''
    if text:
        return text, f'[{FAMILY_TABLE}] row for {remote} in {machineconfig.config_path()}'
    return '', f'{manifest} (or a [{FAMILY_TABLE}] row for this repo in the config source)'


def _live(machine: Path | None) -> dict[str, Any]:
    path = machine or machineconfig.config_path()
    return tomllib.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}


def main(argv: list[str] | None = None, *, stdin: TextIO | None = None) -> int:
    """``list`` (default): the ``[repos]`` lines and the census; ``clone-check``: exit 1 with the refusal."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.familyrepos', description=main.__doc__)
    parser.add_argument('--machine', type=Path, default=None, help='the machine file (default: this machine)')
    parser.add_argument('verb', nargs='?', choices=('list', 'clone-check'), default='list')
    args = parser.parse_args(argv)
    try:
        live = _live(args.machine)
    except (OSError, ValueError) as unreadable:  # a guard that cannot read the file refuses nothing
        emit(f'family repos unread: {unreadable}', err=True)
        return 0
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
