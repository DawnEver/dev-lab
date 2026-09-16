"""lab-commons ADOPTS the shared registry -- the repo that AUTHORS it, held to it.

WHY THIS FILE MATTERS MORE THAN IT LOOKS. The registry was authored here, so every mechanism it
first carried was a path in ANOTHER repo's tree, and the module promised that "a second adopter
inherits the statements and must supply the mechanism for its own tree" while offering no way to
supply one. Measured 2026-09-15: driven against its own tree, lab-commons refused its OWN registry
with 70 failures. `Adoption` is what closed that, and this file is the proof it works -- a real
checkout, with a real git-tracked mechanism list, none of it borrowed from the authoring rows.

THE SOURCE OF A RULE MAY NOT BE ITS WORST ADOPTER, which is what this file is for. When it was first
written it enforced ONE rule of 28 and declared 27 absent. Raised 2026-09-15 to 16 enforced and 12
absent, and again the same day to 18 and 10, by BUILDING the missing mechanisms in this tree
(`tests/test_arch_*.py`) rather than by re-describing the ones another repo has.

THE TWO SETS ARE BOTH PINNED BY NAME, and the pin is the ceiling. A rule added to the registry must
be typed into one of the two or `assert_adopted` reds -- so the absent set cannot grow by accident,
and `_ABSENT_CEILING` forces the hand that shrinks it to lower the number in the same edit.

WHAT THIS PROVES, STATED PRECISELY, because overclaiming it would be the defect it guards: every
rule is ACCOUNTED FOR -- enforced with each named mechanism TRACKED in this tree and, for a lint
mechanism, selected and not globally ignored -- or declared absent. It does NOT run those mechanisms
and cannot say they pass; that is the suite's business.

THE TEN ABSENT RULES ARE ABSENT FOR A REASON, AND THE REASONS ARE NOT THE SAME KIND. Four name
machinery this repo does not have (a gate runner, a hook directory, a network wrapper, a production
entry point) -- adoptable, and unbuilt. Four are about a SUBJECT this library does not have (an
accuracy matrix, an acceptance bar, a capability registry, a retired-name registry): a library with
no solvers has nothing to declare unsupported. One is a shape no file in this tree can reach: the
push obligation is a fact about origin. And one is CIRCULAR rather than merely unbuilt --
HOOKS-ARE-WIRED cannot be closed by shipping a hook and a guard in the same edit, because the guard
would then pass by construction.

WHAT THE 2026-09-15 SECOND RAISE CLOSED, and how, because the CHEAP close was available for both and
was the wrong one. TOLERANCE-CARRIES-A-UNIT was declared VIOLATED here, not merely unenforced: seven
bare `pytest.approx` calls with no `abs=` floor, so a guard would have RED on the repo that authors
the rule. It would have been one edit to write the guard with those seven pinned as a waived set,
and that is a loosened band arriving through the pin. It was closed instead by seven real edits, a
floor per site chosen from the quantity it measures. MEMORY-SHAPE had no subject at all -- no
`.claude/memory/` existed -- and the cheap close there was a guard over an absent directory, which
passes while reading as protection; it was closed by writing a real first entry and giving the scan
a floor of ONE, so an empty tree refuses instead of passing.
"""

from __future__ import annotations

from pathlib import Path

from lab_commons.dev.profile import RepoProfile
from lab_commons.dev.rules import RULES, Adoption, assert_adopted, guard, lint, unadopted, waived

_ROOT = Path(__file__).resolve().parents[1]

_PROFILE = RepoProfile(
    app_name='lab-commons',
    package='lab_commons',
    root=_ROOT,
    lint_config='pyproject.toml',
)

#: Rules this repo refuses a violation of TODAY, each with the mechanism in THIS tree that does the
#: refusing. A rule usually names more than one file, because the guard and the control that proves
#: it can still fail are different claims and either can rot alone.
_ENFORCED = {
    'DECLARATION-LIES': (
        guard('tests/test_arch_public_surface.py'),
        guard('tests/test_arch_rules_pages.py'),
    ),
    'DOCS-SPLIT': (guard('tests/test_arch_rules_pages.py'),),
    'ESCAPE-HATCH-CEILING': (
        guard('tests/test_arch_module_size_alarm.py'),
        guard('tests/test_the_adoption_accounts_for_every_rule.py'),
    ),
    'FIX-THE-CAUSE': (guard('tests/test_arch_one_name_one_definition.py'),),
    'FLOOR-ON-EVERY-SCAN': (
        guard('tests/test_arch_every_scan_binds_a_floor.py'),
        guard('tests/_arch_corpus.py'),
    ),
    'LATEST-DEPENDENCIES': (guard('tests/test_arch_dependencies.py'),),
    'MEMORY-SHAPE': (
        guard('tests/test_arch_memory_lives_in_a_dated_directory.py'),
        guard('tests/_arch_corpus.py'),
    ),
    'MODULE-SIZE-ALARM': (guard('tests/test_arch_module_size_alarm.py'),),
    'NAMED-SETS-NOT-COUNTS': (
        guard('tests/test_arch_module_size_alarm.py'),
        guard('tests/test_arch_skips_are_a_named_set.py'),
        guard('tests/test_the_adoption_accounts_for_every_rule.py'),
    ),
    'NO-LAZY-IMPORT': (lint('PLC0415'),),
    'PLANTED-CONTROL': (guard('tests/test_arch_every_scan_binds_a_floor.py'),),
    'PUBLIC-SURFACE-DECLARED': (guard('tests/test_arch_public_surface.py'),),
    'TOLERANCE-CARRIES-A-UNIT': (guard('tests/test_arch_every_approx_states_its_floor.py'),),
    'RATCHET-TWO-SIDES': (
        guard('tests/test_arch_module_size_alarm.py'),
        guard('tests/test_arch_dependencies.py'),
    ),
    'REGISTRY-OWNS-THE-DECISION': (guard('tests/test_arch_registry_data_is_separate.py'),),
    'UNITS-GO-THROUGH-PINT': (
        guard('tests/test_dev_units.py'),
        guard('tests/test_no_name_carries_a_unit.py'),
    ),
    'VERDICT-BAR-IS-THE-INCREMENT': (guard('tests/test_dev_verdict.py'),),
    'XFAIL-NOT-SKIP': (guard('tests/test_arch_skips_are_a_named_set.py'),),
}

#: Rules this repo does NOT yet refuse a violation of, BY NAME with the reason. A mapping rather than
#: a bare set: an exemption with no recorded reason is indistinguishable from a hole somebody widened
#: during a red suite, and a reason makes that repair a sentence somebody has to write.
_ABSENT_REASONS = {
    'AGENT-GUARD': (
        'HALF-CLOSED 2026-09-16, and the remaining half is NAMED rather than deferred. The rule says '
        'the refusal is IDENTICAL in every repo that adopts it, and the shared half of that now '
        'exists here: `lab_commons.dev.hooks` holds the universal rows and this repo supplies its '
        'own remedies, driven against this tree by '
        'tests/test_the_deny_adoption_ships_only_remedied_rules.py. What is still absent is the '
        'INSTALLATION -- no .claude/settings.json here points a PreToolUse matcher at an engine, so '
        'a bare test line typed in this repo is still not refused. Rendering the rules a repo may '
        'ship and WIRING them are two changes, and claiming the rule on the first would be the '
        'declaration that lies. The 2026-09-15 reason (that the rules had no subject here) is now '
        'false, and was replaced rather than left standing'
    ),
    'BAR-IS-A-CONSTANT': 'no acceptance bar: this library produces no measurement to judge',
    'HOOKS-ARE-WIRED': (
        'no declared hooks, so there is nothing whose absence could fail loudly -- and a wiring guard '
        'over a hook created in the same edit passes by construction rather than by holding'
    ),
    'IMPLEMENT-EVERYTHING': 'no combination matrix and no accuracy tag: the subject is absent',
    'NETWORK-RETRY-THEN-REPORT': 'nothing here calls a network verb, so a retry wrapper would guard nothing',
    'PRODUCTION-ENTRY-POINT': 'a library with no CLI has no production entry point to reproduce through',
    'REFUSAL-NAMES-THE-REMEDY': 'no runner and no wait to bound; the remedy half is unmechanised here',
    'RETIRED-NAMES-REGISTERED': 'no retired-spelling registry in this tree yet',
    'SHARED-CHECKOUT': 'the push obligation is a fact about origin, not about any file here',
    'UNSUPPORTED-RAISES': 'no capability registry: there is no unsupported combination to refuse',
}

_ABSENT = frozenset(_ABSENT_REASONS)

#: The ceiling on the absent set, MEASURED 2026-09-15 after the raise (it was 27). It may only go
#: DOWN: closing a gap deletes a name above AND lowers this number, so the number cannot quietly
#: track an absent set that grew.
_ABSENT_CEILING = 10


def _adoption() -> Adoption:
    return Adoption(app_name='lab-commons', mechanisms=_ENFORCED, declared_absent=_ABSENT)


def test_the_adoption_accounts_for_every_rule() -> None:
    """THE CHECK. Every rule is either enforced here with a live mechanism, or named as a gap."""
    assert_adopted(_PROFILE, _adoption())


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


def test_every_gap_carries_its_reason() -> None:
    """A waiver with no reason recorded is a hole that reads as a decision."""
    silent = sorted(name for name, why in _ABSENT_REASONS.items() if not why.strip())
    assert silent == [], f'declared absent with no reason recorded: {silent}'


def test_the_gap_is_visible_rather_than_silent() -> None:
    """`waived` and `unadopted` are different facts, and this is the one that is on record."""
    adoption = _adoption()
    assert unadopted(RULES, adoption) == (), 'the check above would already red; keep the two in step'
    assert set(waived(RULES, adoption)) == _ABSENT
