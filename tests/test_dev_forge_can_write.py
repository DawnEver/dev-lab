"""``Client.can_write`` over a real loopback transport: who the forge records as a writer of the repository.

Gitea answers ``permission: none`` for a login whose write comes from a unit-scoped org team (measured on Gitea
28.3.0, 2026-11-06), so every internal PR read as external and nothing auto-merged. A team member is a writer; a
stranger is not; a refused permission read is not; GitHub's own answer is final.
"""

from __future__ import annotations

from collections.abc import Iterator
from http.server import ThreadingHTTPServer

import pytest
from _forge_fake import Loopback, Recorder, answer, client, serve

from dev_lab.dev.forge import Forge

_GITEA = Forge('forge.example.org', 'o', 'r')
_REPO = '/api/v1/repos/o/r'
_DEVELOPER = {'id': 5, 'permission': 'none', 'units_map': {'repo.code': 'write', 'repo.pulls': 'write'}}
_BOT = {'id': 6, 'permission': 'none', 'units_map': {'repo.code': 'read', 'repo.pulls': 'write'}}


@pytest.fixture
def httpd() -> Iterator[ThreadingHTTPServer]:
    yield from serve()


def _gitea_team_grant(member: str) -> None:
    """A login with no direct grant, the repository's teams, and *member* listed in the developer team."""
    answer('GET', f'{_REPO}/teams', (200, [_BOT, _DEVELOPER]))
    answer('GET', f'/api/v1/teams/5/members/{member}', (200, {'login': member}))


def test_a_gitea_team_member_with_code_write_can_write(httpd: ThreadingHTTPServer) -> None:
    answer('GET', f'{_REPO}/collaborators/dev/permission', (200, {'permission': 'none', 'role_name': 'none'}))
    _gitea_team_grant('dev')
    assert client(_GITEA, Loopback(httpd)).can_write('dev')


def test_a_gitea_stranger_cannot_write(httpd: ThreadingHTTPServer) -> None:
    """The planted control: the same teams, but no team lists the login (every membership read answers 404)."""
    answer('GET', f'{_REPO}/collaborators/stranger/permission', (200, {'permission': 'none'}))
    _gitea_team_grant('dev')
    assert not client(_GITEA, Loopback(httpd)).can_write('stranger')


def test_a_team_granting_no_code_write_is_not_asked(httpd: ThreadingHTTPServer) -> None:
    """A member of the pulls-only bot team is not a writer, and its membership is never read."""
    answer('GET', f'{_REPO}/collaborators/bot/permission', (200, {'permission': 'none'}))
    answer('GET', f'{_REPO}/teams', (200, [_BOT]))
    answer('GET', '/api/v1/teams/6/members/bot', (200, {'login': 'bot'}))
    assert not client(_GITEA, Loopback(httpd)).can_write('bot')
    assert '/api/v1/teams/6/members/bot' not in [r['path'] for r in Recorder.received]


def test_a_refused_permission_read_cannot_write(httpd: ThreadingHTTPServer) -> None:
    answer('GET', f'{_REPO}/collaborators/dev/permission', (403, {'message': 'forbidden'}))
    answer('GET', '/api/v1/user', (200, {'login': 'me'}))
    _gitea_team_grant('dev')
    assert not client(_GITEA, Loopback(httpd)).can_write('dev')


def test_a_direct_gitea_grant_needs_no_team_read(httpd: ThreadingHTTPServer) -> None:
    answer('GET', f'{_REPO}/collaborators/dev/permission', (200, {'permission': 'write'}))
    assert client(_GITEA, Loopback(httpd)).can_write('dev')
    assert [r['path'] for r in Recorder.received] == [f'{_REPO}/collaborators/dev/permission']


def test_github_reads_its_permission_answer_alone(httpd: ThreadingHTTPServer) -> None:
    """GitHub's permission answer already counts teams: a ``read`` is final, and no team is asked."""
    answer('GET', '/repos/o/r/collaborators/dev/permission', (200, {'permission': 'read'}))
    assert not client(Forge('github.com', 'o', 'r'), Loopback(httpd)).can_write('dev')
    assert [r['path'] for r in Recorder.received] == ['/repos/o/r/collaborators/dev/permission']
