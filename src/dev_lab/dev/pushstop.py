"""PUSHED-HEAD-IS-WATCHED, the ``Stop`` half: a turn does not end while a head it pushed is unwatched or red.

User ruling 2026-11-04: a session pushed PRs, said "in review" and ended its turn with nothing watching them,
and reds sat unfixed. So ``python -m dev_lab.dev.pushstop`` -- the ``Stop`` hook -- reads the heads this
session pushed (:func:`dev_lab.dev.pushwatch.pushed_by`, journalled by the ``PostToolUse`` half) and asks the
forge for each one's checks (:func:`stop_refusal`):

* a head still ``pending`` with no live ``forge watch`` refuses the stop EVERY time, naming the one watch to
  arm -- arming it is the remedy, and a live watcher lifts the refusal;
* a RED check refuses it only on a PR the session opened or pushed, in ANY repository (SESSION-HEARS-ITS-PRS,
  :func:`dev_lab.dev.forgewatch.unacknowledged_reds`, ruling 2026-11-11), and EVERY time until the session
  pushes a newer head or records why the red stands (``forge watch --session <id> --ack <key> --reason <why>``);
  a red head that is no session PR's -- an integration head the session merely pushed -- is not blocked on;
* an open PR of the session with no live ``forge watch --session`` (:func:`dev_lab.dev.sessionprs.watching`)
  and no fresh machine-watcher beat covering it (:func:`dev_lab.dev.prwatcher.heard`, dev-lab#581) refuses it
  EVERY time, naming the watcher door and the Monitor command to arm (:func:`unwatched_refusal`, 2026-11-12);
* a head with no ``tests/*`` status :data:`GRACE_S` after its push has nothing to watch (review F-05c3ae4cb27f);
* a pending head that LANDED needs no watch (:func:`landed`, task toolchain-1114 O3): its PR merged or closed, the
  PR's current head or the branch tip on origin descends from it and is itself watched or landed, or it is an
  ancestor of the declared integration branch -- a superseded sha's checks never settle;
* a pending head whose ``forge watch`` ran to its deadline is released on a repeated stop, with a note;
* a green head, a session that pushed nothing, or a forge that cannot answer ends the turn. Always exits 0.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, TextIO

from lab_commons.census import processes as census
from lab_commons.log import emit

from dev_lab.dev import prwatcher, sessionprs, walls
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgepulls import pr_list
from dev_lab.dev.forgestatus import status_list
from dev_lab.dev.forgewatch import clients_at, settled, unacknowledged_reds
from dev_lab.dev.forgework import Client, client_for
from dev_lab.dev.lanepolicy import load_policy
from dev_lab.dev.pushwatch import (
    RULE,
    deadline_reached,
    descends,
    origin_tip,
    pushed_at,
    pushed_by,
    watch_command,
    watched,
)
from dev_lab.dev.sessionpoll import TESTS
from dev_lab.dev.venvpath import running_interpreter

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from dev_lab.dev.forge import Forge

__all__ = ['GRACE_S', 'Stop', 'landed', 'main', 'red_refusal', 'stop_refusal', 'unwatched_refusal']


#: How long after its push a head with NO ``tests/*`` status is still awaited: time for CI to post its first
#: ``pending``. Past it the head has nothing to watch -- a branch CI does not run on, or a docs-only head.
GRACE_S: Final = 600.0


@dataclass(frozen=True, slots=True)
class Stop:
    """The gate's answer: *block* refuses the stop; *note* is said when a stop is let through anyway."""

    block: str | None = None
    note: str | None = None


def stop_refusal(
    root: Path,
    session: str,
    *,
    client: Client,
    processes: Callable[[], Iterable[str]],
    again: bool,
    now: float | None = None,
) -> Stop:
    """Whether *session* may end its turn; *again* is a stop already refused once, *now* the clock (epoch s).

    A pending head with no live watcher names the watch to arm (a red is :func:`red_refusal`'s). A head with no
    ``tests/*`` status :data:`GRACE_S` after its push has nothing to watch; a pending head whose
    watch ran to its deadline is released on a repeated stop, with a note -- the user decides.
    Raises :class:`ForgeCallFailed`/``ValueError`` when unreadable.
    """
    pushed = pushed_at(root, session)
    clock = time.time() if now is None else now
    pending = []
    for sha in sorted(pushed):
        statuses = status_list(client, sha)
        if not any(s.context.startswith(TESTS) for s in statuses):
            if clock - pushed[sha] < GRACE_S:
                pending.append(sha)
        elif not settled(statuses):
            pending.append(sha)
    live = list(processes())
    unwatched = [sha for sha in pending if not watched(sha, live, root=root)]
    if unwatched:
        branches = {sha: ref.removeprefix('refs/heads/') for ref, sha in pushed_by(root, session).items()}
        unwatched = [sha for sha in unwatched if not landed(root, sha, branches.get(sha, ''), client=client, live=live)]
    ran_out = deadline_reached(root) if again else frozenset()
    released = [sha for sha in unwatched if sha in ran_out]
    if unwatched := [sha for sha in unwatched if sha not in ran_out]:
        named = ' '.join(sha[:12] for sha in unwatched)
        return Stop(
            block=f'{RULE}: this session pushed {named}, its checks are pending and nothing watches them.\n'
            f'Arm a Monitor and act on each result before ending the turn: {watch_command(*unwatched)}\n'
            'A live watch on a newer head that descends from it (the forge synced the branch past it) counts too.'
        )
    if released:
        named = ' '.join(sha[:12] for sha in released)
        return Stop(note=f'{RULE}: {named} is still pending after its watch reached its deadline; released -- '
                         'the user decides whether to wait on it.')  # fmt: skip
    return Stop()


def _integration_holds(root: Path, sha: str) -> bool:
    """Whether *sha* is an ancestor of ``origin/<integration>`` (the branch ``[tool.dev_lab.integrator]`` names)."""
    try:
        integration = load_policy(root).integration
    except (OSError, ValueError):
        return False
    tip = origin_tip(root, integration)
    return bool(tip) and (tip.startswith(sha) or descends(root, sha, tip))


def landed(root: Path, sha: str, branch: str, *, client: Client, live: Iterable[str]) -> bool:
    """Whether pushed *sha* (of *branch*) needs no watch: its checks can never settle, or no longer matter.

    True when (c) it is an ancestor of the integration branch; (a) the newest PR from *branch* is merged or closed;
    or (b) that PR's current head, or *branch*'s tip on origin, is a strict descendant of it that is itself watched
    in *live* or held by the integration branch. A still-current head of an open PR is never landed.
    """
    if _integration_holds(root, sha):
        return True
    if not branch:
        return False
    tips = [origin_tip(root, branch)]
    pulls = [pull for pull in pr_list(client, state='all') if pull.head == branch]
    if pulls:
        newest = max(pulls, key=lambda pull: pull.number)
        if newest.state != 'open':
            return True
        tips.append(newest.head_sha)
    return any(
        tip and not tip.startswith(sha) and descends(root, sha, tip)
        and (watched(tip, live) or _integration_holds(root, tip))
        for tip in tips
    )  # fmt: skip


def red_refusal(session: str, *, clients: Callable[[Forge], Client]) -> Stop:
    """Refuse the stop while a session PR's head is red and unacknowledged, naming each PR and failing context."""
    reds = unacknowledged_reds(session, clients=clients)
    if not reds:
        return Stop()
    return Stop(
        block=f'{sessionprs.RULE}: a PR of this session has a red check:\n'
        + ''.join(f'  {line}\n' for line in reds)
        + 'Read it, fix it and push a newer head -- or, when the red stands on purpose, record why: '
        f'{running_interpreter()} -m dev_lab.dev.forge watch --session {session} '
        '--ack <host>/<owner>/<repo>#<number> --reason <why>'
    )


#: A session watch, as any interpreter's command line names it (#554: a watch from another checkout counts).
_SESSION_WATCH: Final = '-m dev_lab.dev.forge watch --session'


def _session_watched(session: str, command_lines: Iterable[str]) -> bool:
    """Whether a live process runs ``forge watch --session <session>``, whatever interpreter path runs it."""
    for line in command_lines:
        if _SESSION_WATCH in line and line.split(_SESSION_WATCH, 1)[1].split()[:1] == [session]:
            return True
    return False


def unwatched_refusal(session: str, *, processes: Callable[[], Iterable[str]] = lambda: ()) -> Stop:
    """Refuse the stop while the session has an open PR on record and no live session watch.

    A watch counts by its marker or by its command line in *processes* -- from any checkout's interpreter, so a
    watch kept out of the venv a relock needs still counts (#554).
    """
    prs = sessionprs.open_rows(session)
    if not prs or prwatcher.heard(session) or sessionprs.watching(session) or _session_watched(session, processes()):
        return Stop()
    return Stop(
        block=f'{sessionprs.RULE}: this session has open PRs ({", ".join(row.key for row in prs)}) and nothing '
        'watches them, so no merge or red check would reach you. Start the machine watcher (it covers a new PR at '
        f'its next poll, within {prwatcher.POLL_S:g} s): {running_interpreter()} -m dev_lab.dev.prwatcher start -- '
        f'or arm ONE persistent Monitor running: {sessionprs.watch_session_command(session)} '
        '(a watch run from any checkout interpreter counts)'
    )


def _gate(
    payload: dict,
    processes: Callable[[], Iterable[str]],
    client: Callable[[Path], Client] | None,
    clients: Callable[[Forge], Client] | None,
    out: TextIO | None,
) -> int:
    session = str(payload.get('session_id') or '')
    root = Path(payload.get('cwd') or Path.cwd())
    pushed, prs = pushed_by(root, session), sessionprs.open_rows(session)
    if not pushed and not prs:
        return 0
    try:
        said = (
            stop_refusal(
                root,
                session,
                client=(client or client_for)(root),
                processes=processes,
                again=bool(payload.get('stop_hook_active')),
            )
            if pushed
            else Stop()
        )
        if said.block is None and prs and (red := red_refusal(session, clients=clients or clients_at(root))).block:
            said = red
        if said.block is None and prs:
            said = unwatched_refusal(session, processes=processes)
    except (ForgeCallFailed, OSError, ValueError):
        return 0
    if said.block is not None:
        walls.refused_text(root, said.block, reason='stop', session=session)
        answer = {'decision': 'block', 'reason': said.block}
    elif said.note is not None:
        answer = {'systemMessage': said.note}
    else:
        return 0
    if out is None:
        emit(json.dumps(answer))
    else:
        out.write(json.dumps(answer))
    return 0


def main(
    argv: list[str] | None = None,
    *,
    stdin: TextIO | None = None,
    processes: Callable[[], Iterable[str]] | None = None,
    client: Callable[[Path], Client] | None = None,
    clients: Callable[[Forge], Client] | None = None,
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
    return _gate(payload, processes or (lambda: (one.command_line for one in census())), client, clients, out)


if __name__ == '__main__':
    raise SystemExit(main())
