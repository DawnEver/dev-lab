"""``hpchost deploy-fleet``: each declared account on ITS declared host, one detached ssh and one log each."""

from __future__ import annotations

from pathlib import Path

from lab_commons.hpc.grants import Grant

from dev_lab.dev.hpchost.fleet import Target, deploy_fleet, remote_argv

_HOSTS = ('hpclogin01.example', 'hpclogin02.example')
_FLEET = (
    Grant(user='alice', hosts=_HOSTS, slurm_account='acct'),
    Grant(user='bob', hosts=_HOSTS, slurm_account='acct'),
    Grant(user='carol', hosts=_HOSTS, slurm_account='acct'),
)

#: What each account's own machine file declares, as ``sed`` prints its [deploy] table (and the next header).
_DEPLOY = {
    'alice': (
        '[deploy]\nhost = "hpclogin02.example"\nroot = "src"\nrepos = [\n  { name = "dev-lab" },\n]\n[[hpc.grant]]\n'
    ),
    'bob': '[deploy]\nhost = "hpclogin01.example"\nroot = "work"\n',
    'carol': '',
}


def _run(
    tmp_path: Path, accounts: tuple[str, ...] = (), deploy: dict[str, str] = _DEPLOY
) -> tuple[int, list[list[str]], list[str]]:
    started: list[list[str]] = []
    said: list[str] = []
    code = deploy_fleet(
        _FLEET,
        accounts,
        home=tmp_path,
        dry_run=False,
        say=said.append,
        connect=lambda grant: lambda _cmd, _stdin=None: deploy[grant.user],
        launch=lambda argv, _log: started.append(list(argv)),
    )
    return code, started, said


def test_each_account_deploys_on_its_own_declared_host(tmp_path: Path) -> None:
    code, started, said = _run(tmp_path, ('alice', 'bob'))
    assert code == 0
    assert [argv[5] for argv in started] == ['alice@hpclogin02.example', 'bob@hpclogin01.example']
    assert 'cd ~/work/dev-lab' in started[1][-1], "bob's declared root"
    assert {p.name for p in tmp_path.rglob('*.log')} == {'alice.log', 'bob.log'}
    assert not any('refused' in line for line in said)


def test_an_account_with_no_declared_host_is_refused_and_the_rest_deploy(tmp_path: Path) -> None:
    code, started, said = _run(tmp_path)
    assert code == 2
    assert [argv[5] for argv in started] == ['alice@hpclogin02.example', 'bob@hpclogin01.example']
    assert any(line.startswith('carol: refused') and '[deploy] host' in line for line in said)


def test_a_declared_host_outside_the_grant_is_refused(tmp_path: Path) -> None:
    """PLANTED CONTROL: a machine file naming a host the grant does not is never ssh'd to."""
    code, started, said = _run(tmp_path, ('bob',), {'bob': '[deploy]\nhost = "elsewhere.example"\n'})
    assert code == 2
    assert started == []
    assert any('not a login host' in line for line in said)


def test_an_undeclared_account_is_refused_and_nothing_starts(tmp_path: Path) -> None:
    """PLANTED CONTROL: one stranger among declared names refuses the whole run."""
    code, started, _ = _run(tmp_path, ('alice', 'mallory'))
    assert code == 2
    assert started == []


def test_the_remote_runs_the_accounts_own_deploy_never_prompting() -> None:
    argv = remote_argv('alice', Target('hpclogin02.example', 'src'))
    assert argv[:3] == ['ssh', '-o', 'BatchMode=yes']
    assert 'cd ~/src/dev-lab && .venv/bin/python -m dev_lab.dev.hpchost deploy' in argv[-1]


def test_an_account_with_two_grants_is_refused_rather_than_one_silently_kept(tmp_path: Path) -> None:
    said: list[str] = []
    twice = (*_FLEET, Grant(user='alice', hosts=('other.example',), slurm_account='acct'))
    code = deploy_fleet(
        twice,
        (),
        home=tmp_path,
        dry_run=False,
        say=said.append,
        connect=lambda grant: lambda _cmd, _stdin=None: _DEPLOY[grant.user],
        launch=lambda _argv, _log: None,
    )
    assert code == 2
    assert any("['alice'] hold more than one" in line for line in said)
