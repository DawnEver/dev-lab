"""``python -m lab_commons.dev.forge <noun> <verb>`` -- the one noun dispatch over the ``forge*`` doors.

``status`` for commit statuses, ``issue claim|status|comments|comments-since`` for derived issue
state and comment reads, ``auth`` for the token, ``publish`` for the status outbox, ``records`` for
run records, ``tick`` for requests and claims, ``queue`` for the read-only status view, ``route <record>``
for failure routing and ``serve`` for the whole harness sequence, ``promote`` / ``sync`` / ``integration``
for the branch flow, ``tidy`` for declared issue hygiene, ``reserve`` / ``release`` for leases; anything
else is the issue/PR door. The verbs live in the sibling modules, which import :mod:`forge`, so
:mod:`forge` reaches this module only from its entry point.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lab_commons.dev import (
    forgeauth,
    forgeintegration,
    forgeissue,
    forgeoutbox,
    forgepromote,
    forgequeue,
    forgerecords,
    forgereserve,
    forgeroute,
    forgeserve,
    forgestatus,
    forgesync,
    forgetick,
    forgetidy,
    forgework,
    servekit,
    servelock,
)
from lab_commons.hpc.retired import refusal
from lab_commons.log import emit

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

__all__ = ['ISSUE_VERBS', 'NOUNS', 'main']

NOUNS: dict[str, Callable[[list[str]], int]] = {
    'auth': forgeauth.main,
    'status': forgestatus.main,
    'publish': forgeoutbox.main,
    'records': forgerecords.main,
    'route': forgeroute.main,
    'serve': lambda argv: servelock.locked(argv, lambda rest: servekit.current(rest, forgeserve.main)),
    'tick': forgetick.main,
    'promote': forgepromote.main,
    'queue': forgequeue.main,
    'sync': forgesync.main,
    'integration': forgeintegration.main,
    'tidy': forgetidy.main,
    'reserve': forgereserve.reserve_main,
    'release': forgereserve.release_main,
}

#: The ``issue`` verbs :mod:`forgeissue` owns; every other ``issue`` verb is the issue/PR door's.
ISSUE_VERBS = frozenset({'claim', 'status', 'comments', 'comments-since'})


def main(argv: Sequence[str]) -> int:
    """Route *argv* to the door owning its noun; returns that door's exit code."""
    args = list(argv)
    if args[:1] and args[0] in NOUNS:
        if refused := next(filter(None, (refusal(f'forge {args[0]}', w.split('=', 1)[0]) for w in args[1:])), None):
            emit(refused, err=True)
            return 2
        return NOUNS[args[0]](args[1:])
    if args[:1] == ['issue'] and args[1:2] and args[1] in ISSUE_VERBS:
        return forgeissue.main(args[1:])
    return forgework.main(args)
