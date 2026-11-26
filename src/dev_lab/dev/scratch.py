"""SCRATCH-IS-NEVER-COMMITTED: the one place an agent may leave a one-off, and its two exits.

USER RULING 2026-10-22: "scratch is tracked by git, but committing it is forbidden" -- and, the same
day, scratch is THE one place agents may dump junk so the rest of the worktree stays clean. Every
one-off leaves by one of TWO exits: PROMOTED into ``src/`` with tests when it is useful, DELETED when
it is not; a finding it produced goes to memory as numbers. ``scripts/`` is NOT an exit -- it holds
dev mechanisms only. The archive-to-memory exit this replaced is retired with no compatibility path.

VISIBLE, NEVER COMMITTED. The directory is never git-ignored (the family ``.gitignore`` bans the line),
so an untracked one-off shows in ``git status``; it is anchored by one tracked :data:`SCRATCH_README`
stating the two exits, and nothing else under it is ever committed. It is the stray census's declared
sink (:func:`dev_lab.dev.strays.stray_files`), so a one-off there is never a stray.

ONE DECLARATION, read off the repo's ``layout.toml`` by
:func:`dev_lab.dev.codeplace.declared_placement`: ``scratch`` (the directory, the family's
``scratch/`` when omitted), ``max_age`` (a duration: when the notice starts naming a one-off) and
``scratch_anchor`` (default true: the tracked README anchors it; false, user ruling 2026-11-17 "scratch
should hold nothing": no README, and the tracked set under scratch is EMPTY).

TWO ENFORCEMENT POINTS, and only the forge blocks (toolchain plan P3: a local copy of a forge check
refused the same commit twice; ``python -m dev_lab.dev.scratch check <paths>`` remains for a repo that
declares it as a row of its own, naming both exits through :func:`staged_scratch`):

* the forge body :func:`assert_scratch_never_committed` holds the TRACKED set to exactly the README
  (empty when unanchored),
  so a commit made with hooks off still reds on the forge;
* the ``SessionStart`` notice (``remind``) lists one-offs older than ``max_age`` and prints
  NOTHING when there are none -- a reminder that never blocks and costs no tokens when clean.

THE CLI, so a consumer needs no ``scripts/`` adopter: ``list`` (every untracked top-level entry, its size, age
and owner, oldest first), ``discard <paths>`` (delete one-off files; anything outside scratch, or its README, is
refused and nothing is deleted) and ``clear [NAME ...] [--keep NAME ...] [--approved WORDS] --yes`` -- THE door for
emptying scratch, named by RECURSIVE-DELETE: it deletes the named UNTRACKED top-level entries (this session's when
none is named), never a tracked file and never outside scratch, refuses the whole clear when a link or junction
inside an entry points out of scratch, and clears the read-only/hidden attributes Windows sets so a nested ``.git``
deletes. It works on a main checkout: git decides what is deletable, not the kind of checkout.

EVERY ENTRY CARRIES THE SESSION THAT MADE IT (:mod:`dev_lab.dev._scratch_owners`; 2026-11-25: a start-snapshot diff
named a live agent's entry as the stopping session's own, and ``clear`` deleted files a running agent used). The
``claim`` rows, wired by :mod:`dev_lab.dev.agent_wiring`, record it where the entry is made: before a write tool
writes under scratch, and after a shell command that spells ``<scratch>/<name>`` of a freshly born entry. So:

* ``stop`` blocks on the entries THIS session made and does not keep -- never on another session's; the integrator
  is told of the entries no live session owns, once quiet, by a detached row (:mod:`dev_lab.dev.scratchorphans`);
* ``clear`` refuses, by name and naming the owner, an entry another LIVE session owns, or one not this session's
  touched within the last half hour; the user's approval (``--approved "<the user's words>"``) is the door past it;
* ``clear --keep NAME`` marks an entry left on purpose (adopting a gone session's), so no stop names it again.
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
    ScratchEscape,
    ScratchInUse,
    _clear,
    _hook,
    clear_scratch,
    in_use,
    own_entries,
    owner_label,
    untracked_scratch,
)
from dev_lab.dev._scratch_owners import owners
from dev_lab.dev.codeplace import PRUNED_NAMES, PlacementNotDeclared, checkout_root, declared_placement
from dev_lab.dev.native_session import session_of

if TYPE_CHECKING:
    from collections.abc import Iterable
    from typing import TextIO

__all__ = [
    'SCRATCH_README',
    'ScratchCommitted',
    'ScratchEscape',
    'ScratchInUse',
    'assert_scratch_never_committed',
    'clear_scratch',
    'discard_scratch',
    'in_use',
    'main',
    'overdue_scratch',
    'own_entries',
    'pending_scratch',
    'scratch_reminder',
    'staged_scratch',
    'untracked_scratch',
]

_VERBS = frozenset({'list', 'discard', 'clear', 'remind', 'check', 'claim', 'stop'})
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


def staged_scratch(paths: Iterable[str], *, scratch: str, anchor: bool = True) -> list[str]:
    """The repo-relative POSIX *paths* under *scratch* a commit may never carry: all but an *anchor* README."""
    prefix = f'{scratch.strip("/")}/'
    kept = f'{prefix}{SCRATCH_README}' if anchor else None
    return sorted(p for p in paths if p.startswith(prefix) and p != kept)


class ScratchCommitted(AssertionError):
    """The tracked files under a repo's scratch are not exactly its README."""


def assert_scratch_never_committed(root: Path) -> None:
    """THE FORGE BODY: the tracked files under *root*'s declared scratch are exactly its README, or none.

    Anchored (the default), a missing README reds too: it keeps the directory visible, and an empty tracked
    set would read exactly like a clean one. Declared ``scratch_anchor = false``, the tracked set is EMPTY.

    Raises:
        ScratchCommitted: a one-off is committed, or the README's presence contradicts the declaration.

    """
    placement = declared_placement(root)
    scratch = placement.scratch
    done = launch.run(
        ['git', '-C', str(root), 'ls-files', '-z', '--', scratch],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=True,
    )
    tracked = set(filter(None, done.stdout.split('\0')))
    readme = f'{scratch}{SCRATCH_README}'
    want = {readme} if placement.scratch_anchor else set()
    if tracked == want:
        return
    door = (
        f'git rm --cached each one-off (then {_EXITS}); a missing README: commit {readme}, or declare '
        f'scratch_anchor = false in layout.toml so scratch holds nothing tracked'
        if placement.scratch_anchor
        else f'scratch_anchor = false in layout.toml declares no README: git rm --cached each '
        f'(a README too), then {_EXITS}'
    )
    msg = (
        f'SCRATCH-IS-NEVER-COMMITTED: the tracked files under {scratch} must be {sorted(want)}, '
        f'and are {sorted(tracked)}. {door}'
    )
    raise ScratchCommitted(msg)


def scratch_reminder(root: Path) -> str | None:
    """The SessionStart notice naming every one-off past the declared age, with both exits; ``None`` when none."""
    try:
        placement = declared_placement(root)
    except PlacementNotDeclared:
        return None
    late = overdue_scratch(root / placement.scratch, root=root, max_age_days=placement.max_age / 86400)
    if not late:
        return None
    return (
        f'SCRATCH-IS-NEVER-COMMITTED: {len(late)} one-off(s) older than {placement.max_age / 86400:g} days: '
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
        found = staged_scratch(rest, scratch=placement.scratch, anchor=placement.scratch_anchor)
        if found:
            emit(f'SCRATCH-IS-NEVER-COMMITTED: {", ".join(found)} staged; unstage (git restore --staged). {_EXITS}')
        return 1 if found else 0
    if mode == 'list':
        records, session, now = owners(root), session_of(), time.time()
        for rel, size, age in untracked_scratch(root):
            emit(f'{size:>14,}  {age:7.1f}d  {owner_label(records, rel, session, now=now):<12}  {rel}')
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
    """``python -m dev_lab.dev.scratch {list | discard | clear | remind | check | claim | stop}``.

    Exit 0 on success and from ``remind``, ``claim`` and ``stop`` always; 1 from ``check`` on a staged one-off; 2 on a
    usage error, a refused ``discard`` or ``clear``, or a ``clear`` without ``--yes``.
    """
    mode, *rest = argv or [None]
    if mode not in _VERBS:
        emit(f'usage: python -m dev_lab.dev.scratch {{{" | ".join(sorted(_VERBS))}}} [args]')
        return 2
    if mode in {'claim', 'stop'}:
        return _hook(mode, rest, stdin)
    return _remind(stdin) if mode == 'remind' else _verb(mode, rest, Path.cwd())


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
