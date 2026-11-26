"""THE ORIGINAL `dev_lab.dev` GUARDS OVER TRACKED VALUES, GUARD COLLECTION AND THE SESSION VOLUME -- DATA, one per name.

A half of the `original` registry (`_original_rows.py` holds the rest; split by responsibility at the module-size
band, 2026-11-26). READ AS SOURCE by `dev_lab.dev._provenance.provenance_rows`, never imported.
"""

from __future__ import annotations

from typing import Final

__all__ = ['ORIGINAL_MODULES']

ORIGINAL_MODULES: Final[tuple[str, ...]] = (
    'evidencerefs',  # no consumer judged a recorded value's provenance in the output tree (dev-lab#843)
    'guardcollection',  # no guard judged whether a rule's test mechanism collects and runs (dev-lab#599)
)
