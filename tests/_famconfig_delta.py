r"""lab-commons' own DELTAS against the family config bases -- data, computed by nothing.

GIT HOOKS ARE NOT A DELTA HERE: they are TOML (`[tool.lab_commons.hooks]` in pyproject.toml over
`lab_commons/dev/githooks/base.toml`) and nothing is rendered for them.

`.gitignore` IS ADOPTED AS OF 2026-10-03, on the user's ruling that every project-level file has ONE
source in this package. The base grew the family-mandated lines (`_famconfig_rows.GITIGNORE_FAMILY_LINES`)
that made it cover this tree: `.verify/`, `**/__version__.py` (which reaches the hatch-vcs file
`src/lab_commons/__version__.py`), `/build/`, `/dist/` and the ordered Claude project-state section, which
covers `.claude/worktrees/`. What stays is ONE line, `*.py[cod]` -- a compiled file OUTSIDE a `__pycache__/`,
which no consumer ignores and this repo always has. :data:`DELTAS` now holds all three artefacts, so
the completeness arm runs here too.
"""

from __future__ import annotations

from typing import Final

from lab_commons.dev.famconfig import Delta

__all__ = [
    'DELTAS',
    'GITATTRIBUTES',
    'GITATTRIBUTES_DELTA',
    'GITIGNORE',
    'GITIGNORE_DELTA',
    'MAKEFILE',
    'MAKEFILE_DELTA',
    'MAKE_TARGET_FLOOR',
    'REPO',
    'RGIGNORE',
]

#: How this repo names itself in a rendered file's drop and anchor comments.
REPO: Final = 'lab-commons'

#: The Makefile, spelled once.
MAKEFILE: Final = 'Makefile'

#: This repo's OWN Makefile lines -- everything the family base does not name. MEASURED 2026-09-18 by
#: the kit's survey against the adopted file: 26 lines, 0 drops. The ceiling IS the measurement rather
#: than a round number above it, so the next recipe line anybody adds raises it in the same edit.
#:
#: WHAT IS IN HERE AND WHY IT IS NOT IN THE BASE. Every `.PHONY:` line -- `MAKEFILE_RESIDUAL_SIGNALS`
#: names all eight as flagged by the anti-fork arm and DECLINES to promote them, because `.PHONY: fmt`
#: is one SPELLING of a declaration a Makefile may equally make as a single `.PHONY: a b c` line, and
#: a base requiring the spelling would legislate style. `.DEFAULT_GOAL := all` is in that same set. The
#: recipes are here because the base is REQUIRED rather than RENDERED: the measurement across the four
#: repos found NO shared recipe at all except `verify`'s, which is why that one line sits in the base.
#:
#: `fmt-check:` and `adoption:` are the two target headers that are this repo's alone. `fmt-check` is
#: the half of a verdict a formatter-only CI leg wants; `adoption` runs the one suite this repo
#: publishes a Makefile door for.
MAKEFILE_DELTA: Final = Delta(
    repo=REPO,
    added=(
        '.DEFAULT_GOAL := all',
        '.PHONY: install',
        '\tuv pip install -e .',
        '.PHONY: install-dev',
        '\tuv pip install -e ".[dev]"',
        '.PHONY: lint',
        '\tpython -m ruff check .',
        '.PHONY: fmt-check',
        'fmt-check:',
        '\tpython -m ruff format --check .',
        '.PHONY: fmt',
        '\tpython -m ruff check . --fix',
        '\tpython -m ruff format .',
        '.PHONY: test',
        '\tpython -m pytest',
        '.PHONY: test-parallel',
        '\tpython -m pytest -n auto',
        '.PHONY: adoption',
        'adoption:',
        '\tpython -m pytest tests/test_the_adoption_accounts_for_every_rule.py -v',
        '.PHONY: verify',
        '.PHONY: clean',
        "\tpython -c \"import shutil; [shutil.rmtree(d, True) for d in ('dist', 'build', '.verify')]\"",
        "\tpython -c \"import shutil; [shutil.rmtree(d, True) for d in ('.pytest_cache', '.ruff_cache')]\"",
        '\tpython -c "import pathlib, shutil; [shutil.rmtree(d, True) for d in pathlib.Path().rglob(\'__pycache__\')]"',
        '.PHONY: all',
    ),
    dropped={},
    ceiling=26,
)

#: How many target headers the live Makefile must declare before a presence check over it means
#: anything. NINE is the base's own count of contract lines, and the floor sits there rather than at
#: the eleven this repo happens to have: a floor refuses a file that parsed to nothing, it is not a
#: second pin on this repo's target list.
MAKE_TARGET_FLOOR: Final = 9

#: This repo's `.gitignore` beyond the family base: one line, see the docstring. The ceiling IS the
#: measurement, so the next line anybody adds raises it in the same edit and says what it is for.
GITIGNORE: Final = '.gitignore'
GITIGNORE_DELTA: Final = Delta(repo=REPO, added=('*.py[cod]',), dropped={}, ceiling=1)

#: `.gitattributes` is the base and nothing else: its one line (`*.sh text eol=lf`) is the rule this repo
#: wrote for itself first, for the payloads it ships, and the reason moved into the base with it.
GITATTRIBUTES: Final = '.gitattributes'
GITATTRIBUTES_DELTA: Final = Delta(repo=REPO, added=(), dropped={}, ceiling=0)

#: `.rgignore` is the base and nothing else.
RGIGNORE: Final = '.rgignore'
RGIGNORE_DELTA: Final = Delta(repo=REPO, added=(), dropped={}, ceiling=0)

#: Every artefact this repo declares a delta against -- every one of the kit's bases.
DELTAS: Final[dict[str, Delta]] = {
    MAKEFILE: MAKEFILE_DELTA,
    GITIGNORE: GITIGNORE_DELTA,
    GITATTRIBUTES: GITATTRIBUTES_DELTA,
    RGIGNORE: RGIGNORE_DELTA,
}
