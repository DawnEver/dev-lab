r"""The family CONFIG bases, as DATA -- one row per artefact, computed by nothing.

This file holds tables and no logic, exactly as `_rule_rows.py` does for `rules.py` and
`_deny_rows.py` does for `hooks.py`. The machinery that renders a base, reads a repo's delta back off
disk and refuses a hand edit is :mod:`lab_commons.dev.famconfig`; a base edited through the module
that checks it drifts away from what it describes, because the same edit that adds a line can relax
the check that would have refused it.

MEASURED 2026-09-17 against four checkouts -- `lab-commons`, `wdg-lab`, `optimi-lab` and the
motronics-studio LANE at `.claude/worktrees/feat/optimi-lab` -- by set intersection over the live
files, never by line count. The numbers below are re-derivable with a five-line script and every one
of them is quoted with what it was measured over, because a base is a claim about three other repos
and a claim about somebody else's tree ages fastest.

THE THREE ARTEFACTS ARE NOT THE SAME KIND OF THING, AND THAT IS THE FINDING THIS FILE EXISTS TO
RECORD. Reading the census rows one would expect three tables of shared lines. Measured, only two of
the three artefacts share LINES at all:

* `.gitignore` -- 14 shared patterns out of 61/30/73. A pattern is a whole statement, so the shared
  half renders verbatim. RENDERED.
* `.pre-commit-config.yaml` -- 11 shared hook ids out of 22/19/18, drawn from exactly two upstream
  repos. The ids are shared and the SPELLING is not: the labs write the `repos:` list unindented and
  motronics indents it, and the three disagree on both pins (`pre-commit-hooks` v6.0.0 / v5.0.0 /
  v5.0.0, `commitizen` v4.13.9 / v4.6.0 / v4.6.0). Three spellings of one whitelist is precisely the
  hand-maintenance this base removes, so the base fixes ONE spelling and ONE pin pair. RENDERED.
* `Makefile` -- 3 target NAMES in all four repos, 8 in all three CONSUMERS, and NO shared recipe at
  all. lab-commons and optimi-lab are byte-identical on `fmt`, `lint` and `test`; wdg-lab's `lint`
  also runs `cargo fmt` and `cargo clippy`, and
  motronics' `test` selects `tests/unit -m "not femm"`. A recipe naming a tree or a vendor mark is a
  fact about that tree. **So rendering a family Makefile would be a declaration that lies** -- the
  base here is a target CONTRACT (these names must exist) plus the one recipe that genuinely is the
  family's, `verify`, which `lab_commons.dev.verify` already ships as code. REQUIRED.

`[tool.ruff]` IS DELIBERATELY ABSENT FROM THIS FILE. It is the fourth artefact the census names and
it is owned by the stage that widens this repo's own select from 12 selectors to the consumers' 58;
building a base for it here would put two renderers on one artefact while that stage is mid-sweep.
The absence is NAMED rather than silent, which is the whole point of writing it down.

WHY `uv.lock` STAYS IN THE GITIGNORE BASE, since the next reader will ask. It is in the measured
three-way intersection, and the family ruling of 2026-09-17 is that the lockfile stays OUT of git --
"the latest from that URL" is a deliberate declaration, not an oversight. What that ruling does NOT
say is that no lockfile exists: `wdg-lab/uv.lock` is present on disk, untracked, pinning
`lab-commons 0.2.2.dev26`, and `uv run`'s implicit sync served that pin back three times in one day
while every review saw nothing, because the file is invisible to git. The line stays; the defect it
hid is closed elsewhere (`uv run --no-sync` in the hooks, and a refreshing install door), and it is
recorded here so that deleting this line is never mistaken for the fix.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    'BASES',
    'GITIGNORE_BASE',
    'GITIGNORE_FLOOR',
    'HOOK_ID_CORE',
    'MAKEFILE_BASE',
    'MAKEFILE_RESIDUAL_SIGNALS',
    'MAKE_TARGET_CONSUMER_CORE',
    'MAKE_TARGET_CORE',
    'ORDER_SENSITIVE_ARTEFACTS',
    'PRECOMMIT_BASE',
    'REPO_FLOOR',
    'STAMP',
]

#: The sentence a rendered file carries so that "not ours" and "ours, edited" are different answers.
#: It names the RENDERER rather than a version or a date: a stamp carrying a timestamp makes every
#: re-render a diff, which is how a generated file acquires the reputation that justifies hand
#: edits. Staleness is not stored here at all -- the guard re-renders from the live base and
#: compares, so there is no recorded digest that can itself go stale.
STAMP: Final = 'Rendered by lab_commons.dev.famconfig'

#: How many consumer files a survey must reach before "no fork" means anything. THREE, because three
#: is how many consumers there are: a survey that read two of them has not measured the family.
REPO_FLOOR: Final = 3

# ------------------------------------------------------------------------------- .gitignore

#: The 14 patterns, MEASURED as the three-way intersection of the consumers' live `.gitignore`
#: files and then CANONICALISED on the one axis they disagree about.
#:
#: THE LITERAL INTERSECTION IS 12, NOT 14, and the two-line gap is worth the sentence. wdg-lab and
#: optimi-lab write `**/__pycache__` and `*.egg-info`; motronics writes `**/__pycache__/` and
#: `*.egg-info/`. Strip the trailing slash and the intersection is 14 and the pairwise overlaps are
#: 27 / 33 / 16; keep it and they are 12 and 27 / 31 / 14. The two spellings are NOT equivalent to
#: git -- a trailing slash matches a directory only -- so this is a real disagreement and not
#: whitespace, and a base has to pick one. It picks the SLASHED spelling, because every one of the
#: five patterns in question names a directory and the unslashed form would also match a FILE of
#: that name. That is a change of behaviour for two repos and it belongs in their adoption commit,
#: stated, rather than in a normaliser that hides it.
#:
#: Sorted, because the order is then re-derivable by anybody who repeats the measurement. A
#: `.gitignore` is order-insensitive apart from negations, and the base declares none -- a clause
#: `negated_base_lines` now ENFORCES rather than asserts, since `!` sorts above every rule here.
#:
#: THAT PARENTHETICAL WAS THE WHOLE RISK SURFACE AND IT WAS PROSE UNTIL 2026-09-18. Sorting is only
#: safe while no line here needs to sit AFTER another, and nothing checked it. The shape that breaks
#: it is on record in a sibling repo's own file: `**/.claude/**/__pycache__/` exists there for no
#: reason except POSITION -- `**/__pycache__/` already excludes everything it excludes -- and it works
#: only because it is written BELOW the `!**/.claude/memory/**` negation that re-included the cache.
#: Promoted into this table it would render ABOVE every delta line, re-tracking the `.pyc` the sibling
#: repo measured as TRACKED in 2026-08, and `fork_signals` would have argued FOR the promotion. See
#: :data:`ORDER_SENSITIVE_ARTEFACTS` for the mechanism that now refuses it.
GITIGNORE_BASE: Final[tuple[str, ...]] = (
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

#: WHICH ARTEFACTS ARE LAST-MATCH-WINS, and the floating-rule floor each scan over one must reach.
#:
#: THE GAP THIS DECLARES, stated as a mechanism rather than as the sentence it replaces. A `Delta`
#: maps a BASE line to delta lines rendered AFTER it (`Delta.anchored`); there is no expression for
#: the other direction, "this base line must come after that delta line", and every base line renders
#: before every delta line. So in a last-match-wins file a base line whose only job is to come LAST
#: cannot be a base line at all -- it would be promoted, rendered first, and silently defeated by the
#: negation it was written to close.
#:
#: HOW SUCH A LINE IS RECOGNISED WITHOUT KNOWING THE DELTAS, which is what makes this checkable on the
#: base ALONE and therefore on every future promotion from a repo nobody surveyed: a rule whose entire
#: value is its position is a rule that is otherwise REDUNDANT. `**/.claude/**/__pycache__/` excludes
#: a strict subset of what `**/__pycache__/` already excludes, so as a set of paths it adds nothing;
#: all it can add is order, and this table cannot carry order. A line that is NOT subsumed by a
#: floating sibling is promotable as normal -- `**/.DS_Store` matches nothing another base line
#: matches, so it means the same wherever it renders.
#:
#: THE FLOOR IS PER ARTEFACT because it is a fact about that base: two floating rules here,
#: `**/__pycache__/` and `**/.env`, and a scan that found none would report what a base with no
#: shared rules reports. The map is a NAMED SET rather than a flag on `Base`, so extending the check
#: to a second artefact is a decision somebody typed here with its own floor.
ORDER_SENSITIVE_ARTEFACTS: Final[dict[str, int]] = {'.gitignore': 2}

#: The floor under the gitignore base: a scan or a render over an EMPTY base is indistinguishable
#: from one over a clean tree. Set below the measured 14 on purpose -- a floor refuses an unread
#: table, it is not a second pin on the count.
GITIGNORE_FLOOR: Final = 10

# --------------------------------------------------------------- .pre-commit-config.yaml

#: The 11 hook ids declared by ALL THREE consumers, MEASURED over 22 / 19 / 18 declared ids. This is
#: the base's SUBJECT, held separately from the YAML lines that express it so that the rendered text
#: can be checked against the thing it is supposed to say. A base that lost a hook while still
#: rendering valid YAML would be green everywhere else.
HOOK_ID_CORE: Final[tuple[str, ...]] = (
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

#: The base as YAML BODY LINES. Two upstream repos, one pin each, the 11 core ids.
#:
#: THE PINS ARE THE NEWEST MEASURED, and choosing is the point: the three consumers hold
#: `pre-commit-hooks` at v6.0.0 / v5.0.0 / v5.0.0 and `commitizen` at v4.13.9 / v4.6.0 / v4.6.0, and
#: no repo has a reason on record for being behind. A base that carried three pins would be the
#: hand-maintenance it replaces, wearing a shared file as a disguise.
#:
#: `fail_fast: false` IS HERE BECAUSE THE INSTRUMENT FOUND IT. The first cut of this base held only
#: the hook ids; running :func:`lab_commons.dev.famconfig.fork_signals` over the three measured
#: deltas named `fail_fast: false` as a line ALL THREE consumers add, which is the definition of a
#: base line that was never promoted. It is the anti-fork arm correcting its own author on first
#: run, and that is the argument for keeping the arm rather than a note about one line.
#:
#: `default_stages` IS DECLARED HERE because leaving it out is not neutral: without it a hook's
#: stage comes from the UPSTREAM manifest, which is a decision taken in another repository. Only
#: motronics declares it today. `commitizen` overrides it to `commit-msg` inline, which is the stage
#: it must run at -- and MEASURED 2026-09-17 neither lab has a `commit-msg` hook installed, so in
#: both labs this is the one declaration nothing executes. The base cannot fix that; installation is
#: `lab_commons.dev.hook_install`'s question and is named here so the two are not confused.
PRECOMMIT_BASE: Final[tuple[str, ...]] = (
    'fail_fast: false',
    'default_stages: [pre-commit]',
    '',
    'repos:',
    '  - repo: https://github.com/pre-commit/pre-commit-hooks',
    '    rev: v6.0.0',
    '    hooks:',
    '      - id: check-added-large-files',
    '      - id: check-ast',
    '      - id: check-case-conflict',
    '      - id: check-json',
    '      - id: check-merge-conflict',
    '      - id: check-toml',
    '      - id: debug-statements',
    '      - id: end-of-file-fixer',
    '      - id: mixed-line-ending',
    '      - id: trailing-whitespace',
    '',
    '  - repo: https://github.com/commitizen-tools/commitizen',
    '    rev: v4.13.9',
    '    hooks:',
    '      - id: commitizen',
    '        stages: [commit-msg]',
)

# ---------------------------------------------------------------------------------- Makefile

#: The three targets present in ALL FOUR repos, MEASURED over 6 / 18 / 14 / 15 declared targets.
#: `verify` is NOT among them -- it is in three of four and motronics is the exception, which the
#: census records as that repo's own gap rather than as a family absence.
MAKE_TARGET_CORE: Final[tuple[str, ...]] = ('fmt', 'lint', 'test')

#: The NINE targets present in ALL THREE CONSUMERS, MEASURED over 18 / 14 / 16. It read EIGHT until
#: 2026-09-18, and both halves of that number have since moved:
#:
#: - `verify` joined, because motronics grew one. The old comment for the eight said `clean`,
#:   `install`, `install-dev` and `test-parallel` were "absent from lab-commons alone -- the kit held
#:   to less than what it ships". Re-measured, lab-commons carries all four, so that gap closed too.
#: - The consequence is worth stating rather than leaving for a reader to notice: this tuple is now
#:   EQUAL to `MAKE_TARGET_CORE`, the all-four set. They are kept as two names because they answer two
#:   QUESTIONS -- what the consumers share, and what the whole family shares -- and today's answer is
#:   that the kit adopted its own base with an empty delta. That is the same shape `HOOK_ID_CORE`
#:   reached on 2026-09-17, and it is what a base looks like once it has actually landed.
#:
#: THE ANTI-FORK ARM ARGUED FOR THIS SET AND THE FIRST CUT OF THIS FILE DID NOT HAVE IT. Run over the
#: three measured deltas, `fork_signals` named `clean:`, `install:` and `test-parallel:` as lines every
#: consumer adds; they are here now because it did.
MAKE_TARGET_CONSUMER_CORE: Final[tuple[str, ...]] = (
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

#: The Makefile base, and it is a CONTRACT rather than a rendering -- see this module's docstring for
#: the measurement that forces the difference. Each line is a target header that must be PRESENT in
#: the repo's own Makefile; the recipe under it is the repo's, because every measured recipe names a
#: tree (`src tests examples scripts`), a toolchain (`cargo clippy`) or a mark (`-m "not femm"`).
#:
#: `verify` carries its recipe because that recipe is portable by construction: `lab_commons.dev.verify`
#: runs ruff, ruff format and pytest, tees them into a log and prints a stamped verdict, and it takes
#: no argument naming a tree. It is the one line here that is the family's answer rather than the
#: family's question, and motronics -- the only repo with no `verify` at all -- is the one whose
#: verdict path (`scripts/gate/runner.py`) its Makefile never mentions.
MAKEFILE_BASE: Final[tuple[str, ...]] = (
    'all:',
    'clean:',
    'fmt:',
    'install:',
    'install-dev:',
    'lint:',
    'test:',
    'test-parallel:',
    'verify:',
    '\tpython -m lab_commons.dev.verify',
)

#: WHAT THE ANTI-FORK ARM ALSO NAMED AND THIS BASE DELIBERATELY DOES NOT TAKE. The same run flagged
#: `.DEFAULT_GOAL := all` and seven `.PHONY: <target>` lines as present in every consumer delta. They
#: are NOT promoted, and the reason is the RENDERED/REQUIRED distinction one level down: a target
#: header is a CONTRACT a repo can satisfy however it likes, while `.PHONY: fmt` is one SPELLING of a
#: declaration a Makefile may equally make as a single `.PHONY: a b c` line. Requiring the spelling
#: would force a restructure on any repo that chose the other one, which is a base legislating style
#: rather than sharing a decision. Named here so the residual signal is accounted for rather than
#: rotting into noise the next reader learns to scroll past.
MAKEFILE_RESIDUAL_SIGNALS: Final[tuple[str, ...]] = (
    '.DEFAULT_GOAL := all',
    '.PHONY: all',
    '.PHONY: clean',
    '.PHONY: fmt',
    '.PHONY: install-dev',
    '.PHONY: lint',
    '.PHONY: test',
    '.PHONY: test-parallel',
)

#: Every base, by artefact. The render MODE is the machinery's word and is attached there; what this
#: table owns is WHICH lines, and nothing else.
BASES: Final[dict[str, tuple[str, ...]]] = {
    '.gitignore': GITIGNORE_BASE,
    '.pre-commit-config.yaml': PRECOMMIT_BASE,
    'Makefile': MAKEFILE_BASE,
}
