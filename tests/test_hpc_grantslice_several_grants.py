"""An account holding SEVERAL grants of one cluster and user is one account: its rows resolve together.

MEASURED 2026-11-22 on a research account holding two grants (two ``slurm_account`` rows, one cluster, one user):
``deploy-fleet`` refused "the family file ... declares no [[hpc.grant]] of <user> for <cluster>-<user>", because
``own_grant`` resolved nothing unless exactly one row matched. PLANTED CONTROLS: rows of DIFFERENT accounts with
no host still resolve nothing; another account's rows are never the named account's; and a row whose
``slurm_account`` is no association of the user still refuses the deploy -- every row is confirmed, not the first.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from lab_commons.config import FAMILY_TABLE

from dev_lab.dev.devdeclared import OWN_TABLE
from dev_lab.dev.hpcaccount import account
from dev_lab.dev.hpcaccount.grantslice import granted_root, own_grant, own_grants
from dev_lab.dev.hpcaccount.steps import Step, Tools


def _row(cluster: str, user: str, slurm_account: str) -> dict[str, str]:
    return {'cluster': cluster, 'user': user, 'slurm_account': slurm_account, 'role': 'research'}


TWO = [_row('c1', 'alice', 'a'), _row('c1', 'alice', 'b')]
HPC: dict[str, Any] = {
    'grant': [*TWO, _row('c1', 'bob', 'a'), _row('c2', 'alice', 'a')],
    'clusters': {'c1': {'root': '/shared/{user}/lab'}, 'c2': {'root': '/other/{user}/lab'}},
}


def test_several_rows_of_one_cluster_and_user_are_one_account() -> None:
    assert own_grants(HPC, 'c1-alice') == TWO
    assert own_grant(HPC, 'c1-alice') == TWO[0]
    assert granted_root(HPC, 'c1-alice') == '/shared/alice/lab', 'the same cluster is the same root'
    alone = {'grant': TWO, 'clusters': HPC['clusters']}
    assert own_grants(alone) == TWO, "a slice holding one account's rows alone needs no host"
    assert granted_root(alone) == '/shared/alice/lab'


def test_rows_of_different_accounts_still_resolve_nothing_without_a_host() -> None:
    assert own_grants(HPC) == []
    assert own_grant(HPC) is None
    assert granted_root(HPC) == ''
    assert own_grants(HPC, 'c1-bob') == [_row('c1', 'bob', 'a')], "another account's rows are never taken"
    assert own_grants(HPC, 'c3-alice') == []


def _deploy_grant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, associations: str) -> int:
    """The deploy's grant confirmation of ``c1-alice`` over :data:`HPC`, ``sacctmgr`` answering *associations*."""
    monkeypatch.setattr(account, 'machine_table', lambda _path: {'hpc': HPC})
    monkeypatch.setattr(account, 'grant_refusal', lambda _path: '')
    tools = replace(Tools(), sacctmgr=(sys.executable, '-c', f'print({associations!r})'))
    live = {FAMILY_TABLE: {'source': 'family'}, OWN_TABLE: {'host': 'c1-alice'}}
    return account._family_grant(Step(tools, dry=False), tmp_path / 'machine.toml', live, 'alice')


def test_the_deploy_confirms_an_account_holding_two_grants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _deploy_grant(tmp_path, monkeypatch, 'a|cpu=96\nb|cpu=8') == 0
    assert 'holds the grant (alice, a, b)' in capsys.readouterr().out


def test_every_row_is_confirmed_against_the_users_associations_not_the_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _deploy_grant(tmp_path, monkeypatch, 'a|cpu=96') == 2
    assert "the declared slurm_account 'b' is not one of alice's" in capsys.readouterr().err
