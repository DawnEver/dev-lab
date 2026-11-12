"""``hpcaccount credential``: a minted forge token staged on a declared key-only account, verified, then placed."""

from __future__ import annotations

import io
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
from dev_lab.dev.hpcaccount import credential
from dev_lab.dev.hpcaccount.account import _READER_REMEDY
from dev_lab.dev.hpcaccount.credential import (
    CredentialRefused,
    DeclaredForge,
    declared_logins,
    digest,
    discard_command,
    drop_host,
    place_credential,
    read_forge,
    rewrite_command,
    stage_command,
    usage,
    verify_prefix,
)
from dev_lab.dev.hpcaccount.division import Division

_HOSTS = ('login1.example', 'login2.example')
_FLEET = (Grant(user='alice', hosts=_HOSTS, slurm_account='acct'),)
_DIVISION = Division(grant_roles={'alice': 'verification'})
_FORGE = DeclaredForge(Path('forge-a.toml'), ('forge.example',), {'forge-ci': ('org/dev-lab',)})
_MINTED = 'tok3n-SECRET-value'
_REPO = 'https://forge.example/org/dev-lab.git'
_DEPLOY = '[deploy]\nhost = "login1.example"\nroot = "src"\n'
_STAMP = '20261112T120000Z'


def _account(*, answers: str, seen: list[tuple[str, str | None]]) -> Runner:
    def shell(cmd: str, stdin: str | None = None) -> str:
        seen.append((cmd, stdin))
        if 'sed -n' in cmd:
            return _DEPLOY
        if 'auth role' in cmd:
            return json.dumps({'login': answers, 'push': True, 'admin': False})
        if cmd.startswith('umask 077 && f='):
            return 'backup ~/.git-credentials.bak-' + _STAMP + '\n'
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
        account, login=login, token=_MINTED, url=url, forge=_FORGE, grants=_FLEET, division=division,
        say=said.append, connect=connect, stamp=_STAMP,
    )  # fmt: skip
    return code, said, seen, connected


def test_the_token_is_staged_verified_then_placed() -> None:
    code, said, seen, connected = _run()
    assert code == 0
    assert connected == ['alice']
    commands = [cmd for cmd, _ in seen]
    staged = [(cmd, stdin) for cmd, stdin in seen if stdin]
    assert staged == [(stage_command(_STAMP), f'https://forge-ci:{_MINTED}@forge.example\n')]
    role = next(cmd for cmd in commands if 'auth role' in cmd)
    assert role.startswith(verify_prefix(_STAMP) + 'cd ~/src/dev-lab && ')
    assert f'--url {_REPO}' in role  # the default: the login's first declared repo on the forge
    rewrite = rewrite_command('forge.example', _STAMP, staged=True)
    assert commands.index(role) < commands.index(rewrite)  # verified BEFORE the store is touched
    assert all(_MINTED not in cmd for cmd in commands)  # never in the remote argv
    assert all(_MINTED not in line for line in said)  # never printed
    assert digest(_MINTED) in said[-1]
    assert '.git-credentials.bak-' + _STAMP in said[-1]


def test_a_url_off_the_declared_forge_is_refused_before_any_connection() -> None:
    """PLANTED CONTROL: the account's GitHub origin for a forge login -- the line it once destroyed."""
    code, said, seen, connected = _run(url='https://github.com/org/dev-lab.git')
    assert (code, connected, seen) == (2, [], [])
    assert 'github.com' in said[0]


def test_a_url_on_the_declared_forge_is_taken() -> None:
    code, _, seen, _ = _run(url='https://forge.example/org/other.git')
    assert code == 0
    assert any('--url https://forge.example/org/other.git' in cmd for cmd, _ in seen)


def test_a_forge_answering_as_another_login_leaves_the_store_untouched() -> None:
    """PLANTED CONTROL: the staged token is somebody else's -- discarded, never moved into place."""
    code, said, seen, _ = _run(answers='mallory')
    assert code == 2
    commands = [cmd for cmd, _ in seen]
    assert discard_command(_STAMP) in commands
    assert not any(cmd.startswith('umask 077 && f=') for cmd in commands)
    assert 'mallory' in said[-1]
    assert 'untouched' in said[-1]


def test_an_undeclared_login_is_refused_before_any_connection() -> None:
    """PLANTED CONTROL: a login neither [hpc.roles] nor [ops.forge.accounts] declares."""
    code, said, _, connected = _run(login='intruder', url=_REPO)
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


_HOST_CONFIG = """[ops]
home = "/srv/ops"
python = "/usr/bin/python3"

[ops.caddy]
allow = ["127.0.0.1/32"]
sites = ["forge.example"]

[ops.forge]
api = "http://127.0.0.1:3000"
admin = "root"

[ops.forge.accounts.forge-ci]
role = "write"
repos = ["org/dev-lab"]
"""


def _host_config(tmp_path: Path, text: str = _HOST_CONFIG) -> Path:
    path = tmp_path / 'forge-a.toml'
    path.write_text(text, encoding='utf-8')
    return path


def test_the_forge_is_read_from_the_host_config(tmp_path: Path) -> None:
    """The forge host's reviewed config is the one source of its site and accounts; this machine holds no copy."""
    forge = read_forge(_host_config(tmp_path))
    assert (forge.sites, dict(forge.accounts)) == (('forge.example',), {'forge-ci': ('org/dev-lab',)})
    division = Division(grant_roles={}, roles={'research': {'reader': 'forge-ro'}, 'verification': {}})
    assert declared_logins(division, forge) == {'forge-ro', 'forge-ci'}
    assert 'intruder' not in declared_logins(_DIVISION, forge)  # PLANTED CONTROL: read, not everything-goes


def test_an_unreadable_host_config_is_refused_naming_it(tmp_path: Path) -> None:
    """PLANTED CONTROL: never an empty set that refuses every login silently."""
    with pytest.raises(CredentialRefused, match=r'absent\.toml'):
        read_forge(tmp_path / 'absent.toml')


@pytest.mark.parametrize('cut', ['[ops.caddy]', '[ops.forge]'])
def test_a_host_config_without_a_forge_site_or_accounts_is_refused_naming_it(tmp_path: Path, cut: str) -> None:
    """PLANTED CONTROL: a host file that is not the forge's declares no login and no site to place for."""
    head, _, tail = _HOST_CONFIG.partition(cut)
    text = head + (tail.partition('[ops.forge]')[1] + tail.partition('[ops.forge]')[2] if cut == '[ops.caddy]' else '')
    with pytest.raises(CredentialRefused, match=r'forge-a\.toml.*\[ops\.forge\.accounts\]'):
        read_forge(_host_config(tmp_path, text))


def test_no_url_and_no_declared_repo_is_refused() -> None:
    forge = DeclaredForge(Path('f.toml'), ('forge.example',), {'forge-ci': ()})
    with pytest.raises(CredentialRefused, match='give --url'):
        forge.url_for('forge-ci', '')


def test_main_refuses_an_unreadable_host_config_before_any_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(credential, 'section', lambda name: {'grant': []} if name == 'hpc' else {})
    monkeypatch.setattr(credential, 'place_credential', lambda *_a, **_k: pytest.fail('placed without a forge'))
    monkeypatch.setattr('sys.stdin', io.StringIO(_MINTED))
    code = credential.main(['alice@login1.example', '--login', 'forge-ci', '--host-config', str(tmp_path / 'no.toml')])
    assert code == 2
    said = capsys.readouterr()
    assert 'no.toml' in said.out + said.err


def test_a_host_name_that_is_no_host_is_refused() -> None:
    with pytest.raises(ValueError, match='not a forge host'):
        rewrite_command("forge.example' ; rm -rf ~ ; '", _STAMP, staged=False)
    with pytest.raises(ValueError, match='not a timestamp'):
        stage_command('$(reboot)')


_BASH = shutil.which('bash')
_OLD = 'x'  # a stale credential's placeholder


def _stored(login: str, host: str, held: str = _OLD) -> str:
    """One ``~/.git-credentials`` line, assembled from parts so no fixture reads as an email address."""
    return f'https://{login}:{held}' + '@' + host


def _bash(tmp_path: Path, command: str, stdin: str = '') -> str:
    assert _BASH, 'every login host runs these commands in bash'
    env = {**os.environ, 'HOME': tmp_path.as_posix(), 'GIT_TERMINAL_PROMPT': '0'}
    done = subprocess.run([_BASH, '-c', command], input=stdin.encode(), env=env, check=False, capture_output=True)
    assert done.returncode == 0, done.stderr.decode()
    return done.stdout.decode()  # bytes both ways: a text pipe on Windows writes CRLF


def test_stage_then_rewrite_replaces_only_its_forge_line_after_a_backup(tmp_path: Path) -> None:
    store = tmp_path / '.git-credentials'
    other = _stored('u', 'github.com')
    lookalike = _stored('v', 'forge.example.evil')  # PLANTED CONTROL: a host merely starting with it is kept
    before = f'{_stored("old", "forge.example")}\n{other}\n{lookalike}\n'
    store.write_text(before, encoding='utf-8')
    line = _stored('forge-ci', 'forge.example', _MINTED)
    _bash(tmp_path, stage_command(_STAMP), line + '\n')
    assert store.read_text(encoding='utf-8') == before  # staging never touches the store
    said = _bash(tmp_path, rewrite_command('forge.example', _STAMP, staged=True))
    assert store.read_text(encoding='utf-8').splitlines() == [other, lookalike, line]
    backup = tmp_path / f'.git-credentials.bak-{_STAMP}'
    assert backup.read_text(encoding='utf-8') == before
    assert backup.name in said
    assert sorted(p.name for p in tmp_path.iterdir()) == ['.git-credentials', backup.name]  # staged file consumed


def test_a_discarded_stage_leaves_the_store_as_it_was(tmp_path: Path) -> None:
    store = tmp_path / '.git-credentials'
    store.write_text(_stored('u', 'github.com') + '\n', encoding='utf-8')
    _bash(tmp_path, stage_command(_STAMP), _stored('forge-ci', 'forge.example', _MINTED) + '\n')
    _bash(tmp_path, discard_command(_STAMP))
    assert [p.name for p in tmp_path.iterdir()] == ['.git-credentials']
    assert store.read_text(encoding='utf-8') == _stored('u', 'github.com') + '\n'


def test_the_verify_prefix_points_git_at_only_the_staged_file(tmp_path: Path) -> None:
    line = _stored('forge-ci', 'forge.example', _MINTED)
    (tmp_path / '.git-credentials').write_text(_stored('old', 'forge.example') + '\n', encoding='utf-8')
    _bash(tmp_path, stage_command(_STAMP), line + '\n')
    # the path spelled as this OS's git reads it (Git for Windows does not read an MSYS ``/c/...`` $HOME)
    prefix = verify_prefix(_STAMP).replace('$HOME', tmp_path.as_posix())
    asked = prefix + "printf 'protocol=https\\nhost=forge.example\\n\\n' | git credential fill"
    assert f'password={_MINTED}' in _bash(tmp_path, asked)


def test_drop_host_removes_exactly_that_line_after_a_backup(tmp_path: Path) -> None:
    """The repair door: only the named host's line goes; a look-alike host stays (PLANTED CONTROL)."""
    store = tmp_path / '.git-credentials'
    keep = [_stored('v', 'github.com.evil'), _stored('w', 'forge.example')]
    before = '\n'.join([_stored('u', 'github.com'), *keep]) + '\n'
    store.write_text(before, encoding='utf-8')
    said: list[str] = []
    code = drop_host(
        'alice@login1.example', host='github.com', grants=_FLEET, say=said.append, stamp=_STAMP,
        connect=lambda _grant: lambda cmd, _stdin=None: _bash(tmp_path, cmd),
    )  # fmt: skip
    assert code == 0
    assert store.read_text(encoding='utf-8').splitlines() == keep
    assert (tmp_path / f'.git-credentials.bak-{_STAMP}').read_text(encoding='utf-8') == before
    assert f'.git-credentials.bak-{_STAMP}' in said[-1]


def test_drop_host_refuses_an_undeclared_account() -> None:
    said: list[str] = []
    code = drop_host(
        'mallory@login1.example', host='github.com', grants=_FLEET, say=said.append,
        connect=lambda _grant: pytest.fail('connected for an undeclared account'),
    )  # fmt: skip
    assert code == 2


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
        'alice@login1.example', login='forge-ci', token='', url='', forge=_FORGE, grants=_FLEET, division=_DIVISION,
        say=said.append, connect=lambda _grant: pytest.fail('connected with no token'),
    )  # fmt: skip
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
