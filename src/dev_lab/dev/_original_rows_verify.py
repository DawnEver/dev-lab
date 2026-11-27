"""THE ORIGINAL `dev_lab.dev` MODULES OF THE VERIFY RUN AND ITS STORE -- DATA, one name per module.

The verify half of the `original` registry (`_original_rows.py` holds the rest; split by responsibility at the
module-size band, 2026-11-27): what a run needs, costs and runs beside pytest, and the run store it records into.
READ AS SOURCE by `dev_lab.dev._provenance.provenance_rows`, never imported.
"""

from __future__ import annotations

from typing import Final

__all__ = ['ORIGINAL_MODULES']

ORIGINAL_MODULES: Final[tuple[str, ...]] = (
    'needs',  # ORIGINAL: 2026-11-24, one family need registry; a missing declared need fails by name (T2)
    'testcost',  # ORIGINAL: 2026-11-24, cost derived from the durations ledger against the host budget (T3, H1)
    'baselines',  # ORIGINAL: 2026-11-24, baselines live in the run store, one lock in the repo (H2)
    'cargostep',  # ORIGINAL: 2026-11-24, verify runs cargo test natively beside pytest, its own result (T8)
    'oraclegc',  # ORIGINAL: 2026-11-25, a report-only GC of the run store, every branch a root (D86)
    'rangebase',  # ORIGINAL: 2026-11-26, one family answer for no merge base with the integration branch
)
