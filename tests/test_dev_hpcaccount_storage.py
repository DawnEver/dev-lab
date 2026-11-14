"""``hpcaccount retention``: each account's quota, tick lines and its OWN retention report, through the door."""

from __future__ import annotations

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

    code = retention_fleet(_FLEET, accounts, apply=apply, say=said.append, connect=connect)
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
    assert 'alice: serve tick lines in crontab: 0 -- serve never ticks' in said
    _, said, _ = _run(ticks='3', accounts=('alice',))  # control: a ticking account carries no warning
    assert 'alice: serve tick lines in crontab: 3' in said


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
_KIB_AT = ((8, '/.cargo/bin'), (700, '/.cache/uv'), (200, '/ci/envs'), (10, '/ci/trees'), (720, '/.cache'))
_BYTES = '\n'.join(f'{n} {_HOME}{p}' for n, p in (*_KIB_AT, (230, '/ci'), (9, '/.cargo'), (959, '')))


def _census_account(seen: list[str]) -> Runner:
    def shell(cmd: str, _stdin: str | None = None) -> str:
        seen.append(cmd)
        if '--inodes' in cmd:
            return _FILES
        if cmd.startswith('du '):
            return _BYTES
        if cmd.startswith('crontab'):
            return '2'
        if cmd.startswith('quota'):
            return _QUOTA
        return _DEPLOY

    return shell


def test_a_census_counts_files_per_directory_and_deletes_nothing() -> None:
    seen: list[str] = []
    said: list[str] = []
    code = retention_fleet(
        _FLEET, ('alice',), apply=False, census=True, say=said.append, connect=lambda _g: _census_account(seen)
    )
    assert code == 0
    # PLANTED: a census is read-only -- no retention run, no apply, no deletion verb reaches the account
    assert not any('dev_lab.dev.retention' in cmd or '--apply' in cmd or 'rm ' in cmd for cmd in seen)
    rows = said[said.index('alice: census (files, KiB, path; most files first)') + 1 :]
    assert rows[0].split() == ['1430', '959', '~']
    assert rows[1].split() == ['950', '720', '~/.cache']  # dotdirs are counted
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


def test_census_and_apply_are_exclusive(monkeypatch: pytest.MonkeyPatch) -> None:
    said: list[str] = []
    monkeypatch.setattr(storage, 'emit', said.append)
    with pytest.raises(SystemExit):
        storage.main(['--account', 'alice', '--census', '--apply'])
