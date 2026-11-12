"""forgeauthnotice: a refused token is heard at session start -- one GET /user per declared forge, bounded."""

from __future__ import annotations

import http.client
import io
import json
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Final

import pytest
from _forge_fake import Loopback, Recorder, answer, credential_env, make_repo, run_git, serve

from dev_lab.dev import agent_wiring, forgeauthnotice
from dev_lab.dev.forge import Transport
from dev_lab.dev.forgeauthnotice import BUDGET_S, declared_forges, notices

URL: Final = 'https://forge.example.org/o/r.git'


@pytest.fixture
def server() -> Iterator[ThreadingHTTPServer]:
    yield from serve()


def _said(repo: Path, tmp_path: Path, transport: Transport) -> tuple[str, ...]:
    return notices(repo, env=credential_env(tmp_path), transport=transport)


def test_a_token_the_forge_answers_is_silent_and_asks_get_user_once(server, tmp_path: Path) -> None:
    answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    repo = make_repo(tmp_path, URL)
    assert _said(repo, tmp_path, Loopback(server)) == ()
    assert [(r['method'], r['path']) for r in Recorder.received] == [('GET', '/api/v1/user')]


def test_a_refused_token_is_one_line_naming_the_host_and_the_remedy_door(server, tmp_path: Path) -> None:
    """PLANTED CONTROL for the silence above: the same check, the forge refusing, speaks."""
    answer('GET', '/api/v1/user', *[(401, {'message': 'invalid username, password or token'})] * 3)
    (line,) = _said(make_repo(tmp_path, URL), tmp_path, Loopback(server))
    assert 'forge.example.org refuses' in line
    assert 'dev_lab.dev.forge auth login --host forge.example.org' in line


def test_a_forge_not_reached_is_unreachable_never_refused(tmp_path: Path) -> None:
    def dropped(host: str, _timeout: float) -> http.client.HTTPConnection:
        raise ConnectionRefusedError(host)

    (line,) = _said(make_repo(tmp_path, URL), tmp_path, dropped)
    assert 'unreachable' in line
    assert 'refuses' not in line


def test_the_budget_is_shared_and_bounds_every_connection(tmp_path: Path) -> None:
    clock = iter([0.0, 0.5, BUDGET_S + 1])
    timeouts: list[float] = []

    def slow(host: str, timeout: float) -> http.client.HTTPConnection:
        timeouts.append(timeout)
        raise TimeoutError(host)

    said = notices(make_repo(tmp_path, URL), env=credential_env(tmp_path), transport=slow, now=lambda: next(clock))
    assert timeouts == [BUDGET_S - 0.5], 'the first connection gets what is left; the next finds the budget spent'
    (line,) = said
    assert f'not answered within {BUDGET_S:g} s' in line


def test_one_question_per_distinct_host(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, URL)
    run_git(repo, 'remote', 'add', 'mirror', 'https://forge.example.org/o/other.git')
    run_git(repo, 'remote', 'add', 'hub', 'https://github.com/o/r.git')
    assert [f.host for f in declared_forges(repo)] == ['github.com', 'forge.example.org'], 'git lists hub first'


def test_no_stored_credential_is_silent(tmp_path: Path) -> None:
    env = {'GIT_CONFIG_GLOBAL': str(tmp_path / 'absent'), 'GIT_CONFIG_SYSTEM': str(tmp_path / 'absent')}
    assert notices(make_repo(tmp_path, URL), env=env) == ()


def test_the_hook_is_wired_at_session_start_and_reads_its_cwd(tmp_path: Path, monkeypatch) -> None:
    wire = next(w for w in agent_wiring.WIRING if w.marker == 'dev_lab.dev.forgeauthnotice')
    assert wire.event == 'SessionStart'
    assert 'dev_lab.dev.forgeauthnotice --session-start' in wire.command
    seen: list[Path] = []
    monkeypatch.setattr(forgeauthnotice, 'notices', lambda root: seen.append(root) or ())
    repo = make_repo(tmp_path, URL)
    assert forgeauthnotice.main(['--session-start'], stdin=io.StringIO(json.dumps({'cwd': str(repo)}))) == 0
    assert [p.resolve() for p in seen] == [repo.resolve()]
