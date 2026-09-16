"""lab-commons ADOPTS the shared deny registry -- the repo that AUTHORS it, held to it.

WHY THIS FILE MATTERS MORE THAN IT LOOKS. The registry was authored here, and the authoring repo is
the one with the least reason to notice that its rows lean on another repo's tree. The rules
registry learned that the hard way: driven against its own checkout it refused itself with 70
failures, all of them motronics paths. So the deny half is driven against THIS tree from the day it
lands, with remedies that resolve here and NOTHING borrowed from the repo the rules came from.

WHAT THIS REPO CAN HONESTLY SHIP TODAY, and the asymmetry is the point rather than an embarrassment:

* the verdict entry point EXISTS here -- it is this package's own ``python -m lab_commons.dev.verify``
  -- so the two rules that route to it (a hand-written test line, a ``--no-verify`` push) ship;
* the retry wrapper and the process-tree killer DO NOT exist here. Those two rules are declared
  ABSENT and are NOT RENDERED, because a deny rule whose exit does not exist in the repo reading it
  leaves an agent with disobey or stop, and the first is what actually happens;
* the three rules that need nothing from a repo (a stash, a force-push, an unnamed worktree base)
  ship unconditionally: their exit is git's own vocabulary, which every checkout already has.

WHAT THIS FILE DOES NOT CLAIM. It does not claim the hook is WIRED here -- no `.claude/settings.json`
in this repo points at an engine, and that is why ``AGENT-GUARD`` remains declared absent in
`tests/test_the_adoption_accounts_for_every_rule.py`. Rendering the rules a repo may ship and
INSTALLING them are two changes, and a test that conflated them would read as protection while
refusing nothing -- which is the defect this whole registry exists to remove.
"""

from __future__ import annotations

import json

import pytest
from _arch_corpus import ROOT

from lab_commons.dev.hook_adoption import (
    HookAdoption,
    assert_shippable,
    deny_rules,
    needing,
    remedy_gaps,
    render,
    unremedied,
    waived,
)
from lab_commons.dev.hooks import DENY_RULES, Remedy, UnremediedRule, denies
from lab_commons.dev.rules import tracked_files

#: THIS repo's exit from a hand-written test line, and it is the reason the shared rule is shippable
#: here at all: the portable verdict entry point lives in this very package. ``path`` names the file
#: that implements it, so "the remedy exists" is resolved against git rather than asserted.
_VERIFY = Remedy(
    kind='verdict-entry-point',
    command='python -m lab_commons.dev.verify',
    allow=r'\blab_commons\.dev\.verify\b',
    path='src/lab_commons/dev/verify.py',
)

#: Rules this repo supplies an exit for, by ID.
_REMEDIES = {'BARE-TEST-INVOCATION': _VERIFY, 'PUSH-NO-VERIFY': _VERIFY}

#: Rules this repo may NOT ship, with the reason. A mapping rather than a bare set: an exemption
#: with no recorded reason is indistinguishable from a hole somebody widened during a red suite.
_ABSENT_REASONS = {
    'GIT-NETWORK-VERB': (
        'no retry wrapper in this tree, so the rule would refuse every push and name a script that '
        'does not exist -- the sealed road the remedy field exists to prevent'
    ),
    'RAW-PROCESS-KILL': (
        'no process-tree killer here: this suite runs in ~18s on one worker, so there is no orphaned '
        'subtree to reap and nothing to route a kill to'
    ),
}

_ABSENT = frozenset(_ABSENT_REASONS)

#: The ceiling on the escape hatch, MEASURED 2026-09-16. It may only go DOWN: building one of the two
#: remedies deletes a name above AND lowers this number in the same edit.
_ABSENT_CEILING = 2

_ADOPTION = HookAdoption(app_name='lab-commons', remedies=_REMEDIES, declared_absent=_ABSENT)


def test_the_adoption_accounts_for_every_rule_that_needs_this_repo() -> None:
    """THE CHECK, against the REAL tracked file list of this checkout."""
    assert_shippable(_ADOPTION, tracked_files(ROOT))


def test_the_two_sets_account_for_the_needing_rules_exactly() -> None:
    """A new rule that needs a repo artefact must be typed into one of the sets, or this reds."""
    accounted = set(_REMEDIES) | _ABSENT
    assert accounted == needing(DENY_RULES), (
        f'deny rules neither remedied nor declared absent here: {sorted(needing(DENY_RULES) - accounted)}; '
        f'names that need nothing or are not rules: {sorted(accounted - needing(DENY_RULES))}. Whether this '
        f'repo can honestly ship a rule is a decision it has to make, not a line that appears in a list.'
    )


def test_the_absent_set_may_only_shrink() -> None:
    """The ceiling: closing a gap lowers the number in the same edit that deletes the name."""
    assert len(_ABSENT) <= _ABSENT_CEILING, (
        f'{len(_ABSENT)} deny rules are declared absent, above the {_ABSENT_CEILING} ceiling. An escape hatch '
        f'needs a CEILING rather than a reason.'
    )
    silent = sorted(name for name, why in _ABSENT_REASONS.items() if not why.strip())
    assert silent == [], f'declared absent with no reason recorded: {silent}'
    assert set(waived(DENY_RULES, _ADOPTION)) == _ABSENT
    assert unremedied(DENY_RULES, _ADOPTION) == (), 'the check above would already red; keep the two in step'


def test_the_unremedied_rules_are_not_rendered_at_all() -> None:
    """The design, measured on this repo: a rule with no exit here is DROPPED, not softened."""
    shipped = {row['name'] for row in deny_rules(_ADOPTION)}
    assert shipped & _ABSENT == set(), f'rules with no exit in this tree were shipped anyway: {shipped & _ABSENT}'
    assert set(_REMEDIES) <= shipped, 'a remedied rule must ship'
    unconditional = {rule.id for rule in DENY_RULES if rule.needs is None}
    assert unconditional <= shipped, 'a rule that needs nothing from a repo ships everywhere'
    assert shipped == unconditional | set(_REMEDIES)


def test_every_shipped_reason_names_an_exit_that_exists_here() -> None:
    """A refusal is only obeyed if the road it leaves open is one this repo actually has."""
    for row in deny_rules(_ADOPTION):
        assert row['reason'].strip(), f'{row["name"]} ships an empty reason'
        remedy = _REMEDIES.get(row['name'])
        if remedy is not None:
            assert remedy.command in row['reason'], f'{row["name"]} does not name this repo command'
    assert denies(DENY_RULES, _VERIFY.command, _REMEDIES) is None, (
        'the verify command this repo routes a refused test line to is itself refused by the registry -- '
        'that is the sealed road reached by a different street'
    )


def test_the_rendered_file_is_the_engine_s_own_schema() -> None:
    """What is written is what the JS engine reads: no translation layer between the halves."""
    rows = json.loads(render(_ADOPTION))
    assert rows, 'the render read empty -- an unread registry is not a shipped one'
    assert render(_ADOPTION).endswith('\n')
    for row in rows:
        assert set(row) <= {'name', 'pattern', 'matches', 'allow', 'reason'}, f'unknown key in {row["name"]}'
        assert {'name', 'pattern', 'matches', 'reason'} <= set(row)


def test_a_planted_missing_remedy_is_refused() -> None:
    """THE PLANTED CONTROL, through the REAL checker: a remedy naming a file no tree tracks."""
    planted = HookAdoption(
        app_name='planted',
        remedies={'BARE-TEST-INVOCATION': Remedy('verdict-entry-point', 'run it', path='scripts/gone.py')},
        declared_absent=_ABSENT | {'PUSH-NO-VERIFY'},
    )
    assert remedy_gaps(planted, ('src/other.py',)) == (
        'BARE-TEST-INVOCATION: the verdict-entry-point remedy runs scripts/gone.py, which is not a tracked file',
    )
    with pytest.raises(UnremediedRule, match='do not exist in its tree'):
        assert_shippable(planted, ('src/other.py',))
    assert remedy_gaps(planted, ('scripts/gone.py',)) == (), 'the same adoption passes once the file is there'


def test_a_planted_silent_gap_and_a_planted_stranger_are_refused() -> None:
    """The other two refusals: a rule nobody answered for, and an ID that remedies nothing."""
    with pytest.raises(UnremediedRule, match='neither remedies nor declares absent'):
        assert_shippable(HookAdoption(app_name='planted'), ())
    stranger = HookAdoption(app_name='planted', remedies=_REMEDIES, declared_absent=_ABSENT | {'NO-SUCH-RULE'})
    with pytest.raises(UnremediedRule, match='which the deny registry does not define'):
        assert_shippable(stranger, tracked_files(ROOT))


def test_a_planted_pointless_waiver_is_refused() -> None:
    """A waiver of a rule that ships anyway reads as a decision and is not one."""
    unconditional = next(rule.id for rule in DENY_RULES if rule.needs is None)
    pointless = HookAdoption(app_name='planted', remedies=_REMEDIES, declared_absent=_ABSENT | {unconditional})
    with pytest.raises(UnremediedRule, match='ship anyway'):
        assert_shippable(pointless, tracked_files(ROOT))


def test_a_rule_cannot_be_both_shipped_and_waived() -> None:
    """The contradiction is refused at construction, where a stale half cannot sit unread."""
    with pytest.raises(ValueError, match='One of the two is stale'):
        HookAdoption(app_name='planted', remedies=_REMEDIES, declared_absent=frozenset({'BARE-TEST-INVOCATION'}))
