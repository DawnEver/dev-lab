r"""The family's RUFF configuration as DATA -- one row per owned TOML table, computed by nothing.

Held apart from :mod:`lab_commons.dev._famconfig_sections`, which reads it, for the reason
`_rule_rows.py` is held apart from `rules.py`: a table edited through the module that checks it
drifts away from what it describes, because the same edit that adds a row can relax the check that
would have refused it, and the diff looks like one change.

IT IS A SEPARATE FILE FROM :mod:`lab_commons.dev._famconfig_rows` BECAUSE ITS SUBJECT IS A DIFFERENT
KIND OF THING, and that is this arm's whole finding rather than a filing decision. That module's
bases are WHOLE FILES keyed by FILENAME; a ruff base owns a named TOML TABLE and must leave every
other table in the file alone. Measured 2026-09-18 against the live kit, `artefact_base('ruff.toml')`
and `artefact_base('pyproject.toml')` both raise `ForkedDelta`, and pointing the whole-file mechanism
at `pyproject.toml` is not the workaround: `RENDERED` would then demand the base own
`[build-system]`, `[project]`, `[tool.pytest.ini_options]` and `[tool.pyright]` as well.

MEASURED 2026-09-18 by parsing the live config of all four checkouts -- `lab-commons`, `wdg-lab`,
`optimi-lab` and the motronics-studio LANE at `.claude/worktrees/feat/optimi-lab` -- and taking set
intersections, never line counts:

* ``select`` -- 58 selectors, and the four-way symmetric difference is EMPTY. Not a shared core with
  local extras: the same 58 in every repo, which is what the widening stage landed.
* ``ignore`` -- intersection 10, union 67. The 10 are :data:`RUFF_IGNORE_CORE` and they are exactly
  what the kit ignores, so the kit's delta is empty and each consumer's is its own waiver set with
  its own ceiling. That asymmetry is the arm: a base that only asserted PRESENCE could not see a
  consumer ADD a waiver, and adding one is the move the ratchet exists to catch.
* ``line-length`` -- 120 in all four.
* ``quote-style`` -- ``single`` in all four; the other six ``[format]`` keys are shared by the three
  CONSUMERS and absent from the kit, so they are not the family's and are not here.
* ``target-version`` -- NOT shared, and named in :data:`RUFF_TARGET_VERSIONS` rather than dropped
  silently. The kit says ``py312`` and all three consumers say ``py313``. A base carrying either
  would be legislating a floor that is a fact about each repo's own interpreter, and one of the
  consumers derives it from its own ``requires-python`` under its own test.

THE ARTEFACT IS NOT A FILE, and this table is keyed accordingly. motronics keeps these tables in
``ruff.toml`` (where they lose the ``tool.ruff`` prefix and the root table is the file itself); the
other three keep them in ``pyproject.toml``. The kit already ruled that the PATH is per-repo data --
:data:`lab_commons.dev.profile.DEFAULT_LINT_CONFIG` says so, and
:func:`lab_commons.dev.rules.lint_selection` reads both shapes on purpose -- so a base keyed by
FILENAME would be the third place this family re-decided a question it had already answered twice.

WHY THE SECTION BASE IS KEYED BY TABLE AND NOT BY FILE, and why that is a fact about THIS repo's
data rather than about the machinery that reads it. motronics keeps the ruff tables in
``ruff.toml``; the other three keep them in ``pyproject.toml``. The kit had already ruled the path
is per-repo data twice (`profile.DEFAULT_LINT_CONFIG`, `rules.lint_selection`); converging the lone
dissenter onto one filename would re-decide it a third time, and MEASURED 2026-09-18 it is not the
cheap direction the plan assumed. That repo names ``ruff.toml`` in 15 tracked files, SEVEN of them
live mechanisms that would have to move with it: five open it by path (its one-Python-version
source, its cited-test root-config walk, its enforced registry, its registry-adoption test and its
disabled-rule ratchet) and two pin it by name (a 123-line config ratchet and a suppression ratchet
keyed on the filename). Keying the base by TABLE costs none of that, because reading both spellings
is a thing this package already does.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    'RUFF_CONFIG_NAMES',
    'RUFF_IGNORE_CORE',
    'RUFF_LINE_LENGTH',
    'RUFF_QUOTE_STYLE',
    'RUFF_SECTION_PREFIX',
    'RUFF_SECTION_ROWS',
    'RUFF_SELECT',
    'RUFF_SELECT_FLOOR',
    'RUFF_TARGET_VERSIONS',
]

#: The 58 selector groups, MEASURED as the four-way intersection and equal to the four-way UNION.
#: Sorted, so the order is re-derivable by anybody who repeats the measurement; a ruff ``select`` is
#: a set and nothing here depends on position, which is what makes sorting safe in a way it is NOT
#: safe for a last-match-wins `.gitignore` (see `_famconfig_rows.ORDER_SENSITIVE_ARTEFACTS`).
RUFF_SELECT: Final[tuple[str, ...]] = (
    'A',
    'AIR',
    'ANN',
    'ARG',
    'ASYNC',
    'B',
    'BLE',
    'C4',
    'C90',
    'COM',
    'D',
    'DJ',
    'DTZ',
    'E',
    'EM',
    'ERA',
    'F',
    'FA',
    'FBT',
    'FIX',
    'FLY',
    'FURB',
    'G',
    'I',
    'ICN',
    'INP',
    'INT',
    'ISC',
    'LOG',
    'N',
    'NPY',
    'PD',
    'PERF',
    'PGH',
    'PIE',
    'PLC',
    'PLE',
    'PLR',
    'PLW',
    'PT',
    'PTH',
    'PYI',
    'Q',
    'RET',
    'RSE',
    'RUF',
    'S',
    'SIM',
    'SLF',
    'SLOT',
    'T10',
    'T20',
    'TD',
    'TID',
    'TRY',
    'UP',
    'W',
    'YTT',
)

#: The floor under the select base. A scan or a comparison over an EMPTY select is indistinguishable
#: from one over a repo that agrees with the family. Set well below the measured 58 on purpose -- a
#: floor refuses an unread table, it is not a second pin on the count.
RUFF_SELECT_FLOOR: Final = 40

#: The 10 codes EVERY repo in the family globally ignores, MEASURED over 10 / 63 / 62 / 66 declared
#: ignores with a union of 67. This is the base; a consumer's remaining waivers are its DELTA, each
#: with a ceiling, which is the shape this arm exists to make expressible at all.
RUFF_IGNORE_CORE: Final[tuple[str, ...]] = (
    'COM812',
    'D203',
    'D213',
    'D400',
    'D401',
    'N818',
    'PLR0913',
    'Q000',
    'Q003',
    'S603',
)

#: MEASURED in all four repos. A scalar the base owns is EXACT rather than present: a repo that
#: widened its own line length is a divergence with a reason, not a fact the base should absorb.
RUFF_LINE_LENGTH: Final = 120

#: MEASURED in all four ``[format]`` tables. The only formatter key the KIT shares with the
#: consumers -- the other six (`preview`, `indent-style`, `line-ending`, `skip-magic-trailing-comma`,
#: `docstring-code-format`, `docstring-code-line-length`) are identical across the three consumers
#: and absent here, so they are the CONSUMERS' agreement and not the family's. Promoting them would
#: make this repo adopt three other repos' formatter settings on the strength of their agreeing with
#: each other, which is the anti-fork arm pointing the wrong way.
RUFF_QUOTE_STYLE: Final = 'single'

#: WHAT IS MEASURED AND DELIBERATELY NOT IN ANY BASE. Recorded rather than omitted, because an absent
#: key and a key nobody looked at read the same. The kit is one minor version behind its consumers
#: and that is a fact about the interpreters each repo runs on, not a family decision; motronics
#: additionally DERIVES its value from `requires-python` under its own test, so a family base
#: carrying a literal here would be a second source for a number that repo already single-sources.
RUFF_TARGET_VERSIONS: Final[dict[str, str]] = {
    'lab-commons': 'py312',
    'wdg-lab': 'py313',
    'optimi-lab': 'py313',
    'motronics-studio': 'py313',
}

#: The filenames a ruff config may live in, in RUFF'S OWN PRECEDENCE. A ``ruff.toml`` beside a
#: ``pyproject.toml`` WINS -- verified against ``ruff check --show-settings``, which prints the
#: settings path it used -- so a repo carrying both has one live config and one dead one, and reading
#: ``[tool.ruff]`` unconditionally would report the dead one as current.
RUFF_CONFIG_NAMES: Final[tuple[str, ...]] = ('.ruff.toml', 'ruff.toml', 'pyproject.toml')


#: The prefix a DEDICATED config file drops. In ``pyproject.toml`` the tables are ``[tool.ruff]*``;
#: in a ``ruff.toml`` the same tables are the file's root and ``[lint]`` / ``[format]``. One base,
#: two spellings, and the resolver refuses a file that somehow declares both.
RUFF_SECTION_PREFIX: Final[tuple[str, ...]] = ('tool', 'ruff')

#: Every owned table, by the spelling a reader writes it in. The value is
#: ``(dotted path, EXACT scalars, SET-valued keys)``; what the machinery adds is the prefix rule, the
#: comparison and the refusals, and this table owns WHICH tables and WHICH keys and nothing else.
RUFF_SECTION_ROWS: Final[dict[str, tuple[tuple[str, ...], dict[str, object], dict[str, tuple[str, ...]]]]] = {
    '[tool.ruff]': (('tool', 'ruff'), {'line-length': RUFF_LINE_LENGTH}, {}),
    '[tool.ruff.lint]': (('tool', 'ruff', 'lint'), {}, {'select': RUFF_SELECT, 'ignore': RUFF_IGNORE_CORE}),
    '[tool.ruff.format]': (('tool', 'ruff', 'format'), {'quote-style': RUFF_QUOTE_STYLE}, {}),
}
