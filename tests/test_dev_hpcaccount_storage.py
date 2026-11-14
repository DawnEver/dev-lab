"""``hpcaccount retention``: each account's quota, tick lines and its OWN retention report, through the door."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest
from lab_commons.hpc.cluster import Runner, Unreachable
from lab_commons.hpc.grants import AccessRefused, Grant

from dev_lab.dev.agentpolicy import exits_of
from dev_lab.dev.hpcaccount import storage
from dev_lab.dev.hpcaccount.storage import UNREACHABLE, retention_fleet

_HOSTS = ('login01.example', 'login02.example')
_FLEET = (
    Grant(user='alice', hosts=_HOSTS, slurm_account='acct'),
    Grant(user='bob', hosts=_HOSTS, slurm_account='acct'),
)
_DEPLOY = '[deploy]\nhost = "login01.example"\nroot = "src"\n'
_QUOTA = 'Disk quotas for user alice\n  /home  29G  30G  30G  999k* 1000k 1000k'


def _account(*, ticks: str = '2', unreachable: bool = False, seen: list[str]) -> Runner:
    def shell(cmd: str, _stdin: str | None = None) -> str:
        if unreachable:
            msg = 'no login host answered'
            raise Unreachable(msg)
        seen.append(cmd)
        if 'sed -n' in cmd:
            return _DEPLOY
        if cmd.startswith('crontab'):
            return ticks
        if cmd.startswith('quota'):
            return _QUOTA
        return 'trees/abc  tree-not-in-flight  12 MB  4000 files\nusage files 999k -> 995k'

    return shell


def _run(
    *, apply: bool = False, accounts: tuple[str, ...] = (), down: tuple[str, ...] = (), ticks: str = '2'
) -> tuple[int, list[str], dict[str, list[str]]]:
    seen: dict[str, list[str]] = {'alice': [], 'bob': []}
    said: list[str] = []

    def connect(grant: Grant) -> Runner:
        return _account(ticks=ticks, unreachable=grant.user in down, seen=seen[grant.user])

    code = retention_fleet(
        _FLEET, accounts, apply=apply, say=said.append, connect=connect, pin=lambda grant, _host: connect(grant)
    )
    return code, said, seen


def _retentions(seen: list[str]) -> list[str]:
    return [cmd for cmd in seen if 'dev_lab.dev.retention' in cmd]


def test_a_dry_run_runs_the_accounts_own_retention_without_apply() -> None:
    code, said, seen = _run()
    assert code == 0
    assert _retentions(seen['alice']) == ['cd ~/src/dev-lab && .venv/bin/python -m dev_lab.dev.retention --cluster']
    assert not any('--apply' in cmd for cmd in seen['alice'] + seen['bob'])  # PLANTED: a dry run deletes nothing
    assert any('999k' in line for line in said)  # the files column of the quota is printed
    assert 'alice: retention (dry run)' in said


def test_apply_passes_apply_to_the_accounts_retention() -> None:
    code, said, seen = _run(apply=True, accounts=('bob',))
    assert code == 0
    assert _retentions(seen['bob']) == [
        'cd ~/src/dev-lab && .venv/bin/python -m dev_lab.dev.retention --cluster --apply'
    ]
    assert seen['alice'] == []  # only the named account is reached
    assert 'bob: retention --apply' in said


def test_an_account_whose_serve_never_ticks_is_named() -> None:
    _, said, _ = _run(ticks='0', accounts=('alice',))
    assert 'alice: serve tick lines in crontab on login01.example: 0 -- serve never ticks' in said
    _, said, _ = _run(ticks='3', accounts=('alice',))  # control: a ticking account carries no warning
    assert 'alice: serve tick lines in crontab on login01.example: 3' in said


def test_tick_lines_are_read_on_the_declared_deploy_host_not_the_first_that_answers() -> None:
    """A crontab belongs to ONE login host: the deploy writes it on ``[deploy] host``.

    Reading it wherever the failover lands reported "never ticks" for a ticking account.
    PLANTED CONTROL: the failover host's crontab (``0``) is never the one reported.
    """
    seen: list[str] = []
    pinned: list[str] = []
    said: list[str] = []

    def pin(grant: Grant, host: str) -> Runner:
        def shell(cmd: str, _stdin: str | None = None) -> str:
            pinned.append(f'{grant.user}@{host}: {cmd}')
            return '3'

        return shell

    code = retention_fleet(
        _FLEET, ('alice',), apply=False, say=said.append, connect=lambda _g: _account(ticks='0', seen=seen), pin=pin
    )
    assert code == 0
    assert 'alice: serve tick lines in crontab on login01.example: 3' in said
    assert pinned == [f'alice@login01.example: {storage.ticks_command()}']
    assert not any(cmd.startswith('crontab') for cmd in seen)


def test_an_unreachable_cluster_is_one_line_naming_the_door() -> None:
    code, said, _ = _run(down=('alice',))
    assert code == 2
    assert f'alice: refused -- {UNREACHABLE}' in said
    assert any(line.startswith('bob: retention') for line in said)  # the rest still run
    assert 'VPN' in UNREACHABLE


def test_an_account_outside_the_fleet_refuses_the_whole_run() -> None:
    code, said, seen = _run(accounts=('mallory',))
    assert code == 2
    assert said == ["retention: refused -- ['mallory'] not in the declared fleet ['alice', 'bob']"]
    assert seen == {'alice': [], 'bob': []}


def test_an_account_of_a_role_this_session_does_not_reach_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """PLANTED: a research-only machine asked for a verification account refuses before any ssh."""

    def refuse(_accounts: object) -> object:
        msg = "alice is a 'verification' account and this machine reaches ['research']"
        raise AccessRefused(msg)

    monkeypatch.setattr(storage, 'reached_machine', refuse)
    said: list[str] = []
    monkeypatch.setattr(storage, 'emit', said.append)
    assert storage.main(['--account', 'alice']) == 2
    assert said == ["retention: refused -- alice is a 'verification' account and this machine reaches ['research']"]


def test_retention_is_an_exit_of_hpc_through_the_door() -> None:
    assert 'retention' in exits_of('HPC-THROUGH-THE-DOOR', 'dev_lab.dev.hpcaccount')


_HOME = '/srv/acct'
_FILES_AT = ((40, '/.cargo/bin'), (900, '/.cache/uv'), (300, '/ci/envs'), (50, '/ci/trees'), (950, '/.cache'))
_FILES = '\n'.join(f'{n} {_HOME}{p}' for n, p in (*_FILES_AT, (420, '/ci'), (60, '/.cargo'), (1430, '')))


def _census_account(seen: list[str], *, slow: bool = False) -> Runner:
    def shell(cmd: str, _stdin: str | None = None) -> str:
        seen.append(cmd)
        if cmd.startswith('du '):
            if slow:
                raise subprocess.TimeoutExpired(cmd, 3600)
            return _FILES
        if cmd.startswith('crontab'):
            return '2'
        if cmd.startswith('quota'):
            return _QUOTA
        return _DEPLOY

    return shell


def _census(*, slow: bool = False) -> tuple[int, list[str], list[str]]:
    seen: list[str] = []
    said: list[str] = []
    code = retention_fleet(
        _FLEET,
        ('alice',),
        apply=False,
        census=True,
        say=said.append,
        connect=lambda _g: _census_account(seen, slow=slow),
        pin=lambda _g, _h: _census_account(seen, slow=slow),
    )
    return code, said, seen


def test_a_census_counts_files_per_directory_in_one_walk_and_deletes_nothing() -> None:
    code, said, seen = _census()
    assert code == 0
    # PLANTED: a census is read-only -- no retention run, no apply, no deletion verb reaches the account
    assert not any('dev_lab.dev.retention' in cmd or '--apply' in cmd or 'rm ' in cmd for cmd in seen)
    assert [cmd for cmd in seen if cmd.startswith('du ')] == [storage.CENSUS]  # ONE walk of the home
    rows = said[said.index('alice: census (files, path; most files first)') + 1 :]
    assert rows[0].split() == ['1430', '~']
    assert rows[1].split() == ['950', '~/.cache']  # dotdirs are counted
    assert [row.split()[-1] for row in rows] == [
        '~',
        '~/.cache',
        '~/.cache/uv',
        '~/ci',
        '~/ci/envs',
        '~/.cargo',
        '~/ci/trees',
        '~/.cargo/bin',
    ]


def test_a_walk_that_outlasts_the_timeout_is_one_line_naming_the_door() -> None:
    code, said, _ = _census(slow=True)
    assert code == 2
    assert said[-1].startswith('alice: refused -- a remote command ran past its timeout')
    assert '--timeout' in said[-1]


def test_the_timeout_reaches_the_ssh_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    got: list[float] = []
    monkeypatch.setattr(storage, 'reached_machine', lambda _a: SimpleNamespace(grants=_FLEET))
    monkeypatch.setattr(storage, 'emit', lambda _line: None)

    def runner(_grant: Grant, timeout: float) -> Runner:
        got.append(timeout)
        return _census_account([])

    def pinned(_grant: Grant, _host: str, timeout: float) -> Runner:
        got.append(timeout)
        return _census_account([])

    monkeypatch.setattr(storage, 'runner_for', runner)
    monkeypatch.setattr(storage, 'on_host', pinned)
    assert storage.main(['--account', 'alice', '--census', '--timeout', '7200']) == 0
    assert got == [7200.0, 7200.0]  # the failover runner and the deploy host's pinned one alike


def test_census_and_apply_are_exclusive(monkeypatch: pytest.MonkeyPatch) -> None:
    said: list[str] = []
    monkeypatch.setattr(storage, 'emit', said.append)
    with pytest.raises(SystemExit):
        storage.main(['--account', 'alice', '--census', '--apply'])
