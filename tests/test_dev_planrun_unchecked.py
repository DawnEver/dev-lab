"""A GREEN PREFLIGHT SAYS WHAT IT DID NOT CHECK, and a refusal the host can name with no code blocks before the code.

Incident 2026-11-22: ``planrun preflight`` printed ``preflight: green (ask the user for the code)`` while its only
host was UNREACHABLE; the run then stopped on ``already holds a token named host-x; --rotate deletes it and mints
anew`` -- a refusal a reachable preflight would have shown -- and the user's code was spent. Two repairs, both here:

* the last line tells ``green, every door checked`` from ``green, but N step(s) are unchecked: <what>``, and says the
  code buys the hold first and those steps are checked at run;
* a step whose host would refuse it AS IT STANDS (the read form's :data:`~dev_lab.ops.consent.actions.STANDING`
  line, read through the issuer with no code, or asked of a reached host) is BLOCKED -- unless an earlier step of
  the plan on that host may clear it, which is then named as unchecked.

PLANTED controls: the same plan with no standing refusal is green; a fully reached host reads ``every door
checked``; a run's refusal says whether the grant was spent in BOTH directions.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from test_dev_planrun import PLAN, STEPS, FakeHost, _granted, _run, secret_here
from test_dev_planrun_subject_read import CONF, HOST, PY, UPGRADE, Unreached, Wire, _plan, _readers, issuer

from dev_lab.dev import planrunpreflight, planrunsteps
from dev_lab.ops.consent.actions import STANDING
from dev_lab.ops.consent.issuer import Issuer
from dev_lab.ops.consent.plan import Plan, parsed

__all__ = ['issuer', 'secret_here']

SUBJECT = 'd' * 64
HELD = 'dev-login already holds a token named host-x; --rotate deletes it and mints anew'
MINT = planrunsteps.Step(
    ('forge', 'token', 'mint', '--login', 'dev-login', '--name', 'host-x', '--scope', 'read:repository'), HOST, CONF, PY
)
REVOKE = planrunsteps.Step(('forge', 'token', 'revoke', '--login', 'dev-login', '--name', 'host-x'), HOST, CONF, PY)


def _mint_plan(*, revoke_first: bool = False) -> tuple[Plan, planrunsteps.Steps]:
    grants = [{'host': HOST, 'action': 'ops.forge.token', 'subject': SUBJECT}]
    if revoke_first:
        grants.insert(0, {'host': HOST, 'action': 'ops.forge.revoke', 'subject': SUBJECT})
    steps = (REVOKE, MINT) if revoke_first else (MINT,)
    return parsed({'hosts': [HOST], 'grants': grants}), planrunsteps.Steps(steps)


def test_a_fully_reached_plan_reads_every_door_checked() -> None:
    """PLANTED: the plain green still exists -- every host answered, every door and subject was asked."""
    green, lines = planrunpreflight.preflight(PLAN, STEPS, lambda _dest: FakeHost())
    assert green, lines
    assert lines[-1].startswith('preflight: green, every door checked')
    assert 'unchecked' not in lines[-1]


def test_a_green_plan_on_an_unreached_host_names_each_unchecked_step(issuer: Issuer) -> None:
    green, lines = planrunpreflight.preflight(
        _plan(), planrunsteps.Steps((UPGRADE,)), lambda _d: Unreached(), readers=_readers(Wire(issuer))
    )
    assert green, lines
    last = lines[-1]
    assert last.startswith('preflight: green, but 1 step(s) are unchecked: ')
    assert f'step 1 ops.upgrade on {HOST} (unreached: ' in last
    assert 'its sudo door' in last
    assert 'the code buys the hold first' in last
    assert 'checked at run' in last
    assert 'every door checked' not in last


def test_a_door_that_waits_on_an_earlier_config_apply_is_unchecked_too() -> None:
    host = FakeHost()
    host.doors = {('config', 'apply')}  # the secret door is installed by step 1's apply
    green, lines = planrunpreflight.preflight(PLAN, STEPS, lambda _dest: host)
    assert green, lines
    assert lines[-1].startswith('preflight: green, but 1 step(s) are unchecked: step 2 ops.secret.place')
    assert 'step 1' in lines[-1]


def test_a_held_token_name_read_through_the_issuer_blocks_before_any_code(issuer: Issuer) -> None:
    """The incident: the host is unreached, yet its refusal is read with no code and the plan is NOT green."""
    plan, steps = _mint_plan()
    wire = Wire(issuer, f'{STANDING}{HELD}\n{SUBJECT}')
    green, lines = planrunpreflight.preflight(plan, steps, lambda _d: Unreached(), readers=_readers(wire))
    assert not green
    assert any(f'BLOCKED -- its host would refuse it as it stands ({HELD})' in line for line in lines), lines
    assert lines[-1].startswith('preflight: BLOCKED')
    assert not any('code' in request for request in wire.sent)


def test_the_same_mint_on_a_forge_that_admits_it_is_green_but_unchecked(issuer: Issuer) -> None:
    """PLANTED: no standing line, so the plan is offered -- and still says its host was not reached."""
    plan, steps = _mint_plan()
    green, lines = planrunpreflight.preflight(
        plan, steps, lambda _d: Unreached(), readers=_readers(Wire(issuer, SUBJECT))
    )
    assert green, lines
    assert lines[-1].startswith('preflight: green, but 1 step(s) are unchecked: step 1 ops.forge.token')


def test_a_standing_refusal_an_earlier_step_may_clear_is_unchecked_not_blocked() -> None:
    """A plan that revokes host-x and then mints it is valid: the mint's refusal is the revoke's to clear, at run."""
    plan, steps = _mint_plan(revoke_first=True)
    readers = planrunpreflight.Readers(
        issued=lambda _dest, action, _argv: (SUBJECT, HELD if action == 'ops.forge.token' else None)
    )
    green, lines = planrunpreflight.preflight(plan, steps, lambda _d: Unreached(), readers=readers)
    assert green, lines
    assert 'but 2 step(s) are unchecked' in lines[-1]
    assert f'whether step 1 clears "{HELD}"' in lines[-1]


def test_a_reached_host_that_would_refuse_the_step_as_it_stands_is_blocked() -> None:
    plan, steps = _mint_plan()
    host = FakeHost()
    host.doors = {('forge', 'token')}
    host.subjects = {'forge': f'{STANDING}{HELD}\n{SUBJECT}'}
    green, lines = planrunpreflight.preflight(plan, steps, lambda _dest: host)
    assert not green
    assert any(f'would refuse it as it stands ({HELD})' in line for line in lines), lines
    host.subjects = {'forge': SUBJECT}  # PLANTED: the same host with the name free is green, every door checked
    green, lines = planrunpreflight.preflight(plan, steps, lambda _dest: host)
    assert green, lines
    assert lines[-1].startswith('preflight: green, every door checked')


@pytest.mark.parametrize(
    ('registers', 'said'),
    [
        (False, 'the grant is NOT spent'),
        (True, 'the grant IS spent'),
    ],
)
def test_a_refused_step_says_whether_the_grant_was_spent(tmp_path: Path, *, registers: bool, said: str) -> None:
    """Both directions: a refusal before the redeem keeps the code's grant, one after it has spent it."""
    host = FakeHost()
    _granted(tmp_path)
    host.outcomes['config'] = ('refused: the host says no', 2, registers)
    finished, lines = _run(host, tmp_path)
    assert not finished
    assert 'STOPPED -- refused (exit 2)' in lines[-1]
    assert said in lines[-1]
    assert 'a re-authored plan is a new digest' in lines[-1]
    other = 'the grant is NOT spent' if registers else 'the grant IS spent'
    assert other not in lines[-1]
