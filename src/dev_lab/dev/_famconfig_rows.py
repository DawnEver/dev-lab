r"""The family CONFIG bases, as DATA -- one row per artifact, computed by nothing.

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

THE ARTIFACTS ARE NOT THE SAME KIND OF THING, AND THAT IS THE FINDING THIS FILE EXISTS TO
RECORD. Reading the census rows one would expect three tables of shared lines. Measured, only two of
the three artifacts share LINES at all:

* `.gitignore` -- 14 shared patterns out of 61/30/73. A pattern is a whole statement, so the shared
  half renders verbatim. RENDERED.
* `Makefile` -- 3 target NAMES in all four repos, 8 in all three CONSUMERS, and NO shared recipe at
  all. lab-commons and consumer-c are byte-identical on `fmt`, `lint` and `test`; consumer-b's `lint`
  also runs `cargo fmt` and `cargo clippy`, and
  consumer-a' `test` selects `tests/unit -m "not femm"`. A recipe naming a tree or a vendor mark is a
  fact about that tree. **So rendering a family Makefile would be a declaration that lies** -- the
  base here is a target CONTRACT (these names must exist) plus the one recipe that genuinely is the
  family's, `verify`, which `dev_lab.dev.verify` already ships as code. REQUIRED.

`[tool.ruff]` IS DELIBERATELY ABSENT FROM THIS FILE. It is the fourth artifact the census names and
it is owned by the stage that widens this repo's own select from 12 selectors to the consumers' 58;
building a base for it here would put two renderers on one artifact while that stage is mid-sweep.
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
    'GITIGNORE_FAMILY_LINES',
    'GITIGNORE_FLOOR',
    'ORDERED_SECTIONS',
    'ORDER_SENSITIVE_ARTIFACTS',
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

#: THE PRINCIPLE (user ruling 2026-11-24, superseding the measured three-way intersection of 2026-09-17):
#: a `.gitignore` lists ONLY paths that legitimately exist untracked in every checkout. A misplaced
#: artifact is NOT ignored: it shows in `git status` and the closed inventory refuses it. So every line
#: is root-anchored unless the artifact genuinely appears at any depth, and each names what writes it.
#: Tool caches (pytest, ruff, mypy, coverage, hypothesis) are not here: the family pyproject rows send
#: them under `output/cache/<tool>/`. Retired with the old base, each for having no writer in every
#: checkout: `**/.env`, the cache directories, `.coverage*`, `htmlcov/`, `*.egg-info/`, `*.spec`, `*.c`,
#: `**/log/*.log(.error)`, `/dumps/`, `/report/`, `**/ignore/`, `**/_meta.json`, `!**/attic/**` and the
#: rem/tasks/sharp-review/agents/skills/commands/workflows/output-styles/docs re-inclusions.
GITIGNORE_FAMILY_LINES: Final[dict[str, str]] = {
    '/.venv/': 'the checkout`s environment, written by the bootstrap door (dev_lab.dev.dep --bootstrap).',
    '/.venvs/': 'the per-run verify environments dev_lab.dev.verify seats beside the checkout`s own.',
    '**/__pycache__/': 'the interpreter`s bytecode cache, beside every imported module at any depth.',
    '/build/': 'the build backend`s staging directory, at the root of every repo that builds a wheel.',
    '/dist/': 'the built wheels and sdists, at the root of every repo that builds one.',
    '/src/**/__version__.py': 'the version file hatch-vcs / setuptools-scm write into the package at build time.',
    '/output/': 'the dated artifact tree (dev_lab.dev.datedlog) and every redirected tool cache.',
    '/config/': 'the dev-mode in-repo config root a consumer generates from packaged defaults.',
    '/temp/': 'the root temporary directory a run may create; a source package named `temp` is not it.',
    '/target/': 'cargo`s build directory beside a root workspace Cargo.toml (a repo whose Rust sits at the root).',
    '/rust/target/': 'cargo`s build directory beside a rust/Cargo.toml workspace (a repo whose Rust sits in rust/).',
    '**/.DS_Store': 'macOS Finder state; a platform artifact at any depth.',
}

#: THE CLOSED AGENT/EDITOR SECTION -- ONE ORDERED BLOCK (last match wins), identical in every repo,
#: declared in :data:`ORDERED_SECTIONS` and rendered verbatim after the sorted lines. It mirrors the
#: closed `.claude/` inventory (dev_lab.dev.claudelayout): a nested `.claude/` is ignored, everything
#: under the root one is ignored except the declared files, and memory re-includes only
#: `<yyyy>/<mm>/<dd>/*.md` -- so `settings.local.json`, `automode.json` and `worktrees/` stay ignored by
#: construction. Codex keeps only the two rendered rule files, the editor only its shared settings.
GITIGNORE_CLAUDE_SECTION: Final[tuple[str, ...]] = (
    '*/**/.claude/',
    '/.claude/*',
    '!/.claude/settings.json',
    '!/.claude/hooks/',
    '/.claude/hooks/*',
    '!/.claude/hooks/deny-commands.js',
    '!/.claude/hooks/venv_resolver.js',
    '!/.claude/hooks/py.js',
    '!/.claude/hooks/deny-rules.json',
    '!/.claude/hooks/native_session.json',
    '!/.claude/memory/',
    '/.claude/memory/**',
    '!/.claude/memory/*/',
    '!/.claude/memory/*/*/',
    '!/.claude/memory/*/*/*/',
    '!/.claude/memory/*/*/*/*.md',
    '/.codex/*',
    '!/.codex/rules/',
    '/.codex/rules/*',
    '!/.codex/rules/family-doors.rules',
    '!/.codex/rules/family-denies.rules',
    '/.vscode/*',
    '!/.vscode/settings.json',
)

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

#: THE BASE: the sorted family lines, then the ordered closed agent/editor section.
GITIGNORE_BASE: Final[tuple[str, ...]] = (
    *sorted(GITIGNORE_FAMILY_LINES),
    *GITIGNORE_CLAUDE_SECTION,
)

#: Per artifact, the base lines that form ONE ORDERED block: rendered in the order written, and
#: exempt from :func:`dev_lab.dev.famconfig.assert_base_is_order_free`, whose refusal exists for
#: lines whose order the sorted table cannot keep.
ORDERED_SECTIONS: Final[dict[str, tuple[str, ...]]] = {'.gitignore': GITIGNORE_CLAUDE_SECTION}

#: WHICH ARTIFACTS ARE LAST-MATCH-WINS, and the floating-rule floor each scan over one must reach.
#:
#: THE GAP THIS DECLARES, stated as a mechanism rather than as the sentence it replaces. A `Delta`
#: maps a BASE line to delta lines rendered AFTER it (`Delta.anchored`); there is no expression for
#: the other direction, "this base line must come after that delta line", and every base line renders
#: before every delta line. So in a last-match-wins file a base line whose only job is to come LAST
#: cannot be a base line at all -- it would be promoted, rendered first, and silently defeated by the
#: negation it was written to close.
#:
#: HOW SUCH A LINE IS RECOGNIZED WITHOUT KNOWING THE DELTAS, which is what makes this checkable on the
#: base ALONE and therefore on every future promotion from a repo nobody surveyed: a rule whose entire
#: value is its position is a rule that is otherwise REDUNDANT. `**/.claude/**/__pycache__/` excludes
#: a strict subset of what `**/__pycache__/` already excludes, so as a set of paths it adds nothing;
#: all it can add is order, and this table cannot carry order. A line that is NOT subsumed by a
#: floating sibling is promotable as normal -- `**/.DS_Store` matches nothing another base line
#: matches, so it means the same wherever it renders.
#:
#: THE FLOOR IS PER ARTIFACT because it is a fact about that base: two floating rules here,
#: `**/__pycache__/` and `**/.env`, and a scan that found none would report what a base with no
#: shared rules reports. The map is a NAMED SET rather than a flag on `Base`, so extending the check
#: to a second artifact is a decision somebody typed here with its own floor.
ORDER_SENSITIVE_ARTIFACTS: Final[dict[str, int]] = {'.gitignore': 2}

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
#: reason holds in all four. Repo-wide normalization (`* text=auto eol=lf`) stays a repo's delta --
#: adopting it renormalizes every tracked file, which is a repo's decision, not the family's.
#:
#: SUPERSEDED 2026-11-24 (user ruling): the base is the ONE repo-wide normalization line. `*.sh text eol=lf`,
#: CRLF for `*.bat`/`*.cmd` and the binary lines are a repo's DELTA, declared only where it tracks such files.
GITATTRIBUTES_BASE: Final[tuple[str, ...]] = ('* text=auto eol=lf',)

#: Every base, by artifact. The render MODE is the machinery's word and is attached there; what this
#: table owns is WHICH lines, and nothing else.
BASES: Final[dict[str, tuple[str, ...]]] = {
    '.gitignore': GITIGNORE_BASE,
    '.gitattributes': GITATTRIBUTES_BASE,
}
