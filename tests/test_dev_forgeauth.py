"""``dev_lab.dev.forgeauth`` -- ``auth login|status`` against a REAL loopback server and a REAL git.

The credential store is git's own ``store`` helper pointed at a file under ``tmp_path``, configured
through ``GIT_CONFIG_GLOBAL`` with the system config masked -- so ``git credential approve`` and
``fill`` run for real and the user's actual credential manager is never reached.
"""

from __future__ import annotations

import base64
import io
import subprocess
import sys
from pathlib import Path

import pytest
from test_dev_forgework import _answer, _Loopback, _Recorder, _repo, server

from dev_lab.dev.forge import Forge, store_credential, token_for
from dev_lab.dev.forgeauth import main
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgework import Client
from dev_lab.dev.netverb import DEFAULT_ATTEMPTS, Disposition

__all__ = ['server']

_PAT = 'pat-0123456789abcdef'


def _isolated_store(tmp_path: Path) -> tuple[dict[str, str], Path]:
    store = tmp_path / 'credentials'
    config = tmp_path / 'gitconfig'
    config.write_text(f'[credential]\n\thelper = "store --file={store.as_posix()}"\n', encoding='utf-8')
    return {'GIT_CONFIG_GLOBAL': str(config), 'GIT_CONFIG_SYSTEM': str(tmp_path / 'absent')}, store


def _no_prompt(_prompt: str) -> str:
    pytest.fail('the token was read from the prompt although --token-stdin was given')


def test_whoami_asks_the_user_endpoint_of_each_backend(server) -> None:
    _answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    _answer('GET', '/user', (200, {'login': 'bob'}))
    transport = _Loopback(server)
    assert Client(Forge('f.example', 'o', 'r'), 'T', transport=transport).whoami() == 'alice'
    assert Client(Forge('github.com', '', ''), 'T', transport=transport).whoami() == 'bob'
    assert [r['headers']['Authorization'] for r in _Recorder.received] == ['token T', 'Bearer T']
    assert transport.asked == ['f.example', 'api.github.com']


def test_login_verifies_then_stores_where_the_fallback_and_git_push_find_it(server, tmp_path, capsys) -> None:
    repo = _repo(tmp_path, 'https://f.example/o/r.git')
    env, store = _isolated_store(tmp_path)
    _answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    code = main(
        ['login', '--token-stdin'], cwd=repo, env=env, transport=_Loopback(server), stdin=io.StringIO(_PAT + '\n')
    )
    assert code == 0
    assert _Recorder.received[0]['headers']['Authorization'] == f'token {_PAT}'
    assert token_for('f.example', cwd=repo, env=env) == _PAT
    assert store.read_text(encoding='utf-8').strip() == f'https://alice:{_PAT}@f.example'
    out = capsys.readouterr()
    assert 'alice' in out.out
    assert _PAT not in out.out + out.err


def test_login_reads_the_token_without_echo_when_no_stdin_flag(server, tmp_path) -> None:
    repo = _repo(tmp_path, 'https://f.example/o/r.git')
    env, _ = _isolated_store(tmp_path)
    _answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    prompts: list[str] = []

    def secret(prompt: str) -> str:
        prompts.append(prompt)
        return _PAT

    assert main(['login'], cwd=repo, env=env, transport=_Loopback(server), read_secret=secret) == 0
    assert len(prompts) == 1
    assert 'f.example' in prompts[0]


def test_a_rejected_token_is_never_stored(server, tmp_path, capsys) -> None:
    repo = _repo(tmp_path, 'https://f.example/o/r.git')
    env, store = _isolated_store(tmp_path)
    _answer('GET', '/api/v1/user', (403, {'message': 'token does not have the required scope'}))
    stdin = io.StringIO(_PAT)
    code = main(['login', '--token-stdin'], cwd=repo, env=env, transport=_Loopback(server), stdin=stdin)
    assert code == 1
    assert not store.exists() or not store.read_text(encoding='utf-8').strip()
    err = capsys.readouterr().err
    assert 'NOT stored' in err
    assert _PAT not in err


def test_an_empty_token_is_refused_before_any_request(server, tmp_path) -> None:
    repo = _repo(tmp_path, 'https://f.example/o/r.git')
    env, _ = _isolated_store(tmp_path)
    code = main(['login', '--token-stdin'], cwd=repo, env=env, transport=_Loopback(server), stdin=io.StringIO('\n'))
    assert code == 2
    assert _Recorder.received == []


def test_host_flag_overrides_origin_and_needs_no_repository(server, tmp_path) -> None:
    env, _ = _isolated_store(tmp_path)
    _answer('GET', '/user', (200, {'login': 'bob'}))
    transport = _Loopback(server)
    stdin = io.StringIO(_PAT)
    argv = ['login', '--host', 'github.com', '--token-stdin']
    assert main(argv, cwd=tmp_path, env=env, transport=transport, stdin=stdin, read_secret=_no_prompt) == 0
    assert transport.asked == ['api.github.com']
    assert token_for('github.com', cwd=tmp_path, env=env) == _PAT


def test_status_names_the_source_and_the_login_and_never_the_secret(server, tmp_path, capsys) -> None:
    repo = _repo(tmp_path, 'https://f.example/o/r.git')
    env, _ = _isolated_store(tmp_path)
    _answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    transport = _Loopback(server)
    main(['login', '--token-stdin'], cwd=repo, env=env, transport=transport, stdin=io.StringIO(_PAT))
    capsys.readouterr()
    assert main(['status'], cwd=repo, env=env, transport=transport) == 0
    out = capsys.readouterr().out
    assert 'git credential' in out
    assert 'alice' in out
    assert _PAT not in out


def test_status_with_no_token_says_how_to_get_one(tmp_path, capsys) -> None:
    repo = _repo(tmp_path, 'https://f.example/o/r.git')
    env, _ = _isolated_store(tmp_path)
    assert main(['status'], cwd=repo, env=env) == 1
    assert 'auth login' in capsys.readouterr().err


def test_the_forge_module_routes_auth_to_this_door() -> None:
    done = subprocess.run(
        [sys.executable, '-m', 'dev_lab.dev.forge', 'auth', '--help'],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert 'login' in done.stdout
    assert 'status' in done.stdout


def _basic(username: str, secret: str) -> str:
    return 'Basic ' + base64.b64encode(f'{username}:{secret}'.encode()).decode()


def _store_password(tmp_path: Path, env: dict[str, str], host: str, username: str, secret: str) -> None:
    store_credential(host, username, secret, cwd=tmp_path, env=env)


@pytest.mark.parametrize(('host', 'path'), [('f.example', '/api/v1/user'), ('github.com', '/user')])
def test_status_presents_the_stored_credential_as_git_does_basic_with_its_username(
    server, tmp_path, capsys, host, path
) -> None:
    env, _ = _isolated_store(tmp_path)
    _store_password(tmp_path, env, host, 'alice', 'a-password')
    _Recorder.accept = lambda header: header == _basic('alice', 'a-password')
    _answer('GET', path, (200, {'login': 'alice'}))
    assert main(['status', '--host', host], cwd=tmp_path, env=env, transport=_Loopback(server)) == 0
    assert 'authenticated as alice' in capsys.readouterr().out


def test_planted_control_a_basic_only_server_refuses_the_token_header(server) -> None:
    _Recorder.accept = lambda header: header.startswith('Basic ')
    _answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    client = Client(Forge('f.example', 'o', 'r'), 'a-password', transport=_Loopback(server), sleep=lambda _s: None)
    with pytest.raises(ForgeCallFailed):
        client.whoami()


def test_planted_control_a_token_header_only_server_refuses_basic(server) -> None:
    _Recorder.accept = lambda header: header == f'token {_PAT}'
    _answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    transport = _Loopback(server)
    assert Client(Forge('f.example', 'o', 'r'), _PAT, transport=transport).whoami() == 'alice'
    basic = Client(Forge('f.example', 'o', 'r'), _PAT, username='alice', transport=transport, sleep=lambda _s: None)
    with pytest.raises(ForgeCallFailed):
        basic.whoami()


@pytest.mark.parametrize('code', [401, 403])
def test_an_auth_refusal_is_asked_once_and_names_the_remedy(server, tmp_path, capsys, code) -> None:
    env, _ = _isolated_store(tmp_path)
    _store_password(tmp_path, env, 'f.example', 'alice', 'stale')
    _answer('GET', '/api/v1/user', (code, {'message': 'invalid username, password or token'}))
    assert main(['status', '--host', 'f.example'], cwd=tmp_path, env=env, transport=_Loopback(server)) == 1
    assert len(_Recorder.received) == 1
    err = capsys.readouterr().err
    assert 'transient' not in err
    # A plain store holds no refresh token: a 401's refresh empties it, the one case a re-login fixes.
    # A 403 authenticated the credential and refused the act, so no refresh is spent and none is named.
    assert ('auth login' in err) is (code == 401)
    assert 'stale' not in err


def test_a_server_error_stays_transient_and_is_retried(server) -> None:
    _answer('GET', '/api/v1/user', (503, {'message': 'down'}))
    client = Client(Forge('f.example', 'o', 'r'), _PAT, transport=_Loopback(server), sleep=lambda _s: None)
    with pytest.raises(ForgeCallFailed) as failed:
        client.whoami()
    assert failed.value.report.disposition is Disposition.EXHAUSTED
    assert len(_Recorder.received) == DEFAULT_ATTEMPTS
