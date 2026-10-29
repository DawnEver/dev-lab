"""ROUND-ENDS-GREEN: a session's round ends only when every head it pushed is green -- or watched while pending.

User ruling 2026-10-29 (D81), the same on both forges. A session that pushes and then ends its turn leaves a
head whose verdict nobody reads: a red goes unseen until someone else trips on it. So the ``Stop`` hook
(:mod:`dev_lab.dev.handback`) asks this module, and the turn is refused:

* while a head THIS session pushed is red (a part ``failure`` or ``error``, a blocking review or security) --
  naming it, and how to read why (``forge status show <sha>``);
* while one is pending (no settled ``tests/`` status yet) and no live ``forge watch <sha>`` process is waiting on
  it -- naming the exact command to start in the BACKGROUND, so the session is woken when it settles.

Green ends the round. A head is THIS session's when an ``origin`` branch's tip carries its ``Lab-Session``
trailer (:mod:`dev_lab.dev.labsession`): derived from git and the forge, so there is no record to keep. A
session with no id, a head nobody pushed, and a forge that cannot answer all end the round: the gate never
holds a session on a fact it could not read.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door
from lab_commons.census import processes as census

from dev_lab.dev.forge import _GIT, _GIT_TIMEOUT_S
from dev_lab.dev.forgecontexts import MERGE_READY_CONTEXT, REVIEW_CONTEXT
from dev_lab.dev.forgestatus import status_list
from dev_lab.dev.forgewatch import TESTS, settled
from dev_lab.dev.forgework import ForgeCallFailed, client_for
from dev_lab.dev.labsession import ENV, TRAILER
from dev_lab.dev.venvpath import running_interpreter

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from pathlib import Path

    from dev_lab.dev.forgework import Client

__all__ = ['RULE', 'for_session', 'pushed_heads', 'refusal', 'watched']

#: The rule this gate enforces (``dev_lab.dev.rules``).
RULE: Final = 'ROUND-ENDS-GREEN'

#: The door a pending head waits on, as its process command line names it.
_WATCH: Final = '-m dev_lab.dev.forge watch'

#: The shortest sha prefix a watch may be started with and still count as watching the head.
_SHORT: Final = 7

_RED: Final = frozenset({'failure', 'error'})

#: Never a red of its own: the merge decision only repeats what is missing, and a review that could not run is
#: advisory (:func:`dev_lab.dev.forgemerge.review_blocks`).
_NOT_RED: Final = frozenset({
    (MERGE_READY_CONTEXT, 'failure'), (MERGE_READY_CONTEXT, 'error'), (REVIEW_CONTEXT, 'error'),
})  # fmt: skip


def pushed_heads(root: Path, session: str) -> dict[str, str]:
    """``{origin branch: tip sha}`` for every ``origin`` branch whose tip carries ``Lab-Session: <session>``."""
    form = f'%(objectname) %(refname:lstrip=3) %(trailers:key={TRAILER},valueonly,separator=%x20)'
    done = _door.run(
        [_GIT, '-C', str(root), 'for-each-ref', f'--format={form}', 'refs/remotes/origin'],
        capture_output=True, text=True, encoding='utf-8', timeout=_GIT_TIMEOUT_S, check=False,
    )  # fmt: skip
    heads = {}
    for line in done.stdout.splitlines() if done.returncode == 0 else ():
        sha, _, rest = line.partition(' ')
        branch, _, sessions = rest.partition(' ')
        if branch != 'HEAD' and session in sessions.split():
            heads[branch] = sha
    return heads


def watched(sha: str, command_lines: Iterable[str]) -> bool:
    """Whether a live process is ``forge watch``-ing *sha* (named by it or by a prefix of at least 7 hex)."""
    for line in command_lines:
        if _WATCH not in line:
            continue
        named = line.split(_WATCH, 1)[1].split()
        if named and len(named[0]) >= _SHORT and sha.startswith(named[0]):
            return True
    return False


def refusal(
    root: Path, session: str, client: Client, *, processes: Callable[[], Iterable[str]]
) -> str | None:  # fmt: skip
    """Why *session*'s round may not end yet, or ``None`` (module docstring); one line per head that holds it."""
    if not session:
        return None
    held: list[str] = []
    lines: list[str] | None = None
    for branch, sha in sorted(pushed_heads(root, session).items()):
        tests = [one for one in status_list(client, sha) if one.context.startswith(TESTS)]
        red = sorted(one.context for one in tests if one.state in _RED and (one.context, one.state) not in _NOT_RED)
        if red:
            show = f'{running_interpreter()} -m dev_lab.dev.forge status show {sha}'
            held.append(f'{branch} {sha[:12]} is red ({", ".join(red)}): read why with `{show}`, fix it and push')
            continue
        if settled(tests):
            continue
        lines = list(processes()) if lines is None else lines
        if not watched(sha, lines):
            watch = f'{running_interpreter()} -m dev_lab.dev.forge watch {sha}'
            held.append(f'{branch} {sha[:12]} is pending and nobody watches it: start, IN THE BACKGROUND, `{watch}`')
    if not held:
        return None
    return f'{RULE}: a head this session pushed is not green yet -- ' + '; '.join(held)


def for_session(root: Path) -> str | None:
    """:func:`refusal` for this process's ``LAB_SESSION`` in *root*; ``None`` whenever it cannot be read."""
    session = os.environ.get(ENV, '')
    if not session:
        return None
    try:
        return refusal(root, session, client_for(root), processes=lambda: (one.command_line for one in census()))
    except (ForgeCallFailed, OSError, ValueError):
        return None
