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

from dev_lab.dev import forgeoutbox
from dev_lab.dev.forge import Forge, NoCredential
from dev_lab.dev.forgealarm import NONDETERMINISM, Alarm
from dev_lab.dev.forgeoutbox import Post, PostFailed, content_name, enqueue, flush, outbox_dir, queued
from dev_lab.dev.forgework import Client

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
    answer('GET', f'{API}/statuses/{sha}', (200, []))  # no result on the forge yet
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
    answer('GET', f'{API}/issues/3/assets', (200, []))
    answer('POST', f'{API}/issues/3/assets', (201, {'id': 7, 'name': record.name, 'browser_download_url': url}))
    answer('GET', f'{API}/statuses/{sha}', (200, []))  # no result on the forge yet
    answer('POST', f'{API}/statuses/{sha}', (201, {'context': 'tests/linux', 'status': 'success'}))
    lines = flush(repo, client=lambda _root: client(FORGE, Loopback(server)))
    assert lines == [f'status: tests/linux=success on {sha[:12]} -> {url}']
    upload = next(r for r in Recorder.received if r['method'] == 'POST' and 'assets' in r['path'])
    assert payload in upload['raw'], 'the record bytes are what was uploaded'
    assert upload['path'].endswith(f'?name={content_name(record.name, payload)}'), 'named by its content hash'
    assert Recorder.received[-1]['body']['target_url'] == url
    assert list(outbox_dir(repo).iterdir()) == [], 'the entry and its copied record are both gone'


def test_a_result_is_stored_by_its_content_hash_before_it_is_uploaded(tmp_path: Path) -> None:
    """D19: the record is on disk under its hash first; the same bytes are one file, other bytes another."""
    repo, sha = _committed(tmp_path)
    record = tmp_path / f'run-{sha}-linux-r1.json.gz'
    record.write_bytes(b'first')
    enqueue(repo, Post(sha, 'tests/linux', 'success', 'v'), record=record)
    enqueue(repo, Post(sha, 'tests/windows', 'success', 'v'), record=record)
    stored = sorted(path.name for path in outbox_dir(repo).glob('*.json.gz'))
    assert stored == [content_name(record.name, b'first')], 'the same bytes are one stored result'
    assert (outbox_dir(repo) / stored[0]).read_bytes() == b'first'
    record.write_bytes(b'second')  # PLANTED CONTROL: different bytes are a different result, never a rewrite
    enqueue(repo, Post(sha, 'tests/macos', 'success', 'v'), record=record)
    assert len(list(outbox_dir(repo).glob('*.json.gz'))) == 2
    assert {post.record for post in queued(repo)} == {
        content_name(record.name, b'first'),
        content_name(record.name, b'second'),
    }


def test_a_refused_post_raises_after_trying_every_entry_and_keeps_the_failed_one(server, tmp_path: Path) -> None:
    repo, sha = _committed(tmp_path)
    _pushed(repo, sha)
    enqueue(repo, Post(sha, 'tests/linux', 'failure', 'VERDICT result=fail'))
    enqueue(repo, Post(sha, 'tests/windows', 'success', 'scope=full ran=2'))
    answer('GET', f'{API}/statuses/{sha}', (200, []))  # no result on the forge yet
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
    answer('GET', f'{API}/statuses/{sha}', (200, []))  # no result on the forge yet
    answer('POST', f'{API}/statuses/{sha}', (201, {'context': 'tests/linux', 'status': 'success'}))
    env = credential_env(tmp_path)
    assert forgeoutbox.main([], cwd=repo, env=env, transport=_RedirectedLoopback(server)) == 0
    assert 'tests/linux=success' in capsys.readouterr().out
    assert forgeoutbox.main([], cwd=repo, env=env, transport=_RedirectedLoopback(server)) == 0
    assert 'outbox is empty' in capsys.readouterr().out


class _RedirectedLoopback(Loopback):
    """The CLI builds its own client from origin; route its HTTPS host to the loopback server."""


def _decided(server, tmp_path: Path, first: str, later: str) -> tuple[list[str], list[Alarm]]:
    """*first* is already the forge's result for the commit and context; the outbox holds *later* for it."""
    repo, sha = _committed(tmp_path)
    _pushed(repo, sha)
    enqueue(repo, Post(sha, 'tests/linux', later, 'scope=full ran=9'))
    answer('GET', f'{API}/statuses/{sha}', (200, [{'id': 1, 'context': 'tests/linux', 'status': first}]))
    alarms: list[Alarm] = []
    lines = flush(repo, client=lambda _root: client(FORGE, Loopback(server)), alarm=alarms.append)
    assert not [r for r in Recorder.received if r['method'] == 'POST'], 'the first result stands: nothing posted'
    assert queued(repo) == (), 'decided: the entry leaves the outbox'
    return lines, alarms


def test_an_identical_later_result_is_dropped(server, tmp_path: Path) -> None:
    """D18: a duplicate run (a lost lease, a partition) wastes time but never posts twice."""
    lines, alarms = _decided(server, tmp_path, 'success', 'success')
    assert 'the identical result dropped' in lines[0]
    assert alarms == []


def test_a_differing_later_result_alarms_and_the_first_stands(server, tmp_path: Path) -> None:
    """PLANTED CONTROL for the one above: the same unit, a different verdict -- non-determinism found."""
    lines, alarms = _decided(server, tmp_path, 'success', 'failure')
    assert 'ALARMED' in lines[0]
    [alarm] = alarms
    assert alarm.kind == NONDETERMINISM
    assert 'gave success and then failure' in alarm.subject


def test_a_held_status_the_forge_refuses_for_good_is_dropped_once_with_its_record(server, tmp_path: Path) -> None:
    """A 422 is the forge's final answer: kept, it raised PostFailed on every tick of every host."""
    repo, sha = _committed(tmp_path)
    _pushed(repo, sha)
    enqueue(repo, Post(sha, 'tests/linux', 'error', 'released'))
    answer('POST', f'{API}/statuses/{sha}', (422, {'message': 'invalid'}))
    built = lambda _root: client(FORGE, Loopback(server))  # noqa: E731
    assert flush(repo, client=built) == [
        f'status: dropped tests/linux on {sha[:12]} -- the forge refused it (422), final'
    ]
    assert list(outbox_dir(repo).iterdir()) == [], 'the entry left the outbox'
    assert flush(repo, client=built) == [], 'recorded once, never again'


def test_a_held_status_whose_credential_is_refused_stays_queued(server, tmp_path: Path) -> None:
    """PLANTED CONTROL: a 401 the credential check confirms is the box's fault, not the post's."""
    repo, sha = _committed(tmp_path)
    _pushed(repo, sha)
    enqueue(repo, Post(sha, 'tests/linux', 'error', 'released'))
    answer('POST', f'{API}/statuses/{sha}', (401, {'message': 'unauthorized'}))
    answer('GET', '/api/v1/user', (401, {'message': 'unauthorized'}))
    with pytest.raises(PostFailed, match='forge-refused'):
        flush(repo, client=lambda _root: client(FORGE, Loopback(server)))
    assert len(queued(repo)) == 1
