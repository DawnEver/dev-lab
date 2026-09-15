"""lab-commons ADOPTS the shared registry -- the first repo to do it from outside.

WHY THIS FILE MATTERS MORE THAN IT LOOKS. The registry was authored here, so every mechanism it
first carried was a path in ANOTHER repo's tree, and the module promised that "a second adopter
inherits the statements and must supply the mechanism for its own tree" while offering no way to
supply one. Measured 2026-09-15: driven against its own tree, lab-commons refused its OWN registry
with 70 failures. `Adoption` is what closed that, and this file is the proof it works -- the first
adopter that is not the author, over a real checkout, with a real git-tracked mechanism list.

THE TWO SETS ARE BOTH PINNED BY NAME, and the pin is the ceiling. `_ENFORCED` names the rules this
repo can refuse a violation of TODAY; `_ABSENT` names the ones it cannot yet, so the gap is on
record instead of silent. A rule added to the registry must be typed into one of the two or
`assert_adopted` reds -- so the absent set cannot grow by accident, and `_ABSENT_CEILING` forces the
hand that shrinks it to also lower the number.
"""

from __future__ import annotations

from pathlib import Path

from lab_commons.dev.profile import RepoProfile
from lab_commons.dev.rules import RULES, Adoption, assert_adopted, guard, unadopted, waived

_ROOT = Path(__file__).resolve().parents[1]

_PROFILE = RepoProfile(
    app_name='lab-commons',
    package='lab_commons',
    root=_ROOT,
    lint_config='pyproject.toml',
)

#: Rules this repo can refuse a violation of TODAY, each with the mechanism that does the refusing.
#: Two tests, because they answer different questions: `test_dev_units.py` proves the scan WORKS over
#: planted trees, `test_no_name_carries_a_unit.py` proves THIS repo is clean -- which no planted
#: fixture can say about the tree it ships in.
_ENFORCED = {
    'UNITS-GO-THROUGH-PINT': (
        guard('tests/test_dev_units.py'),
        guard('tests/test_no_name_carries_a_unit.py'),
    ),
}

#: Rules this repo does NOT yet refuse a violation of. Typed out rather than computed, because a
#: computed set would absorb a newly added rule silently -- which is the whole failure this pin
#: exists to prevent. lab-commons has no architecture suite yet; that is the work this list names.
_ABSENT = frozenset(
    {
        'AGENT-GUARD',
        'BAR-IS-A-CONSTANT',
        'DECLARATION-LIES',
        'DOCS-SPLIT',
        'ESCAPE-HATCH-CEILING',
        'FIX-THE-CAUSE',
        'FLOOR-ON-EVERY-SCAN',
        'HOOKS-ARE-WIRED',
        'IMPLEMENT-EVERYTHING',
        'LATEST-DEPENDENCIES',
        'MEMORY-SHAPE',
        'MODULE-SIZE-ALARM',
        'NAMED-SETS-NOT-COUNTS',
        'NETWORK-RETRY-THEN-REPORT',
        'NO-LAZY-IMPORT',
        'PLANTED-CONTROL',
        'PRODUCTION-ENTRY-POINT',
        'PUBLIC-SURFACE-DECLARED',
        'RATCHET-TWO-SIDES',
        'REFUSAL-NAMES-THE-REMEDY',
        'REGISTRY-OWNS-THE-DECISION',
        'RETIRED-NAMES-REGISTERED',
        'SHARED-CHECKOUT',
        'TOLERANCE-CARRIES-A-UNIT',
        'UNSUPPORTED-RAISES',
        'VERDICT-BAR-IS-THE-INCREMENT',
        'XFAIL-NOT-SKIP',
    }
)

#: The ceiling on the absent set, MEASURED when this file was written. It may only go DOWN: closing a
#: gap means deleting a name above AND lowering this number, so the number cannot quietly track an
#: absent set that grew.
_ABSENT_CEILING = 27


def test_the_adoption_accounts_for_every_rule() -> None:
    """THE CHECK. Every rule is either enforced here with a live mechanism, or named as a gap."""
    assert_adopted(_PROFILE, Adoption(app_name='lab-commons', mechanisms=_ENFORCED, declared_absent=_ABSENT))


def test_the_two_sets_account_for_the_registry_exactly() -> None:
    """A rule added to the registry must be typed into one of the sets, or this reds before the check."""
    accounted = set(_ENFORCED) | _ABSENT
    live = {rule.id for rule in RULES}
    assert accounted == live, (
        f'rules neither enforced nor declared absent here: {sorted(live - accounted)}; names that are '
        f'not rules: {sorted(accounted - live)}. A new universal rule is a decision this repo has to '
        f'make for itself, not a line that appears in a list it never read.'
    )


def test_the_absent_set_may_only_shrink() -> None:
    """The ceiling on the escape hatch: closing a gap lowers the number in the same edit."""
    assert len(_ABSENT) <= _ABSENT_CEILING, (
        f'{len(_ABSENT)} rules are declared absent, above the {_ABSENT_CEILING} ceiling. An escape hatch '
        f'needs a CEILING rather than a reason: a waiver that no one must justify is how a check reaches '
        f'zero without anything being fixed.'
    )


def test_the_gap_is_visible_rather_than_silent() -> None:
    """`waived` and `unadopted` are different facts, and this is the one that is on record."""
    adoption = Adoption(app_name='lab-commons', mechanisms=_ENFORCED, declared_absent=_ABSENT)
    assert unadopted(RULES, adoption) == (), 'the check above would already red; keep the two in step'
    assert set(waived(RULES, adoption)) == _ABSENT
