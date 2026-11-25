"""THE ORIGINAL `dev_lab.dev` MODULES OF THE STATIC ARCHITECTURE CHECKS -- DATA, one name per module.

The architecture-check half of the `original` registry (`_original_rows.py` holds the rest; split by responsibility
at the module-size band, 2026-11-25): the readers of a repo's source and the opt-in checks built on them.
READ AS SOURCE by `dev_lab.dev._provenance.provenance_rows`, never imported.
"""

from __future__ import annotations

from typing import Final

__all__ = ['ORIGINAL_MODULES']

ORIGINAL_MODULES: Final[tuple[str, ...]] = (
    'importedges',  # ORIGINAL: 2026-11-24, the family's one static import-edge reader for architecture tests
    'corechange',  # ZERO-CORE-CHANGE: application work leaves the core, else a recorded decision (2026-11-24), new here
    'nativefirst',  # NATIVE-FIRST: Python orchestrates, the native stage computes (2026-11-25), new here
    'pyfacts',  # ORIGINAL: 2026-11-25, per-file Python facts (uses, forwards) read once and cached by stat
    'rustsource',  # ORIGINAL: 2026-11-25, the family's static Rust source reader (literals, use trees, items)
    'deptable',  # ORIGINAL: 2026-11-25, a repo's root dependencies.toml read by its shape (OWNER-DAG)
    'ownerdag',  # ORIGINAL: 2026-11-25, OWNER-DAG: actual imports against the declared owner graph
    'rustdeps',  # ORIGINAL: 2026-11-25, OWNER-DAG over Rust: Cargo dependencies and std uses
    'passthrough',  # ORIGINAL: 2026-11-25, NO-DETOUR: a forwarding module names what its hop adds
)
