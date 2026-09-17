"""THE TWO ARMS OF R1: the kit may not be linted less strictly than the code it ships to.

WHY THIS IS TWO RULES AND NOT ONE. The obvious statement -- "a consumer's ``select`` is a superset of
the kit's" -- is FALSE on arrival, and a rule that is false the day it lands teaches its readers to
weaken it. Measured 2026-09-17 across the four repos: the three consumers select an IDENTICAL 58
groups while lab-commons selected 12, so the kit was blind to 50 groups it lints everything it ships
to for; but inside the 8 groups both sides took, every consumer GLOBALLY IGNORES 8 codes the kit
enforces (``B018 B904 E501 RUF012 RUF043 SIM108 SIM113 UP017``). Neither side contains the other.

So the measurement supports two separate facts, and each gets its own arm:

* :func:`test_the_kit_selects_every_group_any_consumer_selects` -- the blindness, CLOSED by this
  commit's adoption of the 58. It is stated over selector COVERAGE rather than set membership, so a
  kit that selected ``E`` while a consumer selected ``E501`` would still pass, and a consumer that
  adds a group the kit has never heard of reds here rather than in a reader's head.
* :func:`test_no_code_the_kit_enforces_is_globally_ignored_by_a_consumer` -- the counter-direction,
  which is NOT closed and cannot be closed from this repo: the remedy is in the consumers' own
  ``pyproject.toml`` files, and this lane may not write in them. It therefore ships with those eight
  as a NAMED, SHRINKING waiver set with a ceiling. The arm reds if the set GROWS, and reds if a
  declared waiver stops being needed -- a ratchet has two sides, and a waiver nothing uses asserts a
  constraint on code that no longer exists.

THE MATCHING TRAP IS NOT RE-IMPLEMENTED HERE. ``'ERA001'.startswith('E')`` is True and ruff's answer
is False; the same for ``F`` and ``FBT003``. :func:`_config_census.selector_covers` resolves the
alphabetic LINTER part exactly and only then matches the digits by prefix, and it is the ONE
implementation both this module and the census use. It carries its own planted control there, and
:func:`test_the_arms_are_stated_over_coverage_and_not_over_string_prefixes` plants the same
confusions THROUGH THESE ARMS, so a regression in the matcher fails where it would do damage rather
than only where it is unit-tested.

A CONSUMER THAT IS NOT CHECKED OUT IS NOT EVIDENCE. Both arms run over whichever consumers are
reachable beside this repo and assert a FLOOR on that reach, so "found nothing" cannot read as green.
"""

from __future__ import annotations

from typing import Final

import pytest
from _config_census import reachable_repos, ruff_ignore, ruff_select, selector_covers
from _config_census_rows import CONSUMER_SELECT, COUNTER_DIRECTION_CODES, KIT_SELECT, REPO_PATHS

#: The consumers, in census order. lab-commons is the kit and is never its own consumer.
CONSUMERS: Final[tuple[str, ...]] = ('wdg-lab', 'optimi-lab', 'motronics-studio')

#: THE WAIVER SET, AND THE ONLY ONE. Eight codes this repo enforces that all three consumers disable
#: globally. Each row says which side should move; none of them says "lower the count".
#:
#: R1 DECIDED EACH ONE SEPARATELY, and the split is 3 the KIT should stop enforcing / 5 the CONSUMERS
#: should stop ignoring. The five are not this lane's to change -- they live in three other repos'
#: ``pyproject.toml`` files -- so they are recorded here to be spent in a later lane, which is what a
#: waiver set with a ceiling is FOR. The three in the kit's direction are already closed: this repo's
#: own ``[tool.ruff.lint] ignore`` deliberately does NOT contain any of the eight, so a consumer that
#: drops one of them from its ignore list closes that row without any edit here.
WAIVED_CONSUMER_IGNORES: Final[dict[str, str]] = {
    'B018': (
        'THE CONSUMERS SHOULD STOP IGNORING IT. A useless expression is a statement someone meant to '
        'assert; in all three consumers it sits under "TODO: remove these ignore rules", which is '
        'their own authors saying the same thing.'
    ),
    'B904': (
        'THE CONSUMERS SHOULD STOP IGNORING IT. `raise ... from` is what keeps a re-raise from hiding '
        'the error it was handling, and a family whose refusals are supposed to name their cause '
        'cannot afford to drop the causal chain. The kit raises `from exc` throughout already.'
    ),
    'E501': (
        'THE CONSUMERS SHOULD STOP IGNORING IT. All four repos already set `line-length = 120`, so the '
        'ignore says the declared width is not enforced -- a limit nothing checks is not a limit. This '
        'repo holds the line at 120 with zero waivers, which is the evidence that it is reachable.'
    ),
    'RUF012': (
        'THE KIT SHOULD KEEP ENFORCING IT AND THE CONSUMERS SHOULD ADOPT IT, but this is the weakest '
        'of the eight: a mutable class attribute that is never mutated is harmless, and `ClassVar` is '
        'the annotation that says so. The kit has no site needing the waiver, so it costs nothing here.'
    ),
    'SIM113': (
        'THE CONSUMERS SHOULD STOP IGNORING IT. `enumerate` over a hand-incremented index is a '
        'mechanical rewrite with no judgement in it, and it too sits in their TODO block.'
    ),
    'RUF043': (
        'THE KIT SHOULD STOP ENFORCING IT -- pending. It fires on `match=` patterns containing regex '
        'metacharacters, and a refusal message full of `(` and `.` is exactly what this family writes; '
        'the kit has no live site, so the decision costs nothing today and is recorded rather than '
        'acted on. It stays enforced here until a site argues otherwise.'
    ),
    'SIM108': (
        'THE KIT SHOULD STOP ENFORCING IT -- pending, for the same reason: a ternary is not always '
        'clearer than the if/else it replaces, and this is a taste rule rather than a defect rule. No '
        'live site in the kit, so nothing is being protected by keeping it.'
    ),
    'UP017': (
        'THE KIT SHOULD STOP ENFORCING IT -- pending. `datetime.UTC` over `timezone.utc` is cosmetic, '
        'and DTZ005 (which the kit DOES enforce, with two named waivers) is the rule that carries the '
        'actual timezone hazard. No live site in the kit.'
    ),
}

#: The floor on the reach. One consumer beside this repo is the least that makes either arm evidence.
REACH_FLOOR: Final[int] = 1

#: THE SECOND TIER, AND IT IS THE COST OF THE ADOPTION RATHER THAN A PRE-EXISTING DIVERGENCE.
#:
#: The eight above were measured BEFORE R1, inside the 8 selector groups the kit and the consumers
#: already shared -- they were divergences while the kit selected only 12. Adopting the consumers'
#: 58 without adopting their 62-code ignore list turned 48 more codes into the same relation: the
#: kit now ENFORCES them and every consumer still drops them globally. That is the kit being
#: STRICTER, which is the direction R1 wanted, so these are not eight more judgements -- they are one
#: judgement held 48 times, and the row below says it once.
#:
#: WHY THE KIT DID NOT SIMPLY COPY THE 62. Twenty of them sit under a literal "TODO: remove these
#: ignore rules" header in all three consumers, which is their own authors saying the list is debt.
#: A kit that inherits its consumers' debt on the day it adopts their standard has adopted the
#: number, not the standard. So the kit's own ignore list was built from what this repo MEASURED --
#: ten entries, each naming why the rule is wrong HERE -- and the gap is recorded rather than copied.
#:
#: MEASURED 2026-09-17: 56 codes in total across the three consumers (wdg-lab 52, optimi-lab 51,
#: motronics 55), of which 8 are the decided rows above. The ceiling is the union; it may only
#: SHRINK, and it shrinks from either end -- a consumer dropping an ignore, or the kit deciding a
#: rule is wrong for it too.
ADOPTION_DEBT: Final[tuple[str, ...]] = (
    'ANN001',
    'ANN002',
    'ANN003',
    'ANN201',
    'ANN202',
    'ANN205',
    'ANN206',
    'ARG002',
    'B023',
    'C901',
    'D100',
    'D101',
    'D102',
    'D103',
    'D104',
    'D105',
    'D107',
    'D205',
    'D415',
    'D417',
    'DTZ005',
    'ERA001',
    'FBT',
    'FIX',
    'INP001',
    'LOG015',
    'N801',
    'N802',
    'N803',
    'N805',
    'N806',
    'N815',
    'N816',
    'NPY002',
    'PLR0912',
    'PLR0915',
    'PLR0917',
    'PLR2004',
    'PLW2901',
    'PT012',
    'PT018',
    'RUF002',
    'RUF003',
    'S101',
    'S311',
    'SLF001',
    'TD',
    'TRY300',
)

#: The whole ceiling: the eight decided rows plus the adoption debt. 56 codes on 2026-09-17.
WAIVER_CEILING: Final[frozenset[str]] = frozenset(WAIVED_CONSUMER_IGNORES) | frozenset(ADOPTION_DEBT)


def _reached_consumers() -> dict[str, object]:
    reached = reachable_repos(REPO_PATHS)
    return {repo: root for repo, root in reached.items() if repo in CONSUMERS}


def _enforced_by_kit(code: str) -> bool:
    """Is *code* selected by lab-commons AND not on its own ignore list? The kit's live answer."""
    kit = reachable_repos(REPO_PATHS)['lab-commons']
    if not any(selector_covers(selector, code) for selector in ruff_select(kit)):
        return False
    return not any(selector_covers(waived, code) for waived in ruff_ignore(kit))


# --------------------------------------------------------------------- arm 1: the kit's coverage


def test_the_kit_selects_every_group_any_consumer_selects() -> None:
    """ARM 1. Whatever a consumer asks of its own code, the kit asks of the code it SHIPS them.

    Stated over COVERAGE, not membership: a kit selecting ``PLR`` satisfies a consumer selecting
    ``PLR2004``, and the arm is about what is enabled rather than about how it is spelled.
    """
    reached = _reached_consumers()
    assert len(reached) >= REACH_FLOOR, (
        f'only {sorted(reached)} of {list(CONSUMERS)} are checked out beside this repo, so this arm '
        f'measured nothing; a reach below {REACH_FLOOR} is INCONCLUSIVE, not green'
    )
    kit = ruff_select(reachable_repos(REPO_PATHS)['lab-commons'])
    for repo, root in reached.items():
        blind = sorted(
            group for group in ruff_select(root) if not any(selector_covers(selector, group) for selector in kit)
        )
        assert blind == [], (
            f'{repo} lints {blind} and the kit does not select them. The kit SHIPS code to that repo, '
            f'so every one of those groups is a question its own source is never asked. Add them to '
            f'[tool.ruff.lint] select in this repo and fix what they red -- never narrow the consumer.'
        )


def test_the_kit_select_is_the_recorded_fifty_eight() -> None:
    """The adoption itself, pinned as a NAMED SET so a group cannot fall out unremarked."""
    live = ruff_select(reachable_repos(REPO_PATHS)['lab-commons'])
    assert live == set(CONSUMER_SELECT), (
        f'lab-commons selects {sorted(live)}; the family set is the 58 in CONSUMER_SELECT. A group '
        f'removed here re-opens the blindness R1 closed.'
    )
    assert set(KIT_SELECT) == set(CONSUMER_SELECT), 'KIT_SELECT and CONSUMER_SELECT diverged in the census data'


# ------------------------------------------- arm 2: what the kit enforces, a consumer may not drop


def test_no_code_the_kit_enforces_is_globally_ignored_by_a_consumer() -> None:
    """ARM 2, WITH ITS CEILING. Every live divergence must be a DECLARED one, in one of two tiers."""
    reached = _reached_consumers()
    assert len(reached) >= REACH_FLOOR, (
        f'only {sorted(reached)} of {list(CONSUMERS)} are checked out, so this arm measured nothing'
    )
    kit = reachable_repos(REPO_PATHS)['lab-commons']
    kit_select, kit_ignore = ruff_select(kit), ruff_ignore(kit)
    for repo, root in reached.items():
        enforced_here_and_dropped_there = sorted(
            code
            for code in ruff_ignore(root)
            if any(selector_covers(selector, code) for selector in kit_select)
            and not any(selector_covers(waived, code) for waived in kit_ignore)
        )
        assert enforced_here_and_dropped_there, (
            f'{repo} diverges from the kit on NOTHING, which would mean this arm has stopped measuring '
            f'anything; the eight decided rows were live when it was written'
        )
        grew = [code for code in enforced_here_and_dropped_there if code not in WAIVER_CEILING]
        assert grew == [], (
            f'{repo} globally ignores {grew}, which this kit ENFORCES, and no row declares why. Either '
            f'the consumer stops ignoring it or the kit stops enforcing it -- and whichever it is, the '
            f'row goes in WAIVED_CONSUMER_IGNORES with its own reason (a decision) or in ADOPTION_DEBT '
            f'(one judgement held many times). The ceiling may only SHRINK.'
        )


def test_every_declared_waiver_is_still_needed_and_still_says_why() -> None:
    """THE OTHER SIDE OF THE RATCHET. A waiver nothing uses is as wrong as an undeclared one."""
    reached = _reached_consumers()
    assert len(reached) >= REACH_FLOOR, f'only {sorted(reached)} are checked out, so the ratchet measured nothing'
    live: set[str] = set()
    for root in reached.values():
        live |= {code for code in ruff_ignore(root) if _enforced_by_kit(code)}
    stale = sorted(WAIVER_CEILING - live)
    assert stale == [], (
        f'{stale} are declared waivers that no reachable consumer needs any more. Delete the rows in '
        f'the same edit that observed it -- the ceiling is what makes this set worth having.'
    )
    reasonless = sorted(code for code, why in WAIVED_CONSUMER_IGNORES.items() if not why.strip())
    assert reasonless == [], f'a bare waiver says a divergence exists, not why it may: {reasonless}'
    overlap = sorted(set(WAIVED_CONSUMER_IGNORES) & set(ADOPTION_DEBT))
    assert overlap == [], (
        f'{overlap} are in BOTH tiers. A decided row and a bulk row are different claims, and a code '
        f'in both lets the decided one be deleted without the ceiling moving.'
    )


def test_the_decided_tier_is_the_eight_the_census_measured() -> None:
    """The decided half is a NAMED SET, and it is the same eight the config census records."""
    assert tuple(sorted(WAIVED_CONSUMER_IGNORES)) == tuple(sorted(COUNTER_DIRECTION_CODES)), (
        f'the decided waiver set is {sorted(WAIVED_CONSUMER_IGNORES)} and the census measured '
        f'{sorted(COUNTER_DIRECTION_CODES)}; two records of one fact have drifted'
    )
    assert all(_enforced_by_kit(code) for code in WAIVED_CONSUMER_IGNORES), (
        'a waived code is no longer ENFORCED by this kit, so there is nothing for a consumer to be '
        'diverging from -- that row is closed and belongs deleted, not carried'
    )
    assert len(WAIVER_CEILING) == 56, (
        f'the ceiling is {len(WAIVER_CEILING)} codes, measured at 56 on 2026-09-17. A ratchet may only '
        f'shrink, so a LARGER number is the failure and a smaller one is the edit that lowers this line.'
    )


# ------------------------------------------------------------------------------ planted controls


@pytest.mark.parametrize(
    ('selector', 'code', 'covered'),
    [
        ('E', 'E501', True),
        ('E', 'ERA001', False),
        ('F', 'FBT003', False),
        ('F', 'FIX001', False),
        ('B', 'B018', True),
        ('PLR', 'PLR2004', True),
        ('PLC0415', 'PLC0414', False),
        ('SIM', 'SIM108', True),
        ('UP', 'UP017', True),
    ],
)
def test_the_arms_are_stated_over_coverage_and_not_over_string_prefixes(
    selector: str, code: str, *, covered: bool
) -> None:
    """PLANTED CONTROL, through the matcher BOTH ARMS USE rather than beside it.

    Every row is a pair the naive ``code.startswith(selector)`` gets wrong or right for the wrong
    reason. ``ERA001`` and ``FBT003`` are the two that actually moved a published number: computing
    the counter-direction set naively inflated it from 8 codes to 13, and all five extras belonged to
    other linters entirely.
    """
    assert selector_covers(selector, code) is covered


def test_a_planted_consumer_ignore_of_an_enforced_code_is_refused() -> None:
    """THE ARM'S OWN REFUSAL, PLANTED. A code outside the waiver set must red, not merely count."""
    kit_select = ('E', 'W', 'F', 'B')
    kit_ignore = ('E501',)
    planted = ('B018', 'W605')

    violations = sorted(
        code
        for code in planted
        if any(selector_covers(s, code) for s in kit_select) and not any(selector_covers(w, code) for w in kit_ignore)
    )
    assert violations == ['B018', 'W605'], violations
    assert [code for code in violations if code not in WAIVED_CONSUMER_IGNORES] == ['W605'], (
        'B018 is a declared waiver and must pass; W605 is not and must red -- if both pass, the '
        'ceiling is not being applied and the arm cannot see the set grow'
    )


def test_a_planted_blind_kit_is_refused_by_arm_one() -> None:
    """ARM 1's REFUSAL, PLANTED: a consumer group no kit selector covers is named, not counted."""
    kit = ('E', 'W', 'F')
    consumer = ('E', 'W', 'F', 'D', 'ANN')
    blind = sorted(group for group in consumer if not any(selector_covers(s, group) for s in kit))
    assert blind == ['ANN', 'D'], blind
