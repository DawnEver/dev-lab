"""``hpcaccount ci-pause`` / ``ci-resume``: refused on drift, only the marked lines, the declared lines back, no job."""

from __future__ import annotations

import inspect
import tomllib
from pathlib import Path
from typing import Final

import pytest
from _hpcaccount_fakes import FAMILY, HOST, home_of, tools_of
from lab_commons.hpc.grants import declared_grants

from dev_lab.dev import devhost
from dev_lab.dev.devdeclared import layered
from dev_lab.dev.hpcaccount import cimark, cipause, deploy, drift, tick
from dev_lab.dev.hpcaccount.fleet import account_host, grant_slice
from dev_lab.dev.hpcaccount.grantslice import render_grant, without_hpc
from dev_lab.dev.hpcaccount.spec import MARK, cron_lines, load

MINE: Final = '0 1 * * * echo mine\n'


@pytest.fixture(autouse=True)
def _slurm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deploy, 'slurm_dirs', lambda: ['/opt/slurm/bin'])


def _account(tmp_path: Path, mine: str = '', extra: str = '', family: str = FAMILY) -> tuple[Path, Path, list[str]]:
    """A home, the machine file, and the args naming its clone; its crontab is the declared lines plus *mine*."""
    home, clone, machine = home_of(tmp_path, extra, family)
    spec = load(machine)
    lines = cron_lines(spec, home, slurm=['/opt/slurm/bin']) if spec else []
    (tmp_path / 'crontab.txt').write_text(mine + ''.join(f'{line}\n' for line in lines), encoding='utf-8')
    return home, machine, ['--config', str(machine), '--from', str(clone), '--host', HOST]


def _cron(tmp_path: Path) -> str:
    return (tmp_path / 'crontab.txt').read_text(encoding='utf-8')


def test_pause_without_drift_removes_only_the_marked_lines(tmp_path: Path) -> None:
    home, _, args = _account(tmp_path)
    assert MARK in _cron(tmp_path)
    assert cipause.ci_pause(args, home=home, tools=tools_of(tmp_path)) == 0
    assert _cron(tmp_path) == ''
    assert cimark.marker((home.parent / 'root').as_posix()).is_file()
    assert not list(home.glob('.cache/dev-lab/*/*/*/backup')), 'nothing is backed up'


def test_pause_refuses_while_the_account_drifts_naming_each_item_and_the_door(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home, _, args = _account(tmp_path, mine=MINE, extra='\n[user]\nshell = "zsh"\n')
    before = _cron(tmp_path)
    assert cipause.ci_pause(args, home=home, tools=tools_of(tmp_path)) == 2
    err = capsys.readouterr().err
    assert 'echo mine' in err
    assert 'user.shell' in err
    assert 'declare it in the config source or accept its loss with --discard-drift' in err
    assert _cron(tmp_path) == before
    assert not cimark.marker((home.parent / 'root').as_posix()).exists()


def test_discard_drift_accepts_the_loss_and_keeps_the_users_own_line(tmp_path: Path) -> None:
    home, _, args = _account(tmp_path, mine=MINE)
    assert cipause.ci_pause([*args, drift.DISCARD], home=home, tools=tools_of(tmp_path)) == 0
    assert _cron(tmp_path) == MINE
    assert '1 drift item(s) discarded' in cimark.marker((home.parent / 'root').as_posix()).read_text(encoding='utf-8')


def test_a_stale_clone_refuses_the_pause_and_removes_nothing(tmp_path: Path) -> None:
    home, _, args = _account(tmp_path)
    before = _cron(tmp_path)
    args[args.index('--from') + 1] = str(tmp_path / 'gone')
    assert cipause.ci_pause(args, home=home, tools=tools_of(tmp_path)) == 2
    assert _cron(tmp_path) == before


def test_a_research_account_is_refused_and_untouched(tmp_path: Path) -> None:
    home, machine, args = _account(tmp_path, mine=MINE, family=FAMILY.replace('"verification"', '"research"'))
    assert 'role = "research"' in machine.read_text(encoding='utf-8')
    assert cipause.ci_pause([*args, drift.DISCARD], home=home, tools=tools_of(tmp_path)) == 2
    assert _cron(tmp_path) == MINE
    assert not (home / '.cache').exists()


def test_resume_restores_exactly_the_declared_lines_and_clears_the_marker(tmp_path: Path) -> None:
    home, machine, args = _account(tmp_path, mine=MINE)
    tools = tools_of(tmp_path)
    assert cipause.ci_pause([*args, drift.DISCARD], home=home, tools=tools) == 0
    assert cipause.ci_resume(['--config', str(machine)], home=home, tools=tools) == 0
    lines = _cron(tmp_path).splitlines()
    assert lines[0] == MINE.strip()
    assert len(lines) == 2
    assert lines[1].endswith(f'{MARK}dev-lab')
    assert not cimark.marker((home.parent / 'root').as_posix()).exists()


def test_resume_without_the_marker_is_refused(tmp_path: Path) -> None:
    home, machine, _ = _account(tmp_path)
    before = _cron(tmp_path)
    assert cipause.ci_resume(['--config', str(machine)], home=home, tools=tools_of(tmp_path)) == 2
    assert _cron(tmp_path) == before


def test_a_paused_account_refuses_deploy_naming_the_resume_door(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home, machine, args = _account(tmp_path)
    tools = tools_of(tmp_path)
    assert cipause.ci_pause(args, home=home, tools=tools) == 0
    assert deploy.deploy(['--config', str(machine)], home=home, hostname='login01', tools=tools) == 2
    assert 'ci-resume-fleet' in capsys.readouterr().err
    assert _cron(tmp_path) == ''


def test_the_unpaused_control_reaches_past_the_guard(tmp_path: Path) -> None:
    home, _, _ = _account(tmp_path)
    assert cimark.paused_refusal(home) == ''
    assert 'exit 2' in cimark.paused_guard('/r')


def test_no_job_cancellation_path_exists() -> None:
    for module in (cipause, cimark, drift):
        source = inspect.getsource(module)
        assert not {'scancel', 'squeue', 'sbatch', 'kill'} & set(source.replace('(', ' ').split())


def _deployed(tmp_path: Path, mine: str, other: str) -> Path:
    """The machine file a deploy leaves on the account: the render (no ``[deploy] root``) plus its own grant slice.

    The family declares cluster ``c0`` (root *other*) before the account's ``c1`` (root *mine*, ``''`` for none);
    the slice is written as the deploy's grant phase writes it (:func:`dev_lab.dev.hpcaccount.account.grant`).
    """
    tmp_path.mkdir()
    accounts = '[hpc.clusters.c0.slurm_accounts.a]\nbilled = false\n'
    elsewhere = f'[hpc.clusters.c0]\nhosts = ["login00"]\nroot = "{other}"\n{accounts}'
    rooted = FAMILY.replace('hosts = ["login01"]', f'hosts = ["login01"]\nroot = "{mine}"') if mine else FAMILY
    head, clusters = rooted.split('[hpc.clusters.c1]', 1)
    _home, clone, machine = home_of(tmp_path, family=f'{head}{elsewhere}[hpc.clusters.c1]{clusters}')
    layer = clone / devhost.host_file(HOST)
    held = layer.read_text(encoding='utf-8').splitlines(keepends=True)
    layer.write_text(''.join(line for line in held if not line.startswith('root = ')), encoding='utf-8')
    rendered = devhost.render(clone, HOST, {})
    grants, _ = declared_grants(layered(tomllib.loads(rendered))['hpc'])
    (own,) = (grant for grant in grants if account_host(grant) == HOST)
    table = {**tomllib.loads(rendered).get('hpc', {}), **grant_slice(own)}
    machine.write_text(without_hpc(rendered) + render_grant(table), encoding='utf-8')
    return machine


def test_the_deployed_machine_file_alone_names_its_root_to_every_verb_on_the_account(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The cron tick and ``ci-pause`` read only the account's machine file; its own ``[hpc]`` slice holds the root.

    Measured 2026-11-22: after a deploy that passed, every tick died "no root declared" in ``spec.load`` -- the
    deploy and ``drift`` were each handed the grant's cluster root, the loader of the file itself never read the
    slice beside ``[deploy]``. PLANTED CONTROLS: with no root on the account's own cluster it still refuses with
    the same message, though another cluster declares one; and a slice that is not this account's is never read.
    """
    mine, other = (tmp_path / 'mine-root').as_posix(), (tmp_path / 'other-root').as_posix()
    machine = _deployed(tmp_path / 'a', mine, other)
    text = machine.read_text(encoding='utf-8')
    assert 'root' not in tomllib.loads(text)['deploy'], 'the shape measured: [deploy] states no root'
    spec = load(machine)
    assert spec is not None
    assert spec.root == mine
    assert tick.tick('not-served', home=tmp_path, config=machine) == 2
    assert 'not-served is not a served repo' in capsys.readouterr().err, 'the tick parsed its file and read [deploy]'
    assert not isinstance(cipause._serving(machine), str)
    bare = _deployed(tmp_path / 'b', '', other)
    with bare.open('a', encoding='utf-8') as out:  # the other cluster's root, in the very file read
        out.write(f'\n[hpc.clusters.c0]\nhosts = ["login00"]\nroot = "{other}"\n')
    assert tomllib.loads(bare.read_text(encoding='utf-8'))['hpc']['clusters']['c0']['root'] == other
    with pytest.raises(ValueError, match=r'no root declared -- declare \[hpc.clusters.<cluster>\] root'):
        load(bare)
    stranger = tmp_path / 'stranger.toml'
    assert f'host = "{HOST}"' in text
    stranger.write_text(text.replace(f'host = "{HOST}"', 'host = "c0-alice"'), encoding='utf-8')
    with pytest.raises(ValueError, match='no root declared'):
        load(stranger)
