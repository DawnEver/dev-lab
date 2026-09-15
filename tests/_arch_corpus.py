"""The corpus every architecture guard in this repo reads, and the floor each one binds.

WHY THIS FILE EXISTS RATHER THAN A GLOB IN EACH GUARD. A guard that walks the tree itself answers
"how many files did you read?" with a number nobody checks, and a scan that reached nothing is
indistinguishable from a tree with nothing wrong in it. Every guard here takes its file list from
this module and hands the count to :func:`assert_floor`, so the vacuous-green shape has exactly one
place to be refused instead of one per guard.

TRACKED RATHER THAN MERELY PRESENT, for the reason `lab_commons.dev.rules.tracked_files` gives: a
file that exists only in one working copy is not a file the fleet has, so a guarantee resting on it
is a guarantee nobody else can reproduce. A tracked path that is missing from the working tree is
DROPPED rather than read -- that is a fact about this checkout, not about the repo -- and the floor
is what keeps that drop from turning into an empty scan nobody notices.
"""

from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path
from typing import Final

from lab_commons.dev.rules import tracked_files

#: The repo root: this file is ``<root>/tests/_arch_corpus.py``.
ROOT: Final = Path(__file__).resolve().parents[1]

#: Floors, MEASURED 2026-09-15 (22 tracked modules under ``src/``, 22 test modules). Set below the
#: measurement on purpose: a floor is a refusal of an UNREAD tree, not a second pin on the count --
#: pinning the exact number would red on every file added, which is how a floor gets deleted.
SOURCE_FLOOR: Final = 18
TEST_FLOOR: Final = 18


class VacuousScan(AssertionError):
    """A scan reached fewer files than the floor, so finding nothing proves nothing."""


def assert_floor(reached: int, floor: int, what: str) -> None:
    """Refuse a scan that read fewer than *floor* files -- naming what it was scanning."""
    if reached < floor:
        msg = (
            f'the {what} scan reached only {reached} files, below the {floor} floor. Finding NOTHING '
            f'is vacuous rather than green: a clean tree and an unread one are the same empty result, '
            f'and only one of them means the guard held. Fix the corpus, do not lower the floor.'
        )
        raise VacuousScan(msg)


@lru_cache(maxsize=1)
def _tracked() -> tuple[str, ...]:
    return tuple(sorted(tracked_files(ROOT)))


def _existing(names: tuple[str, ...]) -> tuple[Path, ...]:
    return tuple(ROOT / name for name in names if (ROOT / name).is_file())


def source_modules() -> tuple[Path, ...]:
    """Every tracked ``.py`` under ``src/`` that is present in this working tree."""
    return _existing(tuple(n for n in _tracked() if n.startswith('src/') and n.endswith('.py')))


def suite_modules() -> tuple[Path, ...]:
    """Every tracked ``.py`` under ``tests/`` that is present in this working tree."""
    return _existing(tuple(n for n in _tracked() if n.startswith('tests/') and n.endswith('.py')))


def rules_pages() -> tuple[Path, ...]:
    """Every tracked markdown page under ``.claude/rules/`` -- this repo's always-loaded prose."""
    return _existing(tuple(n for n in _tracked() if n.startswith('.claude/rules/') and n.endswith('.md')))


def rel(path: Path) -> str:
    """*path* as a repo-relative POSIX string -- the spelling every refusal message uses."""
    return path.relative_to(ROOT).as_posix()


def parse(path: Path) -> ast.Module:
    """*path* as an AST. A file that does not parse is a failure, never a file that is skipped."""
    return ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
