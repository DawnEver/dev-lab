"""``hpchost deploy-fleet``: every declared account, one detached ssh and one log each; nothing undeclared."""

from __future__ import annotations

from pathlib import Path

from lab_commons.hpc.grants import Grant

from dev_lab.dev.hpchost.fleet import deploy_fleet, remote_argv

_FLEET = (
    Grant(user='alice', hosts=('login1.example', 'login2.example'), slurm_account='acct'),
    Grant(user='bob', hosts=('login2.example',), slurm_account='acct'),
)


def _run(tmp_path: Path, accounts: tuple[str, ...] = ()) -> tuple[int, list[list[str]]]:
    started: list[list[str]] = []
    code = deploy_fleet(
        _FLEET,
        accounts,
        root='src',
        home=tmp_path,
        dry_run=False,
        say=lambda _l: None,
        launch=lambda argv, _log: started.append(list(argv)),
    )
    return code, started


def test_every_declared_account_is_started_with_its_own_log(tmp_path: Path) -> None:
    code, started = _run(tmp_path)
    assert code == 0
    assert [argv[5] for argv in started] == ['alice@login1.example', 'bob@login2.example']
    assert {p.name for p in tmp_path.rglob('*.log')} == {'alice.log', 'bob.log'}


def test_an_undeclared_account_is_refused_and_nothing_starts(tmp_path: Path) -> None:
    """PLANTED CONTROL: one stranger among declared names refuses the whole run."""
    code, started = _run(tmp_path, ('alice', 'mallory'))
    assert code == 2
    assert started == []


def test_the_remote_runs_the_accounts_own_deploy_never_prompting() -> None:
    argv = remote_argv(_FLEET[0], root='src')
    assert argv[:3] == ['ssh', '-o', 'BatchMode=yes']
    assert 'cd ~/src/dev-lab && .venv/bin/python -m dev_lab.dev.hpchost deploy' in argv[-1]
