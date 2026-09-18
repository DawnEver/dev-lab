r"""The four repos' `pyproject.toml` SECTION deltas -- data, computed by nothing, one entry per repo.

WHY THE KIT DECLARES THREE OTHER REPOS' DELTAS. It already does, three times, for the same reason: a
base is a claim about four trees, and a claim nobody re-derives ages fastest. `PRECOMMIT_OWN_HOOKS`
and `CONSUMER_IGNORE_DELTA` in `_config_census_rows.py` and `SECTION_DELTAS` in
`_famconfig_section_delta.py` are the precedent, and the suite beside this file re-measures every
entry here against the live checkouts rather than trusting it.

WHAT WAS MEASURED 2026-09-19, by parsing the live `pyproject.toml` of `lab-commons`, `wdg-lab`,
`optimi-lab` and the motronics-studio LANE at ``.claude/worktrees/feat/optimi-lab`` -- never the main
checkout:

* ``readme`` -- ``README.md`` in all four, verbatim. No drop exists anywhere.
* ``dynamic`` -- ``["version"]`` in all four, and nothing else in any of them. So every empty
  ``added['dynamic']`` below is a stated answer rather than an omission, and the day a repo adds a
  second dynamic field it raises a ceiling here in the same edit.
* ``testpaths`` -- ``tests`` in all four, and the ONLY key in this pair with a real delta. wdg-lab
  adds ``src/wdg_lab`` and optimi-lab adds ``src``; both do it to collect doctests out of their own
  package, which is the same intent spelled with each repo's own path and is therefore exactly what
  a delta is for rather than something a base could carry. lab-commons and motronics-studio add
  nothing -- the kit runs its doctests through `lab_commons.dev.verify` and motronics keeps its
  source out of collection on purpose.

THE DROP MAPS ARE ALL EMPTY AND THAT IS A MEASUREMENT. All four hold both owned `[project]` keys and
``testpaths``, so there is nothing for a drop to name. The machinery refuses a drop that outlives its
subject, which is what keeps this emptiness from being a default nobody checked.
"""

from __future__ import annotations

from typing import Final

from lab_commons.dev._famconfig_pyproject_rows import PROJECT, PYTEST_INI
from lab_commons.dev.famconfig import SectionDelta

__all__ = ['PYPROJECT_SECTION_DELTAS']

#: Every repo's delta against every owned table: ``repo -> artefact -> SectionDelta``.
#:
#: SIX OF THE EIGHT CELLS ARE ZERO-CEILING and that is the measurement, not a placeholder. The two
#: that are not name a single path each, and the ceiling sits ON the measurement so the next path
#: anybody collects raises a number in this file, in public, in the same edit.
PYPROJECT_SECTION_DELTAS: Final[dict[str, dict[str, SectionDelta]]] = {
    'lab-commons': {
        PROJECT: SectionDelta(repo='lab-commons', added={}, dropped={}, ceiling=0),
        PYTEST_INI: SectionDelta(repo='lab-commons', added={}, dropped={}, ceiling=0),
    },
    'wdg-lab': {
        PROJECT: SectionDelta(repo='wdg-lab', added={}, dropped={}, ceiling=0),
        PYTEST_INI: SectionDelta(
            repo='wdg-lab',
            #: Its own package, collected for `--doctest-modules`. The path names the package, which
            #: is why this is a delta and not a base line: `src/wdg_lab` is true of one repo.
            added={'testpaths': ('src/wdg_lab',)},
            dropped={},
            ceiling=1,
        ),
    },
    'optimi-lab': {
        PROJECT: SectionDelta(repo='optimi-lab', added={}, dropped={}, ceiling=0),
        PYTEST_INI: SectionDelta(
            repo='optimi-lab',
            #: The SAME INTENT as wdg-lab's and a different string -- this repo points at `src`
            #: rather than at the package inside it. Worth recording, because two repos reaching the
            #: same behaviour through two spellings is the case a base line would have flattened.
            added={'testpaths': ('src',)},
            dropped={},
            ceiling=1,
        ),
    },
    'motronics-studio': {
        PROJECT: SectionDelta(repo='motronics-studio', added={}, dropped={}, ceiling=0),
        PYTEST_INI: SectionDelta(repo='motronics-studio', added={}, dropped={}, ceiling=0),
    },
}
