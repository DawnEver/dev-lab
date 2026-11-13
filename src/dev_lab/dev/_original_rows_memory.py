"""THE ORIGINAL `dev_lab.dev` MODULES OF MEMORY AND REM -- DATA, one name per module.

The memory half of the `original` registry (`_original_rows.py` holds the rest; split by responsibility at
the module-size band, 2026-11-13). READ AS SOURCE by `dev_lab.dev._provenance.provenance_rows`, never imported.
"""

from __future__ import annotations

from typing import Final

__all__ = ['ORIGINAL_MODULES']

ORIGINAL_MODULES: Final[tuple[str, ...]] = (
    # ORIGINAL: the PreToolUse door judging a rem task-journal append before it is written (dev-lab#419).
    'journaldoor',
    'memoryadds',  # memory is added to, never edited, new here
    'memoryentry',  # one memory entry's text judged, split from memoryadds (module-size band)
    'remconfig',  # the family's rem.json, new here
)
