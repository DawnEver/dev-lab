"""THE INTEGRATOR'S SCRATCH REPORT: entries no live session owns, quiet half an hour -- a DETACHED ``Stop`` row.

A scratch entry carries the session that made it (:mod:`dev_lab.dev.scratch`). When that session is gone -- or no
session ever named the entry -- no session's own ``Stop`` names it, so it would pile up unseen. This row names it to
the INTEGRATOR only (:mod:`dev_lab.dev.hpcaccount.session`, a consent-proved role), and never to any other session:
another session's leftovers are not its to clear.

DETACHED, because it is a report and not a guard (HOOK-UNDER-FIVE-SECONDS): proving the role imports the consent
client (measured 2026-11-25 at 4.7 s cumulative on a loaded box) and judging quiet walks whole trees. It runs to
completion in the background and reaches the integrator at its next context event.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from lab_commons.log import emit

from dev_lab.dev._scratch_clear import DOOR, RULE, by_owner, hook_payload, minutes, plural, root_of, shown
from dev_lab.dev._scratch_owners import RECENT_S, Owner, touched
from dev_lab.dev.hpcaccount.session import INTEGRATOR, held

if TYPE_CHECKING:
    from typing import TextIO

__all__ = ['integrator', 'main', 'orphan_entries', 'report']


def integrator(session: str) -> bool:
    """Whether *session* holds the integrator role."""
    return INTEGRATOR in held(session=session)


def orphan_entries(root: Path, session: str, *, now: float | None = None) -> list[tuple[str, Owner | None]]:
    """``[(rel, owner), ...]``: *root*'s entries no live session owns or keeps, quiet :data:`RECENT_S`."""
    stamp = time.time() if now is None else now
    return [(rel, o) for rel, o in by_owner(root, session, now=stamp)[1] if stamp - touched(root / rel) >= RECENT_S]


def report(orphans: list[tuple[str, Owner | None]]) -> str:
    """The integrator's notice naming each entry with its gone owner, and the doors."""
    whose = [f'{rel} ({f"gone session {o.session}" if o else "no recorded owner"})' for rel, o in orphans]
    return (
        f'{RULE}: as the integrator: {plural(whose)} of no live session, quiet {minutes(RECENT_S)}: {shown(whose)}.\n'
        f'Promote what is useful into src/ with tests (a finding into memory), then {DOOR} NAME ... --yes, '
        'or --keep NAME to leave it on purpose'
    )


def main(argv: list[str] | None = None, *, stdin: TextIO | None = None) -> int:
    """The ``Stop`` row: name the integrator's ownerless entries; silent for any other session. Always 0."""
    del argv
    payload = hook_payload(stdin or sys.stdin)
    if payload is None or payload.get('stop_hook_active'):
        return 0
    found = root_of(Path(payload.get('cwd') or Path.cwd()).resolve())
    session = str(payload['session_id'])
    if found is None or not by_owner(found[0], session, now=time.time())[1] or not integrator(session):
        return 0
    if orphans := orphan_entries(found[0], session):
        emit(json.dumps({'systemMessage': report(orphans)}))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
