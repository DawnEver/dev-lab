"""``ops github whoami --file P``: whose GitHub token a declared file holds, and its scopes -- never the value."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from dev_lab.ops import githubwho

PLANTED_VALUE = 'ghp_' + 'PLANTED' * 5  # a token-shaped value, built so no scanner reads a literal


class _Answer:
    def __init__(self, status: int, body: object, headers: dict[str, str]) -> None:
        self.status, self._body, self._headers = status, json.dumps(body).encode(), headers

    def read(self) -> bytes:
        return self._body

    def getheader(self, name: str, default: str | None = None) -> str | None:
        return self._headers.get(name, default)


class _Connection:
    def __init__(self, answer: _Answer, seen: list[dict[str, str]]) -> None:
        self.answer, self.seen = answer, seen

    def request(self, method: str, path: str, headers: dict[str, str]) -> None:
        self.seen.append({'method': method, 'path': path, **headers})

    def getresponse(self) -> _Answer:
        return self.answer

    def close(self) -> None:
        pass


def _transport(answer: _Answer, seen: list[dict[str, str]]) -> Callable[[str, float], _Connection]:
    return lambda _host, _timeout: _Connection(answer, seen)


def _file(tmp_path: Path) -> Path:
    path = tmp_path / 'github-token'
    path.write_text(PLANTED_VALUE + '\n', encoding='utf-8')
    return path


def test_a_classic_token_names_its_login_and_scopes_never_its_value(tmp_path: Path) -> None:
    seen: list[dict[str, str]] = []
    answer = _Answer(200, {'login': 'some-bot', 'type': 'User'}, {'X-OAuth-Scopes': 'repo, read:org'})
    said = githubwho.whoami(_file(tmp_path), transport=_transport(answer, seen))
    assert said == 'user some-bot; scopes: read:org, repo'
    assert seen[0]['path'] == '/user'
    assert PLANTED_VALUE not in said  # PLANTED CONTROL: the value is presented, never said


def test_a_fine_grained_token_says_it_has_no_scope_list(tmp_path: Path) -> None:
    answer = _Answer(200, {'login': 'someone', 'type': 'User'}, {})
    assert githubwho.whoami(_file(tmp_path), transport=_transport(answer, [])) == 'user someone; scopes: none listed'


def test_an_installation_token_is_named_as_an_app(tmp_path: Path) -> None:
    answer = _Answer(403, {'message': 'Resource not accessible by integration'}, {})
    assert 'an App installation token' in githubwho.whoami(_file(tmp_path), transport=_transport(answer, []))


def test_a_refused_token_is_said_without_its_value(tmp_path: Path) -> None:
    answer = _Answer(401, {'message': 'Bad credentials'}, {})
    with pytest.raises(githubwho.WhoRefused, match='401 Bad credentials') as refused:
        githubwho.whoami(_file(tmp_path), transport=_transport(answer, []))
    assert PLANTED_VALUE not in str(refused.value)


def test_an_undeclared_file_is_refused_before_it_is_read(tmp_path: Path) -> None:
    with pytest.raises(githubwho.WhoRefused, match='not a secret file'):
        githubwho.declared_file(['/etc/x/token'], str(tmp_path / 'other'))
    assert githubwho.declared_file(['/etc/x/token'], '/etc/x/token') == Path('/etc/x/token')


def test_the_output_stream_is_untouched_by_a_value(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    answer = _Answer(200, {'login': 'some-bot'}, {'X-OAuth-Scopes': 'repo'})
    githubwho.say(githubwho.whoami(_file(tmp_path), transport=_transport(answer, [])))
    said = capsys.readouterr()
    assert 'user some-bot' in said.out + said.err
    assert PLANTED_VALUE not in said.out + said.err
