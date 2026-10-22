r"""The CONFIG-layer placement census, FIRST half -- pure DATA, one row per artefact per repo.

A row is ``<repo>::<artefact> -> Placement(side, why)``, partitioned by REPO because a repo is what
a lane owns. The machinery that reads it, and the three sides it may use, are `_config_census.py`;
this file computes nothing, exactly as `_rule_rows.py` computes nothing for `rules.py`.

MEASURED 2026-09-17 against four checkouts: `lab-commons`, `consumer-b`, `consumer-c`, and the
consumer-a LANE at `.claude/worktrees/feat/consumer-c` (since retired; see `REPO_PATHS`). Every
quantity a row cites is re-derived by the test beside it; the constants below are what it compares
against, so a number that stops being true reds rather than ageing quietly into prose.

THE TWO HEADLINE FINDINGS, both confirmed and both sharper than the line counts that suggested them:

1. THE KIT WAS LINTED LESS STRICTLY THAN EVERYTHING IT SHIPS TO -- CLOSED 2026-09-17 by R1, which
   adopted the 58 verbatim; `GROUPS_THE_KIT_DOES_NOT_LINT` is 0 and
   `test_the_kit_is_not_linted_less_than_what_it_ships.py` reds if it re-opens. The COUNTER-DIRECTION
   half is NOT closed and cannot be from this repo: it lives in three other repos' ignore lists, so
   it ships as a named waiver set with a ceiling. The finding as measured, kept verbatim: it was not
   a clean subset. The
   three consumers share an IDENTICAL 58-selector `select` (symmetric difference EMPTY, all three
   pairs). lab-commons selects 12. Eight of those are whole groups the consumers also take
   (E W F I UP B SIM RUF); the other four are single codes (ARG001 PLC0415 PLW0603 TRY301) that sit
   inside consumer groups ARG PLC PLW TRY and are ignored by NO consumer, so on those four the
   consumers are at least as strict. That leaves 50 selector groups the consumers lint and the kit
   does not. The counter-direction is exactly 8 codes -- inside the 8 shared groups every consumer
   globally ignores B018 B904 E501 RUF012 RUF043 SIM108 SIM113 UP017, which lab-commons enforces.
   So the kit is blind to 50 groups and stricter on 8 codes, and neither half of that is a subset.

2. CONSUMER_A' TWO RUFF CONFIGS ARE NOT TWO DECISIONS. `ruff check --show-settings` prints
   ``Settings path: ...\\ruff.toml``, so `ruff.toml` WINS and `pyproject.toml`'s `[tool.ruff]` is
   never read. What the loser holds is exactly one key -- ``extend = 'ruff.toml'`` -- which names the
   winner and nothing else, so the loser contains nothing the winner does not. It is a dead
   declaration rather than a lying one, and the distinction is worth the row: deleting it changes no
   behaviour, and leaving it invites the next reader to edit the file ruff does not read.
"""

from __future__ import annotations

from _config_census import MOVES, SPLITS, STAYS, Placement

__all__ = [
    'ARTEFACTS',
    'CONSUMER_IGNORE_CORE',
    'CONSUMER_IGNORE_DELTA',
    'CONSUMER_SELECT',
    'COUNTER_DIRECTION_CODES',
    'GROUPS_THE_KIT_DOES_NOT_LINT',
    'KIT_IGNORE',
    'KIT_PER_FILE_WAIVERS',
    'KIT_SELECT',
    'KIT_SELECT_BEFORE_R1',
    'MAKE_TARGET_CORE',
    'PARTITIONS',
    'REPOS',
    'REPO_PATHS',
    'SHARED_GITIGNORE_CORE',
]

#: The four repos of the family, in dependency order: the kit first, then what it ships to.
REPOS: tuple[str, ...] = ('lab-commons', 'consumer-b', 'consumer-c', 'consumer-a')

#: Where each consumer is checked out, RELATIVE TO LAB-COMMONS' PARENT: the PRIMARY checkout, by the
#: same sibling convention `lab-commons/` itself sits under. Until 2026-09-30 the consumer-a entry named
#: a lane worktree (`.claude/worktrees/<lane>`) that had since been disposed of, so every
#: census here silently measured three repos while saying four. A census only READS, and only at
#: HEAD (`read_at_head`), so reading the integrator's checkout touches nothing in it.
#: consumer-b is NOT a direct sibling: the family root groups it under an org directory, and until
#: 2026-10-01 this map said `consumer-b` and every census silently measured three repos again.
#: THESE ARE NEUTRAL DEFAULTS: this tree is published and names no consumer. A box that has the
#: siblings maps each name to its real checkout through `LAB_COMMONS_SIBLINGS`
#: (`dev_lab.dev.doorcensus.sibling_paths`).
REPO_PATHS: dict[str, str] = {
    'consumer-b': 'example-org/consumer-b',
    'consumer-c': 'consumer-c',
    'consumer-a': 'consumer-a',
}

#: The config artefacts under census. ``ruff-config`` is an ARTEFACT rather than a FILE on purpose:
#: three repos hold it inside `pyproject.toml` and one holds it in `ruff.toml`, and a census keyed by
#: filename would score that difference as two unrelated rows instead of one relocation.
ARTEFACTS: tuple[str, ...] = (
    'pyproject.toml',
    'ruff-config',
    '.gitignore',
    'Makefile',
    'docs-src/dev/',
)

#: The 58 selectors all three consumers select, VERBATIM AND IDENTICAL in all three.
CONSUMER_SELECT: tuple[str, ...] = (
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

#: WHAT LAB-COMMONS SELECTED BEFORE R1, kept because COUNTER_DIRECTION_CODES is stated over it. The
#: eight codes below are the divergences that existed INSIDE the groups both sides already took; the
#: adoption necessarily created more (48 of them, held as ADOPTION_DEBT in
#: `test_the_kit_is_not_linted_less_than_what_it_ships.py`), and mixing the two would make the
#: pre-existing eight unfindable. Eight of these twelve are whole groups; four are single codes.
KIT_SELECT_BEFORE_R1: tuple[str, ...] = (
    'E',
    'W',
    'F',
    'I',
    'UP',
    'B',
    'SIM',
    'RUF',
    'PLC0415',
    'PLW0603',
    'ARG001',
    'TRY301',
)

#: What lab-commons selects. AS OF 2026-09-17 (R1) this IS `CONSUMER_SELECT`, adopted verbatim --
#: the blindness below is closed, and the alias is kept rather than collapsed so the census keeps one
#: name per REPO and a future divergence has somewhere to be recorded.
KIT_SELECT: tuple[str, ...] = CONSUMER_SELECT

#: What lab-commons IGNORES, as of the same commit. It was EMPTY before R1, and every entry names a
#: rule that is wrong for this repo rather than one that was expensive; `pyproject.toml` carries the
#: reasons and `test_arch_suppressions_are_a_named_set.py` carries the per-file ones. NONE of the
#: eight COUNTER_DIRECTION_CODES appears here, which is what keeps arm 2 below non-vacuous.
KIT_IGNORE: tuple[str, ...] = (
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

#: Selector groups every consumer lints and lab-commons does not select at all. It was 50 when this
#: census was written on 2026-09-17 and it is 0 by the end of the same day: R1 adopted the 58. The
#: constant STAYS rather than being deleted, because a number that can only be 0 is the shape a
#: ratchet needs -- `test_the_kit_is_not_linted_less_than_what_it_ships.py` is what holds it there.
GROUPS_THE_KIT_DOES_NOT_LINT = 0

#: The 62 codes all three consumers ignore. This is the SHARED BASE of the lint config: the select
#: is byte-identical and the ignore lists agree on 62 of 63/62/66 entries.
CONSUMER_IGNORE_CORE: tuple[str, ...] = (
    'ANN001',
    'ANN002',
    'ANN003',
    'ANN201',
    'ANN202',
    'ANN206',
    'ARG002',
    'B018',
    'B904',
    'C901',
    'COM812',
    'D100',
    'D101',
    'D102',
    'D103',
    'D104',
    'D105',
    'D107',
    'D203',
    'D205',
    'D213',
    'D400',
    'D401',
    'D415',
    'D417',
    'DTZ005',
    'E501',
    'ERA001',
    'EXE',
    'FBT',
    'FIX',
    'INP001',
    'LOG015',
    'N801',
    'N802',
    'N803',
    'N805',
    'N806',
    'N815',
    'N816',
    'N818',
    'NPY002',
    'PLR0912',
    'PLR0913',
    'PLR0915',
    'PLR2004',
    'PLW2901',
    'PT012',
    'PT018',
    'Q000',
    'Q003',
    'RUF012',
    'RUF043',
    'S101',
    'S311',
    'S603',
    'SIM108',
    'SIM113',
    'SLF001',
    'TD',
    'TRY300',
    'UP017',
)

#: What each consumer ignores BEYOND the core -- the whole repo-shaped delta of the lint config, and
#: it is five codes across three repos. This is the measurement the SPLITS rows rest on: a seam is
#: worth naming when the shared side is 62 rows and the private side is one, four and zero.
CONSUMER_IGNORE_DELTA: dict[str, tuple[str, ...]] = {
    'consumer-b': ('ANN205',),
    'consumer-c': (),
    'consumer-a': ('B023', 'PLR0917', 'RUF002', 'RUF003'),
}

#: Codes lab-commons ENFORCES and every consumer disables. The other direction of finding 1, and the
#: reason it is not stated as "lab-commons is a subset".
COUNTER_DIRECTION_CODES: tuple[str, ...] = (
    'B018',
    'B904',
    'E501',
    'RUF012',
    'RUF043',
    'SIM108',
    'SIM113',
    'UP017',
)

#: `.gitignore` patterns shared by all three consumers. FOURTEEN, and it read TWELVE until
#: 2026-09-19: `**/__pycache__/` and `*.egg-info/` are in all three and had been left out, so the
#: constant sat two patterns UNDER its own measurement and the arm guarding it could not see that --
#: it asserted `SHARED_GITIGNORE_CORE <= each consumer`, which any shorter tuple satisfies. It is now
#: asserted as an EQUALITY against the live three-way intersection.
#:
#: THE RE-MEASUREMENT ALSO FOUND THE FOURTEEN ARE EXACTLY `BASES['.gitignore'].content_lines`. The
#: census and the base are two independent readings and that they agree is a FINDING rather than a
#: reason to derive one from the other.
#:
#: lab-commons ADOPTED the rendered base on 2026-10-03 and so holds all fourteen; the base itself is
#: this core plus the family-mandated lines in `_famconfig_rows.GITIGNORE_FAMILY_LINES`.
SHARED_GITIGNORE_CORE: tuple[str, ...] = (
    '**/.env',
    '**/__pycache__/',
    '**/log/*.log',
    '**/log/*.log.error',
    '**/temp/**',
    '*.c',
    '*.egg-info/',
    '*.spec',
    '.coverage*',
    '.mypy_cache/',
    '.pytest_cache/',
    '.ruff_cache/',
    '.venv*',
    'uv.lock',
)

#: Makefile targets present in ALL FOUR repos. NINE, out of 11/18/14/16 -- and it read THREE
#: (`fmt`, `lint`, `test`) until 2026-09-18, when a re-measurement found the shared base had fully
#: ARRIVED underneath this tuple: the all-four set is now EXACTLY the nine targets `MAKEFILE_BASE`
#: defines, `verify` included. The old three were not wrong when written; they were never re-read.
#: This is a NAMED SET and not a floor, so it deliberately sits ON its population: the remedy when a
#: repo drops one is to restore the TARGET, never to shorten this tuple to meet the tree.
MAKE_TARGET_CORE: tuple[str, ...] = (
    'all',
    'clean',
    'fmt',
    'install',
    'install-dev',
    'lint',
    'test',
    'test-parallel',
    'verify',
)

# ------------------------------------------------------------------ lab-commons: the kit itself

ROWS_LAB_COMMONS: dict[str, Placement] = {
    'lab-commons::pyproject.toml': Placement(
        STAYS,
        'THE ONE FILE THAT CANNOT BE SHARED, because its subject is the wheel this repo publishes: '
        'the distribution name, the hatch-vcs version source writing `src/lab_commons/__version__.py`, '
        'the six tier-1 dependencies and the `dev` extra that gates `dev_lab.dev`. At 69 lines it '
        'is the smallest of the four and the difference is not restraint -- it carries no `[tool.ruff]` '
        'exclude list, no pyright block and no Rust build, because this repo has none of those trees. '
        'What breaks if it moved: nothing installs. Only the lint block inside it is a shared question, '
        'and that is the `ruff-config` row, which is why this census keys the artefact rather than '
        'the file.',
    ),
    'lab-commons::ruff-config': Placement(
        SPLITS,
        'THE FINDING, AND HALF OF IT IS NOW CLOSED. As measured on 2026-09-17 this repo selected 12 '
        'selectors against the consumers` IDENTICAL 58, so the kit was blind to 50 selector groups it '
        'lints its own consumers for -- among them D, ANN, S, PTH, PT, N and TRY. R1 ADOPTED THE 58 the '
        'same day, so that half is a ratchet rather than a defect now. It was not a subset either way: '
        'inside the 8 groups both sides took, the consumers globally ignore 8 codes '
        '(B018 B904 E501 RUF012 RUF043 SIM108 SIM113 UP017) that this repo enforces, and THAT half is '
        'open -- its remedy is in three other repos, so it ships as a named waiver set with a ceiling. '
        'THE SEAM: the 58 '
        'selectors and the 62 shared ignores are the base and belong here as shipped DATA; what stays '
        'per repo is `exclude` (which trees a repo carries) and `per-file-ignores`. What breaks if the '
        'base moved: nothing today -- the consumers already agree byte for byte, which is exactly why '
        'sharing it costs nothing and why it has not been noticed that this repo opted out of it.',
    ),
    'lab-commons::.gitignore': Placement(
        SPLITS,
        'RENDERED SINCE 2026-10-03, on the user ruling that every project-level file has one source in '
        'this package. It had been declined: ten patterns, a subset of no consumer in either direction. '
        'What closed it was the BASE moving rather than this file: the family-mandated lines '
        '(`.verify/`, `**/__version__.py`, `/build/`, `/dist/`, `htmlcov/`, `output/`, '
        '`**/.DS_Store` and the ordered Claude project-state section) joined the fourteen-pattern '
        'consumer core, after which this tree`s file is the base plus ONE delta line, `*.py[cod]`. '
        'THE SEAM is the base: every pattern a family mechanism writes. What BREAKS if the one delta line moved: a '
        'compiled file outside `__pycache__/` gets committed. `tests/test_the_kit_renders_its_own_gitignore.py` '
        'holds the rendering.',
    ),
    'lab-commons::Makefile': Placement(
        SPLITS,
        'ELEVEN TARGETS AGAINST 18/14/16, AND THE BASE IS NINE -- WHICH IS TWO CLEAR. This row used to '
        'read "seven against 19/15/16 and the base is three" and to argue the seam was the verify '
        'contract still to be moved. Re-measured 2026-09-18: the move LANDED. All four repos now '
        'carry `verify`, and the all-four common set is EXACTLY the nine targets `MAKEFILE_BASE` '
        'defines, so this file is now two lines clear of the base rather than four short of it. THE '
        'SEAM is therefore no longer a proposal: what STAYS is `adoption`, which runs this repo`s '
        'rules-adoption test BY PATH -- it names a test file, and a path into a tree is the one thing '
        'a shared Makefile cannot carry. What breaks if the remaining two moved: a shared file would '
        'name a test that exists in one repo. Still SPLITS, but on a base that is now thick.',
    ),
    'lab-commons::docs-src/dev/': Placement(
        STAYS,
        'THE ORIGIN OF THE SHARED TREE, so "stays" here is a statement about the other three. Thirteen '
        'pages, and the split measured across the family is not 13/1/1/14 as a line count suggests: the '
        'labs` single page is a POINTER TABLE generated by `dev_lab.dev.devdocs.pointer_table` and '
        'consumer-a` 14 share nine FILENAMES with this tree, every one of them already reduced to a '
        'pointer plus a local delta. So this is the only tree in the family holding the family`s '
        'mechanism as prose, which is what makes it the one that may not move. What breaks if it moved: '
        'the pointer tables in all three consumers resolve to nothing, and `devdocs.PAGES` -- the data '
        'those tables are rendered from -- describes a tree that is not there.',
    ),
}


# ------------------------------------------------------------------ consumer-b

ROWS_CONSUMER_B: dict[str, Placement] = {
    'consumer-b::pyproject.toml': Placement(
        STAYS,
        'THE LARGEST OF THE FOUR AT 344 LINES, and the size is its subject: a maturin/Rust build, a web '
        'backend, and a dependency set that names this repo`s own domain. The packaging half of a '
        'pyproject is per-distribution by definition -- two wheels cannot share a name. What breaks if '
        'it moved: nothing installs, and the Rust extension has no build backend. The only shared '
        'question inside it is `[tool.ruff]`, which this census keys separately because it is the half '
        'that is byte-identical to two other repos.',
    ),
    'consumer-b::ruff-config': Placement(
        SPLITS,
        'SHARED WITH CONSUMER_C AND CONSUMER_A TO WITHIN ONE CODE. Measured: the 58-selector `select` is '
        'IDENTICAL across all three (symmetric difference EMPTY, all three pairs); line-length 120, '
        'target py313, unsafe-fixes true, quote-style single, preview false are identical too; and this '
        'repo`s ignore list is the 62-code core plus exactly ONE code, ANN205. THE SEAM is therefore '
        'sharp: select + the 62 ignores are the base, and the delta is `ANN205`, `exclude` (which names '
        '`experiment/`, `ignore/`, `input/`, `scripts/setup.py` -- trees only this repo has) and 7 '
        '`per-file-ignores` paths into `src/consumer_b/consumer_b_viz/`, which is legacy code being brought up '
        'rather than a policy. What breaks if the base moved: nothing here -- it would move to a file '
        'this repo already depends on, and the 7 viz paths stay because a path is a fact about a tree.',
    ),
    'consumer-b::.gitignore': Placement(
        SPLITS,
        '61 LIVE PATTERNS OVER A 12-PATTERN CONSUMER CORE. THE SEAM is that core -- the caches, '
        '`.venv*`, `.coverage*`, `**/.env`, `**/log/*.log`, `uv.lock`, `*.c`, `*.spec` -- which is a '
        'fact about uv, pytest, ruff and Cython rather than about windings. What STAYS is the other 49: '
        '`target/` and the Rust build products, `htmlcov/`, `archived/`, `schema/`, and the '
        'output/input trees this repo`s examples write into. Those name directories that exist only '
        'here. What breaks if they moved: a shared ignore file would have to list every directory any '
        'repo might have, which is how an ignore file acquires patterns nobody can attribute -- the '
        'exact failure mode a SPLITS seam exists to avoid.',
    ),
    'consumer-b::Makefile': Placement(
        SPLITS,
        'NINETEEN TARGETS, THE MOST OF THE FOUR, AND EIGHT OF THEM ARE THE CONSUMER CORE (`all`, '
        '`clean`, `fmt`, `install`, `install-dev`, `lint`, `test`, `test-parallel` -- measured as the '
        'three-way intersection). THE SEAM is that core plus `verify`: the same lint/format/test triple '
        '`dev_lab.dev.verify` ships as code. What STAYS is `schema`, `serve`, `install-web` and '
        '`setup-hooks` -- the first three name this repo`s web backend and its JSON schema, and the '
        'fourth exists only because this repo needs a hook install step at all. What breaks if the core '
        'moved: nothing, provided `verify` keeps its meaning; what breaks if `serve` moved is that a '
        'shared Makefile would reference a backend three of the four repos do not have.',
    ),
    'consumer-b::docs-src/dev/': Placement(
        MOVES,
        'ALREADY MOVED, AND THE "1" IS THE EVIDENCE RATHER THAN THE GAP. The single page is 30 lines and '
        'is a POINTER TABLE into `../../../lab-commons/docs-src/dev/`, listing all 12 family pages and '
        'generated by `dev_lab.dev.devdocs.pointer_table` so a page renamed upstream cannot leave '
        'this one quietly wrong. Its own text dates the move to 2026-09-16 and states that before it '
        'there was NO page here describing how a verdict is produced -- so the near-zero is a repo that '
        'stopped keeping its own copy, not one that never wrote the mechanics. What a consumer would '
        'lose if it were not shared: the twelve pages, plus the property that the index cannot drift, '
        'and the repo would be back to the state its own page names as the defect it closed.',
    ),
}


# ------------------------------------------------------------------ consumer-c

ROWS_CONSUMER_C: dict[str, Placement] = {
    'consumer-c::pyproject.toml': Placement(
        STAYS,
        '225 LINES WHOSE SUBJECT IS THIS DISTRIBUTION: the package name, the optimiser dependencies and '
        'the extras a consumer installs. A pyproject is the one artefact per repo that is repo-shaped '
        'by construction rather than by habit -- two wheels cannot share a name, a version source or a '
        'dependency set. What breaks if it moved: nothing installs. Its `[tool.ruff]` block is the only '
        'shared question inside it and is keyed as its own artefact, which is what lets this row be a '
        'clean STAYS instead of a SPLITS that never names its seam.',
    ),
    'consumer-c::ruff-config': Placement(
        SPLITS,
        'THE PUREST CASE IN THE CENSUS, AND THE ONE THAT MAKES "NEAR-IDENTICAL" A MEASUREMENT RATHER '
        'THAN AN IMPRESSION: this repo`s ignore list IS the 62-code consumer core with NOTHING added '
        '(delta of zero), its 58-selector select is identical to both other consumers, and all four '
        'scalar knobs match. THE SEAM is therefore everything except `exclude`, which names `archived/`, '
        '`ignore/`, `input/`, `output/` and `**/__version__.py` -- directories this repo has and the '
        'kit does not. What breaks if the shared half moved: nothing measurable, which is precisely the '
        'claim a SPLITS row has to survive -- there is no code in this file the other two do not also '
        'have, so the repo-shaped delta here is a five-entry path list and nothing else.',
    ),
    'consumer-c::.gitignore': Placement(
        SPLITS,
        'THIRTY LIVE PATTERNS, THE SMALLEST CONSUMER, AND 12 OF THEM ARE THE SHARED CORE -- so 40 per '
        'cent of this file is the family`s and the rest is this repo`s trees (`archived/`, `output/`, '
        '`htmlcov/`, `usr/`). THE SEAM is the generated-artefact core: caches, `.venv*`, `.coverage*`, '
        '`uv.lock`, `**/.env`, `**/log/*.log`. What STAYS is `usr/`, which appears in no other repo at '
        'all, and the output trees the examples write into. What breaks if the trees moved into a '
        'shared file: it would have to name every directory any family repo might create, and a pattern '
        'nobody can attribute to a tree is one nobody dares delete -- which is how an ignore file '
        'reaches 61 lines, as the sibling repo`s already has.',
    ),
    'consumer-c::Makefile': Placement(
        SPLITS,
        'FIFTEEN TARGETS, AND THE CLOSEST OF THE THREE CONSUMERS TO THE KIT`S OWN: it is the only one '
        'besides lab-commons carrying BOTH `fmt-check` and `adoption`, and it has `verify` as well -- so '
        'the verify contract (`lint`, `fmt-check`, `test`) is present in identical shape in two repos '
        'and shipped as code in `dev_lab.dev.verify`. THE SEAM is that contract plus the eight-target '
        'consumer core. What STAYS is `purity`, which runs this repo`s own import-purity test by PATH: a '
        'path into a tree cannot be shared, because the tree is what differs. What breaks if `verify` '
        'moved: nothing -- it would become one line calling the module this repo already depends on, '
        'and the three-repo drift in what `verify` MEANS would stop being possible.',
    ),
    'consumer-c::docs-src/dev/': Placement(
        MOVES,
        'ALREADY MOVED, SAME DAY AND SAME SHAPE AS CONSUMER_B: one 30-line page, a pointer table into '
        '`../../../lab-commons/docs-src/dev/` generated by `dev_lab.dev.devdocs.pointer_table`, '
        'listing the same 12 family pages. Its text is sharper than its sibling`s on one point worth '
        'keeping: it says this repo had no `docs-src/` tree AT ALL before that day, so the "1" is a '
        'tree created as a pointer rather than a tree emptied into one. What a consumer would lose if '
        'it were not shared: the twelve pages, and the guarantee that a rename upstream reds here '
        'instead of leaving a table of dead links -- which is the property a copied document cannot '
        'have and is the reason this side is MOVES rather than SPLITS.',
    ),
}


# ------------------------------------------------------------------ consumer-a (the LANE)

ROWS_CONSUMER_A: dict[str, Placement] = {
    'consumer-a::pyproject.toml': Placement(
        SPLITS,
        'STAYS ON ITS PACKAGING HALF for the reason every pyproject does -- the distribution name, the '
        'Rust/maturin build, the `[tool.pyright]` include list that a pre-push hook reads as its own '
        'scope. THE SEAM IS ALREADY CUT AND ONE SPLINTER IS LEFT: `[tool.ruff]` was moved out to '
        '`ruff.toml`, and what remains under that key is a single entry, `extend = "ruff.toml"`, which '
        'ruff never reads -- `ruff check --show-settings` prints `Settings path: ...ruff.toml`, so the '
        'file-level config wins outright. The loser therefore contains nothing the winner does not; it '
        'is dead rather than lying. What breaks if it is deleted: nothing, verified by what ruff '
        'reports it loaded. What breaks if it is LEFT: the next reader edits the file ruff does not '
        'read, and the edit passes every test in this repo.',
    ),
    'consumer-a::ruff-config': Placement(
        SPLITS,
        'THE ONLY REPO WITH A STANDALONE `ruff.toml`, AND IT IS THE WINNER -- verified by '
        '`ruff check --show-settings`, not by reading ruff`s documentation. Its content is the family`s: '
        'the 58-selector select is IDENTICAL to both labs`, the four scalar knobs match, and the ignore '
        'list is the 62-code core plus four (B023, PLR0917, RUF002, RUF003). THE SEAM is select + the '
        '62 ignores against a delta of four codes and an `exclude` naming `attic` and `.claude/memory` '
        '-- two trees only this repo has, and `attic` is a tree the invariants forbid deleting, so its '
        'exclusion is load-bearing rather than cosmetic. RUF002/RUF003 (ambiguous unicode in a '
        'docstring or comment) are the one delta that is arguably the family`s too, since the family '
        'now bans CJK in tracked files outright. What breaks if the base moved: nothing -- the three '
        'consumers already agree on it to within five codes in total.',
    ),
    'consumer-a::.gitignore': Placement(
        SPLITS,
        '73 LIVE PATTERNS, THE LARGEST, AND THE SHARED CORE IS THE SAME 12 the other consumers hold. '
        'THE SEAM is that core. What STAYS is everything that names a tree only this repo has: `attic/` '
        'partially, the Rust `target/`, `cases/*/output/`, the FEMM and JMAG scratch products, and '
        '`.hypothesis/`. Those are not stylistic -- a solver writes large binary artefacts beside the '
        'case that produced them, and the patterns that catch them are derived from this repo`s '
        'directory layout. What breaks if they moved: a shared ignore file would carry vendor-specific '
        'suffixes three of the four repos have never seen, and nobody deleting one could tell whether '
        'some other repo still needed it -- the un-attributable-pattern failure mode again.',
    ),
    'consumer-a::Makefile': Placement(
        SPLITS,
        'SIXTEEN TARGETS, AND THE GAP THIS ROW WAS WRITTEN AROUND IS CLOSED. It used to read "the only '
        'one of the four with no `verify` target at all", and said the move could not be mistaken for '
        'closing it -- correctly, because what closed it was a separate edit in the lane that gave '
        'this repo its own `verify` naming `scripts/gate/runner.py`. Re-measured 2026-09-18: all four '
        'carry `verify`, so the sentence a newcomer reads to learn how to check this repo now names '
        'the check. THE SEAM is the nine-target base. What STAYS is `build-rust`, `fmt-rust`, '
        '`test-femm` and `typecheck` -- a Cargo workspace and a live vendor engine, neither of which '
        'any other repo has. What breaks if the base moved: nothing. A RESIDUAL WAS CLAIMED HERE AND IT '
        'WAS FALSE: this row said "this repo`s `verify` shells its own 1770-line runner rather than '
        '`dev_lab.dev.verify`, so the four repos share the target NAME and not the contract". '
        'MEASURED 2026-09-18 off the live Makefile at line 91 (header 90): the recipe is `python -m '
        'dev_lab.dev.verify`, the family base line verbatim, and `unbound_recipes` confirms it '
        'bound to that header. THE TARGET AND THE CONTRACT ARE BOTH SHARED. The claim was written '
        'from an assumption about what a repo owning a 1770-line runner must do, and never read the '
        'two lines that refute it. What DOES diverge is the VERDICT -- `scripts/gate/runner.py '
        '{measure|gate|heavy}` knows cases, solvers and the live vendor engines and separates '
        'INCONCLUSIVE from PASS/FAIL, none of which the kit`s portable remainder models or should. '
        'That divergence is correct and consumer-a now declares it with a test.',
    ),
    'consumer-a::docs-src/dev/': Placement(
        SPLITS,
        'THE SEAM IS CUT AND EXECUTED, AND THE 14 IS NOT A COPY OF THE KIT`S 13. Nine filenames are '
        'shared with lab-commons and every one of them has already been reduced to a POINTER plus this '
        'repo`s own delta -- `the-three-participants.md` is 6 lines against 38 upstream and says '
        '"MOVED to the family tree on 2026-09-16"; `shared-checkout.md` is 13 against 48 and keeps only '
        'the spellings a reader hunting a symptom would search for. What STAYS is the five pages with '
        'no upstream twin: `gate.md`, `testing.md`, `integration.md`, `user-flow.md` and '
        '`compute-resources.md`, whose subject is the tiered gate runner, the case library and the live '
        'vendor engines. What breaks if those moved: the shared tree would describe a verdict machine '
        'three repos do not have, and `dev/index.md` in both labs already states the opposite as a '
        'promise a reader may rely on.',
    ),
}

#: The partitions, in the order :data:`REPOS` declares. The composer checks every key against the
#: repo its partition names, so a row that drifts into the wrong table is an import-time failure.
PARTITIONS: tuple[tuple[str, dict[str, Placement]], ...] = (
    ('lab-commons', ROWS_LAB_COMMONS),
    ('consumer-b', ROWS_CONSUMER_B),
    ('consumer-c', ROWS_CONSUMER_C),
    ('consumer-a', ROWS_CONSUMER_A),
)


# ------------------------------------------------- the two waivers that are WIDER than an ignore

#: lab-commons' OWN per-file waivers as ``'<glob>::<code>'``, MEASURED 2026-09-18: ten codes over
#: `tests/**`, each line in its own `pyproject.toml` naming the property of a test tree that makes the
#: rule inapplicable. Every OTHER repo declares its own rows in its own tests and calls
#: `dev_lab.dev.ruffwaivers.assert_waivers_declared`; the kit holds no consumer's waivers. The kit
#: EXCLUDES NOTHING, and that is the evidence the zero is reachable -- it is asserted beside the reader.
KIT_PER_FILE_WAIVERS: tuple[str, ...] = (
    'tests/**::ANN001',
    'tests/**::ARG002',
    'tests/**::D101',
    'tests/**::D102',
    'tests/**::D103',
    'tests/**::INP001',
    'tests/**::N802',
    'tests/**::PLR2004',
    'tests/**::S101',
    'tests/**::SLF001',
)
