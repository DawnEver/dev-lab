"""THE ``clear`` VERB: its command line over :func:`dev_lab.dev._scratch_clear.clear_scratch`.

Split from :mod:`dev_lab.dev._scratch_clear` by size when issue dev-lab#1124 (2026-11-28) gave it ``--all`` and a
report of what a no-names clear left; :mod:`dev_lab.dev.scratch`'s docstring states the contract.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import TYPE_CHECKING

from lab_commons.log import emit

from dev_lab.dev._scratch_clear import (
    DOOR,
    RULE,
    ScratchEscape,
    ScratchInUse,
    by_owner,
    clear_scratch,
    entry_name,
    own_entries,
    plural,
    shown,
    untracked_scratch,
)
from dev_lab.dev._scratch_owners import Owner, beat, live, owners, record
from dev_lab.dev.native_session import session_of

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = ['clear_verb']


def _keep(root: Path, session: str, names: Iterable[str]) -> str | None:
    """Mark *names* as entries *session* leaves on purpose, adopting a gone one's; the refusal, else ``None``."""
    entries = {entry_name(rel) for rel, _, _ in untracked_scratch(root)}
    records, now = owners(root), time.time()
    wanted = [entry_name(name) for name in names]
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


def _refused(args: argparse.Namespace, root: Path, session: str) -> str | None:
    """Record ``--keep``; the refusal of the whole verb, else ``None``."""
    if args.approved is not None and not args.approved.strip():
        return "--approved takes the user's own words approving the removal; an empty approval approves nothing"
    if args.keep and not session:
        return 'no native session: --keep records which session keeps an entry'
    if args.keep:
        return _keep(root, session, args.keep)
    if args.all and (args.names or not args.approved):
        return f'--all takes no names and needs --approved "<the user\'s words>": {DOOR} --all --approved WORDS --yes'
    if not args.names and not args.all and not session:
        return (
            "no native session, so no entry is this session's: name the entries to clear, or clear every unowned "
            f'one the user approved: {DOOR} --all --approved "<the user\'s words>" --yes'
        )
    return None


def _unowned(root: Path, session: str) -> list[str]:
    """*root*'s entries no live session owns or keeps, *session*'s own excepted: what ``--all`` takes."""
    return [rel for rel, _ in by_owner(root, session, now=time.time())[1]]


def _left_note(root: Path, session: str) -> str:
    """What a no-names ``clear`` left and why (issue dev-lab#1124); ``''`` when no unowned entry stands."""
    loose = _unowned(root, session)
    if not loose:
        return ''
    return (
        f"{plural(loose)} of no live session kept ({shown(loose)}): with no names clear takes only this session's; "
        f'name them with --approved "<the user\'s words>", or {DOOR} --all --approved "<the user\'s words>" --yes'
    )


def clear_verb(rest: list[str], root: Path) -> int:
    """``clear [NAME ...] [--all] [--keep NAME ...] [--approved WORDS] [--yes]``: the names, else this session's.

    ``--all`` (with the user's ``--approved`` words) takes every entry of no live session, kept ones excepted,
    so a user's "clear it all" needs no fifty-name command line; a no-names clear says what it left and why.
    """
    parser = argparse.ArgumentParser(prog=DOOR, exit_on_error=False)
    parser.add_argument('names', nargs='*', metavar='NAME')
    parser.add_argument('--all', action='store_true', help='every entry of no live session (needs --approved)')
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
    if refused := _refused(args, root, session):
        emit(refused)
        return 2
    left = _unowned(root, session) if args.all else args.names or own_entries(root, session)
    kept = {entry_name(name) for name in args.keep}
    names = [name for name in left if entry_name(name) not in kept]
    if names and not args.yes:
        emit(f'would clear: {", ".join(names)}; re-run with --yes to delete them')
        return 2
    try:
        for rel in clear_scratch(root, names, session=session, approved=args.approved or ''):
            emit(f'cleared {rel}' + (f' (approved: {args.approved})' if args.approved else ''))
    except (ScratchEscape, ScratchInUse) as exc:
        emit(str(exc))
        return 2
    if not args.names and not args.all and (note := _left_note(root, session)):
        emit(note)
    elif not names and not args.names:
        emit("nothing to clear: no entry of this session's or of no live session stands")
    return 0
