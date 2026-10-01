"""``lab_commons.dev.forgework`` -- issue/PR verbs against a REAL loopback server and REAL git repos.

THE SAME DISCIPLINE AS ``test_dev_forge.py``: the evidence is what the SERVER recorded (method, path,
headers, decoded body), never the arguments the test passed. The one substitution is the transport,
which ignores the host it is asked for and connects to loopback -- and RECORDS that host, so the
backend's choice of API host is itself asserted rather than assumed.

Both forges are driven through ONE table of cases, because the claim under test is that the verbs
and the normalized results are identical across backends; only the request shape differs.
"""

from __future__ import annotations

import http.client
import json
import shutil
import subprocess
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

import pytest

from lab_commons.dev.forge import Forge
from lab_commons.dev.forgework import (
    GITEA,
    GITHUB,
    Client,
    Comment,
    ForgeCallFailed,
    Issue,
    PullRequest,
    backend_for,
    main,
    provenance,
    token_route,
)
from lab_commons.dev.netverb import Diagnosis, Disposition

_GIT = shutil.which('git') or 'git'


def _run(cwd: Path, *args: str) -> None:
    subprocess.run([_GIT, *args], cwd=cwd, check=True, capture_output=True, timeout=60)


def _repo(tmp_path: Path, remote: str, *, branch: str = 'feature') -> Path:
    repo = tmp_path / 'repo'
    repo.mkdir()
    _run(repo, 'init', '-q', '-b', branch)
    _run(repo, 'remote', 'add', 'origin', remote)
    return repo


class _Recorder(BaseHTTPRequestHandler):
    """Records every request and answers from a table of ``(method, path) -> (status, payload)``."""

    received: ClassVar[list[dict[str, Any]]] = []
    answers: ClassVar[dict[tuple[str, str], list[tuple[int, Any]]]] = {}

    def _serve(self, method: str) -> None:
        length = int(self.headers.get('Content-Length') or 0)
        body = json.loads(self.rfile.read(length)) if length else None
        type(self).received.append({'method': method, 'path': self.path, 'body': body, 'headers': dict(self.headers)})
        queue = type(self).answers.get((method, self.path)) or [(404, {'message': 'not found'})]
        status, payload = queue.pop(0) if len(queue) > 1 else queue[0]
        encoded = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:
        """Recorded then answered."""
        self._serve('GET')

    def do_POST(self) -> None:
        """Recorded then answered."""
        self._serve('POST')

    def do_PATCH(self) -> None:
        """Recorded then answered."""
        self._serve('PATCH')

    def log_message(self, fmt: str, *args: object) -> None:
        """Silent: the recording IS the log."""


@pytest.fixture
def server() -> Iterator[ThreadingHTTPServer]:
    _Recorder.received = []
    _Recorder.answers = {}
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), _Recorder)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=10)


class _Loopback:
    """A REAL connection to the test server, recording which API host the backend asked for."""

    def __init__(self, httpd: ThreadingHTTPServer) -> None:
        self.address = f'{httpd.server_address[0]}:{httpd.server_address[1]}'
        self.asked: list[str] = []

    def __call__(self, host: str, timeout: float) -> http.client.HTTPConnection:
        self.asked.append(host)
        return http.client.HTTPConnection(self.address, timeout=timeout)


#: (forge, API host, path prefix, Authorization header) -- the only things that differ per backend.
CASES = (
    pytest.param(Forge('forge.example.org', 'o', 'r'), 'forge.example.org', '/api/v1/repos/o/r', 'token T', id='gitea'),
    pytest.param(Forge('github.com', 'o', 'r'), 'api.github.com', '/repos/o/r', 'Bearer T', id='github'),
)

_ISSUE = {
    'number': 7,
    'title': 'a bug',
    'state': 'open',
    'body': 'it broke',
    'html_url': 'https://x/o/r/issues/7',
    'user': {'login': 'alice'},
}
_PR = {
    'number': 9,
    'title': 'a fix',
    'state': 'open',
    'body': 'fixes it',
    'html_url': 'https://x/o/r/pulls/9',
    'user': {'login': 'alice'},
    'head': {'ref': 'feature'},
    'base': {'ref': 'main'},
}
_NORMAL_ISSUE = Issue(7, 'a bug', 'open', 'it broke', 'https://x/o/r/issues/7', 'alice')


def _client(forge: Forge, transport: _Loopback, *, stamp: str | None = None) -> Client:
    return Client(forge, 'T', transport=transport, stamp=stamp, sleep=lambda _s: None)


def _answer(method: str, path: str, *replies: tuple[int, Any]) -> None:
    _Recorder.answers[(method, path)] = list(replies)


# --------------------------------------------------------------------------------------------
# backend selection


def test_github_com_selects_the_github_backend_and_any_other_host_the_gitea_one() -> None:
    assert backend_for(Forge('github.com', 'o', 'r')) is GITHUB
    assert backend_for(Forge('gitea.example.org', 'o', 'r')) is GITEA
    assert backend_for(Forge('GitHub.com', 'o', 'r')) is GITHUB


def test_the_gitea_token_comes_from_the_env_then_from_the_git_credential(tmp_path: Path) -> None:
    repo = _repo(tmp_path, 'https://forge.example.org/o/r.git')
    forge = Forge('forge.example.org', 'o', 'r')
    assert token_route(forge, cwd=repo, env={'GITEA_TOKEN': 'from-env', 'GITHUB_TOKEN': 'wrong'}) == 'from-env'
    config = tmp_path / 'gitconfig'
    config.write_text(
        '[credential]\n\thelper = "!f() { echo username=alice; echo password=from-git; }; f"\n', encoding='utf-8'
    )
    env = {'GIT_CONFIG_GLOBAL': str(config), 'GIT_CONFIG_SYSTEM': str(tmp_path / 'absent'), 'GH_TOKEN': 'wrong'}
    assert token_route(forge, cwd=repo, env=env) == 'from-git'


def test_the_github_token_prefers_GH_TOKEN_then_GITHUB_TOKEN(tmp_path: Path) -> None:
    repo = _repo(tmp_path, 'https://github.com/o/r.git')
    forge = Forge('github.com', 'o', 'r')
    assert token_route(forge, cwd=repo, env={'GH_TOKEN': 'a', 'GITHUB_TOKEN': 'b', 'GITEA_TOKEN': 'c'}) == 'a'
    assert token_route(forge, cwd=repo, env={'GITHUB_TOKEN': 'b'}) == 'b'


# --------------------------------------------------------------------------------------------
# each verb's request shape and normalized result, on both forges


@pytest.mark.parametrize(('forge', 'host', 'root', 'auth'), CASES)
def test_issue_list_reads_open_issues_and_drops_pull_requests(server, forge, host, root, auth) -> None:
    query = '?state=open&type=issues&limit=30' if forge.host != 'github.com' else '?state=open&per_page=30'
    _answer('GET', f'{root}/issues{query}', (200, [_ISSUE, {**_PR, 'pull_request': {}}]))
    transport = _Loopback(server)
    assert _client(forge, transport).issue_list() == (_NORMAL_ISSUE,)
    assert transport.asked == [host]
    assert _Recorder.received[0]['headers']['Authorization'] == auth


@pytest.mark.parametrize(('forge', 'host', 'root', 'auth'), CASES)
def test_issue_view_create_comment_close_send_one_shape_and_answer_one_shape(server, forge, host, root, auth) -> None:
    _answer('GET', f'{root}/issues/7', (200, _ISSUE))
    _answer('POST', f'{root}/issues', (201, _ISSUE))
    _answer('POST', f'{root}/issues/7/comments', (201, {'id': 3, 'body': 'hi', 'html_url': 'https://x/c/3'}))
    _answer('PATCH', f'{root}/issues/7', (200, {**_ISSUE, 'state': 'closed'}))
    transport = _Loopback(server)
    client = _client(forge, transport)
    assert client.issue_view(7) == _NORMAL_ISSUE
    assert client.issue_create('a bug', 'it broke') == _NORMAL_ISSUE
    assert client.issue_comment(7, 'hi') == Comment(3, 'hi', 'https://x/c/3')
    assert client.issue_close(7).state == 'closed'
    sent = [(r['method'], r['path'], r['body']) for r in _Recorder.received]
    assert sent == [
        ('GET', f'{root}/issues/7', None),
        ('POST', f'{root}/issues', {'title': 'a bug', 'body': 'it broke'}),
        ('POST', f'{root}/issues/7/comments', {'body': 'hi'}),
        ('PATCH', f'{root}/issues/7', {'state': 'closed'}),
    ]
    assert set(transport.asked) == {host}
    assert {r['headers']['Authorization'] for r in _Recorder.received} == {auth}


@pytest.mark.parametrize(('forge', 'host', 'root', 'auth'), CASES)
def test_pr_create_and_view(server, forge, host, root, auth) -> None:
    _answer('POST', f'{root}/pulls', (201, _PR))
    _answer('GET', f'{root}/pulls/9', (200, _PR))
    transport = _Loopback(server)
    client = _client(forge, transport)
    expected = PullRequest(9, 'a fix', 'open', 'fixes it', 'https://x/o/r/pulls/9', 'alice', 'feature', 'main')
    assert client.pr_create('a fix', 'fixes it', head='feature', base='main') == expected
    assert client.pr_view(9) == expected
    assert _Recorder.received[0]['body'] == {'title': 'a fix', 'body': 'fixes it', 'head': 'feature', 'base': 'main'}
    assert set(transport.asked) == {host}
    assert _Recorder.received[1]['headers']['Authorization'] == auth


def test_github_requests_carry_the_headers_its_api_demands(server) -> None:
    _answer('GET', '/repos/o/r/issues/7', (200, _ISSUE))
    _client(Forge('github.com', 'o', 'r'), _Loopback(server)).issue_view(7)
    headers = _Recorder.received[0]['headers']
    assert headers['Accept'] == 'application/vnd.github+json'
    assert headers['User-Agent']


# --------------------------------------------------------------------------------------------
# retry, then report -- netverb's diagnosis vocabulary, over HTTP


def test_a_transient_5xx_is_retried_and_recovers(server) -> None:
    _answer('GET', '/api/v1/repos/o/r/issues/7', (502, {'message': 'bad gateway'}), (200, _ISSUE))
    assert _client(Forge('f.example', 'o', 'r'), _Loopback(server)).issue_view(7) == _NORMAL_ISSUE
    assert len(_Recorder.received) == 2


def test_an_answered_refusal_is_not_retried_and_is_reported_with_its_diagnosis(server) -> None:
    _answer('POST', '/api/v1/repos/o/r/issues', (422, {'message': 'title is required'}))
    with pytest.raises(ForgeCallFailed, match='REFUSED') as caught:
        _client(Forge('f.example', 'o', 'r'), _Loopback(server)).issue_create('', '')
    assert len(_Recorder.received) == 1
    assert caught.value.report.disposition is Disposition.REFUSED
    assert caught.value.report.diagnosis is Diagnosis.FORGE_REFUSED
    assert 'title is required' in caught.value.report.attempts[-1].output


def test_a_failure_that_never_clears_stops_at_the_bound(server) -> None:
    _answer('GET', '/api/v1/repos/o/r/issues/7', (503, {'message': 'down'}))
    with pytest.raises(ForgeCallFailed) as caught:
        _client(Forge('f.example', 'o', 'r'), _Loopback(server)).issue_view(7)
    assert caught.value.report.disposition is Disposition.EXHAUSTED
    assert len(_Recorder.received) == 3


# --------------------------------------------------------------------------------------------
# provenance


def test_provenance_names_machine_agent_and_branch_when_both_vars_are_set(tmp_path: Path) -> None:
    repo = _repo(tmp_path, 'https://f.example/o/r.git', branch='lane-x')
    env = {'HARNESS_MACHINE': 'ws1', 'HARNESS_AGENT': 'claude'}
    assert provenance(repo, env) == '[ws1 · claude · lane-x]'


def test_no_provenance_without_both_vars(tmp_path: Path) -> None:
    repo = _repo(tmp_path, 'https://f.example/o/r.git')
    assert provenance(repo, {}) is None
    assert provenance(repo, {'HARNESS_MACHINE': 'ws1'}) is None
    assert provenance(repo, {'HARNESS_MACHINE': 'ws1', 'HARNESS_AGENT': ''}) is None


def test_a_detached_head_omits_the_branch(tmp_path: Path) -> None:
    repo = _repo(tmp_path, 'https://f.example/o/r.git')
    _run(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'x')
    _run(repo, 'checkout', '-q', '--detach')
    assert provenance(repo, {'HARNESS_MACHINE': 'ws1', 'HARNESS_AGENT': 'codex'}) == '[ws1 · codex]'


def test_the_stamp_prefixes_every_created_body_and_comment_and_nothing_else(server) -> None:
    root = '/api/v1/repos/o/r'
    _answer('POST', f'{root}/issues', (201, _ISSUE))
    _answer('POST', f'{root}/issues/7/comments', (201, {'id': 3, 'body': 'x', 'html_url': 'u'}))
    _answer('POST', f'{root}/pulls', (201, _PR))
    _answer('PATCH', f'{root}/issues/7', (200, _ISSUE))
    client = _client(Forge('f.example', 'o', 'r'), _Loopback(server), stamp='[m · a · b]')
    client.issue_create('t', 'body')
    client.issue_comment(7, 'note')
    client.pr_create('t', 'desc', head='b', base='main')
    client.issue_close(7)
    bodies = [r['body'] for r in _Recorder.received]
    assert bodies[0]['body'] == '[m · a · b]\n\nbody'
    assert bodies[1]['body'] == '[m · a · b]\n\nnote'
    assert bodies[2]['body'] == '[m · a · b]\n\ndesc'
    assert bodies[3] == {'state': 'closed'}


# --------------------------------------------------------------------------------------------
# the CLI door


def test_the_cli_prints_the_normalized_result_as_json(server, tmp_path: Path, capsys) -> None:
    repo = _repo(tmp_path, 'https://f.example/o/r.git')
    _answer('GET', '/api/v1/repos/o/r/issues/7', (200, _ISSUE))
    env = {'GITEA_TOKEN': 'T'}
    code = main(['issue', 'view', '7', '--json'], cwd=repo, env=env, transport=_Loopback(server))
    assert code == 0
    assert json.loads(capsys.readouterr().out)['number'] == 7


def test_the_cli_stamps_from_the_environment(server, tmp_path: Path, capsys) -> None:
    repo = _repo(tmp_path, 'https://f.example/o/r.git', branch='lane')
    _answer('POST', '/api/v1/repos/o/r/issues/7/comments', (201, {'id': 1, 'body': 'b', 'html_url': 'u'}))
    env = {'GITEA_TOKEN': 'T', 'HARNESS_MACHINE': 'g', 'HARNESS_AGENT': 'claude'}
    assert main(['issue', 'comment', '7', '--body', 'hello'], cwd=repo, env=env, transport=_Loopback(server)) == 0
    assert _Recorder.received[0]['body'] == {'body': '[g · claude · lane]\n\nhello'}
    assert 'u' in capsys.readouterr().out


def test_the_cli_reports_a_refusal_and_exits_nonzero(server, tmp_path: Path, capsys) -> None:
    repo = _repo(tmp_path, 'https://f.example/o/r.git')
    _answer('GET', '/api/v1/repos/o/r/pulls/9', (404, {'message': 'nope'}))
    assert main(['pr', 'view', '9'], cwd=repo, env={'GITEA_TOKEN': 'T'}, transport=_Loopback(server)) == 1
    assert 'REFUSED' in capsys.readouterr().err


def test_the_forge_module_is_the_cli_door() -> None:
    """``python -m lab_commons.dev.forge`` reaches these verbs, in a fresh interpreter."""
    done = subprocess.run(
        [sys.executable, '-m', 'lab_commons.dev.forge', 'issue', '--help'],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert all(verb in done.stdout for verb in ('list', 'view', 'create', 'comment', 'close'))
