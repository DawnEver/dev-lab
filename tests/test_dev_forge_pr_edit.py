"""``forge pr edit N``: the door rewrites or extends a PR body, the same request on GitHub and Gitea.

THE NEED, 2026-11-25 (dev-lab #956): merge-ready asked for ``Red-On-Record`` lines in a PR body, and the family
door could view, open and close a PR but never change its body -- the wall named a fix no door could make.
"""

from __future__ import annotations

from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from _forge_fake import Loopback as _Loopback
from _forge_fake import Recorder as _Recorder
from _forge_fake import answer as _answer
from _forge_fake import client as _client
from _forge_fake import credential_env, serve
from _forge_fake import make_repo as _repo

from dev_lab.dev.forge import Forge
from dev_lab.dev.forgecli import issue_and_pr
from dev_lab.dev.forgepr import pr_edit

CASES = (
    pytest.param(Forge('forge.example.org', 'o', 'r'), 'forge.example.org', '/api/v1/repos/o/r', id='gitea'),
    pytest.param(Forge('github.com', 'o', 'r'), 'api.github.com', '/repos/o/r', id='github'),
)
_PR = {
    'number': 9,
    'title': 'a fix',
    'state': 'open',
    'body': 'fixes it\n',
    'html_url': 'https://x/o/r/pulls/9',
    'user': {'login': 'alice'},
    'head': {'ref': 'feature'},
    'base': {'ref': 'main'},
}


@pytest.fixture
def server() -> Iterator[ThreadingHTTPServer]:
    yield from serve()


def _writes() -> list[tuple[str, str, object]]:
    return [(r['method'], r['path'], r['body']) for r in _Recorder.received if r['method'] != 'GET']


@pytest.mark.parametrize(('forge', 'host', 'root'), CASES)
def test_a_body_replaces_the_body_in_one_patch(server, forge, host, root) -> None:
    _answer('PATCH', f'{root}/pulls/9', (200, {**_PR, 'body': 'new'}))
    transport = _Loopback(server)
    assert pr_edit(_client(forge, transport), 9, body='new').body == 'new'
    assert [(r['method'], r['path'], r['body']) for r in _Recorder.received] == [
        ('PATCH', f'{root}/pulls/9', {'body': 'new'})
    ]
    assert set(transport.asked) == {host}


@pytest.mark.parametrize(('forge', 'host', 'root'), CASES)
def test_appended_lines_follow_the_body_the_forge_holds(server, forge, host, root) -> None:
    """The current body is READ, so an append never drops what another writer put there."""
    del host
    _answer('GET', f'{root}/pulls/9', (200, _PR))
    _answer('PATCH', f'{root}/pulls/9', (200, _PR))
    pr_edit(_client(forge, _Loopback(server)), 9, append=('Red-On-Record: a -- b', 'Red-On-Record: c -- d'))
    assert _writes() == [
        ('PATCH', f'{root}/pulls/9', {'body': 'fixes it\nRed-On-Record: a -- b\nRed-On-Record: c -- d\n'})
    ]


def test_an_edit_naming_neither_a_body_nor_a_line_is_refused_before_any_call(server, tmp_path: Path) -> None:
    """PLANTED CONTROL: the same verb WITH a body file reaches the forge; with nothing to write nothing is sent."""
    repo = _repo(tmp_path, 'https://f.example/o/r.git')
    env = credential_env(tmp_path)
    with pytest.raises(SystemExit):
        issue_and_pr(['pr', 'edit', '9'], cwd=repo, env=env, transport=_Loopback(server))
    with pytest.raises(ValueError, match='body'):
        pr_edit(_client(Forge('f.example', 'o', 'r'), _Loopback(server)), 9)
    assert _Recorder.received == []
    body = tmp_path / 'body.md'
    body.write_text('from a file\n', encoding='utf-8')
    _answer('PATCH', '/api/v1/repos/o/r/pulls/9', (200, _PR))
    argv = ['pr', 'edit', '9', '--body-file', str(body)]
    assert issue_and_pr(argv, cwd=repo, env=env, transport=_Loopback(server)) == 0
    assert _writes() == [('PATCH', '/api/v1/repos/o/r/pulls/9', {'body': 'from a file\n'})]
