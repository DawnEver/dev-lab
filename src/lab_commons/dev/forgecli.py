"""``python -m lab_commons.dev.forge <noun> <verb>`` -- the one noun dispatch over the ``forge*`` doors.

``status`` for commit statuses, ``issue claim|status|comments|comments-since`` for derived issue
state and comment reads, ``auth`` for the token, ``publish`` for the status outbox, ``records`` for
run records, ``tick`` for requests and claims and ``route <record>`` for failure routing; anything
else is the issue/PR door. The verbs live in the sibling modules, which import :mod:`forge`, so
:mod:`forge` reaches this module only from its entry point.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lab_commons.dev import (
    forgeauth,
    forgeissue,
    forgeoutbox,
    forgerecords,
    forgeroute,
    forgestatus,
    forgetick,
    forgework,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

NOUNS: dict[str, Callable[[list[str]], int]] = {
    'auth': forgeauth.main,
    'status': forgestatus.main,
    'publish': forgeoutbox.main,
    'records': forgerecords.main,
    'route': forgeroute.main,
    'tick': forgetick.main,
}

#: The ``issue`` verbs :mod:`forgeissue` owns; every other ``issue`` verb is the issue/PR door's.
ISSUE_VERBS = frozenset({'claim', 'status', 'comments', 'comments-since'})


def main(argv: Sequence[str]) -> int:
    """Route *argv* to the door owning its noun; returns that door's exit code."""
    args = list(argv)
    if args[:1] and args[0] in NOUNS:
        return NOUNS[args[0]](args[1:])
    if args[:1] == ['issue'] and args[1:2] and args[1] in ISSUE_VERBS:
        return forgeissue.main(args[1:])
    return forgework.main(args)
