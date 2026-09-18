r"""The `pyproject.toml` tables the family OWNS, and every table it measured and DECLINED.

THE GAP THIS CLOSES, MEASURED 2026-09-19 over the four live checkouts. ``pyproject.toml`` is the
biggest config file in the family -- 169 lines in lab-commons, 377 in wdg-lab, 223 in optimi-lab,
293 in the motronics lane -- and NOTHING owned a single key of it. The census scored the whole file
as one placement and stopped there, which is the state where four repos drift a shared convention
apart and no mechanism can say they did.

WHAT WAS MEASURED, table by table, by parsing all four files. Every table any repo declares was
enumerated -- 39 of them -- and each was decided. The two below are OWNED; :data:`PYPROJECT_DECLINED`
records the rest WITH the number that decided it, because a base that quietly omits a table is
indistinguishable from one nobody looked at.

THE BAR FOR PROMOTION IS FOUR-WAY AGREEMENT AND NOT THREE. That is not a style preference, it is the
worked example `RUFF_QUOTE_STYLE` already carries: six ``[tool.ruff.format]`` keys are identical in
the three CONSUMERS and absent in the kit, and promoting them would make the publishing repo adopt
three other repos' settings on the strength of their agreeing with each other -- the anti-fork arm
pointing the wrong way. ``[tool.commitizen]`` and ``[tool.coverage.*]`` have EXACTLY that shape here
(six and three consumer-identical keys apiece, no table at all in the kit) and are declined for
exactly that reason. Three repos agreeing is a fact about the consumers; it is not the family's.

WHY THE TWO PROMOTED KEYS ARE WORTH A BASE AT ALL, given they are two keys against 39 tables. Each
is a family CONVENTION that every repo would otherwise re-decide silently: ``dynamic = ["version"]``
says no repo hard-codes a version -- all four mint it from tags, three through ``setuptools-scm`` and
two through ``hatch-vcs``, and a repo that dropped the key would be pinning a literal that the
release machinery then disagrees with. ``readme = "README.md"`` is the file every repo's packaging
metadata points at. ``testpaths`` is the SET arm: all four collect ``tests``, and the two that also
collect their source tree for doctests ADD it through a delta, which is the direction a
presence-only mode could never see.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    'PROJECT',
    'PYPROJECT_DECLINED',
    'PYPROJECT_FILE',
    'PYPROJECT_SECTION_PREFIX',
    'PYPROJECT_SECTION_ROWS',
    'PYPROJECT_TABLE_FLOOR',
    'PYTEST_INI',
    'README_NAME',
]

#: The file every table below lives in, in all four repos. Unlike the ruff artefact there is no
#: second spelling: a ``pyproject.toml`` is the only place a ``[project]`` table can be.
PYPROJECT_FILE: Final = 'pyproject.toml'

#: The two owned tables, each spelled once so a reader and a declaration cannot drift apart.
PROJECT: Final = '[project]'
PYTEST_INI: Final = '[tool.pytest.ini_options]'

#: There is NO dedicated-file spelling for these tables, so the prefix a `SectionBase` strips is
#: EMPTY. Stated rather than left out: `SectionBase.prefix` is what lets the ruff base read both
#: ``pyproject.toml`` and ``ruff.toml``, and an empty prefix is the declaration that this artefact
#: has one home and the resolver's dedicated-file branch is not in play here.
PYPROJECT_SECTION_PREFIX: Final[tuple[str, ...]] = ()

#: The README filename all four repos' metadata points at. A constant rather than a literal in the
#: row below, because it is also the string the decline reasons quote.
README_NAME: Final = 'README.md'

#: Every owned table, in the spelling a reader writes it in: ``(dotted path, EXACT scalars, SETS)``.
#:
#: ``[project]`` owns TWO of its eleven-to-thirteen keys and that is the measurement, not a start.
#: ``dynamic`` is a SET rather than a scalar because it is one: a repo adding ``classifiers`` to it
#: is adding a member, and a delta can say so, where an exact-list scalar would force a drop of the
#: whole key to express a widening.
#:
#: ``[tool.pytest.ini_options]`` owns ONE key. ``addopts`` is the table's biggest and it is four-way
#: distinct; ``filterwarnings``, ``minversion`` and the rest are recorded in `PYPROJECT_DECLINED`.
PYPROJECT_SECTION_ROWS: Final[dict[str, tuple[tuple[str, ...], dict[str, object], dict[str, tuple[str, ...]]]]] = {
    PROJECT: (('project',), {'readme': README_NAME}, {'dynamic': ('version',)}),
    PYTEST_INI: (('tool', 'pytest', 'ini_options'), {}, {'testpaths': ('tests',)}),
}

#: The floor under how many tables this file DECIDES. A registry of declines is only evidence that
#: somebody looked if it is bigger than the handful anybody would name from memory, and the live
#: measurement enumerated 39 tables across the four repos. SEVEN is the count of the decline ROWS
#: below, each of which covers a table family; the suite asserts the rows against the live files.
PYPROJECT_TABLE_FLOOR: Final = 7

#: EVERY TABLE MEASURED AND NOT PROMOTED, with the number that decided it. Recorded rather than
#: omitted: an absent table and a table nobody looked at read identically, and this family has
#: already been bitten by exactly that (`RUFF_TARGET_VERSIONS` exists for the same reason).
#:
#: The key is the table's dotted path as a tuple, so the suite beside this can walk the live
#: documents and refuse a row naming a table no repo declares -- a decline that outlives its subject
#: is a decision nothing consults.
PYPROJECT_DECLINED: Final[dict[tuple[str, ...], str]] = {
    ('build-system',): (
        'GENUINELY PER-REPO, and it is a 2-2 split rather than a near-miss. lab-commons and '
        'motronics-studio build with `hatchling` + `hatch-vcs`; wdg-lab and optimi-lab build with '
        '`setuptools` + `setuptools-scm`. Neither `requires` nor `build-backend` has a value more '
        'than two repos share, so there is no four-way agreement to promote and no majority that '
        'would not be one pair legislating for the other. The build backend is also the one setting '
        'that cannot be adopted by editing a table: it decides which of `[tool.hatch.*]` or '
        '`[tool.setuptools*]` the rest of the file must speak.'
    ),
    ('tool', 'commitizen'): (
        'THE CONSUMERS AGREE AND THE KIT HAS NO SUCH TABLE -- the `RUFF_QUOTE_STYLE` shape exactly. '
        'Six keys (`name`, `tag_format`, `version_scheme`, `version_provider`, '
        '`update_changelog_on_bump`, `changelog_incremental`) are verbatim identical in all three '
        'consumers and ABSENT in lab-commons, which mints versions from tags through hatch-vcs and '
        'publishes no changelog at all. Promoting them would make the publishing repo adopt a '
        'release workflow it deliberately does not run, on the strength of three other repos '
        'agreeing with each other. `allowed_prefixes` is motronics-only and would be its delta.'
    ),
    ('tool', 'coverage'): (
        'THE SAME SHAPE, AND WEAKER. No table in the kit, which measures no coverage; and among the '
        'three consumers only `run.branch`, `report.precision` and `html.directory` agree. The keys '
        'that carry the content do NOT: `run.source` is `src/wdg_lab` / `src` / `src/motronics`, and '
        '`report.omit` and `report.exclude_lines` each differ in two of the three. So this is not '
        'even a consumer agreement worth arguing about -- it is three repos naming their own package.'
    ),
    ('tool', 'pyright'): (
        'ONE REPO. Only motronics-studio declares it, over six keys, three of which name paths into '
        'that tree (`include = ["src/motronics/contracts", "src/motronics/core"]`, `exclude` naming '
        'its `attic/`). A base over one repo agrees with everything it reads and refuses nothing, '
        'which is the vacuous green every floor in this package exists to stop.'
    ),
    ('tool', 'lab_commons'): (
        'ONE REPO, AND THE KIT ALREADY OWNS IT IN CODE. Only wdg-lab declares '
        '`[tool.lab_commons.verify]`, and its schema is defined by `lab_commons.dev.verify` in this '
        'package. A section base restating that schema would be a SECOND source for it, and the one '
        'key it holds (`allowed_skips`) is eight paths into one lab`s test tree.'
    ),
    ('tool', 'hatch'): (
        'A CONSEQUENCE OF `[build-system]` AND NOT AN INDEPENDENT DECISION. Present in the two '
        'hatchling repos and meaningless in the other two, the same way `[tool.setuptools*]` and '
        '`[tool.setuptools_scm]` are present in the two setuptools repos and meaningless here. '
        'Declining the backend declines both of its consequences; promoting either would be the '
        'base taking a side in a split it has already recorded as per-repo. `[tool.maturin]` and '
        '`[tool.uv]` are one repo apiece and decline for the `[tool.pyright]` reason.'
    ),
    ('project', 'optional-dependencies'): (
        'IT IS THE DEPENDENCY GRAPH, AND `dev` IS THE NEAR MISS WORTH NAMING. All four declare a '
        '`dev` extra and all four differ: the kit lists four packages, the consumers list ten to '
        'fourteen, and only `pytest`, `pytest-mock`, `ruff` and `pre-commit` are common to all four. '
        'Those four ARE the kit`s whole list, so promoting them would pin the publisher at exactly '
        'what it has today while saying nothing about any consumer -- a base that cannot move. Every '
        'other extra (`euclid`, `femm`, `web`, `rust`, `cad3d`, ...) names one repo`s physics or one '
        'repo`s vendor. `[project.scripts]` and `[project.urls]` decline for the same reason: they '
        'name entry points and forges that exist in one repo each.'
    ),
}
