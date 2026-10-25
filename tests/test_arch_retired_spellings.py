"""RETIRED-NAMES-REGISTERED: a retired spelling is registered HERE, and the live tree never says it again.

THE REGISTRY IS :data:`RETIRED_SPELLINGS`, and this file is the one place a retired spelling may appear.
Each row names the REPLACEMENT and the decision that retired it, so a reader who meets the old word in a
dated memory entry can find what it became. Dated memory (``.claude/memory/``) is history and is never
rewritten, so it is outside the scan; everything else a person or agent reads -- source, tests, the
developer docs, the always-loaded rules -- is in it.

A retired spelling survives longest in PROSE: a docstring explaining the rename, an example in a page.
That is why the scan reads every tracked text file in those roots, not just identifiers.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from _arch_corpus import assert_floor, docs_pages, rel, rules_pages, source_modules, suite_modules

#: Retired spelling -> (its replacement, the decision that retired it).
RETIRED_SPELLINGS: Final = {
    'steward': ('integrator', 'user decision 2026-10-20 (lab-commons PR #175): the role keeps its name'),
}

#: Floor on the files read, set under the 2026-10-25 measurement (several hundred): an unread tree is a
#: refusal, not a pass.
PROSE_FLOOR: Final = 100

_THIS: Final = Path(__file__).resolve()


def _pattern(spelling: str) -> re.Pattern[str]:
    return re.compile(rf'\b{re.escape(spelling)}', re.IGNORECASE)


def _hits(text: str) -> list[str]:
    return [old for old in RETIRED_SPELLINGS if _pattern(old).search(text)]


def _corpus() -> tuple[Path, ...]:
    files = (*source_modules(), *suite_modules(), *docs_pages(), *rules_pages())
    return tuple(path for path in files if path.resolve() != _THIS)


def test_no_live_file_spells_a_retired_name() -> None:
    corpus = _corpus()
    assert_floor(len(corpus), PROSE_FLOOR, 'retired-spelling')
    found = {
        f'{rel(path)}: {old} -> {RETIRED_SPELLINGS[old][0]}'
        for path in corpus
        for old in _hits(path.read_text(encoding='utf-8', errors='replace'))
    }
    assert not found, f'retired spellings in the live tree (name the replacement): {sorted(found)}'


def test_planted_retired_spelling_is_found() -> None:
    """PLANTED CONTROL: the matcher sees the old word in prose, any case, and not inside another word."""
    assert _hits('the Steward merges nothing') == ['steward']
    assert _hits('the integrator merges nothing') == []


def test_every_row_names_its_replacement_and_decision() -> None:
    blank = sorted(old for old, (new, why) in RETIRED_SPELLINGS.items() if not new.strip() or not why.strip())
    assert blank == []
