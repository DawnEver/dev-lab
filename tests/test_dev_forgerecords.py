"""RUN RECORDS as forge attachments: one closed issue holds them, and prune keeps only live shas' records."""

from __future__ import annotations

import functools
from collections.abc import Iterator
from datetime import UTC, datetime
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest
from _forge_fake import Loopback, Recorder, answer, client, credential_env, git_out, make_repo, run_git, serve

from lab_commons.dev import forgerecords
from lab_commons.dev.forge import Forge
from lab_commons.dev.forgealarm import STORAGE
from lab_commons.dev.forgerecords import (
    RECORDS_TITLE,
    attach,
    kept_shas,
    listing,
    prune,
    read_named,
    records_issue,
    remove_named,
    replace_named,
    sha_of,
)
from lab_commons.dev.retentionplan import Policy

FORGE = Forge('forge.example.org', 'o', 'r')
API = '/api/v1/repos/o/r'
LIVE, DEAD = 'a' * 40, 'b' * 40


@pytest.fixture
def server() -> Iterator[ThreadingHTTPServer]:
    yield from serve()


def _asset(asset_id: int, name: str) -> dict[str, object]:
    return {'id': asset_id, 'name': name, 'browser_download_url': f'https://forge.example.org/attachments/{asset_id}'}


def test_a_record_name_carries_its_sha_and_nothing_else_is_a_record() -> None:
    assert sha_of(f'run-{LIVE}-linux-r1.json.gz') == LIVE
    assert sha_of('notes.txt') is None
    assert sha_of(f'run-{LIVE[:12]}-linux-r1.json.gz') is None


def test_the_records_issue_is_created_once_and_closed(server) -> None:
    answer('GET', f'{API}/issues', (200, []))
    answer(
        'POST',
        f'{API}/issues',
        (201, {'number': 5, 'title': RECORDS_TITLE, 'state': 'open', 'html_url': 'u', 'user': {'login': 'me'}}),
    )
    answer(
        'PATCH',
        f'{API}/issues/5',
        (200, {'number': 5, 'title': RECORDS_TITLE, 'state': 'closed', 'html_url': 'u', 'user': {'login': 'me'}}),
    )
    built = client(FORGE, Loopback(server))
    assert records_issue(built, create=False) is None
    assert records_issue(built, create=True) == 5
    assert [r['method'] for r in Recorder.received] == ['GET', 'GET', 'POST', 'PATCH']
    assert Recorder.received[-1]['body'] == {'state': 'closed'}


def test_attach_uploads_the_bytes_under_the_attachment_field(server, tmp_path: Path) -> None:
    record = tmp_path / f'run-{LIVE}-linux-r1.json.gz'
    record.write_bytes(b'gz-bytes')
    answer('GET', f'{API}/issues', (200, [{'number': 3, 'title': RECORDS_TITLE}]))
    answer('GET', f'{API}/issues/3/assets', (200, []))
    answer('POST', f'{API}/issues/3/assets', (201, _asset(7, record.name)))
    found = attach(client(FORGE, Loopback(server)), record)
    assert found.url.endswith('/7')
    sent = Recorder.received[-1]
    assert sent['path'] == f'{API}/issues/3/assets?name={record.name}'
    assert sent['headers']['Content-Type'].startswith('multipart/form-data; boundary=')
    assert b'name="attachment"' in sent['raw']
    assert b'gz-bytes' in sent['raw']


def test_attach_sends_nothing_the_forge_already_holds_under_the_name(server, tmp_path: Path) -> None:
    """Idempotent by name -- and a result's name is its content hash: a replayed upload stores nothing twice."""
    record = tmp_path / f'run-{LIVE}-linux-r1-0123456789abcdef.json.gz'
    record.write_bytes(b'gz-bytes')
    answer('GET', f'{API}/issues', (200, [{'number': 3, 'title': RECORDS_TITLE}]))
    answer('GET', f'{API}/issues/3/assets', (200, [_asset(7, record.name)]))
    assert attach(client(FORGE, Loopback(server)), record).url.endswith('/7')
    assert [r['method'] for r in Recorder.received] == ['GET', 'GET'], 'read, never uploaded'


def test_prune_deletes_only_records_of_shas_nobody_keeps(server) -> None:
    """PLANTED CONTROL: a dead sha's record goes, a live sha's record and a non-record file stay."""
    answer('GET', f'{API}/issues', (200, [{'number': 3, 'title': RECORDS_TITLE}]))
    assets = [_asset(1, f'run-{LIVE}-linux-r1.json.gz'), _asset(2, f'run-{DEAD}-linux-r1.json.gz'), _asset(3, 'x.txt')]
    answer('GET', f'{API}/issues/3/assets', (200, assets))
    answer('DELETE', f'{API}/issues/3/assets/2', (204, None))
    built = client(FORGE, Loopback(server))
    assert [a.id for a in listing(built)] == [1, 2, 3]
    dry = prune(built, {LIVE}, unit_results=1, dry_run=True)
    assert [a.id for a in dry] == [2]
    assert not [r for r in Recorder.received if r['method'] == 'DELETE'], 'a dry run deletes nothing'
    assert [a.id for a in prune(built, {LIVE}, unit_results=1)] == [2]
    assert [r['path'] for r in Recorder.received if r['method'] == 'DELETE'] == [f'{API}/issues/3/assets/2']


def test_github_records_live_on_the_prerelease_never_an_issue(server) -> None:
    answer('GET', '/repos/o/r/releases', (200, [{'id': 9, 'tag_name': forgerecords.RECORDS_TAG}]))
    answer('GET', '/repos/o/r/releases/9/assets', (200, [_asset(4, f'run-{LIVE}-linux-r1.json.gz')]))
    assert [a.id for a in listing(client(Forge('github.com', 'o', 'r'), Loopback(server)))] == [4]
    assert not [r for r in Recorder.received if '/issues' in r['path']], 'GitHub never reads an issue for records'


def _history(tmp_path: Path) -> tuple[Path, list[str]]:
    repo = make_repo(tmp_path, 'https://forge.example.org/o/r.git', branch='main')
    shas = []
    for name in ('one', 'two', 'three'):
        (repo / name).write_text(name, encoding='utf-8')
        run_git(repo, 'add', name)
        run_git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', name)
        shas.append(git_out(repo, 'rev-parse', 'HEAD'))
    run_git(repo, 'update-ref', 'refs/remotes/origin/main', shas[-1])
    run_git(repo, 'update-ref', 'refs/remotes/origin/lane/x', shas[0])
    return repo, shas


def test_kept_shas_are_every_origin_tip_and_the_newest_trunk_commits(tmp_path: Path) -> None:
    repo, shas = _history(tmp_path)
    assert kept_shas(repo, trunk='main', keep_trunk=1) == {shas[2], shas[0]}
    assert kept_shas(repo, trunk='main', keep_trunk=3) == set(shas)
    assert kept_shas(repo, trunk='absent', keep_trunk=3) == {shas[2], shas[0]}


def test_the_prune_cli_fetches_then_keeps_live_tips(server, tmp_path: Path, capsys) -> None:
    repo, shas = _history(tmp_path)
    answer('GET', f'{API}/issues', (200, [{'number': 3, 'title': RECORDS_TITLE}]))
    assets = [_asset(1, f'run-{shas[1]}-linux-r1.json.gz'), _asset(2, f'run-{shas[2]}-linux-r1.json.gz')]
    answer('GET', f'{API}/issues/3/assets', (200, assets))
    answer('DELETE', f'{API}/issues/3/assets/1', (204, None))
    fetched: list[Path] = []
    argv = ['prune', '--keep-trunk', '1']
    env = credential_env(tmp_path)
    code = forgerecords.main(argv, cwd=repo, env=env, transport=Loopback(server), fetch=fetched.append)
    assert code == 0
    assert fetched == [repo]
    assert f'deleted run-{shas[1]}' in capsys.readouterr().out


def test_prune_keeps_only_the_newest_unit_results_the_retention_policy_allows(server) -> None:
    """PLANTED CONTROL: unit results (D16) beyond ``[retention] unit_results`` go oldest first; records unaffected."""
    assert Policy().unit_results > 0, 'the one retention policy declares the budget'
    unit = [_asset(i, f'unit-{c * 64}-{"f" * 64}.tar.gz') for i, c in ((4, 'a'), (5, 'b'), (6, 'c'))]
    legacy = _asset(2, f'unit-{"d" * 64}-{"f" * 64}.tar.zst')
    answer('GET', f'{API}/issues', (200, [{'number': 3, 'title': RECORDS_TITLE}]))
    answer('GET', f'{API}/issues/3/assets', (200, [_asset(1, f'run-{LIVE}-linux-r1.json.gz'), legacy, *unit]))
    built = client(FORGE, Loopback(server))
    assert [a.id for a in prune(built, {LIVE}, unit_results=2, dry_run=True)] == [2, 4]
    assert [a.id for a in prune(built, {LIVE}, unit_results=0, dry_run=True)] == [2, 4, 5, 6]


def test_the_serve_prune_runs_at_most_once_per_interval_with_the_retention_budget(monkeypatch, tmp_path: Path) -> None:
    """Rate-limited by a stamp: a tick inside PRUNE_EVERY of the last prune does nothing; a failure alarms."""
    calls: list[tuple[frozenset[str], int]] = []
    monkeypatch.setattr(forgerecords, 'kept_shas', lambda _root, **_k: frozenset({LIVE}))
    monkeypatch.setattr(
        forgerecords, 'prune', lambda _c, keep, *, unit_results: calls.append((keep, unit_results)) or ()
    )
    alarms: list = []
    stamp, now = tmp_path / 'stamp', datetime(2026, 10, 17, tzinfo=UTC)
    run = functools.partial(
        forgerecords.serve_prune, tmp_path, SimpleNamespace(forge=FORGE), stamp=stamp, table={'unit_results': 3},
        say=lambda _l: None, alarm=alarms.append, trunk='main',
    )  # fmt: skip
    run(now=now)
    run(now=now + forgerecords.PRUNE_EVERY / 2)
    assert calls == [(frozenset({LIVE}), 3)], 'once per interval, with the [retention] budget'
    run(now=now + forgerecords.PRUNE_EVERY)
    assert len(calls) == 2
    monkeypatch.setattr(forgerecords, 'prune', lambda *_a, **_k: (_ for _ in ()).throw(OSError('down')))
    run(now=now + 2 * forgerecords.PRUNE_EVERY)
    assert [a.kind for a in alarms] == [STORAGE]


def test_a_named_file_is_replaced_never_duplicated_and_read_back(server) -> None:
    """The one mutable record (``hpc-allocation.json``): put deletes the old copy, get reads the newest."""
    answer('GET', f'{API}/issues', (200, [{'number': 3, 'title': RECORDS_TITLE}]))
    held = [_asset(4, 'hpc-allocation.json'), _asset(5, f'run-{LIVE}-linux-r1.json.gz')]
    answer('GET', f'{API}/issues/3/assets', (200, held))
    answer('DELETE', f'{API}/issues/3/assets/4', (204, None))
    answer('POST', f'{API}/issues/3/assets', (201, _asset(6, 'hpc-allocation.json')))
    answer('GET', '/attachments/4', (200, {'expires': 'x'}))
    built = client(FORGE, Loopback(server))
    assert read_named(built, 'hpc-allocation.json') == b'{"expires": "x"}'
    assert read_named(built, 'absent.json') is None
    assert replace_named(built, 'hpc-allocation.json', b'{}').id == 6
    deleted = [r['path'] for r in Recorder.received if r['method'] == 'DELETE']
    assert deleted == [f'{API}/issues/3/assets/4'], 'only the named file goes; a run record stays'
    assert remove_named(built, 'absent.json') == 0
