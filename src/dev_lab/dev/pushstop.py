"""PUSHED-HEAD-IS-WATCHED, the ``Stop`` half: a turn does not end while a head it pushed is unwatched or red.

User ruling 2026-11-04: a session pushed PRs, said "in review" and ended its turn with nothing watching them,
and reds sat unfixed. So ``python -m dev_lab.dev.pushstop`` -- the ``Stop`` hook -- reads the heads this
session pushed (:func:`dev_lab.dev.pushwatch.pushed_by`, journalled by the ``PostToolUse`` half) and asks the
forge for each one's checks (:func:`stop_refusal`):

* a head still ``pending`` with no live ``forge watch`` refuses the stop EVERY time, naming the one watch to
  arm -- arming it is the remedy, and a live watcher lifts the refusal;
* a RED head refuses it ONCE, naming where to read the red: a red may need the user's decision, so a stop
  already refused (``stop_hook_active``) is let through rather than looping;
* a green head, a session that pushed nothing, or a forge that cannot answer ends the turn. Always exits 0.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

from lab_commons.census import processes as census
from lab_commons.log import emit

from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgestatus import status_list
from dev_lab.dev.forgewatch import TESTS, settled
from dev_lab.dev.forgework import Client, client_for
from dev_lab.dev.pushwatch import RULE, pushed_by, watch_command, watched
from dev_lab.dev.venvpath import running_interpreter

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

__all__ = ['main', 'stop_refusal']


def stop_refusal(
    root: Path, session: str, *, client: Client, processes: Callable[[], Iterable[str]], again: bool
) -> str | None:
    """Why *session* may not end its turn yet, else ``None``; *again* is a stop already refused once.

    ONE remedy per state: a pending head with no live watcher names the watch to arm; a red head names where to
    read its verdict, and only on the first stop. Raises :class:`ForgeCallFailed`/``ValueError`` when unreadable.
    """
    heads = sorted(set(pushed_by(root, session).values()))
    if not heads:
        return None
    pending, red = [], []
    for sha in heads:
        statuses = status_list(client, sha)
        if not settled(statuses):
            pending.append(sha)
        elif any(s.state != 'success' for s in statuses if s.context.startswith(TESTS)):
            red.append(sha)
    live = list(processes())
    if unwatched := [sha for sha in pending if not watched(sha, live)]:
        named = ' '.join(sha[:12] for sha in unwatched)
        return (
            f'{RULE}: this session pushed {named}, its checks are pending and nothing watches them.\n'
            f'Arm a Monitor and act on each result before ending the turn: {watch_command(*unwatched)}'
        )
    if red and not again:
        named = ' '.join(sha[:12] for sha in red)
        return (
            f'{RULE}: this session pushed {named} and its checks are red.\n'
            f'Read the red, fix it and push before ending the turn: '
            f'{running_interpreter()} -m dev_lab.dev.forge status list {red[0]}'
        )
    return None


def _gate(
    payload: dict,
    processes: Callable[[], Iterable[str]],
    client: Callable[[Path], Client] | None,
    out: TextIO | None,
) -> int:
    session = str(payload.get('session_id') or '')
    root = Path(payload.get('cwd') or Path.cwd())
    if not pushed_by(root, session):
        return 0
    try:
        reason = stop_refusal(
            root,
            session,
            client=(client or client_for)(root),
            processes=processes,
            again=bool(payload.get('stop_hook_active')),
        )
    except (ForgeCallFailed, OSError, ValueError):
        return 0
    if reason is not None:
        said = json.dumps({'decision': 'block', 'reason': reason})
        if out is None:
            emit(said)
        else:
            out.write(said)
    return 0


def main(
    argv: list[str] | None = None,
    *,
    stdin: TextIO | None = None,
    processes: Callable[[], Iterable[str]] | None = None,
    client: Callable[[Path], Client] | None = None,
    out: TextIO | None = None,
) -> int:
    """The ``Stop`` hook: block once per state above, else stay silent. Never exits nonzero."""
    del argv
    try:
        payload = json.load(stdin or sys.stdin)
    except ValueError:
        return 0
    if not isinstance(payload, dict):
        return 0
    return _gate(payload, processes or (lambda: (one.command_line for one in census())), client, out)


if __name__ == '__main__':
    raise SystemExit(main())
