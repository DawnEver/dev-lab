"""THE HPC DIVISION IS DATA on the workstation (user rulings 2026-11-09): each grant's role and the role table.

Placeholder names only: dev-lab is public and ships generic mechanism.
"""

from __future__ import annotations

from typing import Any

import pytest
from lab_commons.hpc.grants import Grant, Machine

from dev_lab.dev.hpcaccount import division
from dev_lab.dev.hpcaccount.division import DEFAULT_ROLES, Division, account_role, division_of

_GRANT = {'hosts': ['login01.example'], 'slurm_account': 'acct'}


def _hpc(**extra: object) -> dict[str, Any]:
    grants = [{**_GRANT, 'user': 'acct-a', 'role': 'verification'}, {**_GRANT, 'user': 'acct-b', 'role': 'research'}]
    return {'grant': grants, **extra}


def _division(hpc: dict[str, Any]) -> Division:
    """The division of a machine reaching *hpc*'s grants, through the one reader (:func:`division_of`)."""
    grants = tuple(
        Grant(user=g['user'], hosts=('login01.example',), slurm_account='acct', qos='', role=g.get('role', ''))
        for g in hpc.get('grant', [])
    )
    return division_of(Machine(session=None, grants=grants, roles=hpc.get('roles') or {}))


def test_no_role_table_ships_the_two_defaults() -> None:
    division = _division(_hpc())
    assert division.roles == DEFAULT_ROLES
    assert DEFAULT_ROLES['verification'] == {'serves': True, 'read_only': False}
    assert DEFAULT_ROLES['research'] == {'serves': False, 'read_only': True}
    assert division.role_of('acct-b') == 'research'


def test_a_declared_role_table_replaces_the_defaults_whole() -> None:
    """PLANTED CONTROL: a role the table names passes; one it no longer names is refused."""
    division = _division(_hpc(roles={'research': {'serves': False, 'read_only': True, 'reader': 'ro-login'}}))
    assert set(division.roles) == {'research'}
    assert division.refusal('acct-b') is None
    why = division.refusal('acct-a')
    assert why is not None
    assert 'verification' in why


def test_an_undeclared_grant_role_is_undeclared_not_refused() -> None:
    hpc = _hpc()
    del hpc['grant'][0]['role']
    assert _division(hpc).role_of('acct-a') == ''
    assert _division(hpc).refusal('acct-a') is None


def test_the_division_is_read_off_the_grants_the_machine_reaches() -> None:
    """lab-commons carries each grant's role and the role table; PLANTED CONTROL: no table ships the defaults."""
    grants = (Grant(user='acct-b', hosts=('login01.example',), slurm_account='acct', role='research'),)
    roles = {'research': {'serves': False, 'read_only': True}}
    division = division_of(Machine(session=None, grants=grants, roles=roles))
    assert division.role_of('acct-b') == 'research'
    assert division.role_of('acct-a') == ''
    assert dict(division.roles) == roles
    assert division_of(Machine(session=None, grants=grants)).roles == DEFAULT_ROLES


def test_an_unknown_role_key_is_refused() -> None:
    with pytest.raises(ValueError, match='roles'):
        _division(_hpc(roles={'research': {'serves': False, 'color': 'red'}}))


def test_the_account_role_must_equal_the_workstations() -> None:
    """The workstation is the source. PLANTED CONTROL: the equal role passes with what was passed."""
    passed = {'serves': False, 'read_only': True}
    assert account_role('research', 'research', passed) == passed
    why = account_role('verification', 'research', passed)
    assert isinstance(why, str)
    assert "'verification'" in why
    assert "'research'" in why


def test_a_hand_run_deploy_falls_back_to_the_defaults_and_refuses_another_name() -> None:
    assert account_role('research', '', None) == DEFAULT_ROLES['research']
    assert isinstance(account_role('batch', '', None), str)


def _session_machine() -> Machine:
    research = Grant(user='r', hosts=('login.ada',), slurm_account='a', role='research', cluster_name='ada')
    verify = Grant(user='v', hosts=('login.ada',), slurm_account='a', role='verification', cluster_name='ada')
    return Machine(session=None, grants=(research, verify), reach=frozenset({'research', 'verification'}))


def test_the_integrator_role_needs_a_declared_reach_of_its_accounts_cluster() -> None:
    """User ruling 2026-11-27: undeclared is refused naming the key; declared (direct or vpn) passes."""
    machine = _session_machine()
    why = division.session_reach_refusal(machine, {'reach': ['research']})
    assert why is not None
    assert "['ada']" in why
    assert '[dev] hpc_reach = { ada = "direct" | "vpn" }' in why
    for by in ('direct', 'vpn'):
        assert (
            division.session_reach_refusal(machine, {'reach': ['research'], 'cluster_reach': {'ada': {'reach': by}}})
            is None
        )


def test_a_machine_using_only_its_own_roles_needs_no_declared_reach() -> None:
    """PLANTED CONTROL: the refusal is the session role's, never every machine's."""
    machine = _session_machine()
    assert division.session_reach_refusal(machine, {'reach': ['research', 'verification']}) is None
    assert division.session_reach_refusal(machine, {'reach': ['research']}, accounts=('r',)) is None
