"""THE ORIGINAL `dev_lab.dev` MODULES THAT DECLARE AND RENDER A MACHINE -- DATA, one name per module.

The machine-declaration half of the `original` registry (`_original_rows.py` holds the rest; split by responsibility
at the module-size band, 2026-11-25). READ AS SOURCE by `dev_lab.dev._provenance.provenance_rows`, never imported.
"""

from __future__ import annotations

from typing import Final

__all__ = ['ORIGINAL_MODULES']

ORIGINAL_MODULES: Final[tuple[str, ...]] = (
    'accounthost',  # ORIGINAL: an HPC account is the third host kind, rendered over its family grant (2026-11-15)
    'devhost',  # ORIGINAL: a development machine is declared, its machine file a render (2026-11-12)
    'devschema',
    'devprofile',  # ORIGINAL: an undeclared machine renders the family default; its doors name enrollment (2026-11-16)
    'devservers',  # ORIGINAL: every workstation renders the family servers as [[server]] rows (2026-11-25)
)
