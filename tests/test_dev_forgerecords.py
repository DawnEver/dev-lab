"""RUN RECORDS as forge attachments: one closed issue holds them, and prune keeps only live shas' records."""

from __future__ import annotations

from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from _forge_fake import Loopback, Recorder, answer, client, credential_env, git_out, make_repo, run_git, serve

from lab_commons.dev import forgerecords
from lab_commons.dev.forge import Forge
from lab_commons.dev.forgerecords import RECORDS_TITLE, attach, kept_shas, listing, prune, records_issue, sha_of

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
    answer('POST', f'{API}/issues/3/assets', (201, _asset(7, record.name)))
    found = attach(client(FORGE, Loopback(server)), record)
    assert found.url.endswith('/7')
    sent = Recorder.received[-1]
    assert sent['path'] == f'{API}/issues/3/assets?name={record.name}'
    assert sent['headers']['Content-Type'].startswith('multipart/form-data; boundary=')
    assert b'name="attachment"' in sent['raw']
    assert b'gz-bytes' in sent['raw']


def test_prune_deletes_only_records_of_shas_nobody_keeps(server) -> None:
    """PLANTED CONTROL: a dead sha's record goes, a live sha's record and a non-record file stay."""
    answer('GET', f'{API}/issues', (200, [{'number': 3, 'title': RECORDS_TITLE}]))
    assets = [_asset(1, f'run-{LIVE}-linux-r1.json.gz'), _asset(2, f'run-{DEAD}-linux-r1.json.gz'), _asset(3, 'x.txt')]
    answer('GET', f'{API}/issues/3/assets', (200, assets))
    answer('DELETE', f'{API}/issues/3/assets/2', (204, None))
    built = client(FORGE, Loopback(server))
    assert [a.id for a in listing(built)] == [1, 2, 3]
    dry = prune(built, {LIVE}, dry_run=True)
    assert [a.id for a in dry] == [2]
    assert not [r for r in Recorder.received if r['method'] == 'DELETE'], 'a dry run deletes nothing'
    assert [a.id for a in prune(built, {LIVE})] == [2]
    assert [r['path'] for r in Recorder.received if r['method'] == 'DELETE'] == [f'{API}/issues/3/assets/2']


def test_github_holds_no_records() -> None:
    with pytest.raises(ValueError, match='gitea'):
        records_issue(client(Forge('github.com', 'o', 'r'), Loopback.__new__(Loopback)), create=False)


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
