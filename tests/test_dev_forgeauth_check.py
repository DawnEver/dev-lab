"""``auth check``: what a forge serve tick needs of the stored token, asked with reads only."""

from __future__ import annotations

from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Final

import pytest
from _forge_fake import Loopback, Recorder, answer, credential_env, serve

from dev_lab.dev.forge import forge_of_url
from dev_lab.dev.forgeauth import TICK_SCOPES, main, tick_refusal

URL: Final = 'https://forge.example.org/o/r.git'
API: Final = '/api/v1/repos/o/r'


@pytest.fixture
def server() -> Iterator[ThreadingHTTPServer]:
    yield from serve()


def _forge(*, user: int = 200, push: bool = True, issues: int = 200) -> None:
    answer('GET', '/api/v1/user', (user, {'login': 'alice'} if user == 200 else {'message': 'token scope'}))
    answer('GET', API, (200, {'permissions': {'admin': False, 'push': push, 'pull': True}}))
    answer('GET', f'{API}/issues', (issues, [] if issues == 200 else {'message': 'token scope'}))


def _refusal(server: ThreadingHTTPServer, tmp_path: Path) -> str:
    return tick_refusal(forge_of_url(URL), cwd=tmp_path, env=credential_env(tmp_path), transport=Loopback(server))


def test_a_token_with_every_scope_a_tick_needs_passes_and_writes_nothing(server, tmp_path: Path) -> None:
    _forge()
    assert _refusal(server, tmp_path) == ''
    assert {r['method'] for r in Recorder.received} == {'GET'}, 'the check has no side effect'


@pytest.mark.parametrize(
    ('forge', 'named'),
    [
        ({'user': 403}, 'user (read)'),
        ({'push': False}, 'commit statuses'),
        ({'issues': 403}, 'issues'),
    ],
)
def test_each_missing_permission_is_named(server, tmp_path: Path, forge: dict, named: str) -> None:
    """Ada's token read every repo over git and was refused at GET /user; ls-remote could not see that."""
    _forge(**forge)
    assert named in _refusal(server, tmp_path)


def test_no_stored_credential_is_a_refusal_not_a_crash(tmp_path: Path) -> None:
    env = {'GIT_CONFIG_GLOBAL': str(tmp_path / 'absent'), 'GIT_CONFIG_SYSTEM': str(tmp_path / 'absent')}
    assert 'no stored credential' in tick_refusal(forge_of_url(URL), cwd=tmp_path, env=env)


def test_the_cli_names_the_scopes_and_exits_nonzero(server, tmp_path: Path, capsys) -> None:
    """PLANTED CONTROL: the same CLI against a forge that allows everything exits 0."""
    _forge(user=403)
    env = credential_env(tmp_path)
    assert main(['check', '--url', URL], cwd=tmp_path, env=env, transport=Loopback(server)) == 1
    assert TICK_SCOPES in capsys.readouterr().err
    _forge()
    assert main(['check', '--url', URL], cwd=tmp_path, env=env, transport=Loopback(server)) == 0
