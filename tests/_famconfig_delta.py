r"""lab-commons' own DELTAS against the family config bases -- data, computed by nothing.

GIT HOOKS ARE NOT A DELTA HERE: they are TOML (`[tool.dev_lab.hooks]` in pyproject.toml over
`dev_lab/dev/githooks/base.toml`) and nothing is rendered for them.

`.gitignore` IS ADOPTED AS OF 2026-10-03, on the user's ruling that every project-level file has ONE
source in this package. The base grew the family-mandated lines (`_famconfig_rows.GITIGNORE_FAMILY_LINES`)
that made it cover this tree: `**/__version__.py` (which reaches the hatch-vcs file
`src/lab_commons/__version__.py`), `/build/`, `/dist/` and the ordered Claude project-state section, which
covers `.claude/worktrees/`. What stays is ONE line, `*.py[cod]` -- a compiled file OUTSIDE a `__pycache__/`,
which no consumer ignores and this repo always has. :data:`DELTAS` now holds all three artifacts, so
the completeness arm runs here too.
"""

from __future__ import annotations

from typing import Final

from dev_lab.dev.famconfig import Delta

__all__ = [
    'DELTAS',
    'GITATTRIBUTES',
    'GITATTRIBUTES_DELTA',
    'GITIGNORE',
    'GITIGNORE_DELTA',
    'REPO',
]

#: How this repo names itself in a rendered file's drop and anchor comments.
REPO: Final = 'lab-commons'

#: This repo's `.gitignore` beyond the family base: one line, see the docstring. The ceiling IS the
#: measurement, so the next line anybody adds raises it in the same edit and says what it is for.
GITIGNORE: Final = '.gitignore'
GITIGNORE_DELTA: Final = Delta(repo=REPO, added=('*.py[cod]',), dropped={}, ceiling=1)

#: `.gitattributes` is the base and nothing else: since 2026-11-24 the base normalizes the
#: whole repo, so nothing is left for a delta.
GITATTRIBUTES: Final = '.gitattributes'
GITATTRIBUTES_DELTA: Final = Delta(repo=REPO, added=(), dropped={}, ceiling=0)

#: Every artifact this repo declares a delta against -- every one of the kit's bases.
DELTAS: Final[dict[str, Delta]] = {
    GITIGNORE: GITIGNORE_DELTA,
    GITATTRIBUTES: GITATTRIBUTES_DELTA,
}
