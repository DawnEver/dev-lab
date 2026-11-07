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

#: dev-lab's own tables, moved from ``[tool.lab_commons]`` to ``[tool.dev_lab]`` (plan A3); ``schedule``,
#: ``tools``, ``hpc``, ``tests`` and ``artefacts`` stay, because lab-commons code reads them.
MOVED_TABLES: Final = (
    'areas', 'automode', 'branchset', 'carry', 'ci', 'components', 'dep', 'doors', 'ephemeral_refs', 'forge',
    'hooks', 'integrator', 'parts', 'placement', 'requests', 'review', 'stoprun', 'verify', 'worktrees',
)  # fmt: skip

#: Retired spelling -> (its replacement, the decision that retired it).
RETIRED_SPELLINGS: Final = {
    'steward': ('integrator', 'user decision 2026-10-20 (lab-commons PR #175): the role keeps its name'),
    'PR-REVIEW-IS-ADVISORY': (
        'PR-REVIEW-IS-ONE-SHOT-ADVICE',
        'user ruling 2026-10-26 (review redesign), then 2026-11-06: one review per PR, advice, only security blocks',
    ),
    'PR-REVIEW-BLOCKS-ON-HIGH-OR-SECURITY': (
        'PR-REVIEW-IS-ONE-SHOT-ADVICE',
        'user ruling 2026-11-06: the review is a one-shot independent acceptance with advice; only security blocks',
    ),
    **dict.fromkeys(
        (
            'forgereview_rounds',
            'forgereview_judge',
            'forgereview_dispose',
            'AdjudicationRefused',
            'FAMILY_MAX_ROUNDS',
            'review dispose',
            'review adjudicate',
            'review-claims',
            'capped_waiver',
            'capped_line',
        ),
        (
            'forgereview_advice / forgereview_identity / reviewcap.unreviewed_waiver / forge review again',
            'user ruling 2026-11-06: one review per PR -- no rounds, no re-judging, no claims to adjudicate',
        ),
    ),
    **dict.fromkeys(
        ('split the PR', 'held over the cap', 'structure-level review'),
        (
            'review again after growth; Scope.unread lists what the budget left out',
            'user ruling 2026-11-06: a PR is never split for its review; one session, one task, one PR',
        ),
    ),
    **dict.fromkeys(
        ('review_blocks', 'review_hold'),
        (
            'reviewgate.review_missing',
            'user ruling 2026-10-31 (every PR must get a review): one predicate, nothing advisory',
        ),
    ),
    **dict.fromkeys(
        ('disposition_text', 'DisposeRefused', 'review-disposition'),
        (
            'nothing: findings are advice (user ruling 2026-11-06)',
            'user ruling 2026-10-31, retired with the claims 2026-11-06: a one-shot review disposes of nothing',
        ),
    ),
    **dict.fromkeys(
        ('secret-env', 'ANTHROPIC_API_KEY', 'login anthropic'),
        (
            '--keys-env AI_LAB_KEYS_<TASK> (dev_lab.dev.taskkeys)',
            'user-approved design 2026-11-05: a task carries ONE key bundle; dev-lab names no provider',
        ),
    ),
    'review capped, merge waits': (
        'forgereview_claim.UNREVIEWED_STATUS (not reviewed, merges unreviewed)',
        'user ruling 2026-11-05: a capped review no longer holds the merge; it merges WARNED',
    ),
    'OVER_CAP_TAKEOVER': ('Scope.unread', 'D123 2026-10-31, then 2026-11-06: an oversize head is sliced, never held'),
    **dict.fromkeys(
        ('breakglass enrol', 'wave_hours =', 'max_merges =', '--max-merges'),
        (
            'consent enrol; a breakglass.wave consent credential whose params are hours and max_merges',
            'user-approved design 2026-11-07: the wave TOTP check moved onto consent credentials; no code path stays',
        ),
    ),
    **{
        f'tool.lab_commons.{table}': (
            f'tool.dev_lab.{table}',
            'plan A3 2026-10-27: a table only dev-lab reads lives under [tool.dev_lab]; no fallback reads the old one',
        )
        for table in MOVED_TABLES
    },
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
