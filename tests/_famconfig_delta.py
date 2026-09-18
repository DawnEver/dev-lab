r"""lab-commons' own DELTAS against the family config bases -- data, computed by nothing.

THE GAP THIS CLOSES. This repo SHIPS the hook machinery -- `dev.hook_install` (is a declared hook
actually in the directory git consults), `dev.hooks` and `dev.hook_adoption` (the denied shapes and
their remedies), `dev.githooks` and the `lab-with-venv` bootstrap -- and until 2026-09-17 ran NONE of
it on itself: no `.pre-commit-config.yaml`, no installed hook, no commit-time enforcement at all. The
config census carried that as its own row, and the row's last sentence was the complaint: the one
repo whose tests assert that a config without an install is a lie had neither half.

THE DELTA IS EMPTY, AND THAT IS THE DECISION RATHER THAN THE DEFAULT. Both labs adopted the same base
the same day with deltas of 8 and 62 lines. This repo declares ZERO, and every base line was checked
against this tree before it was accepted rather than taken because the base holds it:

* `check-ast`, `check-case-conflict`, `check-merge-conflict`, `debug-statements`,
  `end-of-file-fixer`, `mixed-line-ending`, `trailing-whitespace`, `check-added-large-files` -- a
  Python tree of 170 formatted files and a git history; every one has a live subject here.
* `check-toml` -- `pyproject.toml`, the only TOML tracked, and the file every consumer installs from.
* `check-json` -- MEASURED: this repo tracks NO `.json` file at all today. It is kept anyway, and
  that is the one line where "no subject" is not "wrong here": the hook is a no-op with nothing to
  check and becomes live the moment a JSON file arrives, which is exactly when a reader would not
  think to add it. A DROP is for a base line that would be WRONG here, not for one that is idle.
* `commitizen` at `commit-msg` -- this family commits in imperative conventional form and this repo
  had no check on it. There is no `[tool.commitizen]` block here, so the hook runs commitizen's
  default `cz_conventional_commits`, which is the convention the family already writes.
* `fail_fast: false` and `default_stages: [pre-commit]` -- the base's two scalars. The narrowing
  `default_stages` performs costs this checkout nothing beyond what it declares, because the stages
  installed here are exactly `pre-commit` and `commit-msg` and `commitizen` names its own.

WHAT WAS CONSIDERED AND REFUSED, because a delta's reasoning is only checkable if the rejected lines
are named. `check-shebang-scripts-are-executable` (optimi-lab declares it) looks like an obvious fit
for a repo shipping five `.sh` payloads -- and it is REFUSED ON MEASUREMENT: all five are mode 100644
in this index, so the hook would red on the first run against a tree whose `.gitattributes` already
owns the property that actually matters here (`*.sh text eol=lf`, so bash does not read a `\r`). A
base line adopted into a red is a hook that gets `--no-verify`'d, which is worse than no hook.

AND NO LOCAL `- repo: local` BLOCK, which is the whole reason this delta is empty where wdg-lab's is
62 lines. That lab's local hooks are a changelog generator, a version bumper and a ruff pair; this
repo mints its versions from tags through hatch-vcs, publishes no changelog, and has ONE verdict --
`make verify`, which is `lint fmt-check test` and which `lab_commons.dev.verify` ships as code. A
pre-push hook re-running that is the "a push must never block development" shape the family kills on
sight, and the census row already records that this repo genuinely has no pre-push gate.

THE `Makefile` BASE IS ADOPTED HERE AS OF 2026-09-18, and the reason is that the kit was the one repo
not meeting the contract it publishes. `MAKEFILE_BASE` demands nine target headers plus the one
portable recipe; MEASURED before this adoption, this repo's Makefile carried `fmt`, `lint`, `test`,
`fmt-check`, `adoption` and `verify` -- FIVE of the nine headers absent (`all`, `clean`, `install`,
`install-dev`, `test-parallel`) and the `verify` recipe a hand-written `lint fmt-check test` chain
rather than the `python -m lab_commons.dev.verify` the base names and this package ships. Both halves
are the same shape one layer apart: the kit held to less than what it shipped.

THE DROP MAP IS EMPTY AND THAT IS A MEASUREMENT rather than a default. After the adoption the kit's
own survey reports 26 added lines and ZERO dropped, so every one of the nine base lines is on disk
under its own recipe. A drop is the honest alternative for a target this repo genuinely cannot have,
and there is none.

`.gitignore` IS STILL NOT ADOPTED and its absence stays named rather than silent. This repo's file is
10 literal lines against the base's 14 patterns; the base writes every cache rule directory-slashed
and floating (`**/__pycache__/`) where this tree writes them unanchored, and it carries
`src/lab_commons/__version__.py`, which no other repo has. Adoption is a real behaviour change with
its own evidence and its own commit. :data:`DELTAS` therefore holds TWO of the kit's three entries,
and the test modules beside it deliberately do not call the kit's
`assert_every_base_is_accounted_for`, because that arm asserts a completeness this repo has not yet
earned.
"""

from __future__ import annotations

from typing import Final

from lab_commons.dev.famconfig import Delta

__all__ = [
    'DELTAS',
    'INSTALLED_STAGES',
    'MAKEFILE',
    'MAKEFILE_DELTA',
    'MAKE_TARGET_FLOOR',
    'PRECOMMIT',
    'PRECOMMIT_DELTA',
    'PRECOMMIT_HOOK_FLOOR',
    'REPO',
]

#: How this repo names itself in a rendered file's drop and anchor comments.
REPO: Final = 'lab-commons'

#: The two artefacts this repo has adopted, each spelled once.
PRECOMMIT: Final = '.pre-commit-config.yaml'
MAKEFILE: Final = 'Makefile'

#: NOTHING ADDED, NOTHING DROPPED -- the module docstring is the evidence for each half. A ceiling of
#: ZERO is the ratchet: this repo runs no hook of its own today, so the next line anybody adds has to
#: raise the ceiling in the same edit and say what it is for, rather than arriving as a diff that
#: looks like the base growing.
PRECOMMIT_DELTA: Final = Delta(repo=REPO, added=(), dropped={}, ceiling=0)

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

#: Every artefact this repo declares a delta against. TWO of the kit's three, and see the docstring
#: for why `.gitignore` is absent rather than adopted.
DELTAS: Final[dict[str, Delta]] = {PRECOMMIT: PRECOMMIT_DELTA, MAKEFILE: MAKEFILE_DELTA}

#: The git hook files this repo INSTALLS, which is the half a configuration cannot answer for itself.
#: Exactly the stages the config declares: `pre-commit` for the default, `commit-msg` for commitizen.
#: NO `pre-push` -- see the docstring; `make verify` is this repo's whole verdict and a hook re-running
#: it would block every push. Both labs went a day with `commitizen` DECLARED at `commit-msg` and no
#: shim installed, so every commit message went unchecked while both trees read as guarded; this
#: constant exists so the same gap cannot open here in silence.
INSTALLED_STAGES: Final[tuple[str, ...]] = ('commit-msg', 'pre-commit')

#: How many hook ids the rendered config must carry before a subset check over it means anything.
#: ELEVEN is the family core and this repo adds none, so the floor IS the count; a file that parsed
#: to nothing would otherwise satisfy every id assertion vacuously.
PRECOMMIT_HOOK_FLOOR: Final = 11
