"""``lab_commons.dev.forgeauth`` -- ``auth login|status`` against a REAL loopback server and a REAL git.

The credential store is git's own ``store`` helper pointed at a file under ``tmp_path``, configured
through ``GIT_CONFIG_GLOBAL`` with the system config masked -- so ``git credential approve`` and
``fill`` run for real and the user's actual credential manager is never reached.
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

import pytest
from test_dev_forgework import _answer, _Loopback, _Recorder, _repo, server

from lab_commons.dev.forge import Forge, token_for
from lab_commons.dev.forgeauth import main
from lab_commons.dev.forgework import Client, token_source

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


def test_the_token_source_is_named_and_the_env_wins(tmp_path: Path) -> None:
    repo = _repo(tmp_path, 'https://f.example/o/r.git')
    env, _ = _isolated_store(tmp_path)
    forge = Forge('f.example', 'o', 'r')
    assert token_source(forge, cwd=repo, env={**env, 'GITEA_TOKEN': 'E'}) == ('GITEA_TOKEN', 'E')


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
    assert main(['status'], cwd=repo, env={**env, 'GITEA_TOKEN': _PAT}, transport=transport) == 0
    out = capsys.readouterr().out
    assert 'GITEA_TOKEN' in out
    assert _PAT not in out


def test_status_with_no_token_says_how_to_get_one(tmp_path, capsys) -> None:
    repo = _repo(tmp_path, 'https://f.example/o/r.git')
    env, _ = _isolated_store(tmp_path)
    assert main(['status'], cwd=repo, env=env) == 1
    assert 'auth login' in capsys.readouterr().err


def test_the_forge_module_routes_auth_to_this_door() -> None:
    done = subprocess.run(
        [sys.executable, '-m', 'lab_commons.dev.forge', 'auth', '--help'],
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
