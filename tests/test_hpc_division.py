"""THE HPC DIVISION IS DATA on the workstation (user rulings 2026-11-09): each grant's role and the role table.

Placeholder names only: dev-lab is public and ships generic mechanism.
"""

from __future__ import annotations

from typing import Any

import pytest
from lab_commons.hpc.grants import Grant, Machine

from dev_lab.dev.hpcaccount.division import DEFAULT_ROLES, account_role, division_of, load_division

_GRANT = {'hosts': ['login01.example'], 'slurm_account': 'acct'}


def _hpc(**extra: object) -> dict[str, Any]:
    grants = [{**_GRANT, 'user': 'acct-a', 'role': 'verification'}, {**_GRANT, 'user': 'acct-b', 'role': 'research'}]
    return {'grant': grants, **extra}


def test_no_role_table_ships_the_two_defaults() -> None:
    division = load_division(_hpc())
    assert division.roles == DEFAULT_ROLES
    assert DEFAULT_ROLES['verification'] == {'serves': True, 'read_only': False}
    assert DEFAULT_ROLES['research'] == {'serves': False, 'read_only': True}
    assert division.role_of('acct-b') == 'research'


def test_a_declared_role_table_replaces_the_defaults_whole() -> None:
    """PLANTED CONTROL: a role the table names passes; one it no longer names is refused."""
    division = load_division(_hpc(roles={'research': {'serves': False, 'read_only': True, 'reader': 'ro-login'}}))
    assert set(division.roles) == {'research'}
    assert division.refusal('acct-b') is None
    why = division.refusal('acct-a')
    assert why is not None
    assert 'verification' in why


def test_an_undeclared_grant_role_is_undeclared_not_refused() -> None:
    hpc = _hpc()
    del hpc['grant'][0]['role']
    assert load_division(hpc).role_of('acct-a') == ''
    assert load_division(hpc).refusal('acct-a') is None


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
        load_division(_hpc(roles={'research': {'serves': False, 'colour': 'red'}}))


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
