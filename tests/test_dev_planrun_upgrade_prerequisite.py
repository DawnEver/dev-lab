"""PREFLIGHT KNOWS AN UPGRADE IS A PREREQUISITE: a step after ``ops upgrade`` is checked once the upgrade ran.

Measured 2026-11-22: a plan ``ops upgrade --sha S`` then ``forge protect apply`` read BLOCKED on the second step --
the host's INSTALLED dev-lab could not derive the subject the upgraded one derives -- so the plan that fixes the host
could never be offered. Only ``ops.config`` was known as a step later ones may wait on. Which actions change what
their host derives is the registry's ``rederives`` (:mod:`dev_lab.ops.consent.actions`), read here, not a second name.

PLANTED CONTROL: the same second step with no upgrade before it is still BLOCKED.
"""

from __future__ import annotations

from _protect_fakes import GITEA_TEXT
from test_dev_planrun import CONF, HOST, PY, FakeHost, secret_here

from dev_lab.dev import planrunpreflight, planrunsteps
from dev_lab.ops import forgeprotection
from dev_lab.ops.consent.actions import ACTIONS
from dev_lab.ops.consent.plan import parsed

__all__ = ['secret_here']

SHA = 'c' * 40
WANT = forgeprotection.local_subject('owner/alpha', 'integrate/main', 'gitea.example', lambda _ref: GITEA_TEXT)
UPGRADE = {'host': HOST, 'action': 'ops.upgrade', 'subject': SHA}
PROTECT = {'host': HOST, 'action': forgeprotection.ACTION, 'subject': WANT}
UPGRADE_STEP = planrunsteps.Step(('upgrade', '--sha', SHA), HOST, CONF, PY)
PROTECT_STEP = planrunsteps.Step(
    ('forge', 'protect', 'apply', '--repo', 'owner/alpha'), HOST, CONF, PY, forge='gitea.example'
)
READERS = planrunpreflight.Readers(declared=lambda *_: GITEA_TEXT)


def _old_host() -> FakeHost:
    """A host whose installed dev-lab cannot derive the protect subject; every sudo door is there."""
    host = FakeHost()
    host.doors |= {('upgrade', '--sha'), ('forge', 'protect')}
    host.subjects['upgrade'] = SHA
    host.refusals['forge'] = 'refused: owner/alpha: no family layer on this machine'
    return host


def test_the_registry_declares_which_actions_change_what_a_host_derives() -> None:
    assert {name for name, row in ACTIONS.items() if row.rederives} == {'ops.config', 'ops.upgrade'}


def test_a_step_after_an_upgrade_is_deferred_and_listed_unchecked_never_blocked() -> None:
    plan = parsed({'hosts': [HOST], 'grants': [UPGRADE, PROTECT]})
    steps = planrunsteps.Steps((UPGRADE_STEP, PROTECT_STEP))
    green, lines = planrunpreflight.preflight(plan, steps, lambda _dest: _old_host(), readers=READERS)
    assert green, lines
    assert lines[2].startswith(f'step 2 {forgeprotection.ACTION}: after step 1 (subject derived once step 1 applied)')
    assert 'green, but 1 step(s) are unchecked' in lines[-1]
    assert 'as it stands the host cannot derive it: refused: owner/alpha: no family layer' in lines[-1]


def test_the_same_step_with_no_upgrade_before_it_is_blocked() -> None:
    """The PLANTED control: nothing in the plan changes the host, so what it answers now is what the run meets."""
    plan = parsed({'hosts': [HOST], 'grants': [PROTECT]})
    green, lines = planrunpreflight.preflight(
        plan, planrunsteps.Steps((PROTECT_STEP,)), lambda _dest: _old_host(), readers=READERS
    )
    assert not green
    assert 'BLOCKED -- the host could not derive the subject' in lines[1]


def test_a_subject_derived_here_that_differs_is_blocked_even_after_an_upgrade() -> None:
    """The upgrade defers only what the HOST answers: a subject this machine derives differently still blocks."""
    plan = parsed({'hosts': [HOST], 'grants': [UPGRADE, PROTECT | {'subject': 'd' * 64}]})
    steps = planrunsteps.Steps((UPGRADE_STEP, PROTECT_STEP))
    green, lines = planrunpreflight.preflight(plan, steps, lambda _dest: _old_host(), readers=READERS)
    assert not green
    assert 'derived here' in lines[2]


def test_a_door_missing_until_the_upgrade_names_the_upgrade_step() -> None:
    plan = parsed({'hosts': [HOST], 'grants': [UPGRADE, PROTECT]})
    steps = planrunsteps.Steps((UPGRADE_STEP, PROTECT_STEP))
    host = _old_host()
    host.doors.discard(('forge', 'protect'))
    green, lines = planrunpreflight.preflight(plan, steps, lambda _dest: host, readers=READERS)
    assert green, lines
    assert 'its door after step 1 (installed by that ops.upgrade)' in lines[2]
