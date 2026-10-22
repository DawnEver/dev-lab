"""ONE RUN PER REF AND PART IN FLIGHT (D6, user ruling 2026-10-17) -- a coalesced tip waits behind its ref's run.

A ref of a ``coalesce`` class (:attr:`lab_commons.compute.model.Schedule.coalesce`) has at most one run of
a part in flight across the fleet: its current tip waits behind that run and is tested next as one batch --
per-test carry makes it cheap. At its holder's next tick that run's NOT-YET-STARTED tasks are withdrawn for the
tip and its STARTED ones drain (``draining``) -- never cancelled -- so the tip carries them (NEWEST-HEAD-ONLY,
user ruling 2026-10-22, :mod:`lab_commons.dev.forgerun`); one already ``publishing`` its gathered
record finishes. A ref of any other class is tested at every pushed sha. The run in
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
from lab_commons.dev.forgestatus import CommitStatus
from lab_commons.dev.platformparts import part_context

__all__ = ['DRAINING', 'EARLIER_TIPS', 'PUBLISHING', 'WAITING_BEHIND', 'behind', 'earlier_tips']

#: The prefix of :attr:`Ranked.blocked` for a coalesced tip waiting on its ref's run in flight.
WAITING_BEHIND: Final = 'waiting behind'
#: How many first-parent commits before a tip :func:`behind` reads before it stops looking.
EARLIER_TIPS: Final = 16
#: The claim progress of a run posting its gathered record (:mod:`lab_commons.dev.forgerun`): never superseded.
PUBLISHING: Final = 'publishing'
#: The claim progress of a superseded run whose started tasks finish (:mod:`lab_commons.dev.forgerun`).
DRAINING: Final = 'draining'


def behind(
    root: Path, wanted: Candidate, schedule: Schedule, history: Callable[[str], Sequence[CommitStatus]], now: datetime
) -> str:
    """Why *wanted* waits on its own ref's run in flight elsewhere; ``''`` when it does not (D6, ruling 2026-10-17).

    A COALESCED class (:attr:`Schedule.coalesce`) holds at most one run per (ref, part) across the fleet: the
    claims already live on the forge, on the tip's first-parent HISTORY -- the same on every host, unlike a
    host's reflog -- newest first, until one whose part is settled. A live claim there blocks the current
    tip until its holder withdraws its pending tasks and its started ones drain; one ``publishing`` finishes.
    An earlier tip nobody claimed is never a candidate at all (:func:`candidates` names only the tip).
    """
    if wanted.kind not in schedule.coalesce:
        return ''
    context, nobody = part_context(wanted.platform), Claim('', '', now)
    for sha in earlier_tips(root, wanted.sha):
        state, holder = assess(history(sha), context, me=nobody, now=now)
        if state == CLAIMED and holder is not None:
            where = holder.hpc or holder.machine or holder.login
            if holder.progress.startswith(DRAINING):
                return f'{WAITING_BEHIND} {sha[:12]} ({holder.progress} on {where})'
            if holder.progress.startswith(PUBLISHING):
                return f'{WAITING_BEHIND} {sha[:12]} ({PUBLISHING} on {where})'
            return f'{WAITING_BEHIND} {sha[:12]} (held on {where}: its pending tasks withdrawn at its next tick)'
        if state == DONE:
            return ''
    return ''


def earlier_tips(root: Path, tip: str) -> list[str]:
    """*tip*'s first-parent history before it, newest first: the same on every host (module docstring)."""
    args = [_GIT, '-C', str(root), 'rev-list', '--first-parent', '-n', str(EARLIER_TIPS), f'{tip}~1', '--']
    done = _door.run(args, capture_output=True, text=True, encoding='utf-8', timeout=_GIT_TIMEOUT_S, check=False)
    listed = done.stdout if done.returncode == 0 else ''  # a root commit has no history before it
    return [sha for sha in listed.splitlines() if sha]
