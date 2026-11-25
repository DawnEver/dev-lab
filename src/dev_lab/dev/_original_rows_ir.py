"""THE ORIGINAL `dev_lab.dev` MODULES OF THE IR SCHEMA -- DATA, one name per module.

The IR-schema half of the `original` registry (`_original_rows.py` holds the rest; split by responsibility at
the module-size band, 2026-11-25). READ AS SOURCE by `dev_lab.dev._provenance.provenance_rows`, never imported.
"""

from __future__ import annotations

from typing import Final

__all__ = ['ORIGINAL_MODULES']

#: ORIGINAL: 2026-11-24, one schema generates the Python and Rust IR of a repo; no consumer held a generator.
ORIGINAL_MODULES: Final[tuple[str, ...]] = (
    'irschema',  # the door: generate, check, rust, migrate, affected
    'irmodel',  # the schema, loaded from [tool.dev_lab.ir_schema]
    'ircheck',  # references, quantities, field keys and record cycles checked across modules
    'irversion',  # what a schema change is, diffed against a git revision
    'irmigrate',  # the one migrate door
    'irpython',  # the Python generator
    'irrust',  # the Rust generator
    'irrustpy',  # the Rust <-> Python conversion behind the pyo3 feature
    'irhatch',  # the hatchling build hook that generates at package build
)
