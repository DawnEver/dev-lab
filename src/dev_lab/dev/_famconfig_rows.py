r"""The family CONFIG bases, as DATA -- one row per artefact, computed by nothing.

This file holds tables and no logic, exactly as `_rule_rows.py` does for `rules.py` and
`_deny_rows.py` does for `hooks.py`. The machinery that renders a base, reads a repo's delta back off
disk and refuses a hand edit is :mod:`dev_lab.dev.famconfig`; a base edited through the module
that checks it drifts away from what it describes, because the same edit that adds a line can relax
the check that would have refused it.

MEASURED 2026-09-17 against four checkouts -- `lab-commons`, `consumer-b`, `consumer-c` and the
consumer-a LANE at `.claude/worktrees/feat/consumer-c` -- by set intersection over the live
files, never by line count. The numbers below are re-derivable with a five-line script and every one
of them is quoted with what it was measured over, because a base is a claim about three other repos
and a claim about somebody else's tree ages fastest.

GIT HOOKS ARE NOT HERE: they are TOML data (`dev_lab/dev/githooks/base.toml` plus each repo`s
`[tool.dev_lab.hooks]`), run by `dev_lab.dev.githooks` and never rendered to a file.

THE ARTEFACTS ARE NOT THE SAME KIND OF THING, AND THAT IS THE FINDING THIS FILE EXISTS TO
RECORD. Reading the census rows one would expect three tables of shared lines. Measured, only two of
the three artefacts share LINES at all:

* `.gitignore` -- 14 shared patterns out of 61/30/73. A pattern is a whole statement, so the shared
  half renders verbatim. RENDERED.
* `Makefile` -- 3 target NAMES in all four repos, 8 in all three CONSUMERS, and NO shared recipe at
  all. lab-commons and consumer-c are byte-identical on `fmt`, `lint` and `test`; consumer-b's `lint`
  also runs `cargo fmt` and `cargo clippy`, and
  consumer-a' `test` selects `tests/unit -m "not femm"`. A recipe naming a tree or a vendor mark is a
  fact about that tree. **So rendering a family Makefile would be a declaration that lies** -- the
  base here is a target CONTRACT (these names must exist) plus the one recipe that genuinely is the
  family's, `verify`, which `dev_lab.dev.verify` already ships as code. REQUIRED.

`[tool.ruff]` IS DELIBERATELY ABSENT FROM THIS FILE. It is the fourth artefact the census names and
it is owned by the stage that widens this repo's own select from 12 selectors to the consumers' 58;
building a base for it here would put two renderers on one artefact while that stage is mid-sweep.
The absence is NAMED rather than silent, which is the whole point of writing it down.

WHY `uv.lock` IS BANNED FROM EVERY `.gitignore` (PIN + FRESHNESS, user ruling 2026-10-17): every family repo
COMMITS its lock, so a host builds a commit's environment with `uv sync --frozen`; "the latest" is the forge's
relock pull request (dev_lab.dev.relock), never an untracked file resolved on the day.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    'BASES',
    'GITATTRIBUTES_BASE',
    'GITIGNORE_BANNED',
    'GITIGNORE_BASE',
    'GITIGNORE_CLAUDE_SECTION',
    'GITIGNORE_CONSUMER_CORE',
    'GITIGNORE_FAMILY_LINES',
    'GITIGNORE_FLOOR',
    'ORDERED_SECTIONS',
    'ORDER_SENSITIVE_ARTEFACTS',
    'REPO_FLOOR',
    'STAMP',
]

#: The sentence a rendered file carries so that "not ours" and "ours, edited" are different answers.
#: It names the RENDERER rather than a version or a date: a stamp carrying a timestamp makes every
#: re-render a diff, which is how a generated file acquires the reputation that justifies hand
#: edits. Staleness is not stored here at all -- the guard re-renders from the live base and
#: compares, so there is no recorded digest that can itself go stale.
STAMP: Final = 'Rendered by dev_lab.dev.famconfig'

#: How many consumer files a survey must reach before "no fork" means anything. THREE, because three
#: is how many consumers there are: a survey that read two of them has not measured the family.
REPO_FLOOR: Final = 3

# ------------------------------------------------------------------------------- .gitignore

#: The 14 patterns, MEASURED as the three-way intersection of the consumers' live `.gitignore`
#: files and then CANONICALISED on the one axis they disagree about.
#:
#: THE LITERAL INTERSECTION IS 12, NOT 14, and the two-line gap is worth the sentence. consumer-b and
#: consumer-c write `**/__pycache__` and `*.egg-info`; consumer-a writes `**/__pycache__/` and
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
GITIGNORE_CONSUMER_CORE: Final[tuple[str, ...]] = (
    '**/.env',
    '**/__pycache__/',
    '*.egg-info/',
    '.mypy_cache/',
    '.pytest_cache/',
    '.ruff_cache/',
    '.venv*',
    # Root-anchored 2026-11-24: a source package named `temp` is source, not scratch.
    '/temp/',
)

#: RETIRED 2026-11-24 (user ruling): `**/log/*.log(.error)`, `/dumps/`, `/report/`, `htmlcov/` and `.coverage*`
#: (coverage data and reports go to output/ via verifysteps' COVERAGE_FILE), `**/ignore/`, `*.spec`, `*.c`,
#: `**/_meta.json` and the `.claude` cache lines -- no family mechanism writes them in every checkout.

#: THE LINES THE FAMILY MANDATES rather than measured, each with the mechanism that writes the path.
#: Added 2026-10-03 on the user's ruling that every repo's `.gitignore` has ONE source here: a line
#: enters when a FAMILY mechanism (this package, the build backend every repo runs, the agent tooling
#: every repo uses) writes that path in every checkout -- not because three files happen to spell it.
#: A consumer delta that restates one of these is refused at render time like any other restatement.
GITIGNORE_FAMILY_LINES: Final[dict[str, str]] = {
    '**/__version__.py': 'the version file hatch-vcs / setuptools-scm write at build time, in every repo.',
    '/build/': 'the build backend`s staging directory, at the root of every repo that builds a wheel.',
    '/dist/': 'the built wheels and sdists, at the root of every repo that builds one.',
    '/output/': 'the dated artefact tree (dev_lab.dev.datedlog) every repo writes under output/.',
    '**/.DS_Store': 'macOS Finder state; a platform artefact with no repo to belong to.',
    '/config/': 'the dev-mode in-repo config root two consumers generate from packaged defaults.',
}

#: THE CLAUDE PROJECT STATE SECTION -- ONE ORDERED BLOCK, identical in every repo (user ruling
#: 2026-10-03, taken from the two reference repos' `# Claude project state` sections). Ignore all of
#: `.claude/`, re-include the shared, checked-in directories, then re-ignore the generated files the
#: re-inclusion would otherwise track. ORDER IS THE RULE here (last match wins), so this block is
#: declared in :data:`ORDERED_SECTIONS`, rendered verbatim AFTER the sorted lines, and exempt from the
#: order-free refusal that binds the sorted part. It covers `.claude/worktrees/` (WORKTREES-STAY-INSIDE)
#: and `<checkout>/.claude/.rem-state.json` because `**/.claude/**` does and nothing re-includes them.
GITIGNORE_CLAUDE_SECTION: Final[tuple[str, ...]] = (
    '**/.claude/**',
    '!**/.claude/settings.json',
    *(
        line
        for directory in ('hooks', 'rules', 'memory')
        for line in (f'!**/.claude/{directory}/', f'!**/.claude/{directory}/**')
    ),
    # The auto-mode prose is MACHINE-LOCAL, derived from the synced fleet sources (dev_lab.dev.automode, user
    # ruling 2026-10-23): a committed copy would put fleet facts in history. Named so no re-inclusion tracks it.
    '**/.claude/automode.json',
)
# The re-inclusions are exactly the tracked directories of the closed `.claude/` inventory
# (dev_lab.dev.claudelayout.CLAUDE_ENTRIES). `!**/attic/**` left the base 2026-11-24: a repo holding an
# archive declares it in its own delta.

#: Lines NO `.gitignore` in the family may carry, base or delta -- as patterns, with the ruling. A
#: scratch-like directory under any name but `scratch/` is a second place for temporary scripts, and
#: a per-tool cache pointer suffix is one repo's tool leaking into its ignore file.
GITIGNORE_BANNED: Final[dict[str, str]] = {
    r'(?:^|/)(?:_scratch|\.scratch|scratchpad)(?:/|$)': '`scratch/` is the one temporary-script directory',
    r'^/?(?:\*\*/)?scratch(?:/\**)?$': (
        '`scratch/` stays VISIBLE to git so a one-off shows in git status (SCRATCH-IS-NEVER-COMMITTED, 2026-10-22)'
    ),
    r'^\*\.[\w-]+-cache$': 'a tool-specific cache pointer suffix is not ignored family-wide (ruling 2026-10-03)',
    r'(?:^|/)uv\.lock$': 'every repo commits its uv.lock at the newest resolution (PIN + FRESHNESS, 2026-10-17)',
}

#: THE BASE: the sorted measured core plus the mandated lines, then the ordered Claude section.
GITIGNORE_BASE: Final[tuple[str, ...]] = (
    *sorted({*GITIGNORE_CONSUMER_CORE, *GITIGNORE_FAMILY_LINES}),
    *GITIGNORE_CLAUDE_SECTION,
)

#: Per artefact, the base lines that form ONE ORDERED block: rendered in the order written, and
#: exempt from :func:`dev_lab.dev.famconfig.assert_base_is_order_free`, whose refusal exists for
#: lines whose order the sorted table cannot keep.
ORDERED_SECTIONS: Final[dict[str, tuple[str, ...]]] = {'.gitignore': GITIGNORE_CLAUDE_SECTION}

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

# ---------------------------------------------------------------------------------- Makefile
# RETIRED 2026-11-24 (user ruling): the Makefile carries no family contract; it is the repo's own file
# (dev_lab.dev.famfiles row OWNED). `make verify` was the one shared recipe and `python -m dev_lab.dev.verify`
# is the door it wrapped.

# ---------------------------------------------------------------------------- .gitattributes

#: ONE LINE, AND IT IS MANDATED BY A MECHANISM RATHER THAN MEASURED (added 2026-10-03, on the user's
#: ruling that every project-level file has one source here). This package SHIPS bash payloads
#: (`dev_lab.dev.githooks/*.sh`) that every consumer executes, on Windows too, where Git for
#: Windows defaults to `core.autocrlf=true`: a CRLF checkout makes bash read `#!/usr/bin/env bash\r`
#: as a missing interpreter and `then\r` as a syntax error, and the failure lands in the CONSUMER.
#: Only two repos carried a `.gitattributes` and they shared no line; this is the one rule whose
#: reason holds in all four. Repo-wide normalisation (`* text=auto eol=lf`) stays a repo's delta --
#: adopting it renormalises every tracked file, which is a repo's decision, not the family's.
#:
#: WIDENED 2026-11-24 (user ruling): repo-wide LF normalisation is now the family's decision, so every
#: consumer delta is empty. `*.bat`/`*.cmd` keep CRLF because cmd.exe misparses LF labels; the binary
#: lines stop text normalisation from corrupting the artefact types the family commits.
GITATTRIBUTES_BASE: Final[tuple[str, ...]] = (
    '* text=auto eol=lf',
    '*.bat text eol=crlf',
    '*.cmd text eol=crlf',
    '*.jpg binary',
    '*.npz binary',
    '*.pdf binary',
    '*.png binary',
    '*.sh text eol=lf',
    '*.xlsx binary',
    '*.zip binary',
)

#: Every base, by artefact. The render MODE is the machinery's word and is attached there; what this
#: table owns is WHICH lines, and nothing else.
BASES: Final[dict[str, tuple[str, ...]]] = {
    '.gitignore': GITIGNORE_BASE,
    '.gitattributes': GITATTRIBUTES_BASE,
}
