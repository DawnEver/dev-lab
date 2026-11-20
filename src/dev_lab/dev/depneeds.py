"""ON-DEMAND EXTRAS (D78): a part's needs name the extras its tests import; a missing one is refused with its door.

A worktree's environment holds the base dependencies and the extras the repo DECLARES
(``[tool.dev_lab.dep] extras``); nothing else is installed by default. The declaration has ONE reader,
:mod:`lab_commons.extras`: this door, CI's per-part sync (``flags``), the cluster build and a research job all
derive their extras from it.
A test that needs more says so by its resource marker -- the need-set its part is named for
(:mod:`lab_commons.hpc.needsets`) -- and the repo maps a need to the extra that serves it, once, beside its extras::

    [tool.dev_lab.dep]
    extras = ["dev"]
    needs = { simba = "simba" }

``verify --part <part>`` asks :func:`missing_for_part` before it runs: every need of the part that maps to an
extra whose requirements are not installed in this interpreter refuses the run BY NAME, with the exact sync that
adds it -- the declared extras plus the missing one, because an explicit ``--extra`` list narrows the sync.
Refusing (not installing) keeps every environment change behind the one ``dep`` door.

LIMITS, STATED: a requirement carrying an environment marker is not judged (this module evaluates no markers), so
it never makes an extra look missing; a targeted selection with no ``--part`` carries no need-set before
collection and is not checked.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tomllib
from collections.abc import Callable, Mapping, Sequence
from importlib import metadata
from pathlib import Path
from typing import Final

from lab_commons import extras
from lab_commons.hpc.needsets import BASE
from lab_commons.log import emit

from dev_lab.dev import taskbinding
from dev_lab.dev.partrows import needs_of_row

__all__ = ['bound_task_extras', 'declared_needs', 'extras_for', 'flags', 'main', 'missing_for_part', 'task_needs']

#: A requirement's distribution name: the leading identifier, before extras, versions, URLs or markers.
_NAME: Final = re.compile(r'\s*([A-Za-z0-9][A-Za-z0-9._-]*)')


def _installed(name: str) -> bool:
    try:
        metadata.distribution(name)
    except metadata.PackageNotFoundError:
        return False
    return True


def _manifest(root: Path) -> dict[str, object]:
    """*root*'s parsed pyproject; a root with no manifest declares nothing."""
    path = root / 'pyproject.toml'
    return tomllib.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}


def declared_needs(root: Path) -> dict[str, str]:
    """``[tool.dev_lab.dep] needs``: need -> extra, read by the ONE reader :func:`lab_commons.extras.declared`."""
    return dict(extras.declared(_manifest(root), str(root / 'pyproject.toml')).needs)


def missing_for_part(root: Path, part: str, *, installed: Callable[[str], bool] = _installed) -> str | None:
    """The refusal naming the sync door when *part*'s needs map to an extra not installed here, else ``None``."""
    manifest = _manifest(root)
    found = extras.declared(manifest, str(root / 'pyproject.toml'))
    needs, available = found.needs, manifest.get('project', {}).get('optional-dependencies', {})
    wanted = [needs[need] for need in part.split('+') if need and need != BASE and need in needs]
    missing = [
        extra for extra in dict.fromkeys(wanted) if not all(installed(name) for name in _names(available[extra]))
    ]
    if not missing:
        return None
    flags = ' '.join(f'--extra {extra}' for extra in dict.fromkeys([*found.extras, *missing]))
    need_list = ', '.join(repr(extra) for extra in missing)
    return (
        f'verify: refused -- part {part} needs extra {need_list}, not installed in this environment '
        f'(D78: extras are installed on demand); add it: python -m dev_lab.dev.dep --sync {root} {flags}'
    )


#: The frontmatter line a task record declares its needs on: ``needs: [simba, windows]`` (D79).
_NEEDS_LINE: Final = re.compile(r'^needs:\s*(.*?)\s*$', re.MULTILINE)
_NEED: Final = re.compile(r'[a-z0-9][a-z0-9_-]*')
#: The line that closes a frontmatter block.
_FENCE: Final = '\n---'


def task_needs(ledger: Path, task: str) -> tuple[str, ...]:
    """The needs the task record ``<ledger>/<slug>/TASK.md`` declares in its frontmatter (D79), else ``()``.

    A TASK DECLARES THE NEEDS ITS WORK EXERCISES -- the same need names its tests' resource markers carry -- never
    an extra: which extra serves a need is the REPO's fact (:func:`declared_needs`), stated once. A line that is no
    ``[a, b]`` list of need names is refused by name, so a typo never silently installs nothing.
    """
    record = Path(ledger) / task.split('@', 1)[0] / 'TASK.md'
    text = record.read_text(encoding='utf-8') if record.is_file() else ''
    front = text[3:].partition(_FENCE)[0] if text.startswith('---') else ''
    found = _NEEDS_LINE.search(front)
    if found is None:
        return ()
    value = found.group(1)
    names = [part.strip() for part in value.strip('[]').split(',')] if value.startswith('[') else None
    if names is None or not value.endswith(']') or any(not _NEED.fullmatch(name) for name in names if name):
        msg = f'{record}: needs must be a list of need names, e.g. needs: [simba, windows] -- got {value!r}'
        raise ValueError(msg)
    return tuple(name for name in names if name)


def extras_for(root: Path, needs: tuple[str, ...]) -> tuple[str, ...]:
    """The extras a sync of *root* selects for *needs* (:func:`lab_commons.extras.extras_for`, the one rule)."""
    return extras.extras_for(_manifest(root), needs, str(root / 'pyproject.toml'))


def flags(root: Path, part: str) -> str:
    """The ``uv sync`` extra flags an environment of *root* for *part* (a need-set name) selects."""
    return ' '.join(f'--extra {extra}' for extra in extras_for(root, tuple(sorted(needs_of_row(part)))))


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m dev_lab.dev.depneeds flags --root R --part P``: print the part's extra flags (CI's sync)."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.depneeds', description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='verb', required=True)
    flag = sub.add_parser('flags', help="the part's `--extra` flags: the declared extras plus its needs' extras")
    flag.add_argument('--root', type=Path, default=Path.cwd())
    flag.add_argument('--part', default=BASE, help=f'a need-set name (default {BASE})')
    args = parser.parse_args(argv)
    try:
        emit(flags(args.root, args.part))
    except (ValueError, TypeError) as refused:
        emit(f'depneeds: refused -- {refused}', err=True)
        return 2
    return 0


def _names(requirements: list[str]) -> list[str]:
    """Distribution names of *requirements*, skipping any with an environment marker (not evaluated here)."""
    return [m.group(1) for req in requirements if ';' not in req and (m := _NAME.match(req))]


def bound_task_extras(root: Path, env: Mapping[str, str] | None = None) -> tuple[str, ...] | None:
    """The extras the session's bound task asks for through its declared needs (D79), else ``None`` (the default).

    An explicit ``--extra`` still overrides. No bound session, or a task declaring no needs, keeps the repo's
    declared extras (``None`` lets :func:`~dev_lab.dev._dep_project.read_project` read them).
    """
    try:
        bound = taskbinding.session_binding(os.environ if env is None else env, start=root)
    except (OSError, ValueError, subprocess.CalledProcessError):
        return None
    if bound is None:
        return None
    needs = task_needs(bound.ledger, bound.task)
    return extras_for(root, needs) if needs else None


if __name__ == '__main__':
    sys.exit(main())
