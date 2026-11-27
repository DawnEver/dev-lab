"""THE ORIGINAL `dev_lab.dev` MODULES THAT PIN A TOOLCHAIN OR A LOCK -- DATA, one name per module.

The toolchain-and-lock half of the `original` registry: the family Python and Rust toolchains, uv's own pin, and
the lock's reading, checking, relocking and syncing (`_original_rows.py` holds the rest; split by responsibility at
the module-size band, 2026-11-27). READ AS SOURCE by `dev_lab.dev._provenance.provenance_rows`, never imported.
"""

from __future__ import annotations

from typing import Final

__all__ = ['ORIGINAL_MODULES']

ORIGINAL_MODULES: Final[tuple[str, ...]] = (
    'lockreach',
    'lockpins',
    'lockwait',
    # ORIGINAL: each Rust repo pinned its own toolchain; the family fact had no source (2026-11-24).
    'rusttoolchain',
    # ORIGINAL: each repo and runner chose its own Python; the family interpreter had no source (2026-11-27).
    'pythontoolchain',
    'lockcheck',
    'relock',
    'syncpins',
    # ORIGINAL: how far a floated sibling's pin lags its line was never read; split from relock (2026-11-07).
    'locklag',
    # ORIGINAL: the lock PIN moved from a pre-push row into the repo's own forge-judged suite (2026-10-24).
    'lockpin',
    'uvfollow',  # uv follows the version its pin needs, through the route it was installed by, new here
)
