"""``hpcaccount ci-pause`` / ``ci-resume``: refused on drift, only the marked lines, the declared lines back, no job."""

from __future__ import annotations

import inspect
import sys
import tomllib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Final

import pytest
from _hpcaccount_fakes import FAMILY, HOST, home_of, tools_of
from _ops_fixtures import git
from lab_commons.config import CONFIG_ENV
from lab_commons.hpc.account import ClusterAccount
from lab_commons.hpc.grants import declared_grants

from dev_lab.dev import devhost, forgeslurm
from dev_lab.dev.devdeclared import layered
from dev_lab.dev.hpcaccount import account, cimark, cipause, deploy, drift, tick
from dev_lab.dev.hpcaccount.fleet import account_host, grant_slice
from dev_lab.dev.hpcaccount.grantslice import grant_setup, render_grant, without_hpc
from dev_lab.dev.hpcaccount.spec import MARK, cron_lines, load
from dev_lab.dev.hpcaccount.steps import Step
from dev_lab.dev.roles import machine_layer

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


#: The family binds the forge's HPC roles to the account's cluster and grant role.
_ROLES: Final = '[roles.gitea]\nreview = { host = "judgehost" }\npromote = { host = "promotehost" }\n' + ''.join(
    f'{role} = {{ hpc = "c1", role = "verification" }}\n' for role in ('tests', 'merge', 'prune')
)


def _deployed(tmp_path: Path, mine: str, other: str, *, stale: bool = False) -> Path:
    """The machine file a deploy leaves on the account: its render, which names its ``[family] source``.

    The family declares cluster ``c0`` (root *other*, where the same user holds a grant of the same role) before the
    account's ``c1`` (root *mine*, ``''`` for none) and binds the forge's roles; the layer states no ``[deploy]
    root``. The deploy's own grant phase has run
    (:func:`dev_lab.dev.hpcaccount.account.grant`). *stale*: the slice a deploy before 2026-11-22 wrote back is
    still in the file -- the shape of an account deployed then and not yet re-rendered.
    """
    tmp_path.mkdir()
    accounts = '[hpc.clusters.c0.slurm_accounts.b]\nbilled = false\n'
    elsewhere = f'[hpc.clusters.c0]\nhosts = ["login00"]\nroot = "{other}"\n{accounts}'
    rooted = FAMILY.replace('hosts = ["login01"]', f'hosts = ["login01"]\nroot = "{mine}"') if mine else FAMILY
    head, clusters = rooted.split('[hpc.clusters.c1]', 1)
    twin = '[[hpc.grant]]\nuser = "alice"\ncluster = "c0"\nslurm_account = "b"\nrole = "verification"\n'
    _home, clone, machine = home_of(tmp_path, family=f'{twin}{head}{elsewhere}[hpc.clusters.c1]{clusters}{_ROLES}')
    layer = clone / devhost.host_file(HOST)
    held = layer.read_text(encoding='utf-8').replace('forge.example/dev-lab.git', 'forge.example/team/dev-lab.git')
    layer.write_text(''.join(ln for ln in held.splitlines(keepends=True) if not ln.startswith('root = ')), 'utf-8')
    rendered = devhost.render(clone, HOST, {})
    machine.write_text(rendered, encoding='utf-8')
    grants, _ = declared_grants(layered(tomllib.loads(rendered))['hpc'])
    (own,) = (grant for grant in grants if account_host(grant) == HOST)
    if stale:
        table = {**tomllib.loads(rendered).get('hpc', {}), **grant_slice(own)}
        machine.write_text(without_hpc(rendered) + render_grant(table), encoding='utf-8')
        return machine
    tools = replace(tools_of(tmp_path), sacctmgr=(sys.executable, '-c', 'print("a|cpu=96")'))
    assert account.grant(Step(tools, dry=False), machine, grant_slice(own)) == 0
    return machine


def test_the_deployed_machine_file_alone_names_its_root_to_every_verb_on_the_account(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The cron tick and ``ci-pause`` read only the account's machine file, over the family file it names.

    Measured 2026-11-22: after a deploy that passed, every tick died "no root declared" in ``spec.load`` -- the
    deploy and ``drift`` were each handed the grant's cluster root, the loader of the file itself never read the
    grant beside ``[deploy]``. PLANTED CONTROLS: with no root on the account's own cluster the tick still refuses
    with the same message, though another cluster declares one; and a grant that is not this account's is never read.
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
    assert tick.tick('dev-lab', home=tmp_path, config=_deployed(tmp_path / 'b', '', other)) == 2
    assert 'no root declared -- declare [hpc.clusters.<cluster>] root' in capsys.readouterr().err
    stranger = tmp_path / 'stranger.toml'
    assert f'host = "{HOST}"' in text
    stranger.write_text(text.replace(f'host = "{HOST}"', 'host = "c0-bob"'), encoding='utf-8')
    with pytest.raises(ValueError, match='no root declared'):
        load(stranger)


def _ticked(tmp_path: Path, machine: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[int, list[Path]]:
    """One tick of ``dev-lab`` on the account of *machine*, its refresh done; the exit and where it served."""
    monkeypatch.setenv(CONFIG_ENV, str(machine))
    monkeypatch.setattr(tick, '_refresh', lambda *_a: ('', []))
    monkeypatch.setattr(tick, 'follow_uv', lambda _name: '')
    served: list[Path] = []

    def run(_argv: list[str], *, cwd: Path, **_kw: object) -> SimpleNamespace:
        served.append(cwd)
        return SimpleNamespace(returncode=0)

    return tick.tick('dev-lab', home=tmp_path, config=machine, run=run, alarm=lambda _alarm: None), served


def test_the_grant_stays_in_the_family_file_and_the_tick_serves_through_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """ONE SOURCE: a machine file naming its ``[family] source`` is written no grant; every reader layers the family.

    Probed 2026-11-22 behind the root fix: the deploy's grant phase wrote the family's ``[hpc]`` slice back into the
    render, and the tick's own roles read (``lab_commons.config.section``) refused every leaf both held -- an
    uncaught ValueError in every tick. PLANTED CONTROL: an account still holding that slice is released by name,
    never a traceback, and its next render drops the slice.
    """
    mine, other = (tmp_path / 'mine-root').as_posix(), (tmp_path / 'other-root').as_posix()
    machine = _deployed(tmp_path / 'a', mine, other)
    assert tomllib.loads(machine.read_text(encoding='utf-8'))['hpc'] == {'reach': ['verification']}, 'no leaf written'
    checkout = Path(mine, 'repos', 'dev-lab')
    checkout.mkdir(parents=True)
    (checkout / 'pyproject.toml').write_text('', encoding='utf-8')
    git(checkout, 'init', '-q')
    git(checkout, 'remote', 'add', 'origin', 'https://forge.example/team/dev-lab.git')
    code, served = _ticked(tmp_path, machine, monkeypatch)
    assert (code, served) == (0, [checkout]), capsys.readouterr().err
    assert machine_layer()['hpc']['clusters']['c1']['root'] == mine
    assert grant_setup(machine, 'alice') == ()
    monkeypatch.setattr(forgeslurm, 'resolve', lambda machine, _read: machine)
    monkeypatch.setattr(forgeslurm, 'submitter', lambda: lambda _grant: None)
    seat = forgeslurm.slurm_cluster(tmp_path, ClusterAccount('any', 'alice'))
    assert [grant.cluster_name for grant in seat.machine.grants] == ['c1'], "the same user's c0 grant is not this seat"
    stale = _deployed(tmp_path / 'b', mine, other, stale=True)
    held = tomllib.loads(stale.read_text(encoding='utf-8'))
    assert held['hpc']['grant'], 'the planted slice'
    code, served = _ticked(tmp_path, stale, monkeypatch)
    err = capsys.readouterr().err
    assert (code, served) == (2, [])
    assert 'restates a key the family layer holds' in err
    assert 'deploy-fleet' in err
    healed = tomllib.loads(devhost.render(Path(held['family']['source']), HOST, held))
    assert healed['hpc'] == {'reach': ['verification']}, 'the next render drops the stale slice'
