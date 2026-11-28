"""A CLOSE'S DISTILLATION CHECK: which of a task's journal decisions no memory entry, rule or doc cites yet.

Split out of :mod:`dev_lab.dev.task` (2026-11-28, MODULE-SIZE-ALARM): ``close`` refuses until each decision is
cited as ``tasks/<slug>/JOURNAL.md#D<n>`` from this checkout, or kept in the journal only.
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Final

__all__ = ['undistilled', 'undistilled_door']

_CITE: Final = 'tasks/{slug}/JOURNAL.md#D'
_DISTILL_HOMES: Final = (('.claude', 'memory'), ('.claude', 'rules'), ('docs-src',))


def _cited(cwd: Path, slug: str) -> set[int]:
    tops = [p for p in (Path(cwd).resolve(), *Path(cwd).resolve().parents) if (p / '.git').exists()][:1]
    cite = re.compile(re.escape(_CITE.format(slug=slug)) + r'(\d+)\b')
    found: set[int] = set()
    for top in tops:
        for home in _DISTILL_HOMES:
            for doc in top.joinpath(*home).rglob('*.md'):
                with contextlib.suppress(OSError):
                    found.update(int(n) for n in cite.findall(doc.read_text(encoding='utf-8').replace('\\', '/')))
    return found


def undistilled(cwd: Path, slug: str, decisions: Iterable[int], journal_only: Sequence[int] = ()) -> list[int]:
    """The decision numbers of *slug* that *cwd*'s checkout does not cite and *journal_only* does not keep."""
    cited = _cited(cwd, slug)
    return [n for n in decisions if n not in cited and n not in journal_only]


def undistilled_door(slug: str, missing: Sequence[int]) -> str:
    """Why a close of *slug* is refused over *missing*, and its door."""
    return (
        f'{", ".join(f"D{n}" for n in missing)} not distilled.\nDoor: cite {_CITE.format(slug=slug)}<n> from a '
        'memory entry, a rule or a doc of this checkout, or keep it in the journal only (--journal-only D<n>)'
    )
