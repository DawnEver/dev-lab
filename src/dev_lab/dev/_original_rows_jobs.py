"""THE ORIGINAL `dev_lab.dev` MODULES OF THE PARTS WORKFLOW JOBS PRODUCE -- DATA, one name per module.

The jobs half of the `original` registry (`_original_rows.py` holds the rest; split by responsibility at the
module-size band, 2026-11-27): the parts a workflow job produces, the hosted parts with a job of their own, their
setup, and a pinned measurement on hosted runners.
READ AS SOURCE by `dev_lab.dev._provenance.provenance_rows`, never imported.
"""

from __future__ import annotations

from typing import Final

__all__ = ['ORIGINAL_MODULES']

ORIGINAL_MODULES: Final[tuple[str, ...]] = (
    'jobparts',  # ORIGINAL: a new mechanism no consumer held a file for: the parts produced by workflow jobs
    'hostedjobs',  # ORIGINAL: split from jobparts: a hosted part's own workflow job render (2026-11-21)
    'hostedparts',  # ORIGINAL: split from jobparts: the hosted-part declaration reader (2026-11-17)
    'hostedsetup',  # ORIGINAL: a hosted part's declared setup, posted under its own class when it fails (#998)
    # ORIGINAL: no prior mechanism measured a pinned selection on hosted runners without producing a part (2026-11-15).
    'jobmeasure',
)
