"""``ops forge token whoami --role R``: the Gitea login a configured token file is, and its repos' read -- no value."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from dev_lab.ops import forgeaccounts, forgewho

PLANTED_VALUE = 'gitea' + 'PLANTED' * 5  # a token-shaped value, built so no scanner reads a literal
HOST = 'gitea.example.test'


class _Answer:
    def __init__(self, status: int, body: object) -> None:
        self.status, self._body = status, json.dumps(body).encode()

    def read(self) -> bytes:
        return self._body


class _Connection:
    """A Gitea answering ``/api/v1/user`` and the repositories in *readable*; 404 to any other."""

    def __init__(self, login: str | None, readable: set[str], seen: list[dict[str, str]]) -> None:
        self.login, self.readable, self.seen, self.path = login, readable, seen, ''

    def request(self, method: str, path: str, headers: dict[str, str]) -> None:
        self.seen.append({'method': method, 'path': path, **headers})
        self.path = path

    def getresponse(self) -> _Answer:
        if self.path == '/api/v1/user':
            return _Answer(200, {'login': self.login}) if self.login else _Answer(401, {'message': 'bad token'})
        repo = self.path.removeprefix('/api/v1/repos/')
        return _Answer(200, {'full_name': repo}) if repo in self.readable else _Answer(404, {})

    def close(self) -> None:
        pass


def _transport(login: str | None, readable: set[str], seen: list[dict[str, str]]) -> Callable[..., _Connection]:
    return lambda host, _timeout: (seen.append({'host': host}), _Connection(login, readable, seen))[1]


def _tokens(tmp_path: Path) -> dict[str, str]:
    path = tmp_path / 'token'
    path.write_text(PLANTED_VALUE + '\n', encoding='utf-8')
    return {HOST: str(path)}


REPOS = (f'https://{HOST}/owner/a.git', f'https://{HOST}/owner/b.git', 'https://other.test/owner/c.git')


def test_the_token_names_its_login_and_each_repo_on_its_forge_never_its_value(tmp_path: Path) -> None:
    seen: list[dict[str, str]] = []
    said = forgewho.whoami(_tokens(tmp_path), REPOS, role='breakglass',
                           transport=_transport('glass-bot', {'owner/a'}, seen))  # fmt: skip
    assert said[0].startswith(f'{HOST}: breakglass token (sha256 ')
    assert said[0].endswith('is login glass-bot')
    assert said[1:] == ['  owner/a: readable', '  owner/b: not readable (404)']  # PLANTED: an unreadable repo
    assert PLANTED_VALUE not in '\n'.join(said)  # PLANTED CONTROL: presented, never said
    assert any(one.get('Authorization') == f'token {PLANTED_VALUE}' for one in seen)
    assert {one['host'] for one in seen if 'host' in one} == {HOST}


def test_a_refused_token_is_refused_without_its_value(tmp_path: Path) -> None:
    with pytest.raises(forgewho.WhoRefused, match='401') as refused:
        forgewho.whoami(_tokens(tmp_path), REPOS, role='breakglass', transport=_transport(None, set(), []))
    assert PLANTED_VALUE not in str(refused.value)


def test_an_unconfigured_forge_is_refused_before_any_read(tmp_path: Path) -> None:
    seen: list[dict[str, str]] = []
    with pytest.raises(forgewho.WhoRefused, match='--forge'):
        forgewho.whoami(_tokens(tmp_path), REPOS, role='probe', forge='nowhere.test',
                        transport=_transport('x', set(), seen))  # fmt: skip
    assert seen == []


def test_the_verb_parses_on_the_forge_parser_and_refuses_an_unknown_role() -> None:
    parser = argparse.ArgumentParser()
    forgeaccounts.add_parser(parser.add_subparsers(dest='verb'))
    args = parser.parse_args(['forge', 'token', 'whoami', '--role', 'breakglass', '--forge', HOST])
    assert (args.kind, args.action, args.role, args.forge) == ('token', 'whoami', 'breakglass', HOST)
    with pytest.raises(SystemExit):
        parser.parse_args(['forge', 'token', 'whoami', '--role', 'nobody'])
