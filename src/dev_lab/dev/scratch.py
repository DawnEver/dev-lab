"""SCRATCH-IS-NEVER-COMMITTED: the one place an agent may leave a one-off, and its two exits.

USER RULING 2026-10-22: "scratch is tracked by git, but committing it is forbidden" -- and, the same
day, scratch is THE one place agents may dump junk so the rest of the worktree stays clean. Every
one-off leaves by one of TWO exits: PROMOTED into ``src/`` with tests when it is useful, DELETED when
it is not; a finding it produced goes to memory as numbers. ``scripts/`` is NOT an exit -- it holds
dev mechanisms only. The archive-to-memory exit this replaced is retired with no compatibility path.

VISIBLE, NEVER COMMITTED. The directory is never git-ignored (the family ``.gitignore`` bans the line),
so an untracked one-off shows in ``git status``; it is anchored by one tracked :data:`SCRATCH_README`
stating the two exits, and nothing else under it is ever committed. It is the stray census's declared
sink (:func:`dev_lab.dev.codeplace.stray_files`), so a one-off there is never a stray.

ONE DECLARATION, read off the repo's ``[tool.lab_commons.placement]`` by
:func:`dev_lab.dev.codeplace.declared_placement`: ``scratch`` (the directory, the family's
``scratch/`` when omitted) and ``max_age_days`` (when the notice starts naming a one-off).

THREE ENFORCEMENT POINTS, cheapest first, and only one of them blocks:

* the ``scratch-commit`` pre-commit row (``python -m dev_lab.dev.scratch check <paths>``) refuses
  a staged path under scratch other than its README, naming both exits (:func:`staged_scratch`);
* the forge body :func:`assert_scratch_never_committed` holds the TRACKED set to exactly the README,
  so a commit made with hooks off still reds on the forge;
* the ``SessionStart`` notice (``remind``) lists one-offs older than ``max_age_days`` and prints
  NOTHING when there are none -- a reminder that never blocks and costs no tokens when clean.

THE CLI, so a consumer needs no ``scripts/`` adopter: ``pending`` (every one-off, oldest first) and
``discard <paths>`` (delete one-offs; anything outside scratch, or its README, is refused and nothing
is deleted).
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Iterable
from pathlib import Path
from typing import TextIO

from lab_commons import launch
from dev_lab.dev.codeplace import (
    PRUNED_NAMES,
    PlacementNotDeclared,
    checkout_root,
    declared_placement,
)
from lab_commons.log import emit

__all__ = [
    'SCRATCH_README',
    'ScratchCommitted',
    'assert_scratch_never_committed',
    'discard_scratch',
    'main',
    'overdue_declared',
    'overdue_scratch',
    'pending_scratch',
    'scratch_reminder',
    'staged_scratch',
]

_SECONDS_PER_DAY = 86400.0
#: How many one-offs the notice names before it elides the rest.
_SHOWN = 20
_VERBS = frozenset({'pending', 'discard', 'remind', 'check'})

#: The ONE tracked file under scratch: it anchors the directory and states the two exits.
SCRATCH_README = 'README.md'
#: The two exits, spelled once for every refusal and notice that names them.
_EXITS = (
    'PROMOTE it into src/ with tests, or DELETE it (python -m dev_lab.dev.scratch discard <path>); '
    'a finding it produced goes to memory as numbers. scripts/ is not an exit (dev mechanisms only).'
)


def pending_scratch(scratch: Path, *, root: Path, now: float | None = None) -> list[tuple[str, float]]:
    """``[(root-relative path, age in days), ...]`` of every one-off in *scratch*, oldest first; the README is none."""
    if not scratch.is_dir():
        return []
    stamp = time.time() if now is None else now
    rows = [
        (path.relative_to(root).as_posix(), (stamp - path.stat().st_mtime) / _SECONDS_PER_DAY)
        for path in scratch.rglob('*')
        if path.is_file()
        and path != scratch / SCRATCH_README
        and not PRUNED_NAMES.intersection(path.relative_to(scratch).parts)
    ]
    return sorted(rows, key=lambda row: -row[1])


def overdue_scratch(scratch: Path, *, root: Path, max_age_days: float, now: float | None = None) -> list[str]:
    """The one-offs in *scratch* older than *max_age_days*, oldest first."""
    return [path for path, age in pending_scratch(scratch, root=root, now=now) if age > max_age_days]


def overdue_declared(root: Path) -> list[str]:
    """:func:`overdue_scratch` over the scratch directory and age *root* declares."""
    placement = declared_placement(root)
    return overdue_scratch(root / placement.scratch, root=root, max_age_days=placement.max_age_days)


def staged_scratch(paths: Iterable[str], *, scratch: str) -> list[str]:
    """The repo-relative POSIX *paths* under *scratch* other than its README: what a commit may never carry."""
    prefix = f'{scratch.strip("/")}/'
    return sorted(p for p in paths if p.startswith(prefix) and p != f'{prefix}{SCRATCH_README}')


class ScratchCommitted(AssertionError):
    """The tracked files under a repo's scratch are not exactly its README."""


def assert_scratch_never_committed(root: Path) -> None:
    """THE FORGE BODY: the tracked files under *root*'s declared scratch are exactly its README.

    A missing README reds too: it is the anchor that keeps the directory visible, and an empty tracked
    set would read exactly like a clean one.

    Raises:
        ScratchCommitted: a one-off is committed, or the README is not.

    """
    scratch = declared_placement(root).scratch
    done = launch.run(
        ['git', '-C', str(root), 'ls-files', '-z', '--', scratch], capture_output=True, text=True, check=True
    )
    tracked = set(filter(None, done.stdout.split('\0')))
    readme = f'{scratch}{SCRATCH_README}'
    if tracked != {readme}:
        msg = (
            f'SCRATCH-IS-NEVER-COMMITTED: the tracked files under {scratch} must be exactly {{{readme}}}, '
            f'and are {sorted(tracked)}. A committed one-off: git rm --cached it, then {_EXITS}'
        )
        raise ScratchCommitted(msg)


def scratch_reminder(root: Path) -> str | None:
    """The SessionStart notice naming every one-off past the declared age, with both exits; ``None`` when none."""
    try:
        placement = declared_placement(root)
    except PlacementNotDeclared:
        return None
    late = overdue_scratch(root / placement.scratch, root=root, max_age_days=placement.max_age_days)
    if not late:
        return None
    return (
        f'SCRATCH-IS-NEVER-COMMITTED: {len(late)} one-off(s) older than {placement.max_age_days:g} days: '
        f'{", ".join(late[:_SHOWN])}{" ..." if len(late) > _SHOWN else ""}. For each: {_EXITS}'
    )


def discard_scratch(paths: Iterable[str], *, root: Path) -> list[str]:
    """Delete one-offs under *root*'s declared scratch, returning them repo-relative; nothing is deleted on a refusal.

    Raises:
        ValueError: a path is outside scratch, is its README, or is not a file.

    """
    scratch = (root / declared_placement(root).scratch).resolve()
    targets: list[Path] = []
    for raw in paths:
        path = Path(raw) if Path(raw).is_absolute() else root / raw
        path = path.resolve()
        if not path.is_relative_to(scratch) or path == scratch / SCRATCH_README or not path.is_file():
            msg = f'{raw}: discard deletes only a one-off file under {scratch}, never its {SCRATCH_README}'
            raise ValueError(msg)
        targets.append(path)
    for path in targets:
        path.unlink()
    return [path.relative_to(root.resolve()).as_posix() for path in targets]


def _remind(stdin: TextIO | None) -> int:
    """The ``SessionStart`` notice for the checkout the payload's ``cwd`` is in; silent when nothing is overdue."""
    try:
        payload = json.load(stdin or sys.stdin)
    except ValueError:
        payload = {}
    cwd = Path((payload if isinstance(payload, dict) else {}).get('cwd') or Path.cwd()).resolve()
    root = cwd if (cwd / '.git').exists() else checkout_root(cwd)
    notice = None if root is None else scratch_reminder(root)
    if notice is not None:
        emit(notice)
    return 0


def _verb(mode: str, rest: list[str], root: Path) -> int:
    """``pending``, ``discard <paths>`` and ``check <paths>`` over the checkout *root*."""
    try:
        placement = declared_placement(root)
    except PlacementNotDeclared as exc:
        if mode == 'check':
            return 0  # an undeclared checkout is not judged; its own placement test reds on the table
        emit(str(exc))
        return 2
    if mode == 'check':
        found = staged_scratch(rest, scratch=placement.scratch)
        if found:
            emit(f'SCRATCH-IS-NEVER-COMMITTED: {", ".join(found)} staged; unstage (git restore --staged). {_EXITS}')
        return 1 if found else 0
    if mode == 'pending':
        for rel, age in pending_scratch(root / placement.scratch, root=root):
            emit(f'{age:7.1f}d  {rel}')
        return 0
    try:
        for rel in discard_scratch(rest, root=root):
            emit(f'discarded {rel}')
    except ValueError as exc:
        emit(str(exc))
        return 2
    return 0


def main(argv: list[str] | None = None, *, stdin: TextIO | None = None) -> int:
    """``python -m dev_lab.dev.scratch {pending | discard <paths> | remind | check <paths>}``.

    Exit 0 on success and from ``remind`` always; 1 from ``check`` on a staged one-off; 2 on a usage
    error or a refused ``discard``.
    """
    mode, *rest = argv or [None]
    if mode not in _VERBS:
        emit(f'usage: python -m dev_lab.dev.scratch {{{" | ".join(sorted(_VERBS))}}} [paths]')
        return 2
    return _remind(stdin) if mode == 'remind' else _verb(mode, rest, Path.cwd())


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
