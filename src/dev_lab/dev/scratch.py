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

ONE DECLARATION, read off the repo's ``[tool.dev_lab.placement]`` by
:func:`dev_lab.dev.codeplace.declared_placement`: ``scratch`` (the directory, the family's
``scratch/`` when omitted) and ``max_age_days`` (when the notice starts naming a one-off).

TWO ENFORCEMENT POINTS, and only the forge blocks (toolchain plan P3: a local copy of a forge check
refused the same commit twice; ``python -m dev_lab.dev.scratch check <paths>`` remains for a repo that
declares it as a row of its own, naming both exits through :func:`staged_scratch`):

* the forge body :func:`assert_scratch_never_committed` holds the TRACKED set to exactly the README,
  so a commit made with hooks off still reds on the forge;
* the ``SessionStart`` notice (``remind``) lists one-offs older than ``max_age_days`` and prints
  NOTHING when there are none -- a reminder that never blocks and costs no tokens when clean.

THE CLI, so a consumer needs no ``scripts/`` adopter: ``list`` (every untracked top-level entry, its size
and age, oldest first), ``discard <paths>`` (delete one-off files; anything outside scratch, or its README,
is refused and nothing is deleted) and ``clear [NAME ...] [--keep NAME ...] --yes`` -- THE door for emptying
scratch, named by RECURSIVE-DELETE: it deletes the named UNTRACKED top-level entries (this session's when none
is named), never a tracked file and never outside scratch, refuses the whole clear when a link or junction
inside an entry points out of scratch, and clears the read-only/hidden attributes Windows sets so a nested
``.git`` deletes. It works on a main checkout: git decides what is deletable, not the kind of checkout.

THIS SESSION'S LEFTOVERS ONLY (``snapshot`` at SessionStart, ``stop`` at Stop, both wired by
:mod:`dev_lab.dev.agent_wiring`): the start records the checkout's untracked entries under the machine-local
state, keyed by session id; the stop blocks once on an entry new since then -- nothing else ever cleared one,
so they piled up across sessions -- and never on one that predates the session or another session made.
``clear --keep NAME`` acknowledges one; ``clear`` with no names takes this session's entries
(``CLAUDE_CODE_SESSION_ID``), anything else only by name.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from lab_commons import launch
from lab_commons.log import emit

from dev_lab.dev._scratch_clear import (
    _SECONDS_PER_DAY,
    _SHOWN,
    SCRATCH_README,
    SESSION_DIR,
    ScratchEscape,
    _clear,
    _hook,
    clear_scratch,
    session_entries,
    snapshot,
    untracked_scratch,
)
from dev_lab.dev.codeplace import PRUNED_NAMES, PlacementNotDeclared, checkout_root, declared_placement

if TYPE_CHECKING:
    from collections.abc import Iterable
    from typing import TextIO

__all__ = [
    'SCRATCH_README',
    'SESSION_DIR',
    'ScratchCommitted',
    'ScratchEscape',
    'assert_scratch_never_committed',
    'clear_scratch',
    'discard_scratch',
    'main',
    'overdue_declared',
    'overdue_scratch',
    'pending_scratch',
    'scratch_reminder',
    'session_entries',
    'snapshot',
    'staged_scratch',
    'untracked_scratch',
]

_VERBS = frozenset({'list', 'discard', 'clear', 'remind', 'check', 'snapshot', 'stop'})
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
        ['git', '-C', str(root), 'ls-files', '-z', '--', scratch],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=True,
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
    """``list``, ``discard <paths>``, ``clear`` and ``check <paths>`` over the checkout *root*."""
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
    if mode == 'list':
        for rel, size, age in untracked_scratch(root):
            emit(f'{size:>14,}  {age:7.1f}d  {rel}')
    if mode in {'list', 'clear'}:
        return _clear(rest, root) if mode == 'clear' else 0
    try:
        for rel in discard_scratch(rest, root=root):
            emit(f'discarded {rel}')
    except ValueError as exc:
        emit(str(exc))
        return 2
    return 0


def main(argv: list[str] | None = None, *, stdin: TextIO | None = None) -> int:
    """``python -m dev_lab.dev.scratch {list | discard | clear | remind | check | stop}``.

    Exit 0 on success and from ``remind`` and ``stop`` always; 1 from ``check`` on a staged one-off; 2 on a
    usage error, a refused ``discard`` or ``clear``, or a ``clear`` without ``--yes``.
    """
    mode, *rest = argv or [None]
    if mode not in _VERBS:
        emit(f'usage: python -m dev_lab.dev.scratch {{{" | ".join(sorted(_VERBS))}}} [args]')
        return 2
    if mode in {'snapshot', 'stop'}:
        return _hook(mode, stdin)
    return _remind(stdin) if mode == 'remind' else _verb(mode, rest, Path.cwd())


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
