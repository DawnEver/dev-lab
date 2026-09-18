r"""The CONFIG-layer placement census, FIRST half -- pure DATA, one row per artefact per repo.

A row is ``<repo>::<artefact> -> Placement(side, why)``, partitioned by REPO because a repo is what
a lane owns. The machinery that reads it, and the three sides it may use, are `_config_census.py`;
this file computes nothing, exactly as `_rule_rows.py` computes nothing for `rules.py`.

MEASURED 2026-09-17 against four checkouts: `lab-commons`, `wdg-lab`, `optimi-lab`, and the
motronics-studio LANE at `.claude/worktrees/feat/optimi-lab` (never the main checkout). Every
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

2. MOTRONICS' TWO RUFF CONFIGS ARE NOT TWO DECISIONS. `ruff check --show-settings` prints
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
    'HOOK_ID_CORE',
    'INSTALLED_HOOKS',
    'KIT_IGNORE',
    'KIT_SELECT',
    'KIT_SELECT_BEFORE_R1',
    'MACHINE_EXCLUDES',
    'MAKE_TARGET_CORE',
    'PARTITIONS',
    'PER_FILE_WAIVERS',
    'REPOS',
    'REPO_PATHS',
    'SHARED_DEV_PAGES',
    'SHARED_GITIGNORE_CORE',
    'TREE_EXCLUDES',
]

#: The four repos of the family, in dependency order: the kit first, then what it ships to.
REPOS: tuple[str, ...] = ('lab-commons', 'wdg-lab', 'optimi-lab', 'motronics-studio')

#: Where each consumer is checked out, RELATIVE TO LAB-COMMONS' PARENT. The motronics entry names a
#: WORKTREE and that is the whole point: the main checkout is the integrator's and is not read here,
#: so a census run against it would be measuring a tree this lane was told not to touch.
REPO_PATHS: dict[str, str] = {
    'wdg-lab': 'wdg-lab',
    'optimi-lab': 'optimi-lab',
    'motronics-studio': 'motronics-studio/.claude/worktrees/feat/optimi-lab',
}

#: The config artefacts under census. ``ruff-config`` is an ARTEFACT rather than a FILE on purpose:
#: three repos hold it inside `pyproject.toml` and one holds it in `ruff.toml`, and a census keyed by
#: filename would score that difference as two unrelated rows instead of one relocation.
ARTEFACTS: tuple[str, ...] = (
    'pyproject.toml',
    'ruff-config',
    '.gitignore',
    'Makefile',
    '.pre-commit-config.yaml',
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
    'wdg-lab': ('ANN205',),
    'optimi-lab': (),
    'motronics-studio': ('B023', 'PLR0917', 'RUF002', 'RUF003'),
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

#: `.gitignore` patterns shared by all three consumers. lab-commons shares only two of them
#: (`.pytest_cache/`, `.ruff_cache/`) and is a SUBSET OF NONE of the four -- measured, not assumed.
SHARED_GITIGNORE_CORE: tuple[str, ...] = (
    '**/.env',
    '**/log/*.log',
    '**/log/*.log.error',
    '**/temp/**',
    '*.c',
    '*.spec',
    '.coverage*',
    '.mypy_cache/',
    '.pytest_cache/',
    '.ruff_cache/',
    '.venv*',
    'uv.lock',
)

#: Makefile targets present in ALL FOUR repos. Three, out of 7/19/15/16 -- which is why the Makefile
#: rows are SPLITS on a thin base rather than MOVES.
MAKE_TARGET_CORE: tuple[str, ...] = (
    'fmt',
    'lint',
    'test',
)

#: Hook ids declared by all three CONSUMERS. Eleven of 22/19/18 -- and as of 2026-09-17 also the
#: complete set lab-commons declares, because the kit adopted the family base with an EMPTY delta
#: (`tests/_famconfig_delta.py`). So this tuple is no longer "the shared part of three files"; it is
#: the shared part of three files and the whole of a fourth, which is what a base looks like once
#: the repo that publishes it runs it.
HOOK_ID_CORE: tuple[str, ...] = (
    'check-added-large-files',
    'check-ast',
    'check-case-conflict',
    'check-json',
    'check-merge-conflict',
    'check-toml',
    'commitizen',
    'debug-statements',
    'end-of-file-fixer',
    'mixed-line-ending',
    'trailing-whitespace',
)

#: Git hooks actually INSTALLED, per repo, measured 2026-09-17 -- the ratchet's other side for the
#: `.pre-commit-config.yaml` rows, since a configuration cannot answer for its own installation.
#:
#: TWO CORRECTIONS ARE RECORDED IN THIS ONE CONSTANT, and both were made by the test rather than by
#: review. The first is mine: a hand `ls .git/hooks` run from the wrong working directory reported
#: ZERO for every repo, and the test refused it -- git's hooks directory must be resolved through
#: git (`--absolute-git-dir`, and for a WORKTREE the common dir one level up), which is exactly the
#: mechanism `lab_commons.dev.hook_install` exists to supply and which a shell one-liner does not
#: have. The second is upstream's: `hook_install`'s docstring records ZERO installed hooks in
#: wdg-lab and optimi-lab on 2026-09-16, and a day later both have them, so that measurement is now
#: historical and this table is the live one.
#:
#: THE MISSING STAGE WAS CLOSED THE SAME DAY IT WAS RECORDED, and how it was found is the part worth
#: keeping. This paragraph used to read "both labs declare `commitizen`, whose stage is `commit-msg`,
#: and NEITHER has a `commit-msg` hook file". That was true, and nothing was looking for it: both
#: repos read as guarded while EVERY COMMIT MESSAGE WENT UNCHECKED. What surfaced it was not a hunt.
#: The family pre-commit base spells `stages: [commit-msg]` out where both labs had left it implicit,
#: and `hook_install.declared_stages` reads the config TEXT -- so making an implicit declaration
#: EXPLICIT turned `test_the_declared_hooks_are_installed` red and named the shim nobody had
#: installed. The RESOLVED stage never moved; upstream already said `commit-msg`. Writing down what
#: was already true is what made the gap visible, which is the argument for stating a thing rather
#: than relying on it.
#:
#: lab-commons LEFT ZERO ON 2026-09-17, and the sentence this replaces is worth keeping in view: it
#: read "lab-commons stays at ZERO and that is its own row rather than an oversight". That was an
#: accurate description and a bad resting place. The repo shipping `hook_install`, `hooks`,
#: `hook_adoption`, `githooks` and the `lab-with-venv` bootstrap ran NONE of it on itself, so every
#: commit here went through no check of any kind while this table judged three other repos on
#: exactly that property. It now renders the family `.pre-commit-config.yaml` with an EMPTY delta and
#: installs the two stages that config declares.
#:
#: TWO STAGES, NOT THREE, and the missing one is a decision rather than a gap: there is no `pre-push`
#: here because `make verify` is this repo's whole verdict and a hook re-running it would block every
#: push. `tests/test_the_kit_renders_its_own_precommit_config.py` pins that absence in BOTH
#: directions, so installing one later is a red rather than a discovery.
#:
#: THE INTERPRETER IN THE SHIM IS NOT THIS REPO'S VENV, measured at install: `pre-commit` is a
#: user-level `uv tool`, so `INSTALL_PYTHON` names the tool's environment. That is deliberate --
#: installing into `.venv` would move an environment other worktrees gate against, mid-run -- and it
#: is why `pre-commit` is declared in the `dev` extra anyway: the extra states what a CONSUMER needs
#: to run `hook_install.install_command`, which is a different question from what this box happens
#: to have on PATH.
INSTALLED_HOOKS: dict[str, tuple[str, ...]] = {
    'lab-commons': ('commit-msg', 'pre-commit'),
    'wdg-lab': ('commit-msg', 'pre-commit', 'pre-push'),
    'optimi-lab': ('commit-msg', 'pre-commit'),
    'motronics-studio': ('commit-msg', 'pre-commit', 'pre-push'),
}

#: Page names lab-commons' `docs-src/dev/` and motronics' both carry. Nine of 13 and 14 -- and in
#: motronics every one of the nine is already a POINTER plus a local delta, not a copy.
SHARED_DEV_PAGES: tuple[str, ...] = (
    'alignment.md',
    'docs-pipeline.md',
    'fanout.md',
    'forge.md',
    'index.md',
    'orphans.md',
    'retirement.md',
    'shared-checkout.md',
    'the-three-participants.md',
)


# ------------------------------------------------------------------ lab-commons: the kit itself

ROWS_LAB_COMMONS: dict[str, Placement] = {
    'lab-commons::pyproject.toml': Placement(
        STAYS,
        'THE ONE FILE THAT CANNOT BE SHARED, because its subject is the wheel this repo publishes: '
        'the distribution name, the hatch-vcs version source writing `src/lab_commons/__version__.py`, '
        'the six tier-1 dependencies and the `dev` extra that gates `lab_commons.dev`. At 69 lines it '
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
        'TEN PATTERNS, AND ONLY TWO OF THEM ARE THE FAMILY`S. Measured: the three consumers share a '
        '12-pattern core and this repo holds just `.pytest_cache/` and `.ruff_cache/` of it -- it is a '
        'SUBSET OF NONE of the other three, and none of them is a subset of it. THE SEAM is the '
        'generated-artefact core (caches, venv, coverage, `**/.env`, `**/log/*.log`), which is a fact '
        'about the toolchain every repo runs. What STAYS is one line and it names this repo: '
        '`src/lab_commons/__version__.py`, the file hatch-vcs writes -- the consumers spell the same '
        'idea `**/__version__.py`, and neither spelling is portable to the other because one repo has '
        'one package and the others have several. What breaks if that line moved: a generated version '
        'file gets committed and the build stops being reproducible from the tag.',
    ),
    'lab-commons::Makefile': Placement(
        SPLITS,
        'SEVEN TARGETS AGAINST 19/15/16, AND THE BASE IS THREE. Measured: `fmt`, `lint` and `test` are '
        'the only targets present in all four repos. THE SEAM is the verify contract -- `verify: lint '
        'fmt-check test` is this file`s whole argument (its own comment: "CI calls `verify` and nothing '
        'else"), and `lab_commons.dev.verify` already ships that contract as code, so the target is a '
        'three-line shim over a shared entry point. What STAYS is `adoption`, which runs this repo`s '
        'rules-adoption test by path: it names a test file, and a path into a tree is the one thing a '
        'shared Makefile cannot carry. What breaks if `verify` moved: nothing -- the consumers would '
        'gain a verdict-producing target, which is the deliverable `lab_commons.dev.verify` was '
        'written for and which motronics is the only repo to have its own version of.',
    ),
    'lab-commons::.pre-commit-config.yaml': Placement(
        SPLITS,
        'ABSENT UNTIL 2026-09-17, AND THE ABSENCE WAS THE ROW. This repo SHIPS the hook machinery -- '
        '`dev.hook_install` (is a declared hook actually in the directory git consults), `dev.hooks` '
        'and `dev.hook_adoption` (the denied shapes and their remedies), `dev.githooks` (the '
        'bump-version payload wdg-lab now calls BY NAME rather than by copy), the `lab-with-venv` '
        'bootstrap -- and ran none of it on itself: no config, no installed hook, no commit-time check '
        'of any kind. It was finding 1 one layer out, the kit held to less than what it ships. IT IS '
        'NOW A SPLIT WHOSE REPO HALF IS EMPTY, and that is the whole repair: the artefact is the '
        'family base rendered by `famconfig` with a delta of ZERO lines, so every line of this file '
        'came from `_famconfig_rows` and NOTHING is repo-shaped. THE SEAM is therefore the entire '
        'file, which is the strongest form this row could take and the reason the side did not change '
        'to MOVES -- a lab-commons row may not say MOVES, because this IS where a shared artefact '
        'goes. The delta is empty by DECISION and not by '
        'default -- each of the eleven base ids was checked against this tree, '
        '`check-shebang-scripts-are-executable` was considered and refused on measurement (the five '
        'shipped `.sh` payloads are mode 100644 here, so it would red on the first run), and the '
        'pre-push gate the labs have is genuinely absent because `make verify` is this repo`s whole '
        'verdict. Both declared stages are INSTALLED, which is the half a configuration cannot answer '
        'for itself. What broke while it was absent: nothing reds, which was the complaint -- the one '
        'repo whose own tests assert that a config without an install is a lie had neither.',
    ),
    'lab-commons::docs-src/dev/': Placement(
        STAYS,
        'THE ORIGIN OF THE SHARED TREE, so "stays" here is a statement about the other three. Thirteen '
        'pages, and the split measured across the family is not 13/1/1/14 as a line count suggests: the '
        'labs` single page is a POINTER TABLE generated by `lab_commons.dev.devdocs.pointer_table` and '
        'motronics` 14 share nine FILENAMES with this tree, every one of them already reduced to a '
        'pointer plus a local delta. So this is the only tree in the family holding the family`s '
        'mechanism as prose, which is what makes it the one that may not move. What breaks if it moved: '
        'the pointer tables in all three consumers resolve to nothing, and `devdocs.PAGES` -- the data '
        'those tables are rendered from -- describes a tree that is not there.',
    ),
}


# ------------------------------------------------------------------ wdg-lab

ROWS_WDG_LAB: dict[str, Placement] = {
    'wdg-lab::pyproject.toml': Placement(
        STAYS,
        'THE LARGEST OF THE FOUR AT 344 LINES, and the size is its subject: a maturin/Rust build, a web '
        'backend, and a dependency set that names this repo`s own domain. The packaging half of a '
        'pyproject is per-distribution by definition -- two wheels cannot share a name. What breaks if '
        'it moved: nothing installs, and the Rust extension has no build backend. The only shared '
        'question inside it is `[tool.ruff]`, which this census keys separately because it is the half '
        'that is byte-identical to two other repos.',
    ),
    'wdg-lab::ruff-config': Placement(
        SPLITS,
        'SHARED WITH OPTIMI-LAB AND MOTRONICS TO WITHIN ONE CODE. Measured: the 58-selector `select` is '
        'IDENTICAL across all three (symmetric difference EMPTY, all three pairs); line-length 120, '
        'target py313, unsafe-fixes true, quote-style single, preview false are identical too; and this '
        'repo`s ignore list is the 62-code core plus exactly ONE code, ANN205. THE SEAM is therefore '
        'sharp: select + the 62 ignores are the base, and the delta is `ANN205`, `exclude` (which names '
        '`experiment/`, `ignore/`, `input/`, `scripts/setup.py` -- trees only this repo has) and 7 '
        '`per-file-ignores` paths into `src/wdg_lab/wdg_viz/`, which is legacy code being brought up '
        'rather than a policy. What breaks if the base moved: nothing here -- it would move to a file '
        'this repo already depends on, and the 7 viz paths stay because a path is a fact about a tree.',
    ),
    'wdg-lab::.gitignore': Placement(
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
    'wdg-lab::Makefile': Placement(
        SPLITS,
        'NINETEEN TARGETS, THE MOST OF THE FOUR, AND EIGHT OF THEM ARE THE CONSUMER CORE (`all`, '
        '`clean`, `fmt`, `install`, `install-dev`, `lint`, `test`, `test-parallel` -- measured as the '
        'three-way intersection). THE SEAM is that core plus `verify`: the same lint/format/test triple '
        '`lab_commons.dev.verify` ships as code. What STAYS is `schema`, `serve`, `install-web` and '
        '`setup-hooks` -- the first three name this repo`s web backend and its JSON schema, and the '
        'fourth exists only because this repo needs a hook install step at all. What breaks if the core '
        'moved: nothing, provided `verify` keeps its meaning; what breaks if `serve` moved is that a '
        'shared Makefile would reference a backend three of the four repos do not have.',
    ),
    'wdg-lab::.pre-commit-config.yaml': Placement(
        SPLITS,
        'THE SEAM IS ALREADY HALF-CUT HERE, AND IT IS THE PROOF THE OTHER ROWS REST ON: `bump-api-version` '
        'runs `python -m lab_commons.dev.githooks bump-version` -- the payload reached BY NAME after a '
        'forked copy had drifted into four separate defects, recorded in this file`s own comment. So '
        'one hook already demonstrates that the shared half is shareable. The rest of the shared half '
        'is the 11-hook core (commitizen plus the pre-commit-hooks whitelist) declared identically by '
        'all three consumers. What STAYS: `generate-changelog`, the `^\\.claude/|^experiment/` excludes, '
        'and the `_suppressions.tsv` trailing-whitespace exclusion, which exists because a formatter '
        'rewrote 351 rows of a five-column TSV -- an incident, and an incident is not portable. What '
        'breaks TODAY: the commit-msg half only. `pre-commit` and `pre-push` ARE installed here (measured '
        '2026-09-17), but no `commit-msg` hook is, and `commitizen` runs at that stage -- so the '
        'message-format half of this 98-line file governs nothing while the rest of it works.',
    ),
    'wdg-lab::docs-src/dev/': Placement(
        MOVES,
        'ALREADY MOVED, AND THE "1" IS THE EVIDENCE RATHER THAN THE GAP. The single page is 30 lines and '
        'is a POINTER TABLE into `../../../lab-commons/docs-src/dev/`, listing all 12 family pages and '
        'generated by `lab_commons.dev.devdocs.pointer_table` so a page renamed upstream cannot leave '
        'this one quietly wrong. Its own text dates the move to 2026-09-16 and states that before it '
        'there was NO page here describing how a verdict is produced -- so the near-zero is a repo that '
        'stopped keeping its own copy, not one that never wrote the mechanics. What a consumer would '
        'lose if it were not shared: the twelve pages, plus the property that the index cannot drift, '
        'and the repo would be back to the state its own page names as the defect it closed.',
    ),
}


# ------------------------------------------------------------------ optimi-lab

ROWS_OPTIMI_LAB: dict[str, Placement] = {
    'optimi-lab::pyproject.toml': Placement(
        STAYS,
        '225 LINES WHOSE SUBJECT IS THIS DISTRIBUTION: the package name, the optimiser dependencies and '
        'the extras a consumer installs. A pyproject is the one artefact per repo that is repo-shaped '
        'by construction rather than by habit -- two wheels cannot share a name, a version source or a '
        'dependency set. What breaks if it moved: nothing installs. Its `[tool.ruff]` block is the only '
        'shared question inside it and is keyed as its own artefact, which is what lets this row be a '
        'clean STAYS instead of a SPLITS that never names its seam.',
    ),
    'optimi-lab::ruff-config': Placement(
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
    'optimi-lab::.gitignore': Placement(
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
    'optimi-lab::Makefile': Placement(
        SPLITS,
        'FIFTEEN TARGETS, AND THE CLOSEST OF THE THREE CONSUMERS TO THE KIT`S OWN: it is the only one '
        'besides lab-commons carrying BOTH `fmt-check` and `adoption`, and it has `verify` as well -- so '
        'the verify contract (`lint`, `fmt-check`, `test`) is present in identical shape in two repos '
        'and shipped as code in `lab_commons.dev.verify`. THE SEAM is that contract plus the eight-target '
        'consumer core. What STAYS is `purity`, which runs this repo`s own import-purity test by PATH: a '
        'path into a tree cannot be shared, because the tree is what differs. What breaks if `verify` '
        'moved: nothing -- it would become one line calling the module this repo already depends on, '
        'and the three-repo drift in what `verify` MEANS would stop being possible.',
    ),
    'optimi-lab::.pre-commit-config.yaml': Placement(
        SPLITS,
        'THE THINNEST LIVE CONFIG OF THE THREE, AND ALMOST ALL OF IT IS THE SHARED HALF: 19 declared '
        'hooks, of which 11 are the consumer core and the rest are the remainder of the same upstream '
        'pre-commit-hooks whitelist. Everything repo-shaped in it is COMMENTED OUT -- the whole local '
        'lint/format/mypy/pytest block is dead text, so this repo declares NO local hook at all and '
        'runs no ruff at commit time. THE SEAM: the core plus the whitelist is shareable as it stands; '
        'what would stay is a local block that does not yet exist. What breaks today: `pre-commit` is '
        'installed (measured 2026-09-17) and runs the upstream whitelist, but `commit-msg` is NOT, and '
        '`commitizen` -- the one hook here that is not from that whitelist -- runs at that stage. So '
        'the only repo-specific thing this file declares is the one part of it nothing executes.',
    ),
    'optimi-lab::docs-src/dev/': Placement(
        MOVES,
        'ALREADY MOVED, SAME DAY AND SAME SHAPE AS WDG-LAB: one 30-line page, a pointer table into '
        '`../../../lab-commons/docs-src/dev/` generated by `lab_commons.dev.devdocs.pointer_table`, '
        'listing the same 12 family pages. Its text is sharper than its sibling`s on one point worth '
        'keeping: it says this repo had no `docs-src/` tree AT ALL before that day, so the "1" is a '
        'tree created as a pointer rather than a tree emptied into one. What a consumer would lose if '
        'it were not shared: the twelve pages, and the guarantee that a rename upstream reds here '
        'instead of leaving a table of dead links -- which is the property a copied document cannot '
        'have and is the reason this side is MOVES rather than SPLITS.',
    ),
}


# ------------------------------------------------------------------ motronics-studio (the LANE)

ROWS_MOTRONICS: dict[str, Placement] = {
    'motronics-studio::pyproject.toml': Placement(
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
    'motronics-studio::ruff-config': Placement(
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
    'motronics-studio::.gitignore': Placement(
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
    'motronics-studio::Makefile': Placement(
        SPLITS,
        'SIXTEEN TARGETS AND THE ONLY ONE OF THE FOUR WITH NO `verify` TARGET AT ALL -- measured, and it '
        'is the sharpest thing in this row: this repo`s verdict is `python scripts/gate/runner.py '
        '{measure|gate|heavy}`, a 1770-line runner, and the Makefile never mentions it, so the one file '
        'a newcomer reads to learn how to check this repo does not name the check. THE SEAM is the '
        'eight-target consumer core. What STAYS is `build-rust`, `fmt-rust`, `test-femm` and '
        '`typecheck` -- a Cargo workspace and a live vendor engine, neither of which any other repo '
        'has. What breaks if the core moved: nothing; what does NOT get fixed by moving it is the '
        'missing verdict target, which is this repo`s own gap and is named here so the move cannot be '
        'mistaken for closing it.',
    ),
    'motronics-studio::.pre-commit-config.yaml': Placement(
        SPLITS,
        'THE ONLY CONFIG IN THE FAMILY WHOSE EVERY DECLARED STAGE IS WIRED -- `commit-msg`, `pre-commit` '
        'and `pre-push` are all present in the checkout`s hooks directory (measured 2026-09-17, through '
        'git`s own resolution: a worktree`s hooks are the PARENT checkout`s, and reading '
        '`<worktree>/.git/hooks` as a directory reports zero). Both labs have the pre-commit half and '
        'neither has `commit-msg`, so this is the only repo where the commitizen declaration executes. '
        'THE SEAM: it declares the same 11-hook core as the labs, which is the shared half. What '
        'STAYS is the entire pre-push half -- `gate`, `pyright-clean-leaf`, `bump-version` and '
        '`commitizen-branch`, every one wrapped in `scripts/hooks/branch-push-only.sh`, plus the '
        '`default_stages` discipline and the `.dxf` exclusions on the rewriting hooks. Those encode '
        'this repo`s verdict model and its data formats. What breaks if the pre-push half moved: a repo '
        'with no gate runner inherits a hook that invokes one, which is a refusal with no exit -- the '
        'failure `lab_commons.dev.hook_adoption` exists to refuse.',
    ),
    'motronics-studio::docs-src/dev/': Placement(
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
    ('wdg-lab', ROWS_WDG_LAB),
    ('optimi-lab', ROWS_OPTIMI_LAB),
    ('motronics-studio', ROWS_MOTRONICS),
)


# ------------------------------------------------- the two waivers that are WIDER than an ignore

#: THE EXCLUDES EVERY CONSUMER HOLDS AND THAT WAIVE NOTHING, measured 2026-09-18 as the three-way
#: intersection of the live ``exclude`` lists. None of the three carries source under review: `.git`
#: is git`s own store, `.venv*` is installed third-party code, and `**/__version__.py` is generated by
#: the version machinery in every repo that has one. They are split out from :data:`TREE_EXCLUDES`
#: precisely so the ratchet below counts only excludes that hide REAL source -- a ceiling that counted
#: `.git` three times would be a number nobody could read.
MACHINE_EXCLUDES: tuple[str, ...] = ('**/__version__.py', '.git', '.venv*')

#: EVERY EXCLUDE THAT HIDES REAL SOURCE, per repo, MEASURED 2026-09-18 from the live config ruff
#: resolves (so the motronics row is read from `ruff.toml`, which wins there, and the other three from
#: `[tool.ruff]`).
#:
#: WHY THIS IS A CEILING AND NOT A VERDICT. An exclude is the WIDEST waiver a ruff config can write --
#: it drops all 58 selectors over a subtree and names no code at all -- and until this table existed
#: nothing in the family read one, so the 13 rows below had never been counted, let alone judged.
#: Judging them is not this lane's to do: `attic` and `.claude/memory` are declared read-only archives
#: in motronics' own AGENTS.md, and wdg-lab's `experiment`, `input`, `output` and `ignore` are that
#: repo`s scratch trees. What the table buys today is that the FOURTEENTH arrives as an edit to a
#: named set with a reason, rather than as a line in a file nothing reads. It may only SHRINK.
#:
#: lab-commons EXCLUDES NOTHING, and that is the evidence that the zero is reachable: the repo that
#: ships the standard opens every file it tracks.
TREE_EXCLUDES: dict[str, tuple[str, ...]] = {
    'lab-commons': (),
    'wdg-lab': ('.claude', 'archived', 'experiment', 'ignore', 'input', 'output', 'scripts/setup.py'),
    'optimi-lab': ('archived', 'ignore', 'input', 'output'),
    'motronics-studio': ('.claude/memory', 'attic'),
}

#: EVERY PER-FILE WAIVER IN THE FAMILY as ``'<glob>::<code>'``, MEASURED 2026-09-18. A glob carrying
#: three codes is three rows, so a code dropped from one glob moves this ratchet.
#:
#: THE THREE POSITIONS HERE ARE ALL DIFFERENT AND THE TABLE IS WHERE THAT BECOMES VISIBLE. lab-commons
#: waives ten codes over `tests/**`, each line in its own `pyproject.toml` naming the property of a
#: test tree that makes the rule inapplicable. wdg-lab waives two codes over seven globs, five of them
#: `PLR0917` over a visualisation subtree. motronics waives NOTHING, by a 2026-08-02 user directive its
#: `ruff.toml` states in full -- a waiver belongs in the file it governs, as a noqa comment carrying a reason,
#: never in a central table -- and `tests/architecture/ratchets/test_suppression_ratchet.py` pins that
#: repo's table at zero pairs. optimi-lab has none either, and declares nothing about it.
#:
#: SO THE FAMILY HOLDS ONE REPO'S PRINCIPLE, ONE REPO'S ZERO AND TWO REPOS' LISTS, and which of those
#: is the family answer is a decision nobody has taken. It is recorded as a ceiling rather than
#: legislated from here, for the same reason the eight-code waiver set is: the remedy for a wdg-lab row
#: is in wdg-lab.
PER_FILE_WAIVERS: dict[str, tuple[str, ...]] = {
    'lab-commons': (
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
    ),
    'wdg-lab': (
        'examples/tasks/**::T201',
        'scripts/*.py::T201',
        'src/wdg_lab/wdg_viz/backend/**::PLR0917',
        'src/wdg_lab/wdg_viz/backend3d/**::PLR0917',
        'src/wdg_lab/wdg_viz/connection/**::PLR0917',
        'src/wdg_lab/wdg_viz/utils.py::PLR0917',
        'src/wdg_lab/wdg_viz/visualize_2d.py::PLR0917',
    ),
    'optimi-lab': (),
    'motronics-studio': (),
}
