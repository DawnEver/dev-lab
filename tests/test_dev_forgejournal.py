"""THE WRITE JOURNAL: every outward forge write is on disk before it is attempted, replayed until acknowledged.

Against a REAL loopback forge. The defect this pins (design D19, 2026-10-16): a write that lived only in a
process -- a status, a comment, an attachment -- was lost when the forge was down or the host crashed. The
planted controls: a forge that refuses every connection (the write survives it), a forge that APPLIES a write
and drops the answer (the replay finds it and never posts it twice), and a probe that does NOT match (the
replay sends -- so "acknowledged without sending" is the probe's finding, not a replay that never sends).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from _forge_fake import Loopback, Recorder, answer, credential_env, make_repo, serve

from lab_commons.dev._forge_journal import Journal, Probe, Write, journal_for, outbox_dir
from lab_commons.dev.forge import Forge
from lab_commons.dev.forgeoutbox import replay
from lab_commons.dev.forgestatus import status_post
from lab_commons.dev.forgework import Client, ForgeCallFailed, client_for

FORGE = Forge('forge.example.org', 'o', 'r')
API = '/api/v1/repos/o/r'
SHA = 'a' * 40


@pytest.fixture
def server() -> Iterator[ThreadingHTTPServer]:
    yield from serve()


def _door(server: ThreadingHTTPServer, journal: Journal) -> Client:
    answer('GET', '/api/v1/user', (200, {'login': 'u'}))  # whoami: a probe matches only this login's objects
    return Client(FORGE, 'T', transport=Loopback(server), sleep=lambda _s: None, journal=journal)


class _Down:
    """A forge that refuses every connection -- and, at that instant, reads what the journal holds."""

    def __init__(self, journal: Journal) -> None:
        self.journal = journal
        self.seen: list[int] = []

    def __call__(self, host: str, timeout: float) -> object:
        self.seen.append(len(self.journal.pending()))
        msg = f'connection refused by {host}'
        raise ConnectionRefusedError(msg)


def test_a_write_is_journaled_before_it_is_attempted_and_survives_a_forge_that_is_down(tmp_path: Path) -> None:
    """PLANTED CONTROL: the forge is down; the write must still exist afterwards, on disk."""
    journal = Journal(tmp_path / 'writes')
    down = _Down(journal)
    door = Client(FORGE, 'T', transport=down, sleep=lambda _s: None, journal=journal)
    with pytest.raises(ForgeCallFailed):
        door.issue_comment(7, 'the run finished')
    assert down.seen, 'the door attempted it'
    assert all(count == 1 for count in down.seen), 'journaled BEFORE the first attempt'
    [kept] = journal.pending()
    assert (kept.method, kept.path) == ('POST', f'{API}/issues/7/comments')
    assert json.loads(kept.body) == {'body': 'the run finished'}
    assert Journal(tmp_path / 'writes').pending() == (kept,), 'a fresh reader (a restarted host) sees it'


def test_an_acknowledged_write_leaves_the_journal(server, tmp_path: Path) -> None:
    journal = Journal(tmp_path / 'writes')
    answer('POST', f'{API}/statuses/{SHA}', (201, {'context': 'tests/linux', 'status': 'success'}))
    status_post(_door(server, journal), SHA, context='tests/linux', state='success', description='ok')
    assert journal.pending() == ()


def test_a_kept_write_is_replayed_once_the_forge_answers(server, tmp_path: Path) -> None:
    journal = Journal(tmp_path / 'writes')
    answer('POST', f'{API}/statuses/{SHA}', (503, {'message': 'down'}))
    with pytest.raises(ForgeCallFailed):
        status_post(_door(server, journal), SHA, context='tests/linux', state='success', description='ok')
    assert len(journal.pending()) == 1
    answer('GET', f'{API}/statuses/{SHA}', (200, []))  # the probe: it never landed
    answer('POST', f'{API}/statuses/{SHA}', (201, {'context': 'tests/linux', 'status': 'success'}))
    Recorder.received.clear()
    assert replay(journal, _door(server, journal)) == [f'outbox: replayed POST {API}/statuses/{SHA}']
    assert [r['method'] for r in Recorder.received] == ['GET', 'GET', 'POST'], 'probed, then sent once'
    assert Recorder.received[-1]['body'] == {'state': 'success', 'context': 'tests/linux', 'description': 'ok'}
    assert journal.pending() == ()


def test_a_write_whose_answer_was_lost_is_never_posted_twice(server, tmp_path: Path) -> None:
    """PLANTED CONTROL: the forge APPLIED the comment and dropped the answer; the replay must find it."""
    journal = Journal(tmp_path / 'writes')
    path = f'{API}/issues/7/comments'
    answer('POST', path, (None, None))
    with pytest.raises(ForgeCallFailed):
        _door(server, journal).issue_comment(7, 'the run finished')
    [kept] = journal.pending()
    assert kept.probe is not None
    landed = {'id': 1, 'body': 'the run finished', 'user': {'login': 'u'}, 'created_at': '2999-01-01T00:00:00+00:00'}
    answer('GET', kept.probe.path.split('?')[0], (200, [landed]))
    Recorder.received.clear()
    assert replay(journal, _door(server, journal)) == [
        f'outbox: POST {path} had landed -- acknowledged, not sent again'
    ]
    assert {r['method'] for r in Recorder.received} == {'GET'}, 'nothing was posted again'
    assert journal.pending() == ()


def test_a_probe_that_does_not_match_sends_the_write(server, tmp_path: Path) -> None:
    """PLANTED CONTROL for the one above: another comment on the issue is not this write."""
    journal = Journal(tmp_path / 'writes')
    path = f'{API}/issues/7/comments'
    journal.record(
        Write('k', 'POST', path, 'application/json', b'{"body": "mine"}', probe=Probe(path, {'body': 'mine'}))
    )
    answer('GET', path, (200, [{'id': 1, 'body': 'somebody else', 'created_at': '2999-01-01T00:00:00+00:00'}]))
    answer('POST', path, (201, {'id': 2, 'body': 'mine'}))
    assert replay(journal, _door(server, journal)) == [f'outbox: replayed POST {path}']


def test_a_lease_is_never_replayed(server, tmp_path: Path) -> None:
    """A pending status is a claim: replayed later it would assert a lease nobody runs."""
    journal = Journal(tmp_path / 'writes')
    answer('POST', f'{API}/statuses/{SHA}', (503, {'message': 'down'}))
    with pytest.raises(ForgeCallFailed):
        status_post(_door(server, journal), SHA, context='tests/linux', state='pending', description='claim')
    Recorder.received.clear()
    assert replay(journal, _door(server, journal)) == [
        f'outbox: dropped POST {API}/statuses/{SHA} -- past its until, never replayed'
    ]
    assert Recorder.received == []
    assert journal.pending() == ()


def test_a_newer_status_supersedes_the_older_one_kept_for_the_same_commit_and_context(server, tmp_path: Path) -> None:
    journal = Journal(tmp_path / 'writes')
    answer('POST', f'{API}/statuses/{SHA}', (503, {'message': 'down'}))
    door = _door(server, journal)
    for description in ('first', 'second'):
        with pytest.raises(ForgeCallFailed):
            status_post(door, SHA, context='tests/linux', state='failure', description=description)
    [kept] = journal.pending()
    assert json.loads(kept.body)['description'] == 'second'


def test_a_forge_still_down_keeps_the_write_for_the_next_tick(server, tmp_path: Path) -> None:
    journal = Journal(tmp_path / 'writes')
    journal.record(Write('k', 'PATCH', f'{API}/issues/3', 'application/json', b'{"state": "closed"}'))
    answer('PATCH', f'{API}/issues/3', (503, {'message': 'down'}))
    [line] = replay(journal, _door(server, journal))
    assert line.startswith(f'outbox: kept PATCH {API}/issues/3 -- ')
    assert len(journal.pending()) == 1


def test_a_torn_entry_is_skipped_never_replayed(tmp_path: Path) -> None:
    journal = Journal(tmp_path / 'writes')
    journal.directory.mkdir(parents=True)
    (journal.directory / 'torn.json').write_text('{"key": "k", "meth', encoding='utf-8')
    assert journal.pending() == ()


def test_the_door_every_verb_builds_journals_into_the_repositorys_outbox(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, 'https://forge.example.org/o/r.git')
    built = client_for(repo, env=credential_env(tmp_path))
    assert built.journal == journal_for(repo)
    assert built.journal.directory.is_relative_to(outbox_dir(repo))
