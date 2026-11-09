"""``auth role``: who the stored credential is on one repository, and whether it may write there -- never the secret.

User ruling 2026-11-09: a research account pulls with a read-only account. The hpcaccount deploy asks this verb,
which reads the credential the way git does (``git credential fill``) and the forge's own answer.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Final

import pytest
from _forge_fake import Loopback, answer, credential_env, serve

from dev_lab.dev.forge import forge_of_url
from dev_lab.dev.forgeauth import RepoRole, main, repo_role

URL: Final = 'https://forge.example.org/o/r.git'
API: Final = '/api/v1/repos/o/r'
PLANTED: Final = 'planted-4f1c'  # the planted control: a live credential this run, never printed


@pytest.fixture
def server() -> Iterator[ThreadingHTTPServer]:
    yield from serve()


def _forge(*, push: bool, admin: bool = False) -> None:
    answer('GET', '/api/v1/user', (200, {'login': 'ro-login'}))
    answer('GET', API, (200, {'permissions': {'admin': admin, 'push': push, 'pull': True}}))


@pytest.mark.parametrize(('push', 'admin'), [(False, False), (True, False), (False, True)])
def test_the_role_is_the_forge_login_and_its_write_permissions(
    server, tmp_path: Path, *, push: bool, admin: bool
) -> None:
    _forge(push=push, admin=admin)
    env = credential_env(tmp_path, PLANTED)
    role = repo_role(forge_of_url(URL), cwd=tmp_path, env=env, transport=Loopback(server))
    assert role == RepoRole('ro-login', push=push, admin=admin)


def test_the_cli_prints_the_role_as_json_and_never_the_token(server, tmp_path: Path, capsys) -> None:
    _forge(push=True)
    env = credential_env(tmp_path, PLANTED)
    assert main(['role', '--url', URL], cwd=tmp_path, env=env, transport=Loopback(server)) == 0
    said = capsys.readouterr()
    assert json.loads(said.out) == {'login': 'ro-login', 'push': True, 'admin': False}
    assert PLANTED not in said.out + said.err  # planted control: the token was live in this run


def test_no_stored_credential_is_anonymous(tmp_path: Path, capsys) -> None:
    env = {'GIT_CONFIG_GLOBAL': str(tmp_path / 'absent'), 'GIT_CONFIG_SYSTEM': str(tmp_path / 'absent')}
    assert main(['role', '--url', URL], cwd=tmp_path, env=env) == 0
    assert json.loads(capsys.readouterr().out) == {'login': '', 'push': False, 'admin': False}
