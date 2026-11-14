"""``hpcaccount forget``: one learned row forgotten on each declared account, through the grant's own hosts."""

from __future__ import annotations

import pytest
from lab_commons.hpc.cluster import Runner, Unreachable
from lab_commons.hpc.grants import Grant

from dev_lab.dev._deny_hpc_row import HPC_THROUGH_THE_DOOR, exits, remedy
from dev_lab.dev.agentpolicy import exits_of
from dev_lab.dev.hpcaccount.forget import forget_fleet

_HOSTS = ('login01.example', 'login02.example')
_FLEET = (
    Grant(user='alice', hosts=_HOSTS, slurm_account='acct'),
    Grant(user='bob', hosts=_HOSTS, slurm_account='acct'),
)
_REPO = 'https://forge.example/org/repo.git'
_DEPLOY = '[deploy]\nhost = "login01.example"\nroot = "src"\n'
_ROW = '{"peak_mem_gb": 412.0, "cpu_s": 1.0, "wall_s": 1.0, "files": 9.0, "ended": "asked"}'


def _account(row: str | None, *, unreachable: bool = False, seen: list[str]) -> Runner:
    def shell(cmd: str, _stdin: str | None = None) -> str:
        if unreachable:
            msg = 'no login host answered'
            raise Unreachable(msg)
        seen.append(cmd)
        if 'sed -n' in cmd:
            return _DEPLOY
        if ' -c ' in cmd:
            return 'null' if row is None else row
        return 'removed slurm| {} (backup ~/.local/state/compute-learned/x.json.bak-1)'

    return shell


def _run(
    rows: dict[str, str | None], accounts: tuple[str, ...] = (), *, dry_run: bool = False, down: tuple[str, ...] = ()
) -> tuple[int, list[str], dict[str, list[str]], list[str]]:
    seen: dict[str, list[str]] = {user: [] for user in rows}
    connected: list[str] = []
    said: list[str] = []

    def connect(grant: Grant) -> Runner:
        connected.append(grant.user)
        return _account(rows[grant.user], unreachable=grant.user in down, seen=seen[grant.user])

    code = forget_fleet(_FLEET, accounts, repo=_REPO, row='slurm|', dry_run=dry_run, say=said.append, connect=connect)
    return code, said, seen, connected


def test_each_account_forgets_the_row_in_its_declared_checkout() -> None:
    code, said, seen, _ = _run({'alice': _ROW, 'bob': _ROW})
    assert code == 0
    assert all(line.split(': ')[1].startswith('forgotten') and 'backup' in line for line in said)
    forgets = [cmd for cmd in seen['alice'] if 'learned forget' in cmd]
    assert forgets == [
        f"cd ~/src/dev-lab && .venv/bin/python -m lab_commons.compute.learned forget --repo {_REPO} --row 'slurm|'"
    ]


def test_dry_run_prints_the_peak_and_changes_nothing() -> None:
    code, said, seen, _ = _run({'alice': _ROW, 'bob': _ROW}, dry_run=True)
    assert code == 0
    assert all('peak 412.0 GB' in line for line in said)
    assert not any('learned forget' in cmd for cmds in seen.values() for cmd in cmds)


def test_an_unknown_row_is_absent_never_an_error_and_the_fleet_continues() -> None:
    """PLANTED CONTROL: alice holds no such row; bob still forgets his."""
    code, said, seen, _ = _run({'alice': None, 'bob': _ROW})
    assert code == 0
    assert said[0].startswith('alice: absent')
    assert not any('learned forget' in cmd for cmd in seen['alice'])
    assert said[1].startswith('bob: forgotten')


def test_one_unreachable_account_is_named_and_the_others_still_run() -> None:
    """PLANTED CONTROL: alice's hosts do not answer."""
    code, said, _, _ = _run({'alice': _ROW, 'bob': _ROW}, down=('alice',))
    assert code == 2
    assert said[0].startswith('alice: refused')
    assert 'no login host answered' in said[0]
    assert said[1].startswith('bob: forgotten')


def test_an_account_outside_the_grants_runs_nothing_anywhere() -> None:
    """PLANTED CONTROL: one stranger refuses the whole run before any connection."""
    code, said, _, connected = _run({'alice': _ROW, 'bob': _ROW}, ('alice', 'mallory'))
    assert code == 2
    assert connected == []
    assert 'mallory' in said[0]


def test_named_accounts_run_only_those() -> None:
    _, said, _, connected = _run({'alice': _ROW, 'bob': _ROW}, ('bob',))
    assert connected == ['bob']
    assert len(said) == 1


def test_forget_is_an_exit_of_hpc_through_the_door() -> None:
    assert 'forget' in exits_of('HPC-THROUGH-THE-DOOR', 'dev_lab.dev.hpcaccount')


def test_the_hpc_refusal_names_forget_among_the_deploy_doors() -> None:
    """User ruling 2026-11-11: per purpose the door's shape; forget's flags live in refusals.md."""
    text = str(HPC_THROUGH_THE_DOOR['remedy'])
    assert 'deploy `hpcaccount deploy*|forget|retention|credential`' in text
    assert '-m dev_lab.dev.<door>' in text


def test_a_verb_removed_from_the_exits_leaves_the_refusal() -> None:
    """PLANTED CONTROL: without the hpcaccount exits, the rendered refusal drops the deploy purpose."""
    kept = [argv for argv in exits() if argv[0] != 'dev_lab.dev.hpcaccount']
    assert len(kept) == len(exits()) - 5
    assert 'hpcaccount' not in remedy(kept)


def test_an_exit_with_no_usage_line_is_refused() -> None:
    """PLANTED CONTROL: a new door exit with no command line cannot render a vague refusal."""
    with pytest.raises(KeyError, match='no USAGES line'):
        remedy([*exits(), ('dev_lab.dev.hpcaccount', 'tick')])
