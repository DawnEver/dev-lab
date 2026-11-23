"""``hpcaccount credential``: a minted forge token staged on a declared key-only account, verified, then placed."""

from __future__ import annotations

import io
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from lab_commons.hpc.cluster import Runner
from lab_commons.hpc.grants import Grant, Machine

from dev_lab.dev._deny_hpc_row import HPC_THROUGH_THE_DOOR
from dev_lab.dev.agentpolicy import exits_of
from dev_lab.dev.credstore import (
    READER_STORE,
    STORE,
    CredentialRefused,
    DeclaredForge,
    Shell,
    digest,
    discard_command,
    drop_held_command,
    held_command,
    named_fill_command,
    place_verified,
    read_forge,
    reader_git,
    restore_command,
    rewrite_command,
    stage_command,
    verify_prefix,
)
from dev_lab.dev.devcredential import local_shell
from dev_lab.dev.hpcaccount import credential
from dev_lab.dev.hpcaccount.account import _READER_REMEDY
from dev_lab.dev.hpcaccount.credential import declared_logins, drop_host, named_login, place_credential, usage
from dev_lab.dev.hpcaccount.division import Division
from dev_lab.dev.sshholdwire import HoldRefused

_HOSTS = ('login1.example', 'login2.example')
_FLEET = (Grant(user='alice', hosts=_HOSTS, slurm_account='acct'),)
_DIVISION = Division(grant_roles={'alice': 'verification'})
_FORGE = DeclaredForge(Path('forge-a.toml'), ('forge.example',), {'forge-ci': ('org/dev-lab',)})
_MINTED = 'f00d' * 10  # a Gitea-shaped token (forgetoken.GITEA)
_REPO = 'https://forge.example/org/dev-lab.git'
_DEPLOY = '[deploy]\nhost = "login1.example"\nroot = "/r/src"\n'
_STAMP = '20261112T120000Z'


def _account(*, answers: str, seen: list[tuple[str, str | None]], deployed: str = _DEPLOY) -> Runner:
    def shell(cmd: str, stdin: str | None = None) -> str:
        seen.append((cmd, stdin))
        if 'credential fill' in cmd:  # a named login's read-back: the stored line returns the placed token
            return _MINTED + chr(10)
        if 'sed -n' in cmd:
            return deployed
        if 'auth role' in cmd:
            return json.dumps({'login': answers, 'push': True, 'admin': False})
        if cmd.startswith('umask 077 && f='):
            name = READER_STORE if f'$HOME/{READER_STORE}"' in cmd else STORE
            return f'backup ~/{name}.bak-{_STAMP}\n'
        return ''

    return shell


def _run(
    account: str = 'alice@login2.example',
    *,
    login: str = 'forge-ci',
    answers: str = 'forge-ci',
    url: str = '',
    division: Division = _DIVISION,
    grants: tuple[Grant, ...] = _FLEET,
    deployed: str = _DEPLOY,
) -> tuple[int, list[str], list[tuple[str, str | None]], list[str]]:
    seen: list[tuple[str, str | None]] = []
    said: list[str] = []
    connected: list[str] = []

    def connect(grant: Grant) -> Runner:
        connected.append(grant.user)
        return _account(answers=answers, seen=seen, deployed=deployed)

    code = place_credential(
        account, login=login, token=_MINTED, url=url, forge=_FORGE, grants=grants, division=division,
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
    assert role.startswith(verify_prefix('forge.example', _STAMP) + 'cd /r/src/repos/dev-lab && ')
    assert f'--url {_REPO}' in role  # the default: the login's first declared repo on the forge
    rewrite = rewrite_command('forge.example', _STAMP, login='forge-ci', staged=True)
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


def test_a_role_with_a_config_reader_also_takes_that_login() -> None:
    """A verification account holds forge-ci AND the config source's reader, one store line each (2026-11-20).

    PLANTED CONTROL: a third declared login is still refused for that role.
    """
    roles = {
        'verification': {'reader': 'forge-ci', 'config_reader': 'server-reader'},
        'research': {'reader': 'forge-ro'},
    }
    division = Division(grant_roles={'alice': 'verification'}, roles=roles)
    assert _run(division=division)[0] == 0
    assert _run(division=division, login='server-reader', answers='server-reader', url=_REPO)[0] == 0
    code, said, _, connected = _run(division=division, login='forge-ro', answers='forge-ro', url=_REPO)
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
    monkeypatch.setattr(credential, 'reached_machine', lambda _accounts: pytest.fail('loaded before the forge'))
    monkeypatch.setattr(credential, 'place_credential', lambda *_a, **_k: pytest.fail('placed without a forge'))
    monkeypatch.setattr('sys.stdin', io.StringIO(_MINTED))
    code = credential.main(['alice@login1.example', '--login', 'forge-ci', '--host-config', str(tmp_path / 'no.toml')])
    assert code == 2
    said = capsys.readouterr()
    assert 'no.toml' in said.out + said.err


def test_a_host_name_that_is_no_host_is_refused() -> None:
    with pytest.raises(ValueError, match='not a forge host'):
        rewrite_command("forge.example' ; rm -rf ~ ; '", _STAMP, login='forge-ci', staged=False)
    with pytest.raises(ValueError, match='not a forge login'):
        rewrite_command('forge.example', _STAMP, login="ci' ; rm -rf ~ ; '", staged=False)
    with pytest.raises(ValueError, match='not a timestamp'):
        stage_command('$(reboot)')


_BASH = shutil.which('bash')
_OLD = 'x'  # a stale credential's placeholder


def _stored(login: str, host: str, held: str = _OLD) -> str:
    """One ``~/.git-credentials`` line, assembled from parts so no fixture reads as an email address."""
    return f'https://{login}:{held}' + '@' + host


def _bash(tmp_path: Path, command: str, stdin: str = '') -> str:
    assert _BASH, 'every login host runs these commands in bash'
    env = {**os.environ, 'HOME': tmp_path.as_posix(), 'GIT_TERMINAL_PROMPT': '0', 'GIT_CONFIG_NOSYSTEM': '1'}
    env['GIT_CONFIG_GLOBAL'] = (tmp_path / '.gitconfig').as_posix()  # never the machine's global config
    done = subprocess.run([_BASH, '-c', command], input=stdin.encode(), env=env, check=False, capture_output=True)
    assert done.returncode == 0, done.stderr.decode()
    return done.stdout.decode()  # bytes both ways: a text pipe on Windows writes CRLF


def test_stage_then_rewrite_replaces_only_its_forge_line_after_a_backup(tmp_path: Path) -> None:
    store = tmp_path / '.git-credentials'
    other = _stored('u', 'github.com')
    lookalike = _stored('v', 'forge.example.evil')  # PLANTED CONTROL: a host merely starting with it is kept
    reader = _stored('server-reader', 'forge.example')  # PLANTED CONTROL: another login on the same host is kept
    prefixed = _stored('forge-ci-old', 'forge.example')  # PLANTED CONTROL: a login merely starting with it is kept
    before = f'{_stored("forge-ci", "forge.example")}\n{other}\n{lookalike}\n{reader}\n{prefixed}\n'
    store.write_text(before, encoding='utf-8')
    line = _stored('forge-ci', 'forge.example', _MINTED)
    _bash(tmp_path, stage_command(_STAMP), line + '\n')
    assert store.read_text(encoding='utf-8') == before  # staging never touches the store
    said = _bash(tmp_path, rewrite_command('forge.example', _STAMP, login='forge-ci', staged=True))
    assert store.read_text(encoding='utf-8').splitlines() == [line, other, lookalike, reader, prefixed]
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
    asked = (
        verify_prefix('forge.example', _STAMP)
        + "printf 'protocol=https\\nhost=forge.example\\n\\n' | git credential fill"
    )
    assert f'password={_MINTED}' in _bash(tmp_path, asked)


def test_a_url_scoped_helper_in_the_global_config_does_not_shadow_the_staged_file(tmp_path: Path) -> None:
    """PLANTED CONTROL: the host-scoped list ``use_store`` writes reads the live store; the env entries come last."""
    (tmp_path / '.git-credentials').write_text(_stored('old', 'forge.example') + '\n', encoding='utf-8', newline='\n')
    gitconfig = tmp_path / '.gitconfig'
    gitconfig.write_text('[credential "https://forge.example"]\n\thelper =\n\thelper = store\n', encoding='utf-8')
    _bash(tmp_path, stage_command(_STAMP), _stored('forge-ci', 'forge.example', _MINTED) + '\n')
    ask = "printf 'protocol=https\nhost=forge.example\n\n' | git credential fill"
    env = f'export GIT_CONFIG_GLOBAL={gitconfig.as_posix()} GIT_CONFIG_NOSYSTEM=1 && '
    assert f'password={_OLD}\n' in _bash(tmp_path, env + ask)  # the control: unprefixed, the live store answers
    answered = _bash(tmp_path, env + verify_prefix('forge.example', _STAMP) + ask)
    assert f'password={_MINTED}\n' in answered
    assert f'password={_OLD}\n' not in answered


def test_a_native_git_under_the_verify_prefix_reads_the_staged_file(tmp_path: Path) -> None:
    """The role check is a native Python running git: an MSYS ``/c/...`` path in the env reached it unconverted.

    PLANTED CONTROL: no live store, so a staged file git cannot open answers nothing -- anonymous (2026-11-12).
    """
    _bash(tmp_path, stage_command(_STAMP), _stored('forge-ci', 'forge.example', _MINTED) + '\n')
    fill = (
        "import subprocess; print(subprocess.run(['git', 'credential', 'fill'], capture_output=True, text=True, "
        "input='protocol=https\\nhost=forge.example\\n\\n').stdout)"
    )
    asked = verify_prefix('forge.example', _STAMP) + shlex.join([Path(sys.executable).as_posix(), '-c', fill])
    assert f'password={_MINTED}' in _bash(tmp_path, asked)


def test_drop_host_removes_exactly_that_line_after_a_backup(tmp_path: Path) -> None:
    """The repair door: only the named host+login line goes; a look-alike host or another login stays (CONTROLS)."""
    store = tmp_path / '.git-credentials'
    keep = [_stored('v', 'github.com.evil'), _stored('w', 'forge.example'), _stored('t', 'github.com')]
    before = '\n'.join([_stored('u', 'github.com'), *keep]) + '\n'
    store.write_text(before, encoding='utf-8')
    said: list[str] = []
    code = drop_host(
        'alice@login1.example', host='github.com', login='u', grants=_FLEET, say=said.append, stamp=_STAMP,
        connect=lambda _grant: lambda cmd, _stdin=None: _bash(tmp_path, cmd),
    )  # fmt: skip
    assert code == 0
    assert store.read_text(encoding='utf-8').splitlines() == keep
    assert (tmp_path / f'.git-credentials.bak-{_STAMP}').read_text(encoding='utf-8') == before
    assert f'.git-credentials.bak-{_STAMP}' in said[-1]


def test_drop_host_refuses_an_undeclared_account() -> None:
    said: list[str] = []
    code = drop_host(
        'mallory@login1.example', host='github.com', login='u', grants=_FLEET, say=said.append,
        connect=lambda _grant: pytest.fail('connected for an undeclared account'),
    )  # fmt: skip
    assert code == 2


def test_credential_is_an_exit_of_hpc_through_the_door() -> None:
    assert 'credential' in exits_of('HPC-THROUGH-THE-DOOR', 'dev_lab.dev.hpcaccount')
    assert 'hpcaccount <verb>' in str(HPC_THROUGH_THE_DOOR['remedy'])


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


def test_the_local_shell_writes_a_staged_line_with_lf_only(tmp_path: Path) -> None:
    """A text-mode pipe on Windows turns the staged LF into CR LF; git's store then matches no host.

    PLANTED: the file the stage command writes must end with exactly one LF and hold no CR.
    """
    target = tmp_path / 'staged'
    local_shell(f'IFS= read -r line && printf "%s\\n" "$line" > "{target.as_posix()}"', 'a-line\n')
    assert target.read_bytes() == b'a-line\n'


def test_a_research_account_deployed_behind_its_login_alias_takes_its_credential() -> None:
    """A research account records the grant's alias as its [deploy] host (no node pin: it installs no cron).

    PLANTED CONTROL: the node it happened to land on is not a login host of the grant and is refused.
    """
    aliased = (Grant(user='alice', hosts=('login.example',), slurm_account='acct', role='research'),)
    division = Division(grant_roles={'alice': 'research'})
    alias = '[deploy]\nhost = "login.example"\nroot = "/r/src"\n'
    code, said, _, _ = _run('alice@login.example', grants=aliased, division=division, deployed=alias)
    assert code == 0, said
    node = '[deploy]\nhost = "login04"\nroot = "/r/src"\n'
    code, said, _, _ = _run('alice@login.example', grants=aliased, division=division, deployed=node)
    assert code == 2
    assert 'login04' in said[-1]


class _Unread(io.StringIO):
    def read(self, size: int | None = -1, /) -> str:
        pytest.fail('the token was read before the account was proven reachable')


def test_an_unreachable_account_is_refused_loudly_before_the_token_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A dead hold refuses, non-zero, naming its cause -- before stdin is read, so the caller keeps the token.

    Measured 2026-11-20: with the account's held session dead, a placement printed nothing and exited 0, and the
    caller deleted a token that never arrived. PLANTED CONTROL: a reachable account goes on to read the token.
    """
    monkeypatch.setattr(credential, 'reached_machine', lambda _a: Machine(session=None, grants=_FLEET, roles={}))

    def dead(_grant: Grant, _timeout: float = 0, **_k: str) -> Runner:
        msg = 'the held session of alice@login1.example is recorded but its holder does not answer'
        raise HoldRefused(msg)

    monkeypatch.setattr(credential, 'grant_runner', dead)
    monkeypatch.setattr('sys.stdin', _Unread())
    argv = ['alice@login1.example', '--login', 'forge-ci', '--host-config', str(_host_config(tmp_path))]
    assert credential.main(argv) == 2
    said = capsys.readouterr()
    assert 'holder does not answer' in said.out + said.err
    assert 'the token stays with you' in said.out + said.err
    placed: list[str] = []
    monkeypatch.setattr(credential, 'grant_runner', lambda _g, _t=0, **_k: lambda _c, _s=None: '')
    monkeypatch.setattr(credential, 'place_credential', lambda *_a, **k: placed.append(k['token']) or 0)
    monkeypatch.setattr('sys.stdin', io.StringIO(_MINTED))
    assert credential.main(argv) == 0
    assert placed == [_MINTED]


def test_a_placed_store_line_is_read_because_the_store_helper_is_set_when_none_is() -> None:
    """A store line git never consults reads as anonymous.

    Measured 2026-11-20: three research accounts took a verified reader line, then the deploy's ``git ls-remote``
    of the private forge repos still exited 128 -- no global ``credential.helper``, so git never read the store.
    The placement sets ``store`` when NO helper is configured, after the rewrite; PLANTED CONTROL: it never
    overrides one already set (the command keeps a configured helper).
    """
    code, _said, seen, _ = _run()
    assert code == 0
    commands = [cmd for cmd, _ in seen]
    helper = next(cmd for cmd in commands if 'credential.helper' in cmd and 'config --global' in cmd)
    assert commands.index(rewrite_command('forge.example', _STAMP, login='forge-ci', staged=True)) < commands.index(
        helper
    )
    assert '[ -n "$(git config --global --get-all credential.helper)" ] ||' in helper
    assert 'git config --global credential.helper store' in helper


def _failover_account(seen: list[tuple[str, str | None]]) -> Runner:
    """An account whose store write landed nowhere: the staged check answers, the stored line reads as anonymous."""
    honest = _account(answers='forge-ci', seen=seen)

    def shell(cmd: str, stdin: str | None = None) -> str:
        if 'auth role' in cmd and not cmd.startswith(verify_prefix('forge.example', _STAMP)):
            seen.append((cmd, stdin))
            return json.dumps({'login': None})
        return honest(cmd, stdin)

    return shell


def test_a_placement_the_stored_line_does_not_answer_is_refused_without_a_success_line() -> None:
    """Measured 2026-11-20: after a login-node failover a placement printed nothing and the token was deleted.

    The STORED line is read back (the forge's ``auth role`` through git's own helper, no staged file) and must
    answer as the login; PLANTED: a store that reads as anonymous exits non-zero and says no ``verified``.
    """
    seen: list[tuple[str, str | None]] = []
    said: list[str] = []
    code = place_credential(
        'alice@login2.example', login='forge-ci', token=_MINTED, url='', forge=_FORGE, grants=_FLEET,
        division=_DIVISION, say=said.append, connect=lambda _g: _failover_account(seen), stamp=_STAMP,
    )  # fmt: skip
    assert code == 2
    assert not any('verified' in line and 'not verified' not in line for line in said)
    assert 'anonymous' in said[-1]
    code, said, _, _ = _run()
    assert code == 0
    assert said[-1].startswith('verified: ')


def _main_from_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, placed: int) -> tuple[int, Path]:
    out = tmp_path / 'state' / 'consent' / 'outputs' / 'forge-ci-reader.token'
    out.parent.mkdir(parents=True)
    out.write_text(_MINTED + '\n', encoding='utf-8')
    monkeypatch.setattr(credential, 'stdout_path', lambda name: out.parent / name)
    monkeypatch.setattr(credential, 'reached_machine', lambda _a: Machine(session=None, grants=_FLEET, roles={}))
    monkeypatch.setattr(credential, 'grant_runner', lambda _g, _t=0, **_k: lambda _c, _s=None: '')
    tokens: list[str] = []
    monkeypatch.setattr(credential, 'place_credential', lambda *_a, **k: tokens.append(k['token']) or placed)
    monkeypatch.setattr('sys.stdin', _Unread())
    argv = ['alice@login1.example', '--login', 'forge-ci', '--host-config', str(_host_config(tmp_path))]
    code = credential.main([*argv, '--from-output', out.name])
    assert tokens == [_MINTED]
    return code, out


def test_from_output_removes_the_consent_output_only_after_a_verified_placement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The door, not the caller, deletes the minted token; PLANTED: a failed placement keeps the file."""
    code, out = _main_from_output(tmp_path, monkeypatch, placed=2)
    assert code == 2
    assert out.exists()


def test_from_output_deletes_the_file_after_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    code, out = _main_from_output(tmp_path, monkeypatch, placed=0)
    assert code == 0
    assert not out.exists()


def test_from_output_refuses_a_name_with_a_path_part(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(credential, 'reached_machine', lambda _a: Machine(session=None, grants=_FLEET, roles={}))
    argv = ['alice@login1.example', '--login', 'forge-ci', '--host-config', str(_host_config(tmp_path))]
    assert credential.main([*argv, '--from-output', '../x.token']) == 2


def test_an_account_deployed_at_an_old_root_still_takes_its_credential() -> None:
    """Measured 2026-11-20, a deadlock: a stale [deploy] root refused the credential the redeploy itself needs.

    The credential refused an account whose root predates its cluster's declared root ("redeploy with --root"),
    while that redeploy refused for want of the very credential.

    The store is home-level, so the placement acts on the checkout as deployed. PLANTED CONTROL: the deploy-side read
    (no ``as_deployed``) still refuses the same stale root.
    """
    rooted = (Grant(user='alice', hosts=_HOSTS, slurm_account='acct', root='/r/declared/lab'),)
    old = '[deploy]\nhost = "login2.example"\nroot = "/r/old/lab-forge"\n'
    code, said, seen, _ = _run(grants=rooted, deployed=old)
    assert code == 0, said
    assert any('cd /r/old/lab-forge/repos/dev-lab && ' in cmd for cmd, _ in seen)
    stale = credential.declared_target(rooted[0], lambda _c, _s=None: old)
    assert isinstance(stale, str)
    assert 'is not the root its cluster declares' in stale


def test_an_account_deployed_at_an_old_home_relative_root_still_takes_its_credential() -> None:
    """Measured 2026-11-20 (ezxmw9): root '.local/share/lab-forge/repos' was refused "must be an absolute path".

    The pre-root layout held checkouts at ``~/<root>/<name>``; the home-level store needs only that checkout.
    PLANTED CONTROL: the deploy-side read (no ``as_deployed``) still refuses the relative root by name.
    """
    rooted = (Grant(user='alice', hosts=_HOSTS, slurm_account='acct', root='/r/declared/lab'),)
    old = '[deploy]\nhost = "login2.example"\nroot = ".local/share/lab-forge/repos"\n'
    code, said, seen, _ = _run(grants=rooted, deployed=old)
    assert code == 0, said
    assert any('cd ~/.local/share/lab-forge/repos/dev-lab && ' in cmd for cmd, _ in seen)
    stale = credential.declared_target(rooted[0], lambda _c, _s=None: old)
    assert isinstance(stale, str)
    assert 'must be an absolute path' in stale


_WRITER_AND_READER = Division(
    grant_roles={'alice': 'verification'},
    roles={'verification': {'serves': True, 'read_only': False, 'config_reader': 'server-reader'}},
)


def _place_line(tmp_path: Path, login: str, token: str, *, store: str = STORE) -> None:
    _bash(tmp_path, stage_command(_STAMP), _stored(login, 'forge.example', token) + '\n')
    _bash(tmp_path, rewrite_command('forge.example', _STAMP, login=login, staged=True, store=store))


def _unnamed_password(tmp_path: Path) -> str:
    asked = "printf 'protocol=https\\nhost=forge.example\\n\\n' | git credential fill | sed -n 's/^password=//p'"
    return _bash(tmp_path, asked).strip()


def _real(tmp_path: Path) -> Shell:
    return lambda cmd, stdin=None: _bash(tmp_path, cmd, stdin or '')


@pytest.mark.parametrize('order', [('forge-ci', 'server-reader'), ('server-reader', 'forge-ci')])
def test_two_logins_on_one_host_each_answer_their_own_request(tmp_path: Path, order: tuple[str, str]) -> None:
    """Two logins on one host: the unnamed request answers as the writer, a request naming the reader as the reader.

    Measured 2026-11-21 on the verification accounts: with the writer and the config reader in one store, git's
    ``store`` returned the FIRST line to the serve's unnamed request -- and (2026-11-22) git moves a line first each
    time it approves it, so no order lasts. The reader is placed in its own file, in either placement order, even
    over a store that still holds its old line. PLANTED CONTROL: the reader placed in the shared store takes the
    unnamed request.
    """
    _bash(tmp_path, 'git config --global credential.helper store')
    tokens = {'forge-ci': 'a1' * 20, 'server-reader': 'b2' * 20}
    (tmp_path / STORE).write_text(_stored('server-reader', 'forge.example') + '\n', encoding='utf-8', newline='\n')
    for login in order:
        refusal, _backup = place_verified(
            _real(tmp_path), login=login, token=tokens[login], repo=_REPO, stamp=_STAMP,
            role=f"echo '{json.dumps({'login': login})}'", named=named_login(_WRITER_AND_READER, 'alice', login),
        )  # fmt: skip
        assert not refusal
    assert (tmp_path / STORE).read_text(encoding='utf-8').splitlines() == [
        _stored('forge-ci', 'forge.example', tokens['forge-ci'])
    ]
    assert (tmp_path / READER_STORE).read_text(encoding='utf-8').splitlines() == [
        _stored('server-reader', 'forge.example', tokens['server-reader'])
    ]
    assert _unnamed_password(tmp_path) == tokens['forge-ci']
    assert _bash(tmp_path, named_fill_command('forge.example', 'server-reader')).strip() == tokens['server-reader']
    assert _bash(tmp_path, held_command('forge.example', 'server-reader')) == ''
    _place_line(tmp_path, 'server-reader', tokens['server-reader'])
    assert _bash(tmp_path, held_command('forge.example', 'server-reader')).strip() == 'held'
    assert _unnamed_password(tmp_path) == tokens['server-reader']


def test_only_a_config_reader_distinct_from_the_unnamed_login_is_named() -> None:
    assert named_login(_WRITER_AND_READER, 'alice', 'server-reader')
    assert not named_login(_WRITER_AND_READER, 'alice', 'forge-ci')
    research = {'reader': 'server-reader', 'config_reader': 'server-reader'}
    same = Division(grant_roles={'alice': 'r'}, roles={'r': research})
    assert not named_login(same, 'alice', 'server-reader')  # PLANTED: a research reader IS the unnamed login
    assert not named_login(_DIVISION, 'alice', '')  # PLANTED: a role naming no config reader names nobody


def _reading(fill: str, held: str, seen: list[tuple[str, str | None]]) -> Runner:
    """An account whose reader file answers a named fill with *fill* and whose store says *held* for the reader."""
    honest = _account(answers='server-reader', seen=seen)

    def shell(cmd: str, stdin: str | None = None) -> str:
        if 'credential fill' in cmd:
            seen.append((cmd, stdin))
            return fill + '\n'
        if cmd == held_command('forge.example', 'server-reader'):
            return held
        if 'auth role' in cmd and not cmd.startswith(verify_prefix('forge.example', _STAMP)):
            return json.dumps({'login': 'forge-ci'})  # the unnamed request: the writer's line
        return honest(cmd, stdin)

    return shell


def test_a_config_reader_is_read_back_by_a_request_naming_it() -> None:
    """A config reader's line is read back from ITS file by a fill naming it, never by the unnamed ``auth role``.

    The forge's ``auth role`` asks for the host alone, so it answers as the writer even when the reader's line was
    placed right: the read-back of a named login is the fill its own git calls make, which must return the placed
    token. PLANTED CONTROLS: a fill returning another token is refused, and so is a shared store that still holds
    a line for the reader -- the shape the reader's next pull turns into the wrong writer.
    """
    forge = DeclaredForge(Path('f.toml'), ('forge.example',), {'forge-ci': ('org/dev-lab',)})
    for fill, held, code in ((_MINTED, '', 0), ('stale-token', '', 2), (_MINTED, 'held\n', 2)):
        seen: list[tuple[str, str | None]] = []
        said: list[str] = []
        got = place_credential(
            'alice@login2.example', login='server-reader', token=_MINTED, url=_REPO, forge=forge, grants=_FLEET,
            division=_WRITER_AND_READER, say=said.append, stamp=_STAMP,
            connect=lambda _g, f=fill, h=held, s=seen: _reading(f, h, s),
        )  # fmt: skip
        assert got == code, said
        commands = [cmd for cmd, _ in seen]
        placed = rewrite_command('forge.example', _STAMP, login='server-reader', staged=True, store=READER_STORE)
        assert placed in commands
        assert drop_held_command('forge.example', _STAMP, login='server-reader') in commands
        assert rewrite_command('forge.example', _STAMP, login='server-reader', staged=True) not in commands
        assert ('.git-credentials.reader answers' in said[-1]) == (code == 0)
        if held:
            assert 'must hold no line' in said[-1]
    assert reader_git('forge.example') in named_fill_command('forge.example', 'server-reader')


def _shadowing(after: str, seen: list[tuple[str, str | None]], *, held: str) -> Runner:
    """An account whose unnamed request answers as the writer until a file is rewritten, then as *after*.

    *held*: the store backup printed when its shared store still holds the reader's line (``''``: it does not).
    """
    honest = _account(answers='server-reader', seen=seen)

    def shell(cmd: str, stdin: str | None = None) -> str:
        if 'auth role' in cmd and not cmd.startswith(verify_prefix('forge.example', _STAMP)):
            seen.append((cmd, stdin))
            rewritten = any(c.startswith('umask 077 && f=') and 'grep -v' in c for c, _ in seen)
            return json.dumps({'login': after if rewritten else 'forge-ci'})
        if cmd == drop_held_command('forge.example', _STAMP, login='server-reader'):
            seen.append((cmd, stdin))
            return held
        return honest(cmd, stdin)

    return shell


@pytest.mark.parametrize('held', [f'backup ~/.git-credentials.bak-{_STAMP}', ''])
def test_a_named_reader_that_takes_the_unnamed_request_is_refused_and_the_store_restored(held: str) -> None:
    """Placing a named reader never changes who answers the host's unnamed request -- the one a serve posts with.

    Measured 2026-11-22 on two verification accounts: the reader's own line read back right (git's fill naming it),
    so the placement said ``verified`` while the unnamed request answered as the reader, and every tick was then
    refused "no push permission". The unnamed request is asked before and after; a changed answer names both
    logins, and puts the store back from the placement's backup when the placement wrote the store (*held*).
    PLANTED CONTROL: the writer still answering is verified and nothing is restored.
    """
    restore = restore_command(_STAMP)
    for after, code in (('forge-ci', 0), ('server-reader', 2)):
        seen: list[tuple[str, str | None]] = []
        said: list[str] = []
        got = place_credential(
            'alice@login2.example', login='server-reader', token=_MINTED, url=_REPO, forge=_FORGE, grants=_FLEET,
            division=_WRITER_AND_READER, say=said.append, stamp=_STAMP,
            connect=lambda _g, a=after, s=seen: _shadowing(a, s, held=held),
        )  # fmt: skip
        assert got == code, said
        assert (restore in [cmd for cmd, _ in seen]) == (code == 2 and bool(held))
        if code:
            assert 'forge-ci' in said[-1]
            assert 'server-reader' in said[-1]
            assert 'as it was before this placement' in said[-1]


def test_the_restore_puts_the_backed_up_store_back(tmp_path: Path) -> None:
    """The restore is the backup, whole: the shadowing line is gone and the writer answers the unnamed request."""
    _bash(tmp_path, 'git config --global credential.helper store')
    _place_line(tmp_path, 'forge-ci', 'writer-TOKEN')
    _place_line(tmp_path, 'server-reader', 'reader-TOKEN')  # PLANTED: the shadow the door refuses
    assert _unnamed_password(tmp_path) == 'reader-TOKEN'
    _bash(tmp_path, restore_command(_STAMP))
    assert _unnamed_password(tmp_path) == 'writer-TOKEN'
    assert _bash(tmp_path, held_command('forge.example', 'server-reader')) == ''


def test_drop_host_removes_the_logins_line_from_the_reader_file_too(tmp_path: Path) -> None:
    """The repair door reaches both files. PLANTED CONTROL: the writer's line, in the store, stays."""
    _place_line(tmp_path, 'forge-ci', 'writer-TOKEN')
    _place_line(tmp_path, 'server-reader', 'reader-TOKEN', store=READER_STORE)
    said: list[str] = []
    code = drop_host(
        'alice@login1.example', host='forge.example', login='server-reader', grants=_FLEET, say=said.append,
        stamp=_STAMP, connect=lambda _grant: _real(tmp_path),
    )  # fmt: skip
    assert code == 0
    assert (tmp_path / READER_STORE).read_text(encoding='utf-8') == ''
    assert (tmp_path / STORE).read_text(encoding='utf-8').splitlines() == [
        _stored('forge-ci', 'forge.example', 'writer-TOKEN')
    ]
    assert f'{READER_STORE}.bak-{_STAMP}' in said[-1]


def test_a_token_not_of_its_forge_kind_shape_stages_nothing_on_the_account() -> None:
    """PLANTED CONTROL: ``_MINTED`` (Gitea-shaped) is staged and verified above; a wrong-shaped token never is."""
    seen: list[str] = []

    def shell(command: str, _stdin: str | None) -> str:
        seen.append(command)
        return ''

    wrong = 'tok3n-SECRET-value'
    refusal, backup = place_verified(shell, login='forge-ci', token=wrong, repo=_REPO, role='true')
    assert 'does not match the declared shape' in refusal
    assert (seen, backup) == ([], '')
