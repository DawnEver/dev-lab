"""THE CRASH TABLE (design D19): any step may crash; nothing is lost; everything resumes.

One row per crash point -- submit, claim, run, upload, status post, the forge down, a login-node restart.
Each row crashes (a raised exception, a refused connection, an answer the forge applied and dropped), then
starts a FRESH reader of what was left on disk -- a restarted host -- and proves two things: the information
is still there, and the job resumes to the end exactly once. The planted controls: the same crash through a
door with NO journal loses the write (so the journal is what saves it), and a live producer is never released
(so only a dead one is).
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from _forge_fake import Loopback, Recorder, answer, git_out, make_repo, run_git, serve
from test_dev_forgeintent import _claimed as _intent_claimed
from test_dev_forgeintent import _Forge, _reattach
from test_dev_forgerun import SHA as RUN_SHA
from test_dev_forgerun import _CrashAtSbatch, _Slurm, _start, _Store, _tick

from lab_commons.config import CONFIG_ENV
from dev_lab.dev import forgeintent, forgerun, forgerunstate
from dev_lab.dev._forge_journal import Journal, journal_for
from dev_lab.dev.forge import Forge
from dev_lab.dev.forgeclaim import DONE, OPEN, Claim, assess
from dev_lab.dev.forgeoutbox import Post, PostFailed, enqueue, flush, queued, replay
from dev_lab.dev.forgestatus import CommitStatus, status_post
from dev_lab.dev.forgework import Client, ForgeCallFailed
from dev_lab.dev.producer import ProducerExit, release_reason

FORGE = Forge('forge.example.org', 'o', 'r')
API = '/api/v1/repos/o/r'
NOW = datetime(2026, 10, 16, 12, tzinfo=UTC)
LEASE = timedelta(hours=6)
USER = ('GET', '/api/v1/user', (200, {'login': 'u'}))


@pytest.fixture
def server() -> Iterator[ThreadingHTTPServer]:
    yield from serve()


class _Down:
    """The forge refusing every connection."""

    def __call__(self, host: str, timeout: float) -> object:
        msg = f'connection refused by {host}'
        raise ConnectionRefusedError(msg)


def _door(transport: object, journal: Journal | None) -> Client:
    return Client(FORGE, 'T', transport=transport, sleep=lambda _s: None, journal=journal)


def _posts(path: str) -> list[dict]:
    return [r for r in Recorder.received if r['method'] == 'POST' and r['path'].split('?')[0] == path]


def _repo(tmp_path: Path) -> tuple[Path, str]:
    """A checkout whose commit is on origin, so its held posts go out."""
    repo = make_repo(tmp_path, 'https://forge.example.org/o/r.git', branch='lane/x')
    (repo / 'a.txt').write_text('a\n', encoding='utf-8')
    run_git(repo, 'add', 'a.txt')
    run_git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'a')
    sha = git_out(repo, 'rev-parse', 'HEAD')
    run_git(repo, 'update-ref', 'refs/remotes/origin/lane/x', sha)
    return repo, sha


@pytest.mark.parametrize('journaled', [True, False], ids=['journal', 'PLANTED-no-journal'])
def test_submit_a_publish_the_forge_never_took_is_replayed_once(server, tmp_path: Path, *, journaled: bool) -> None:
    """Crash at submit: the Job's publish (an issue) failed; the restarted host publishes it, once."""
    journal = Journal(tmp_path / 'writes') if journaled else None
    with pytest.raises(ForgeCallFailed):
        _door(_Down(), journal).issue_create('request: run the sweep', 'producer=sweep')
    restarted = Journal(tmp_path / 'writes')  # a fresh process reads what the crashed one left
    answer(*USER)
    answer('GET', f'{API}/issues', (200, []))
    answer('POST', f'{API}/issues', (201, {'number': 4, 'title': 'request: run the sweep', 'html_url': 'u'}))
    replay(restarted, _door(Loopback(server), restarted))
    published = _posts(f'{API}/issues')
    if not journaled:
        assert published == [], 'PLANTED CONTROL: without the journal the publish is simply lost'
        return
    assert [r['body']['title'] for r in published] == ['request: run the sweep']
    assert restarted.pending() == ()


def test_claim_a_lease_that_never_landed_is_never_asserted_later_and_the_unit_stays_claimable(
    server, tmp_path: Path
) -> None:
    """Crash at claim: the lease post failed, so no run started; replaying it later would hold a unit nobody runs."""
    journal = Journal(tmp_path / 'writes')
    me = Claim('G', 'alice', NOW + LEASE)
    with pytest.raises(ForgeCallFailed):
        status_post(
            _door(_Down(), journal), 'a' * 40, context='tests/linux', state='pending', description=me.description()
        )
    replay(journal, _door(Loopback(server), journal))
    assert Recorder.received == [], 'the lease is never posted after the fact'
    assert journal.pending() == ()
    assert assess((), 'tests/linux', me=me, now=NOW)[0] == OPEN, 'any host may claim it now'


@pytest.mark.parametrize('alive', [False, True], ids=['dead', 'PLANTED-alive'])
def test_run_a_producer_that_died_with_its_host_is_released_claimable(
    tmp_path: Path, monkeypatch, *, alive: bool
) -> None:
    """Crash during the run: the restarted serve re-attaches; a dead producer's unit is open again at once."""
    run_git(tmp_path, 'init', '-q')
    forge = _Forge()
    monkeypatch.setattr(forgeintent, 'status_post', forge.post)
    monkeypatch.setattr(forgeintent, 'status_history', forge.history)
    monkeypatch.setattr(forgeintent, 'close_tree', lambda _r, sha, _c, **_k: f'tree {sha[:12]}: removed')
    _intent_claimed(tmp_path, forge, pid=4242)
    _reattach(tmp_path, alive={4242} if alive else set())
    if alive:
        assert forge.posts[-1].state == 'pending', 'PLANTED CONTROL: a live producer is watched, never released'
        assert len(forgeintent.journaled(tmp_path)) == 1
        return
    other = Claim('H', 'bob', NOW + LEASE)
    assert assess(forge.posts, 'tests/windows', me=other, now=NOW)[0] == OPEN
    assert forgeintent.journaled(tmp_path) == ()


def test_upload_an_upload_whose_answer_was_lost_is_stored_once_and_the_part_still_posts(server, tmp_path: Path) -> None:
    """Crash at upload: the forge stored the record and dropped the answer; the next flush finds it by its name."""
    repo, sha = _repo(tmp_path)
    record = tmp_path / f'run-{sha}-linux-r1.json.gz'
    record.write_bytes(gzip.compress(b'{}', mtime=0))
    enqueue(repo, Post(sha, 'tests/linux', 'success', 'scope=full ran=1'), record=record)
    (stored,) = {post.record for post in queued(repo)}
    journal = journal_for(repo)
    door = _door(Loopback(server), journal)
    answer(*USER)
    answer('GET', f'{API}/issues', (200, [{'number': 3, 'title': 'run records'}]))
    answer('GET', f'{API}/issues/3/assets', (200, []))
    answer('POST', f'{API}/issues/3/assets', (None, None))  # applied, then the answer is lost
    answer('GET', f'{API}/statuses/{sha}', (200, []))
    with pytest.raises(PostFailed):
        flush(repo, client=lambda _root: door)
    assert len(queued(repo)) == 1, 'the part is still queued'
    asset = {'id': 7, 'name': stored, 'browser_download_url': 'https://f/a/7', 'uploader': {'login': 'u'}}
    answer('GET', f'{API}/issues/3/assets', (200, [asset]))
    answer('GET', f'{API}/statuses/{sha}', (200, []))
    answer('POST', f'{API}/statuses/{sha}', (201, {'context': 'tests/linux', 'status': 'success'}))
    flush(repo, client=lambda _root: door)
    assert len(_posts(f'{API}/issues/3/assets')) == DEFAULT_ATTEMPTS_LOST, 'never uploaded again after recovery'
    [posted] = _posts(f'{API}/statuses/{sha}')
    assert posted['body']['target_url'] == 'https://f/a/7'
    assert queued(repo) == ()
    assert journal.pending() == ()


#: The attempts the crashed flush made on the lost upload (the door's bounded retry), none after.
DEFAULT_ATTEMPTS_LOST = 3


def test_status_post_a_refused_status_has_one_owner_and_is_posted_once(server, tmp_path: Path) -> None:
    """Crash at status post: the held entry alone owns it -- the journal does not -- so it lands exactly once.

    An ``error`` release is not a result, so nothing on the forge would dedupe a second copy: this is the
    case where two owners (journal + held entry) used to post it twice after an outage.
    """
    repo, sha = _repo(tmp_path)
    enqueue(repo, Post(sha, 'tests/linux', 'error', 'released: unreachable -- no room'))
    door = _door(Loopback(server), journal_for(repo))
    answer('POST', f'{API}/statuses/{sha}', (503, {'message': 'down'}))
    with pytest.raises(PostFailed):
        flush(repo, client=lambda _root: door)
    assert len(queued(repo)) == 1, 'kept by its held entry'
    assert journal_for(repo).pending() == (), 'and by nothing else: one owner'
    Recorder.received.clear()
    answer('POST', f'{API}/statuses/{sha}', (201, {'context': 'tests/linux', 'status': 'error'}))
    flush(repo, client=lambda _root: door)
    assert len(_posts(f'{API}/statuses/{sha}')) == 1
    assert queued(repo) == ()


def test_gitea_down_every_write_waits_on_disk_and_each_lands_once_it_is_back(server, tmp_path: Path) -> None:
    """The forge refuses every connection for a while: the outbox grows; nothing is lost; each write lands once."""
    repo, sha = _repo(tmp_path)
    journal = journal_for(repo)
    enqueue(repo, Post(sha, 'tests/linux', 'failure', 'scope=full ran=3'))
    down = _door(_Down(), journal)
    with pytest.raises(ForgeCallFailed):
        down.issue_comment(5, 'routed: tests/test_a.py failed')
    with pytest.raises(PostFailed):
        flush(repo, client=lambda _root: down)
    assert len(journal.pending()) == 1
    assert len(queued(repo)) == 1
    up = _door(Loopback(server), Journal(journal.directory))  # the forge is back; a fresh process reads the disk
    answer(*USER)
    answer('GET', f'{API}/issues/5/comments', (200, []))
    answer('POST', f'{API}/issues/5/comments', (201, {'id': 1, 'body': 'x', 'html_url': 'u'}))
    answer('GET', f'{API}/statuses/{sha}', (200, []))
    answer('POST', f'{API}/statuses/{sha}', (201, {'context': 'tests/linux', 'status': 'failure'}))
    flush(repo, client=lambda _root: up)
    assert [json.loads(r['raw'])['body'] for r in _posts(f'{API}/issues/5/comments')] == [
        'routed: tests/test_a.py failed'
    ]
    assert len(_posts(f'{API}/statuses/{sha}')) == 1
    assert (journal.pending(), queued(repo)) == ((), ())


def test_login_node_restart_resumes_the_cluster_run_without_a_human(tmp_path: Path, monkeypatch) -> None:
    """The login node died between sbatch and the run state: cron restarts serve, the journal re-attaches."""
    monkeypatch.setenv(CONFIG_ENV, str(tmp_path / 'home' / 'config.toml'))
    monkeypatch.setattr(forgerun, 'pyproject_at', lambda _root, _sha: '')
    monkeypatch.setattr(forgerun, 'route', lambda *_a: ())
    monkeypatch.setattr(forgerun, 'tip_of', lambda _root, _ref: RUN_SHA)  # the ref has not moved on
    monkeypatch.setattr(forgerun, 'coalesced', lambda _root, _ref: True)
    store, crashing = _Store(), _CrashAtSbatch(tmp_path / 'r')
    _start(tmp_path, store)
    with pytest.raises(ConnectionResetError):
        _tick(store, crashing)
    slurm = _Slurm(tmp_path / 'r')
    slurm.queue = list(crashing.queue)
    resumed = _tick(store, slurm)
    assert resumed is not None
    assert (resumed.phase, slurm.submits, slurm.cancelled) == (forgerunstate.SUBMITTED, 1, ['555'])


@pytest.mark.parametrize(
    ('code', 'state'),
    [(ProducerExit.UNREACHABLE, OPEN), (ProducerExit.INCONCLUSIVE, DONE)],
    ids=['capacity', 'CONTROL'],
)
def test_a_capacity_release_is_claimable_and_a_posted_inconclusive_stays_settled(code: int, state: str) -> None:
    """The box's no-room exit releases RETRYABLE (open); an exit-3 release already on the forge stays DONE.

    Decided 2026-10-22: a posted ``released: inconclusive (exit 3) -- no part`` cannot say whether the box
    had no room or the run ran and wrote nothing, so the predicate does not re-open it -- re-opening every
    genuine inconclusive would re-run it every tick. A head stuck that way (67d955f) is superseded by its
    ref's next push, or re-run by a human; from now on a capacity refusal never posts it.
    """
    posts = [CommitStatus('tests/base', 'error', release_reason(code), '')]
    assert assess(posts, 'tests/base', me=Claim('G', 'alice', NOW + LEASE), now=NOW)[0] == state
