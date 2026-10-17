"""ONE RUN PER REF AND PART IN FLIGHT (D6, user ruling 2026-10-17) -- a coalesced tip waits behind its ref's run.

A ref of a ``coalesce`` class (:attr:`lab_commons.compute.model.Schedule.coalesce`) has at most one run of
a part in flight across the fleet: its current tip waits behind that run, which is never cancelled, and is
tested next as one batch -- per-test carry makes it cheap. A lane is tested at every pushed sha. The run in
flight is read from the claims already on the forge (:mod:`lab_commons.dev.forgeclaim`), on the tip's
first-parent history: the same on every host, unlike a host's reflog. Both the claim pass
(:mod:`lab_commons.dev.forgetake`) and the queue (:mod:`lab_commons.dev.forgequeue`) ask :func:`behind`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Final

import lab_commons.launch as _door
from lab_commons.compute.model import Candidate, Schedule
from lab_commons.dev.forge import _GIT, _GIT_TIMEOUT_S
from lab_commons.dev.forgeclaim import CLAIMED, DONE, Claim, assess
from lab_commons.dev.forgestatus import Status
from lab_commons.dev.platformparts import part_context

__all__ = ['EARLIER_TIPS', 'WAITING_BEHIND', 'behind']

#: The prefix of :attr:`Ranked.blocked` for a coalesced tip waiting on its ref's run in flight.
WAITING_BEHIND: Final = 'waiting behind'
#: How many first-parent commits before a tip :func:`behind` reads before it stops looking.
EARLIER_TIPS: Final = 16


def behind(
    root: Path, wanted: Candidate, schedule: Schedule, history: Callable[[str], Sequence[Status]], now: datetime
) -> str:
    """Why *wanted* waits on its own ref's run in flight elsewhere; ``''`` when it does not (D6, ruling 2026-10-17).

    A COALESCED class (:attr:`Schedule.coalesce`) holds at most one run per (ref, part) across the fleet: the
    claims already live on the forge, on the tip's first-parent HISTORY -- the same on every host, unlike a
    host's reflog -- newest first, until one whose part is settled. A live claim there blocks the current
    tip; it is never cancelled, its verdict stands, and its per-test results carry to the tip. An earlier tip
    nobody claimed is never a candidate at all (:func:`candidates` names only the tip).
    """
    if wanted.kind not in schedule.coalesce:
        return ''
    context, nobody = part_context(wanted.platform), Claim('', '', now)
    for sha in _earlier_tips(root, wanted.sha):
        state, holder = assess(history(sha), context, me=nobody, now=now)
        if state == CLAIMED and holder is not None:
            return f'{WAITING_BEHIND} {sha[:12]} (in flight on {holder.hpc or holder.machine or holder.login})'
        if state == DONE:
            return ''
    return ''


def _earlier_tips(root: Path, tip: str) -> list[str]:
    """*tip*'s first-parent history before it, newest first: the same on every host (module docstring)."""
    args = [_GIT, '-C', str(root), 'rev-list', '--first-parent', '-n', str(EARLIER_TIPS), f'{tip}~1', '--']
    done = _door.run(args, capture_output=True, text=True, encoding='utf-8', timeout=_GIT_TIMEOUT_S, check=False)
    listed = done.stdout if done.returncode == 0 else ''  # a root commit has no history before it
    return [sha for sha in listed.splitlines() if sha]
