"""The CLEAR half of :mod:`dev_lab.dev.scratch`: untracked entries, their owners, the door that deletes them, the hooks.

Split out of :mod:`dev_lab.dev.scratch` by size; that module's docstring states the contract and is the one entry
point (``python -m dev_lab.dev.scratch``). Its constants live here because this is the lower module; who made each
entry is :mod:`dev_lab.dev._scratch_owners`.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import shutil
import stat
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Final

from lab_commons import launch
from lab_commons.log import emit

from dev_lab.dev import walls
from dev_lab.dev._scratch_owners import (
    CLAIM_WINDOW_S,
    RECENT_S,
    Owner,
    beat,
    born,
    claim,
    heard,
    live,
    named,
    owners,
    record,
    release,
    touched,
)
from dev_lab.dev.codeplace import PlacementNotDeclared, checkout_root, declared_placement
from dev_lab.dev.hpcaccount.session import INTEGRATOR, held
from dev_lab.dev.native_session import session_of, valid

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping
    from typing import TextIO

_SECONDS_PER_DAY = 86400.0
RULE: Final = 'SCRATCH-IS-NEVER-COMMITTED'
#: How many one-offs the notice names before it elides the rest.
_SHOWN = 20
#: The ONE tracked file under scratch: it anchors the directory and states the two exits.
SCRATCH_README = 'README.md'
_DOOR: Final = 'python -m dev_lab.dev.scratch clear'


class ScratchEscape(ValueError):
    """A link or junction inside a scratch entry points outside scratch: nothing is cleared."""


class ScratchInUse(ValueError):
    """A named entry belongs to another live session or was touched within the hour's half: nothing is cleared."""


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


def _minutes(seconds: float) -> str:
    return f'{seconds / 60:.0f} min'


def in_use(root: Path, rel: str, session: str, records: Mapping[str, Owner], *, now: float) -> str | None:
    """Why *session* may not clear entry *rel* without the user's approval; ``None`` when it may.

    Its own entry it always may. Another LIVE session's never; anyone else's (a gone session's, or one no session
    claimed) once it has been quiet :data:`RECENT_S` -- a fresh one is somebody's work in progress.
    """
    owner = records.get(_name(rel))
    if owner is not None and owner.session == session:
        return None
    if owner is not None and live(owner.session, now=now):
        return (
            f'{rel} belongs to live session {owner.session} (heard {_minutes(now - (heard(owner.session) or now))} ago)'
        )
    quiet = now - touched(root / rel)
    if quiet < RECENT_S:
        return f'{rel} was touched {_minutes(quiet)} ago, so it is in use (quiet {_minutes(RECENT_S)} frees it)'
    return None


def clear_scratch(
    root: Path, names: Iterable[str], *, session: str = '', approved: str = '', now: float | None = None
) -> list[str]:
    """Delete the untracked top-level scratch entries of *root* named in *names*; return them root-relative.

    A link or junction entry is unlinked, never followed. Nothing is deleted when a name is no untracked entry (a
    tracked file never is one), when a link inside an entry escapes scratch, or -- unless the user *approved* it, in
    their words -- when an entry is in use by anyone but *session* (:func:`in_use`).

    Raises:
        ScratchEscape: a name is no untracked entry, or a link inside an entry points outside scratch.
        ScratchInUse: an entry is another live session's, or freshly touched, and no approval names the user's words.

    """
    scratch = (root / declared_placement(root).scratch).resolve()
    entries = {_name(rel): rel for rel, _, _ in untracked_scratch(root)}
    wanted = list(dict.fromkeys(_name(name) for name in names))
    if missing := [name for name in wanted if name not in entries]:
        msg = f'{missing}: not an untracked entry of scratch (tracked, or absent); nothing cleared'
        raise ScratchEscape(msg)
    records = owners(root)
    stamp = time.time() if now is None else now
    if not approved.strip() and (
        busy := [why for name in wanted if (why := in_use(root, entries[name], session, records, now=stamp))]
    ):
        msg = (
            f'{RULE}: nothing cleared -- {"; ".join(busy)}. Leave it to its owner (its own Stop names it), or wait '
            f'until it has been quiet {_minutes(RECENT_S)}; if the user approves removing it, re-run naming it with '
            f'--approved "<the user\'s words>"'
        )
        raise ScratchInUse(msg)
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
    release(root, wanted)
    return [rel for rel, _ in doomed]


def _by_owner(root: Path, session: str, *, now: float) -> tuple[list[str], list[tuple[str, Owner | None]]]:
    """*root*'s untracked entries *session* made and does not keep, and those no live session owns or keeps."""
    records = owners(root)
    mine: list[str] = []
    loose: list[tuple[str, Owner | None]] = []
    for rel, _, _ in untracked_scratch(root):
        owner = records.get(_name(rel))
        if owner is not None and owner.session == session:
            mine += [] if owner.kept else [rel]
        elif owner is None or not (owner.kept or live(owner.session, now=now)):
            loose.append((rel, owner))
    return mine, loose


def own_entries(root: Path, session: str) -> list[str]:
    """The untracked entries of *root*'s scratch *session* made and does not keep, oldest first."""
    return _by_owner(root, session, now=time.time())[0]


def _shown(rels: list[str]) -> str:
    return ', '.join(rels[:_SHOWN]) + (' ...' if len(rels) > _SHOWN else '')


def _plural(rels: list) -> str:
    return f'{len(rels)} untracked scratch entr{"y" if len(rels) == 1 else "ies"}'


def _stop_hint(mine: list[str], orphans: list[tuple[str, Owner | None]]) -> str:
    """The ``Stop`` block naming this session's entries, and the integrator's ownerless ones, with their doors."""
    lines = []
    if mine:
        lines.append(
            f'{RULE}: this session left {_plural(mine)}: {_shown(mine)}.\nPromote what is useful into src/ with tests '
            f'(a finding into memory), then {_DOOR} [--keep NAME ...] --yes'
        )
    if orphans:
        whose = [f'{rel} ({f"gone session {o.session}" if o else "no recorded owner"})' for rel, o in orphans]
        lines.append(
            f'{RULE}: as the integrator: {_plural(whose)} of no live session, quiet {_minutes(RECENT_S)}: '
            f'{_shown(whose)}.\nPromote what is useful, then {_DOOR} NAME ... --yes, or --keep NAME to leave it'
        )
    return '\n'.join(lines)


def integrator(session: str) -> bool:
    """Whether *session* holds the integrator role (:mod:`dev_lab.dev.hpcaccount.session`)."""
    return INTEGRATOR in held(session=session)


def _root_of(path: Path) -> tuple[Path, str] | None:
    """The checkout holding *path* and its declared scratch; ``None`` outside one or with no placement."""
    root = path if (path / '.git').exists() else checkout_root(path)
    if root is None:
        return None
    try:
        return root, declared_placement(root).scratch.strip('/')
    except PlacementNotDeclared:
        return None


def _claim(kind: str, payload: dict, session: str) -> None:
    """Claim for *session* the scratch entries its tool call names: a write by path, a shell command by spelling."""
    tool = payload.get('tool_input') or {}
    now = time.time()
    if kind == 'shell':
        found = _root_of(Path(payload.get('cwd') or Path.cwd()).resolve())
        if found is None:
            return
        root, rel = found
        names = named(str(tool.get('command') or ''), rel)
    else:
        raw = tool.get('file_path') or tool.get('notebook_path')
        if not raw:
            return
        target = Path(raw) if Path(raw).is_absolute() else Path(payload.get('cwd') or Path.cwd()) / raw
        found = _root_of(target.resolve().parent)
        if found is None:
            return
        root, rel = found
        inside = target.resolve().relative_to(root.resolve()).parts
        prefix = tuple(rel.split('/'))
        names = {inside[len(prefix)]} if len(inside) > len(prefix) and inside[: len(prefix)] == prefix else set()
    for name in names - {SCRATCH_README}:
        path = root / rel / name
        if not (path.exists() or path.is_symlink()):
            if kind == 'write':  # before the write: it is about to make the entry
                claim(root, name, session, now=now)
        elif now - born(path) <= CLAIM_WINDOW_S:
            claim(root, name, session, now=now)


def _payload(stdin: TextIO | None) -> dict | None:
    try:
        payload = json.load(stdin or sys.stdin)
    except ValueError:
        return None
    if not isinstance(payload, dict) or not valid(str(payload.get('session_id'))):
        return None
    return payload


def _hook(mode: str, rest: list[str], stdin: TextIO | None) -> int:
    """``claim write|shell`` records who made an entry; ``stop`` blocks on what this session (or no live one) left."""
    payload = _payload(stdin)
    if payload is None:
        return 0
    session = str(payload['session_id'])
    beat(session)
    if mode == 'claim':
        # a claim is bookkeeping: an unreadable path or placement leaves the entry ownerless, never a fault
        with contextlib.suppress(OSError, ValueError):
            _claim(rest[0] if rest else '', payload, session)
        return 0
    found = None if payload.get('stop_hook_active') else _root_of(Path(payload.get('cwd') or Path.cwd()).resolve())
    if found is None:
        return 0
    root, now = found[0], time.time()
    mine, loose = _by_owner(root, session, now=now)
    # the role check reads credentials and the walk reads whole trees: both only when something is loose
    orphans = (
        [(rel, o) for rel, o in loose if now - touched(root / rel) >= RECENT_S] if loose and integrator(session) else []
    )
    if mine or orphans:
        hint = _stop_hint(mine, orphans)
        walls.refused_text(root, hint, reason='stop', rule=RULE, session=session)
        emit(json.dumps({'decision': 'block', 'reason': hint}))
    return 0


def _keep(root: Path, session: str, names: Iterable[str]) -> str | None:
    """Mark *names* as entries *session* leaves on purpose, adopting a gone one's; the refusal, else ``None``."""
    entries = {_name(rel) for rel, _, _ in untracked_scratch(root)}
    records, now = owners(root), time.time()
    wanted = [_name(name) for name in names]
    if missing := [name for name in wanted if name not in entries]:
        return f'{missing}: not an untracked entry of scratch (tracked, or absent); nothing kept'
    theirs = [
        f'{name} ({o.session})'
        for name in wanted
        if (o := records.get(name)) and o.session != session and live(o.session, now=now)
    ]
    if theirs:
        return f'{RULE}: {", ".join(theirs)} belong to another live session, whose own Stop names them; nothing kept'
    for name in wanted:
        record(root, name, Owner(session, now, kept=True))
    return None


def _kept_or_refused(args: argparse.Namespace, root: Path, session: str) -> str | None:
    """Record ``--keep``; the refusal of the whole verb, else ``None``."""
    if args.approved is not None and not args.approved.strip():
        return "--approved takes the user's own words approving the removal; an empty approval approves nothing"
    if args.keep and not session:
        return 'no native session: --keep records which session keeps an entry'
    if args.keep:
        return _keep(root, session, args.keep)
    if not args.names and not session:
        return "no native session, so no entry is this session's: name the entries to clear"
    return None


def _clear(rest: list[str], root: Path) -> int:
    """``clear [NAME ...] [--keep NAME ...] [--approved WORDS] [--yes]``: the names, else this session's entries."""
    parser = argparse.ArgumentParser(prog=_DOOR, exit_on_error=False)
    parser.add_argument('names', nargs='*', metavar='NAME')
    parser.add_argument('--keep', nargs='+', action='extend', default=[], metavar='NAME')
    parser.add_argument('--approved', default=None, metavar='WORDS', help="the user's words approving the removal")
    parser.add_argument('--yes', action='store_true')
    try:
        args = parser.parse_args(rest)
    except argparse.ArgumentError as exc:
        emit(str(exc))
        return 2
    session = session_of()
    if session:
        beat(session)
    if refused := _kept_or_refused(args, root, session):
        emit(refused)
        return 2
    left = args.names or own_entries(root, session)
    kept = {_name(name) for name in args.keep}
    names = [name for name in left if _name(name) not in kept]
    if names and not args.yes:
        emit(f'would clear: {", ".join(names)}; re-run with --yes to delete them')
        return 2
    try:
        for rel in clear_scratch(root, names, session=session, approved=args.approved or ''):
            emit(f'cleared {rel}' + (f' (approved: {args.approved})' if args.approved else ''))
    except (ScratchEscape, ScratchInUse) as exc:
        emit(str(exc))
        return 2
    return 0


def owner_label(records: Mapping[str, Owner], rel: str, session: str, *, now: float) -> str:
    """Whose entry *rel* is, for ``list``: ``this``, ``live <id>``, ``gone <id>`` (``+kept``), or ``-``."""
    owner = records.get(_name(rel))
    if owner is None:
        return '-'
    who = (
        'this' if owner.session == session else f'{"live" if live(owner.session, now=now) else "gone"} {owner.session}'
    )
    return who + (' +kept' if owner.kept else '')
