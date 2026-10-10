"""THE OUTBOX: a status is kept until its commit is on origin, then posted with its record.

Against a REAL loopback forge and REAL git repositories.

The defect this pins (measured 2026-10-09): a run on an unpushed commit posted its status at once, the
forge refused a commit it did not hold, and every such post failed. The planted control is exactly
that commit: queued, HELD while it is not on origin, posted the moment a remote-tracking ref holds it.
"""

from __future__ import annotations

import gzip
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from _forge_fake import Loopback, Recorder, answer, client, credential_env, git_out, make_repo, run_git, serve

from lab_commons.dev import forgeoutbox
from lab_commons.dev.forge import Forge, NoCredential
from lab_commons.dev.forgeoutbox import Post, PostFailed, enqueue, flush, outbox_dir, queued
from lab_commons.dev.forgework import Client

FORGE = Forge('forge.example.org', 'o', 'r')
API = '/api/v1/repos/o/r'


@pytest.fixture
def server() -> Iterator[ThreadingHTTPServer]:
    yield from serve()


def _committed(tmp_path: Path) -> tuple[Path, str]:
    repo = make_repo(tmp_path, 'https://forge.example.org/o/r.git', branch='lane/x')
    (repo / 'a.txt').write_text('a\n', encoding='utf-8')
    run_git(repo, 'add', 'a.txt')
    run_git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'a')
    return repo, git_out(repo, 'rev-parse', 'HEAD')


def _pushed(repo: Path, sha: str) -> None:
    """What a landed push leaves behind: the remote-tracking ref names the commit."""
    run_git(repo, 'update-ref', 'refs/remotes/origin/lane/x', sha)


def test_a_status_on_an_unpushed_commit_is_held_then_posted_once_it_is_on_origin(server, tmp_path: Path) -> None:
    """PLANTED CONTROL: the commit the old publish always failed on."""
    repo, sha = _committed(tmp_path)
    enqueue(repo, Post(sha, 'tests/linux', 'success', 'VERDICT result=pass'))

    def built(_root: Path) -> Client:
        return client(FORGE, Loopback(server))

    assert flush(repo, client=built) == [f'status: held tests/linux on {sha[:12]} -- the commit is not on origin yet']
    assert Recorder.received == [], 'nothing is sent for a commit the forge does not hold'
    assert len(queued(repo)) == 1, 'a held entry is kept'
    _pushed(repo, sha)
    answer('POST', f'{API}/statuses/{sha}', (201, {'context': 'tests/linux', 'status': 'success'}))
    assert flush(repo, client=built) == [f'status: tests/linux=success on {sha[:12]}']
    assert Recorder.received[-1]['body'] == {
        'state': 'success',
        'context': 'tests/linux',
        'description': 'VERDICT result=pass',
    }
    assert queued(repo) == (), 'a posted entry leaves the outbox'


def test_a_record_is_attached_and_the_status_links_it(server, tmp_path: Path) -> None:
    repo, sha = _committed(tmp_path)
    _pushed(repo, sha)
    record = tmp_path / f'run-{sha}-linux-r1.json.gz'
    payload = gzip.compress(b'{}')  # once: gzip stamps the second into its header
    record.write_bytes(payload)
    enqueue(repo, Post(sha, 'tests/linux', 'success', 'scope=full ran=1'), record=record)
    answer('GET', f'{API}/issues', (200, [{'number': 3, 'title': 'run records'}]))
    url = 'https://forge.example.org/attachments/u1'
    answer('POST', f'{API}/issues/3/assets', (201, {'id': 7, 'name': record.name, 'browser_download_url': url}))
    answer('POST', f'{API}/statuses/{sha}', (201, {'context': 'tests/linux', 'status': 'success'}))
    lines = flush(repo, client=lambda _root: client(FORGE, Loopback(server)))
    assert lines == [f'status: tests/linux=success on {sha[:12]} -> {url}']
    upload = next(r for r in Recorder.received if r['path'].startswith(f'{API}/issues/3/assets'))
    assert payload in upload['raw'], 'the record bytes are what was uploaded'
    assert Recorder.received[-1]['body']['target_url'] == url
    assert list(outbox_dir(repo).iterdir()) == [], 'the entry and its copied record are both gone'


def test_a_refused_post_raises_after_trying_every_entry_and_keeps_the_failed_one(server, tmp_path: Path) -> None:
    repo, sha = _committed(tmp_path)
    _pushed(repo, sha)
    enqueue(repo, Post(sha, 'tests/linux', 'failure', 'VERDICT result=fail'))
    enqueue(repo, Post(sha, 'tests/windows', 'success', 'scope=full ran=2'))
    answer('POST', f'{API}/statuses/{sha}', (403, {'message': 'forbidden'}), (201, {'context': 'tests/windows'}))
    with pytest.raises(PostFailed, match=r'(?s)post FAILED tests/linux.*remedy: it stays queued'):
        flush(repo, client=lambda _root: client(FORGE, Loopback(server)))
    assert [post.context for post in queued(repo)] == ['tests/linux']


def test_no_credential_keeps_the_entry_and_raises_nothing(tmp_path: Path) -> None:
    repo, sha = _committed(tmp_path)
    _pushed(repo, sha)
    enqueue(repo, Post(sha, 'tests/linux', 'success', 'v'))

    def no_token(_root: Path) -> None:
        msg = 'no stored credential for forge.example.org'
        raise NoCredential(msg)

    assert flush(repo, client=no_token)[0].startswith('status: kept tests/linux')
    assert len(queued(repo)) == 1


def test_a_newer_run_replaces_the_queued_post_for_the_same_commit_and_context(tmp_path: Path) -> None:
    repo, sha = _committed(tmp_path)
    enqueue(repo, Post(sha, 'tests/linux', 'failure', 'old'))
    enqueue(repo, Post(sha, 'tests/linux', 'success', 'new'))
    assert [(p.state, p.description) for p in queued(repo)] == [('success', 'new')]


def test_a_post_that_could_never_land_is_refused_at_queueing() -> None:
    with pytest.raises(ValueError, match='one of'):
        Post('a' * 40, 'tests/linux', 'skipped', '')
    with pytest.raises(ValueError, match='40-hex'):
        Post('abc', 'tests/linux', 'success', '')


def test_the_outbox_is_shared_by_every_worktree_of_the_repository(tmp_path: Path) -> None:
    repo, sha = _committed(tmp_path)
    lane = tmp_path / 'lane'
    run_git(repo, 'worktree', 'add', '-q', '--detach', str(lane), sha)
    assert outbox_dir(lane) == outbox_dir(repo)


def test_publish_cli_flushes_with_the_stored_credential(server, tmp_path: Path, capsys) -> None:
    repo, sha = _committed(tmp_path)
    _pushed(repo, sha)
    enqueue(repo, Post(sha, 'tests/linux', 'success', 'v'))
    answer('POST', f'{API}/statuses/{sha}', (201, {'context': 'tests/linux', 'status': 'success'}))
    env = credential_env(tmp_path)
    assert forgeoutbox.main([], cwd=repo, env=env, transport=_RedirectedLoopback(server)) == 0
    assert 'tests/linux=success' in capsys.readouterr().out
    assert forgeoutbox.main([], cwd=repo, env=env, transport=_RedirectedLoopback(server)) == 0
    assert 'outbox is empty' in capsys.readouterr().out


class _RedirectedLoopback(Loopback):
    """The CLI builds its own client from origin; route its HTTPS host to the loopback server."""
