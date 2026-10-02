r"""The kit's `pyproject.toml` SECTION delta -- data, computed by nothing.

THE KIT'S OWN DELTA ONLY. Every consumer declares its delta -- with its own package path -- in its own
tests and judges its own `pyproject.toml` through `lab_commons.dev.famconfig.inspect_section`; a
consumer's delta stored here is a fact about another repo, and it went stale against the real file
the day that repo's package path was not the neutral name this table spelled.

MEASURED 2026-09-19 and unchanged since: ``readme`` is ``README.md``, ``dynamic`` is ``["version"]``,
``testpaths`` is ``tests`` and nothing else -- the kit runs its doctests through
`lab_commons.dev.verify`, so it collects no source path. Both cells are zero-ceiling, and that is the
measurement rather than a placeholder.
"""

from __future__ import annotations

from typing import Final

from lab_commons.dev._famconfig_pyproject_rows import PROJECT, PYTEST_INI
from lab_commons.dev.famconfig import SectionDelta

__all__ = ['PYPROJECT_SECTION_DELTAS']

#: The kit's delta against every owned table: ``repo -> artefact -> SectionDelta``.
PYPROJECT_SECTION_DELTAS: Final[dict[str, dict[str, SectionDelta]]] = {
    'lab-commons': {
        PROJECT: SectionDelta(repo='lab-commons', added={}, dropped={}, ceiling=0),
        PYTEST_INI: SectionDelta(repo='lab-commons', added={}, dropped={}, ceiling=0),
    },
}
