"""``hpcaccount credential``: a minted forge token placed on a declared key-only account, then verified."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from lab_commons.hpc.cluster import Runner
from lab_commons.hpc.grants import Grant

from dev_lab.dev._deny_hpc_row import HPC_THROUGH_THE_DOOR
from dev_lab.dev.agentpolicy import exits_of
from dev_lab.dev.hpcaccount.account import _READER_REMEDY
from dev_lab.dev.hpcaccount.credential import declared_logins, digest, place_command, place_credential, usage
from dev_lab.dev.hpcaccount.division import Division

_HOSTS = ('login1.example', 'login2.example')
_FLEET = (Grant(user='alice', hosts=_HOSTS, slurm_account='acct'),)
_DIVISION = Division(grant_roles={'alice': 'verification'})
_LOGINS = frozenset({'forge-ci'})
_MINTED = 'tok3n-SECRET-value'
_REPO = 'https://forge.example/org/dev-lab.git'
_DEPLOY = '[deploy]\nhost = "login1.example"\nroot = "src"\n'


def _account(*, answers: str = 'forge-ci', seen: list[tuple[str, str | None]]) -> Runner:
    def shell(cmd: str, stdin: str | None = None) -> str:
        seen.append((cmd, stdin))
        if 'sed -n' in cmd:
            return _DEPLOY
        if 'remote get-url origin' in cmd:
            return _REPO + '\n'
        if 'auth role' in cmd:
            return json.dumps({'login': answers, 'push': True, 'admin': False})
        return ''

    return shell


def _run(
    account: str = 'alice@login2.example',
    *,
    login: str = 'forge-ci',
    answers: str = 'forge-ci',
    url: str = '',
    division: Division = _DIVISION,
) -> tuple[int, list[str], list[tuple[str, str | None]], list[str]]:
    seen: list[tuple[str, str | None]] = []
    said: list[str] = []
    connected: list[str] = []

    def connect(grant: Grant) -> Runner:
        connected.append(grant.user)
        return _account(answers=answers, seen=seen)

    code = place_credential(
        account,
        login=login,
        token=_MINTED,
        url=url,
        grants=_FLEET,
        division=division,
        logins=_LOGINS,
        say=said.append,
        connect=connect,
    )
    return code, said, seen, connected


def test_the_token_travels_on_stdin_and_the_forge_answers_as_the_login() -> None:
    code, said, seen, connected = _run()
    assert code == 0
    assert connected == ['alice']
    placed = [(cmd, stdin) for cmd, stdin in seen if stdin]
    assert placed == [(place_command('forge.example'), f'https://forge-ci:{_MINTED}@forge.example\n')]
    assert all(_MINTED not in cmd for cmd, _ in seen)  # never in the remote argv
    assert all(_MINTED not in line for line in said)  # never printed
    assert any(digest(_MINTED) in line for line in said)
    role = next(cmd for cmd, _ in seen if 'auth role' in cmd)
    assert role.startswith('cd ~/src/dev-lab && ')
    assert f'--url {_REPO}' in role


def test_an_explicit_url_names_the_forge_host() -> None:
    _, _, seen, _ = _run(url='https://other.example/org/x.git')
    assert not any('remote get-url' in cmd for cmd, _ in seen)
    assert any(stdin and stdin.endswith('@other.example\n') for _, stdin in seen)


def test_a_forge_answering_as_another_login_is_refused_naming_it() -> None:
    """PLANTED CONTROL: the stored token is somebody else's."""
    code, said, _, _ = _run(answers='mallory')
    assert code == 2
    assert 'mallory' in said[-1]
    assert 'refused' in said[-1]


def test_an_undeclared_login_is_refused_before_any_connection() -> None:
    """PLANTED CONTROL: a login neither [hpc.roles] nor [ops.forge.accounts] declares."""
    code, said, _, connected = _run(login='intruder')
    assert (code, connected) == (2, [])
    assert 'intruder' in said[0]


def test_an_undeclared_account_is_refused_before_any_connection() -> None:
    """PLANTED CONTROL: an account with no [[hpc.grant]]."""
    code, said, _, connected = _run('mallory@login1.example')
    assert (code, connected) == (2, [])
    assert 'mallory' in said[0]


def test_a_host_outside_the_grant_is_refused() -> None:
    code, _, _, connected = _run('alice@elsewhere.example')
    assert (code, connected) == (2, [])


def test_a_role_with_a_reader_takes_only_that_login() -> None:
    """PLANTED CONTROL: forge-ci is declared, but alice's role reads as forge-ro."""
    division = Division(grant_roles={'alice': 'research'}, roles={'research': {'reader': 'forge-ro'}})
    code, said, _, connected = _run(division=division)
    assert (code, connected) == (2, [])
    assert 'forge-ro' in said[0]


def test_declared_logins_are_the_role_readers_and_the_ops_forge_accounts() -> None:
    division = Division(grant_roles={}, roles={'research': {'reader': 'forge-ro'}, 'verification': {}})
    ops = {'forge': {'accounts': {'forge-ci': {'role': 'read'}}}}
    assert declared_logins(division, ops) == {'forge-ro', 'forge-ci'}
    assert declared_logins(division, {}) == {'forge-ro'}


def test_a_host_name_that_is_no_host_is_refused() -> None:
    with pytest.raises(ValueError, match='not a forge host'):
        place_command("forge.example' ; rm -rf ~ ; '")


_BASH = shutil.which('bash')
_OLD = 'x'  # a stale credential's placeholder


def _stored(login: str, host: str, held: str = _OLD) -> str:
    """One ``~/.git-credentials`` line, assembled from parts so no fixture reads as an email address."""
    return f'https://{login}:{held}' + '@' + host


def test_the_place_command_replaces_only_its_forge_line(tmp_path: Path) -> None:
    assert _BASH, 'every login host runs the place command in bash'
    store = tmp_path / '.git-credentials'
    other = _stored('u', 'github.com')
    lookalike = _stored('v', 'forge.example.evil')  # PLANTED CONTROL: a host merely starting with it is kept
    store.write_text(f'{_stored("old", "forge.example")}\n{other}\n{lookalike}\n', encoding='utf-8')
    env = {**os.environ, 'HOME': str(tmp_path)}
    line = _stored('forge-ci', 'forge.example', _MINTED)
    command = [_BASH, '-c', place_command('forge.example')]
    subprocess.run(command, input=line + '\n', text=True, encoding='utf-8', env=env, check=True)
    assert store.read_text(encoding='utf-8').splitlines() == [other, lookalike, line]
    assert [p.name for p in tmp_path.iterdir()] == ['.git-credentials']  # the temp file was moved, not left


def test_the_place_command_writes_private_and_atomic() -> None:
    cmd = place_command('forge.example')
    assert cmd.startswith('umask 077 && ')
    assert 'chmod 600 "$t"' in cmd
    assert cmd.endswith('mv -f "$t" "$f"')


def test_credential_is_an_exit_of_hpc_through_the_door() -> None:
    assert 'credential' in exits_of('HPC-THROUGH-THE-DOOR', 'dev_lab.dev.hpcaccount')
    assert 'hpcaccount deploy*|forget|credential' in str(HPC_THROUGH_THE_DOOR['remedy'])


def test_the_reader_remedy_names_the_door_not_a_hand_edit() -> None:
    assert 'hpcaccount credential' in _READER_REMEDY
    assert 'the USER replaces' not in _READER_REMEDY


def test_an_empty_stdin_places_nothing() -> None:
    """PLANTED CONTROL: no token, no connection."""
    said: list[str] = []
    code = place_credential(
        'alice@login1.example',
        login='forge-ci',
        token='',
        url='',
        grants=_FLEET,
        division=_DIVISION,
        logins=_LOGINS,
        say=said.append,
        connect=lambda _grant: pytest.fail('connected with no token'),
    )
    assert code == 2
    assert 'no token' in said[0]


def test_the_refusals_page_shows_the_credential_usage_its_argparse_renders() -> None:
    """The HPC exits on the refusals page are rendered from the door's own parser, never retyped."""
    shown = usage()
    assert shown.startswith('hpcaccount credential ')
    assert '--login <forge login>' in shown
    assert '[-h]' not in shown, 'PLANTED CONTROL: the help flag is no part of the shape'
    page = (Path(__file__).resolve().parents[1] / 'docs-src' / 'dev' / 'refusals.md').read_text(encoding='utf-8')
    assert f'`{shown}`' in page
