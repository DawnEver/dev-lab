"""Every retirement is classified (keep-valuable-options): a retired name says what was lost, if anything.

A row of a retired-names registry is ``spelling -> (replacement, decision, class)``. The class is one of
:data:`CLASSES`:

* ``renamed`` -- the capability lives on under the replacement the row names;
* ``baggage`` -- an obsolete structure, duplicate or dead path went; no capability was lost;
* ``capability-dropped`` -- an option was removed, which only a user ruling may do, so the decision cites it.

:func:`refusals` names every row that breaks this; a registry's own test asserts it returns nothing. A family
repo whose rows carry no class is refused here by name when it relocks onto this dev-lab, and migrates its
rows once (FORMATS-MIGRATE-ONCE).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Final

CLASSES: Final = ('renamed', 'baggage', 'capability-dropped')

#: A decision that may drop a capability cites the user's ruling or a numbered user decision.
_RULING: Final = re.compile(r'\buser\b|\bD\d+\b')

DOOR: Final = (
    'give the row a third field, its class: renamed (names the successor), baggage (nothing was lost) or '
    'capability-dropped (cite the user ruling that dropped it)'
)


def refusals(rows: Mapping[str, Sequence[str]]) -> list[str]:
    """Every row that is unclassified, wrongly classified, or drops a capability without a ruling."""
    found: list[str] = []
    for spelling, row in rows.items():
        if len(row) != len(('replacement', 'decision', 'class')):
            found.append(f'{spelling!r}: no class -- {DOOR}')
            continue
        _new, why, cls = row
        if cls not in CLASSES:
            found.append(f'{spelling!r}: class {cls!r} is none of {", ".join(CLASSES)} -- {DOOR}')
        elif cls == 'capability-dropped' and not _RULING.search(why):
            found.append(f'{spelling!r}: drops a capability without citing a user ruling -- only the user drops one')
    return found
