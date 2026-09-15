"""The rules registry is only worth carrying if a vanished mechanism is a RED.

The defect this guards is the one the registry was built to remove, so it would be the joke writing
itself if the registry itself could go quiet: a row whose mechanism was deleted would keep reading
exactly as it did the day it was enforced, and nothing would say otherwise. Three properties, and
each has a control in the opposite direction:

* the ID set is a NAMED SET, so a row cannot disappear without the failure naming what left;
* a rule with no mechanism cannot be CONSTRUCTED, so prose cannot enter the registry at all;
* :func:`unresolved` reports a mechanism that is not tracked, not selected, or globally ignored, and
  the control drives the REAL function over a REAL git tree rather than re-implementing its logic and
  agreeing with itself by construction.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from lab_commons.dev.profile import RepoProfile
from lab_commons.dev.rules import (
    RULES,
    Adoption,
    LintRule,
    Rule,
    TestPath,
    UnenforceableRule,
    assert_adopted,
    assert_enforceable,
    guard,
    lint,
    tracked_files,
    unadopted,
    unresolved,
    waived,
)

#: THE PIN, and it is the NAMED SET rather than a count. A count is blind to WHICH row moved, so a
#: registry that lost one rule and gained another would compare equal -- and the honest-looking
#: repair when a count disagrees is to edit the digit. This way a removal has to be typed here, as
#: the rule's own name, in the same commit as the removal.
_IDS = frozenset(
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

#: Non-vacuity floor, MEASURED 2026-09-15 when the registry landed. A floor rather than an
#: expectation: growth is expected and fine, a collapse to one row means the scan is not reading the
#: table any more and every assertion below would be green over nothing.
_FLOOR_RULES = 27


def test_the_registry_is_not_empty() -> None:
    assert len(RULES) >= _FLOOR_RULES, (
        f'the registry carries only {len(RULES)} rules, below the {_FLOOR_RULES} measured when it '
        f'landed. Every check in this file would pass vacuously over a table that stopped loading.'
    )


def test_the_id_set_is_pinned_by_name() -> None:
    """Removing a universal rule has to be typed here as its own name, never as a smaller number."""
    live = frozenset(rule.id for rule in RULES)
    assert live == _IDS, (
        f'rules that vanished from the registry: {sorted(_IDS - live)}; rules that appeared without '
        f'a pin: {sorted(live - _IDS)}. A removal is a decision -- the rules it covered are still '
        f'enforced by whoever adopted them -- so it is named here rather than absorbed by a count.'
    )


def test_no_id_is_used_twice() -> None:
    """An ID is a handle in every adopter's rules page, so a duplicate makes a citation ambiguous."""
    seen = [rule.id for rule in RULES]
    assert len(seen) == len(set(seen)), f'duplicate rule ids: {sorted({i for i in seen if seen.count(i) > 1})}'


def test_every_rule_states_a_constraint() -> None:
    for rule in RULES:
        assert rule.statement.strip(), f'{rule.id} states nothing, so nothing can be refused under it'
        assert rule.mechanisms, f'{rule.id} names no mechanism'


def test_a_rule_with_no_mechanism_cannot_be_constructed() -> None:
    """THE REFUSAL. Prose cannot enter the registry at all -- and the message says what to do."""
    with pytest.raises(UnenforceableRule, match='DECLARATION-LIES'):
        Rule(id='DECLARATION-LIES', statement='a declaration that lies is the dominant defect', mechanisms=())
    with pytest.raises(UnenforceableRule, match='mechanism'):
        Rule(id='NO-MECHANISM-AT-ALL', statement='something a reader would believe', mechanisms=())


def test_a_malformed_rule_is_refused_before_it_can_be_adopted() -> None:
    """The three shapes an ID must NOT take, each refused at construction."""
    for bad in ('declaration-lies', '2ABC', 'A B', ''):
        with pytest.raises(ValueError, match='UPPER-CASE slug'):
            Rule(id=bad, statement='x', mechanisms=(guard('tests/x.py'),))
    with pytest.raises(ValueError, match='states nothing'):
        Rule(id='OK', statement='   ', mechanisms=(guard('tests/x.py'),))


def test_a_mechanism_must_be_repo_relative() -> None:
    """A mechanism naming one box is not a mechanism the fleet has."""
    for bad in ('', '/abs/tests/x.py', r'tests\win.py', 'tests/../x.py'):
        with pytest.raises(ValueError):
            TestPath(bad)
    with pytest.raises(ValueError):
        LintRule('  ')
    assert guard('tests/a.py').path == 'tests/a.py'
    assert lint('PLC0415') == LintRule('PLC0415')


def test_the_check_fires_on_a_planted_dead_mechanism() -> None:
    """Both directions, over the REAL function: a vanished file and a dead lint rule are reported."""
    planted = (
        Rule(id='VANISHED', statement='x', mechanisms=(guard('tests/no_such_mechanism.py'),)),
        Rule(id='DEAD-LINT', statement='y', mechanisms=(lint('ZZZ999'),)),
        Rule(id='ALIVE', statement='z', mechanisms=(guard('tests/live.py'), lint('PLC0415'))),
    )
    problems = unresolved(planted, tracked={'tests/live.py'}, selected={'PLC0415'}, ignored=set())
    assert len(problems) == 2, f'expected exactly the two dead rows, got {problems}'
    assert 'VANISHED' in problems[0] and 'no_such_mechanism' in problems[0]
    assert 'DEAD-LINT' in problems[1] and 'ZZZ999' in problems[1]


def test_a_globally_ignored_lint_rule_is_reported_even_though_it_is_selected() -> None:
    """A waiver is the other way a lint mechanism stops refusing, and it is not the same as absence."""
    planted = (Rule(id='WAIVED', statement='x', mechanisms=(lint('PLC0415'),)),)
    problems = unresolved(planted, tracked=set(), selected={'PLC0415'}, ignored={'PLC0415'})
    assert len(problems) == 1 and 'IGNORED' in problems[0], problems
    assert not unresolved(planted, tracked=set(), selected={'PLC0415'}, ignored=set())


def test_a_tree_with_no_mechanisms_at_all_is_reported_rather_than_passed() -> None:
    """The empty-corpus direction: 'nothing is broken' and 'nothing was read' must not be the same."""
    problems = unresolved(RULES, tracked=set(), selected=set(), ignored=set())
    assert len(problems) >= _FLOOR_RULES, (
        f'an empty tree reported only {len(problems)} problems for {len(RULES)} rules -- the walk is '
        f'not reaching the mechanisms, which is how a dead registry reads green.'
    )


def _scratch_checkout(tmp_path: Path, lint_select: str) -> RepoProfile:
    """A real git tree with a real lint config, so the check runs against files that ARE tracked."""
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'ruff.toml').write_text(f'[lint]\nselect = ["{lint_select}"]\n', encoding='utf-8')
    subprocess.run(['git', '-C', str(tmp_path), 'init'], check=True, capture_output=True)
    return RepoProfile(app_name='scratch', package='scratch', root=tmp_path, lint_config='ruff.toml')


def test_a_missing_mechanism_reds_against_a_real_checkout_and_returns_green_when_restored(
    tmp_path: Path,
) -> None:
    """THE CONTROL THAT MATTERS: drive :func:`assert_enforceable` over a real tree, both ways.

    Everything above works on sets this file hands it. This one runs the whole path -- git tracking,
    the lint config on disk, the profile's root -- so a mechanism that is deleted from a real tree is
    a red that NAMES the rule, and restoring the file is the only edit that clears it.
    """
    profile = _scratch_checkout(tmp_path, 'PLC')
    planted = (Rule(id='NEEDS-A-TEST', statement='x', mechanisms=(guard('tests/test_the_guard.py'),)),)

    with pytest.raises(UnenforceableRule, match='NEEDS-A-TEST'):
        assert_enforceable(profile, planted)

    (tmp_path / 'tests' / 'test_the_guard.py').write_text('# the guard\n', encoding='utf-8')
    subprocess.run(['git', '-C', str(tmp_path), 'add', '-A'], check=True, capture_output=True)
    assert 'tests/test_the_guard.py' in tracked_files(tmp_path), 'the scratch tree must TRACK the mechanism'
    assert_enforceable(profile, planted)

    # And the lint half of the same path, both directions: `PLC` selects PLC0415, nothing selects
    # ZZZ999 -- and the refusal names the CODE, because "a lint rule is not in force" without one is
    # a refusal nobody can act on.
    assert_enforceable(profile, (Rule(id='LINT-ROW', statement='y', mechanisms=(lint('PLC0415'),)),))
    with pytest.raises(UnenforceableRule, match='ZZZ999'):
        assert_enforceable(profile, (Rule(id='LINT-ROW', statement='y', mechanisms=(lint('ZZZ999'),)),))


def test_the_declared_checkout_is_the_one_that_was_read(tmp_path: Path) -> None:
    """A profile with no usable tree must REFUSE rather than grade a directory that is not there."""
    absent = RepoProfile(app_name='scratch', package='scratch', root=tmp_path / 'nowhere')
    with pytest.raises(Exception, match='not a directory'):
        assert_enforceable(absent, (Rule(id='ANY', statement='x', mechanisms=(guard('tests/a.py'),)),))


# ---------------------------------------------------------------------------------------------
# The ADOPTION layer: the half a shared registry cannot hold.
#
# This section exists because of a measured defect in the first version of this module. A row then
# carried ONE mechanism tuple that every adopter was graded against, and all 70 mechanisms named
# motronics paths -- so lab-commons, the repo that AUTHORED the registry, refused its own registry
# with 70 failures. A rule's statement is universal; its mechanism is a file in one tree.
# ---------------------------------------------------------------------------------------------


def test_a_repo_that_neither_enforces_nor_declares_a_rule_is_told_which_rule() -> None:
    """THE REFUSAL THE SHARED REGISTRY WAS MISSING. Silence about a cited rule is the defect."""
    rules = (
        Rule(id='ONE', statement='x', mechanisms=(guard('tests/a.py'),)),
        Rule(id='TWO', statement='y', mechanisms=(guard('tests/b.py'),)),
    )
    adoption = Adoption(app_name='scratch', mechanisms={'ONE': (guard('tests/a.py'),)})
    assert unadopted(rules, adoption) == ('TWO',)

    # Both halves of the pair are legitimate, and they are DIFFERENT facts: one is a decision on
    # record, the other is a rule nobody has looked at yet.
    declared = Adoption(
        app_name='scratch',
        mechanisms={'ONE': (guard('tests/a.py'),)},
        declared_absent=frozenset({'TWO'}),
    )
    assert unadopted(rules, declared) == (), 'a declared-absent rule is on record, not a red'
    assert waived(rules, declared) == ('TWO',)


def test_a_rule_cannot_be_both_enforced_and_declared_absent() -> None:
    """The stale half, refused at construction -- it is what would let a waiver read as enforced."""
    with pytest.raises(ValueError, match='both enforces and declares absent'):
        Adoption(
            app_name='scratch',
            mechanisms={'ONE': (guard('tests/a.py'),)},
            declared_absent=frozenset({'ONE'}),
        )


def test_an_adopted_rule_with_no_mechanism_is_refused_at_adoption() -> None:
    """The Rule refusal, one repo further out: claiming a rule enforced with nothing refusing it."""
    with pytest.raises(UnenforceableRule, match='ABSENT instead'):
        Adoption(app_name='scratch', mechanisms={'ONE': ()})


def test_an_id_the_registry_does_not_define_is_refused(tmp_path: Path) -> None:
    """A typo adopts nothing and says so nowhere, which is how a rule quietly stops being checked."""
    with pytest.raises(ValueError, match='not a rule ID'):
        Adoption(app_name='scratch', mechanisms={'one': (guard('tests/a.py'),)})

    rule = Rule(id='ONE', statement='x', mechanisms=(guard('tests/a.py'),))
    stranger = Adoption(app_name='scratch', declared_absent=frozenset({'NOPE'}))
    with pytest.raises(UnenforceableRule, match='does not define'):
        assert_adopted(_scratch_checkout(tmp_path, 'PLC'), stranger, (rule,))


def test_the_adoption_path_runs_over_a_real_tree_in_both_directions(tmp_path: Path) -> None:
    """THE CONTROL THAT MATTERS, at the level a real adopter uses.

    Everything else in this section works on sets this file hands it. This one drives
    :func:`assert_adopted` end to end -- git tracking, the lint config on disk, a second repo's
    mechanisms replacing the authoring repo's -- so the claim "a second adopter can supply the
    mechanism for its own tree" is a measurement rather than a promise.
    """
    profile = _scratch_checkout(tmp_path, 'PLC')
    # A SHARED row: its mechanisms are the AUTHORING repo's paths, none of which exist here.
    shared = (Rule(id='SHARED', statement='x', mechanisms=(guard('motronics/only/test.py'),)),)

    with pytest.raises(UnenforceableRule, match='neither enforces nor declares absent'):
        assert_adopted(profile, Adoption(app_name='scratch'), shared)

    # Declaring it absent is on record and passes -- and the authoring repo's path is NEVER consulted.
    assert_adopted(profile, Adoption(app_name='scratch', declared_absent=frozenset({'SHARED'})), shared)

    # Supplying THIS repo's mechanism is what makes it enforced, and then it must genuinely be live.
    (tmp_path / 'tests' / 'test_the_guard.py').write_text('# the guard\n', encoding='utf-8')
    subprocess.run(['git', '-C', str(tmp_path), 'add', '-A'], check=True, capture_output=True)
    live = Adoption(app_name='scratch', mechanisms={'SHARED': (guard('tests/test_the_guard.py'),)})
    assert_adopted(profile, live, shared)

    # And deleting that mechanism from the real tree brings the red back, naming the rule.
    (tmp_path / 'tests' / 'test_the_guard.py').unlink()
    subprocess.run(['git', '-C', str(tmp_path), 'add', '-A'], check=True, capture_output=True)
    with pytest.raises(UnenforceableRule, match='SHARED'):
        assert_adopted(profile, live, shared)
