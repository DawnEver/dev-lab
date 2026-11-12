"""The CLEAR half of :mod:`dev_lab.dev.scratch`: untracked entries, the door that deletes them, the session baseline.

Split out of :mod:`dev_lab.dev.scratch` by size; that module's docstring states the contract and is the one entry
point (``python -m dev_lab.dev.scratch``). Its constants live here because this is the lower module.
"""

from __future__ import annotations

import argparse
import json
import shutil
import stat
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from lab_commons import home as _home
from lab_commons import launch
from lab_commons.log import emit

from dev_lab.dev.codeplace import PlacementNotDeclared, checkout_root, declared_placement
from dev_lab.dev.sessionprs import SESSION_ENV, session_of, valid

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from typing import TextIO

_SECONDS_PER_DAY = 86400.0
#: How many one-offs the notice names before it elides the rest.
_SHOWN = 20
#: The directory, under the machine-local state, holding each session's scratch baseline.
SESSION_DIR = 'scratch-sessions'
#: The ONE tracked file under scratch: it anchors the directory and states the two exits.
SCRATCH_README = 'README.md'


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


def _writable(func: Callable[[str], object], path: str, _exc: BaseException) -> None:
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
