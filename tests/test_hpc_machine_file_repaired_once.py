"""A deployed machine file declaring ``[hpc]`` twice heals at the deploy door, once, with a backup.

Measured 2026-11-22 on four research accounts: an older kit's grant phase APPENDED the account's ``[hpc]`` slice
below the rendered one, so every read of the file raised "Cannot declare ('hpc',) twice". ``deploy-fleet``'s render
step read the previous file to keep its local tables, crashed on it, and the deploy after it never ran: the account
could not heal. FORMATS-MIGRATE-ONCE: every reader keeps the current shape and refuses the old one BY NAME with its
door (the redeploy); the render -- that door's own first write -- repairs it once, the previous file backed up.

The steps driven here are the ones :func:`dev_lab.dev.hpcaccount.fleet.deploy_command` names for a RESEARCH
account, run in its order with the real render; the deploy after them reads the healed file.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Final

import pytest
from _hpcaccount_fakes import FAMILY, HOST, clone_of, fleet_source, tools_of
from lab_commons.config import CONFIG_ENV
from lab_commons.hpc.grants import Grant

from dev_lab.dev import devhost, storage
from dev_lab.dev.hpcaccount import drift
from dev_lab.dev.hpcaccount.fleet import Target, deploy_command, grant_slice
from dev_lab.dev.hpcaccount.grantslice import REDEPLOY_DOOR, Unreadable, machine_table, read_machine, render_grant
from dev_lab.dev.hpcaccount.spec import load

#: The fake account as a RESEARCH account (it never serves tests), and its grant as deploy-fleet holds it.
RESEARCH: Final = FAMILY.replace('"verification"', '"research"')
ALICE: Final = Grant(user='alice', hosts=('login01',), slurm_account='a', role='research', cluster_name='c1')
LOCAL: Final = '\n[user]\nshell = "zsh"\n'
BARE: Final = "Cannot declare ('hpc',) twice"


def _account(tmp_path: Path, tail: str) -> tuple[Path, Path, Path, str]:
    """The research account's clone, machine file and backups; the file is its render, a local table, then *tail*."""
    assert RESEARCH != FAMILY
    clone = clone_of(tmp_path, RESEARCH)
    good = devhost.render(clone, HOST, tomllib.loads(LOCAL))
    assert '[hpc]' in good
    machine = tmp_path / 'machine.toml'
    machine.write_bytes((good + tail).encode())
    return clone, machine, tmp_path / 'backups', good


def _twice() -> str:
    """What the older kit's grant phase appended: the account's own ``[hpc]`` slice, a second ``[hpc]`` table."""
    return render_grant(grant_slice(ALICE))


def _render(clone: Path, machine: Path, backups: Path) -> int:
    """The render step of ``deploy-fleet``, with the argv :func:`deploy_command` puts on the account."""
    return devhost.main([
        '--machine', str(machine), 'render', '--host', HOST, '--write', '--from', str(clone), '--backups', str(backups),
    ])  # fmt: skip


def test_the_steps_driven_here_are_the_ones_deploy_fleet_runs_on_a_research_account(tmp_path: Path) -> None:
    source = fleet_source(tmp_path)
    command = deploy_command(ALICE, Target('login01', (tmp_path / 'root').as_posix(), 'research'), source)
    drifted = command.index('-m dev_lab.dev.devhost drift --from')
    rendered = command.index(f'-m dev_lab.dev.devhost render --host {HOST} --write --from')
    deployed = command.index('-m dev_lab.dev.hpcaccount deploy --grant-table')
    assert drifted < rendered < deployed


def test_a_file_declaring_hpc_twice_is_repaired_once_by_the_render_and_backed_up(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    clone, machine, backups, good = _account(tmp_path, _twice())
    broken = machine.read_bytes()
    with pytest.raises(tomllib.TOMLDecodeError, match='twice'):
        tomllib.loads(broken.decode())
    assert devhost.main(['--machine', str(machine), 'drift', '--from', str(clone)]) == 2  # its "; true" step
    assert machine.read_bytes() == broken, 'drift wrote'
    capsys.readouterr()
    assert _render(clone, machine, backups) == 0
    said = capsys.readouterr()
    assert '[hpc] 2 times' in said.err
    assert BARE not in said.err + said.out
    assert machine.read_text(encoding='utf-8') == good  # exactly the render of a well-formed file: [user] kept
    (backup,) = backups.iterdir()
    assert backup.read_bytes() == broken
    assert load(machine) is not None  # the deploy's own first read
    assert machine_table(machine)['user'] == {'shell': 'zsh'}
    assert _render(clone, machine, backups) == 0  # once: the second render has nothing to repair
    assert '[hpc]' not in capsys.readouterr().err


def test_a_well_formed_file_is_rendered_with_no_repair(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """PLANTED CONTROL: the repair says nothing, and changes nothing, on the current shape."""
    clone, machine, backups, good = _account(tmp_path, '')
    assert _render(clone, machine, backups) == 0
    assert machine.read_text(encoding='utf-8') == good
    assert 'times' not in capsys.readouterr().err


@pytest.mark.parametrize(
    'tail',
    [
        '\n[user2]\nshell = \n',  # not TOML, and no second [hpc]
        '\n[hpc]\nreach = ["research"]\n\n[user2]\nshell = \n',  # a second [hpc] AND a break outside it
        '\n[hpc]\nreach = \n',  # a second [hpc] that is itself not TOML
    ],
)
def test_a_file_broken_another_way_is_refused_by_name_and_never_rewritten(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], tail: str
) -> None:
    """PLANTED CONTROL: the door repairs ONE known old shape; anything else is refused, the file untouched."""
    clone, machine, backups, _good = _account(tmp_path, tail)
    broken = machine.read_bytes()
    assert _render(clone, machine, backups) == 2
    assert machine.read_bytes() == broken
    assert not backups.exists()
    err = capsys.readouterr().err
    assert str(machine) in err
    assert 'is not TOML' in err
    assert REDEPLOY_DOOR not in err, 'a redeploy does not repair this file'


def test_every_reader_names_the_cause_and_the_redeploy_door(tmp_path: Path) -> None:
    _clone, machine, _backups, _good = _account(tmp_path, _twice())
    for read in (lambda: read_machine(machine), lambda: machine_table(machine), lambda: load(machine)):
        with pytest.raises(Unreadable, match=r'\[hpc\] 2 times') as refused:
            read()
        assert str(machine) in str(refused.value)
        assert REDEPLOY_DOOR in str(refused.value)
        assert BARE not in str(refused.value)


def test_account_drift_names_the_cause_and_the_door_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    clone, machine, _backups, _good = _account(tmp_path, _twice())
    broken = machine.read_bytes()
    args = ['--from', str(clone), '--host', HOST, '--config', str(machine)]
    assert drift.main(args, home=tmp_path, tools=tools_of(tmp_path)) == 2
    err = capsys.readouterr().err
    assert '[hpc] 2 times' in err
    assert REDEPLOY_DOOR in err
    assert BARE not in err
    assert 'cannot render' not in err, 'the render is fine: the file on the account is what cannot be read'
    assert machine.read_bytes() == broken


def test_account_drift_still_compares_a_well_formed_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """PLANTED CONTROL for the drift refusal above: the same account, its file well formed, is compared."""
    clone, machine, _backups, _good = _account(tmp_path, '')
    args = ['--from', str(clone), '--host', HOST, '--config', str(machine)]
    assert drift.main(args, home=tmp_path, tools=tools_of(tmp_path)) == 1  # its one drift: the local [user]
    assert 'user.shell' in capsys.readouterr().out


def test_the_storage_check_names_the_cause_and_the_door(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _clone, machine, _backups, _good = _account(tmp_path, _twice())
    monkeypatch.setenv(CONFIG_ENV, str(machine))
    assert storage.main(['check', 'archive', '--tree', str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert '[hpc] 2 times' in err
    assert REDEPLOY_DOOR in err
    assert BARE not in err
