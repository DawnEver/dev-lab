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

import argparse
import json
import shutil
import stat
import sys
import time
from collections.abc import Iterable
from pathlib import Path
from typing import TextIO

from lab_commons import home as _home
from lab_commons import launch
from lab_commons.log import emit

from dev_lab.dev.codeplace import (
    PRUNED_NAMES,
    PlacementNotDeclared,
    checkout_root,
    declared_placement,
)
from dev_lab.dev.sessionprs import SESSION_ENV, session_of, valid

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

_SECONDS_PER_DAY = 86400.0
#: How many one-offs the notice names before it elides the rest.
_SHOWN = 20
_VERBS = frozenset({'list', 'discard', 'clear', 'remind', 'check', 'snapshot', 'stop'})
#: The directory, under the machine-local state, holding each session's scratch baseline.
SESSION_DIR = 'scratch-sessions'

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


class ScratchEscape(ValueError):
    """A link or junction inside a scratch entry points outside scratch: nothing is cleared."""


def _is_link(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def _size(path: Path) -> int:
    """The bytes at or under *path*, never following a link."""
    if _is_link(path) or not path.is_dir():
        return path.lstat().st_size
    return sum(p.lstat().st_size for p in path.rglob('*') if not _is_link(p) and p.is_file())


def untracked_scratch(root: Path) -> list[tuple[str, int, float]]:
    """``[(root-relative path, bytes, age in days), ...]`` of every UNTRACKED top-level scratch entry, oldest first.

    An entry holding any tracked file is tracked, and the README anchor is never an entry. Git decides, so a
    main checkout and a linked worktree are judged alike.
    """
    rel = declared_placement(root).scratch.strip('/')
    scratch = root / rel
    if not scratch.is_dir():
        return []
    done = launch.run(
        ['git', '-C', str(root), 'ls-files', '-z', '--', rel],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=True,
    )
    tracked = {path[len(rel) + 1 :].split('/')[0] for path in filter(None, done.stdout.split('\0'))}
    now = time.time()
    rows = [
        (f'{rel}/{entry.name}', _size(entry), (now - entry.lstat().st_mtime) / _SECONDS_PER_DAY)
        for entry in scratch.iterdir()
        if entry.name not in tracked and entry.name != SCRATCH_README
    ]
    return sorted(rows, key=lambda row: -row[2])


def _escapes(entry: Path, scratch: Path) -> list[Path]:
    """Every link or junction under the directory *entry* whose target lies outside *scratch*."""
    found = []
    stack = list(entry.iterdir()) if entry.is_dir() and not _is_link(entry) else []
    while stack:
        path = stack.pop()
        if _is_link(path):
            if not path.resolve().is_relative_to(scratch):
                found.append(path)
        elif path.is_dir():
            stack.extend(path.iterdir())
    return found


def _writable(func, path, _exc) -> None:  # noqa: ANN001 -- shutil's onexc signature
    """The tree delete's error hook: clear read-only (and Windows hidden/system) attributes, then retry once."""
    if sys.platform == 'win32':
        launch.run(['attrib', '-R', '-H', '-S', str(path)], check=False, capture_output=True)
    Path(path).chmod(stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
    func(path)


def _name(entry: str) -> str:
    """A top-level entry's name from *entry*, given bare, as ``scratch/<name>`` or with a trailing slash."""
    return entry.strip('/\\').replace('\\', '/').split('/')[-1]


def clear_scratch(root: Path, names: Iterable[str]) -> list[str]:
    """Delete the untracked top-level scratch entries of *root* named in *names*; return them root-relative.

    A link or junction entry is unlinked, never followed. Nothing is deleted when a link inside an entry
    escapes scratch, or when a name is no untracked entry (a tracked file never is one).

    Raises:
        ScratchEscape: a name is no untracked entry, or a link inside an entry points outside scratch.

    """
    scratch = (root / declared_placement(root).scratch).resolve()
    entries = {_name(rel): rel for rel, _, _ in untracked_scratch(root)}
    wanted = list(dict.fromkeys(_name(name) for name in names))
    if missing := [name for name in wanted if name not in entries]:
        msg = f'{missing}: not an untracked entry of scratch (tracked, or absent); nothing cleared'
        raise ScratchEscape(msg)
    doomed = [(entries[name], root / entries[name]) for name in wanted]
    if escaping := [link for _, path in doomed for link in _escapes(path, scratch)]:
        shown = ', '.join(link.relative_to(root).as_posix() for link in escaping)
        msg = f'{shown}: a link inside scratch points outside it; nothing cleared. Ask the user before removing it.'
        raise ScratchEscape(msg)
    for _, path in doomed:
        if path.is_junction():
            path.rmdir()
        elif path.is_symlink():
            path.unlink()
        elif not path.is_dir():
            path.chmod(stat.S_IWRITE | stat.S_IREAD)
            path.unlink()
        else:
            shutil.rmtree(path, onexc=_writable)
    return [rel for rel, _ in doomed]


def _session_file(session: str) -> Path | None:
    """Where *session*'s scratch baselines live, under the machine-local state; ``None`` for an invalid id."""
    return _home.part('state') / SESSION_DIR / f'{session}.json' if valid(session) else None


def _read(session: str) -> dict:
    path = _session_file(session)
    try:
        data = json.loads(path.read_text(encoding='utf-8')) if path else {}
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(session: str, data: dict) -> None:
    path = _session_file(session)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=1, sort_keys=True), encoding='utf-8')


def snapshot(root: Path, session: str) -> None:
    """Record *root*'s untracked scratch entries as *session*'s baseline, once; a later call keeps the first."""
    data = _read(session)
    if str(root) not in data:
        data[str(root)] = {'before': sorted(_name(rel) for rel, _, _ in untracked_scratch(root)), 'kept': []}
        _write(session, data)


def session_entries(root: Path, session: str) -> list[str] | None:
    """The untracked entries *session* left in *root*'s scratch and did not keep; ``None`` with no baseline."""
    seen = _read(session).get(str(root))
    if not isinstance(seen, dict):
        return None
    old = set(seen.get('before', ())) | set(seen.get('kept', ()))
    return [rel for rel, _, _ in untracked_scratch(root) if _name(rel) not in old]


def _keep(root: Path, session: str, names: Iterable[str]) -> None:
    """Acknowledge *names* as entries *session* leaves in *root*'s scratch on purpose."""
    data = _read(session)
    seen = data.setdefault(str(root), {'before': [], 'kept': []})
    seen['kept'] = sorted({*seen.get('kept', ()), *(_name(name) for name in names)})
    _write(session, data)


def _clear_hint(rels: list[str]) -> str:
    """The ``Stop`` block naming this session's untracked entries and the door that empties them."""
    shown = ', '.join(rels[:_SHOWN]) + (' ...' if len(rels) > _SHOWN else '')
    return (
        f'SCRATCH-IS-NEVER-COMMITTED: this session left {len(rels)} untracked scratch entr'
        f'{"y" if len(rels) == 1 else "ies"}: {shown}.\nPromote what is useful into src/ with tests (a finding '
        'into memory), then python -m dev_lab.dev.scratch clear [--keep NAME ...] --yes'
    )


def _hooked(stdin: TextIO | None) -> tuple[Path, str] | None:
    """The checkout and session a hook payload names; ``None`` when it names neither or declares no placement."""
    try:
        payload = json.load(stdin or sys.stdin)
    except ValueError:
        return None
    if not isinstance(payload, dict) or payload.get('stop_hook_active') or not valid(str(payload.get('session_id'))):
        return None
    cwd = Path(payload.get('cwd') or Path.cwd()).resolve()
    root = cwd if (cwd / '.git').exists() else checkout_root(cwd)
    if root is None:
        return None
    try:
        declared_placement(root)
    except PlacementNotDeclared:
        return None
    return root, str(payload['session_id'])


def _hook(mode: str, stdin: TextIO | None) -> int:
    """``snapshot`` (SessionStart) records the baseline; ``stop`` blocks once on what this session left."""
    hooked = _hooked(stdin)
    if hooked is None:
        return 0
    root, session = hooked
    left = session_entries(root, session) if mode == 'stop' else None
    if left is None:
        snapshot(root, session)  # a session with no baseline yet is judged from now on
    elif left:
        emit(json.dumps({'decision': 'block', 'reason': _clear_hint(left)}))
    return 0


def _clear(rest: list[str], root: Path) -> int:
    """``clear [NAME ...] [--keep NAME ...] [--yes]``: the names, else this session's entries; ``--yes`` deletes."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.scratch clear', exit_on_error=False)
    parser.add_argument('names', nargs='*', metavar='NAME')
    parser.add_argument('--keep', nargs='+', action='extend', default=[], metavar='NAME')
    parser.add_argument('--yes', action='store_true')
    try:
        args = parser.parse_args(rest)
    except argparse.ArgumentError as exc:
        emit(str(exc))
        return 2
    session = session_of()
    if args.keep and session:
        _keep(root, session, args.keep)
    left = args.names or (session_entries(root, session) if session else None)
    if left is None:
        emit(f'no scratch snapshot for this session ({SESSION_ENV}): name the entries to clear')
        return 2
    kept = {_name(name) for name in args.keep}
    names = [name for name in left if _name(name) not in kept]
    if names and not args.yes:
        emit(f'would clear: {", ".join(names)}; re-run with --yes to delete them')
        return 2
    try:
        for rel in clear_scratch(root, names):
            emit(f'cleared {rel}')
    except ScratchEscape as exc:
        emit(str(exc))
        return 2
    return 0


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
