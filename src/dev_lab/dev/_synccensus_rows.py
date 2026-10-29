"""THE SYNC-SELECTION CENSUS, pure DATA -- this repo's pruning commands and the floor under reading them.

The machinery is `synccensus.py` and the reader under it is `syncscope.py`; the seam is the one
`test_arch_registry_data_is_separate.py` names for `_rule_rows.py`. Nothing here computes: a table
edited through the module that checks it drifts away from what it describes, because the same edit
that adds a row can relax the check that would have refused it and the diff reads as one change.

THE KIT MAKES NO SELECTION OF ITS OWN ANY MORE. Its one was the `extras = ""` input to the reusable
`python-verify.yml`, and that workflow retired on 2026-10-29: CI is the plain base render, whose parts
run through `jobparts produce`. Every other repo declares the places IT chooses a set of extras, in its
own tests, and calls :func:`dev_lab.dev.synccensus.assert_scopes` over its own checkout. What stays
here is the other side of the ratchet: a `uv sync` arriving in a declared door reds until it is
recorded in :data:`SITES` with what survives it.
"""

from __future__ import annotations

__all__ = [
    'SITES',
    'SITE_COMMAND_FLOOR',
]

#: EVERY command in this repo's declared door files that moves a POPULATION, as
#: ``(repo, path, command text)``, with why it is the only one. Compared by EQUALITY against the live scan.
#: Empty since 2026-10-29: the one pruning command lived in the retired python-verify.yml.
SITES: dict[tuple[str, str, str], str] = {}

#: The floor under how many installer commands the SITES scan read before its equality means
#: anything. The Makefile's 14 (2026-10-29); the floor sits under it so an ordinary door edit does not
#: red, and well above the zero an unread scan returns.
SITE_COMMAND_FLOOR: int = 12
