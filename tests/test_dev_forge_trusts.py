"""``Client.trusts`` over a real loopback transport: whose PR may auto-merge and whose cap raise is admitted.

Gitea is the family's private forge and vets no author (user ruling 2026-11-06): its Actions token cannot read
org-team rosters, so a team writer read as untrusted and nothing auto-merged. GitHub is public: a login it records
with a writing permission is trusted; a reader, or a refused read, is not.
"""

from __future__ import annotations

from collections.abc import Iterator
from http.server import ThreadingHTTPServer

import pytest
from _forge_fake import Loopback, Recorder, answer, client, serve

from dev_lab.dev.forge import Forge

_HUB = Forge('github.com', 'o', 'r')


@pytest.fixture
def httpd() -> Iterator[ThreadingHTTPServer]:
    yield from serve()


def test_gitea_trusts_every_author_without_asking(httpd: ThreadingHTTPServer) -> None:
    assert client(Forge('forge.example.org', 'o', 'r'), Loopback(httpd)).trusts('stranger')
    assert Recorder.received == []


def test_github_trusts_a_writer(httpd: ThreadingHTTPServer) -> None:
    answer('GET', '/repos/o/r/collaborators/dev/permission', (200, {'permission': 'write'}))
    assert client(_HUB, Loopback(httpd)).trusts('dev')


def test_github_does_not_trust_a_reader(httpd: ThreadingHTTPServer) -> None:
    """The planted control: the same read, answering ``read``."""
    answer('GET', '/repos/o/r/collaborators/dev/permission', (200, {'permission': 'read'}))
    assert not client(_HUB, Loopback(httpd)).trusts('dev')


def test_github_does_not_trust_a_refused_read(httpd: ThreadingHTTPServer) -> None:
    answer('GET', '/repos/o/r/collaborators/dev/permission', (403, {'message': 'forbidden'}))
    answer('GET', '/user', (200, {'login': 'me'}))
    assert not client(_HUB, Loopback(httpd)).trusts('dev')
