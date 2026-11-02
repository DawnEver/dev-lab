"""BRANCH FLOW: trunk by fast-forward only, every PR on integration, child branches synced from integration only.

Real git repositories (a bare ``origin`` and a clone) and the loopback forge for BOTH backends; the
evidence is the refs git holds and the requests the forge server recorded.
"""

from __future__ import annotations

from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from _branch_repos import advance, clone_pair, commit
from _forge_fake import Loopback, Recorder, answer, client, git_out, run_git, serve

from dev_lab.dev import forgesync
from dev_lab.dev.forge import Forge
from dev_lab.dev.forgeintegration import CONTEXT, retarget_note, tick
from dev_lab.dev.forgelanes import OWNER_CLOSED, open_lanes
from dev_lab.dev.forgepulls import Marker, comment_upsert, marker
from dev_lab.dev.forgerecords import RECORDS_TAG, attach, listing
from dev_lab.dev.lanepolicy import Policy, load_policy
from dev_lab.dev.trialmerge import merged_at, trial

_DECLARED = Policy(integration='integrate/main')  # every repo declares its integration branch (D83)

GITEA = Forge('forge.example.org', 'o', 'r')
GITHUB = Forge('github.com', 'o', 'r')
GAPI, HAPI = '/api/v1/repos/o/r', '/repos/o/r'
POLICY = _DECLARED


@pytest.fixture
def server() -> Iterator[ThreadingHTTPServer]:
    yield from serve()


def _part(state: str = 'success', scope: str = 'full', sid: int = 1) -> dict[str, object]:
    return {
        'id': sid,
        'context': 'tests/base',
        'status': state,
        'description': f'scope={scope} ran=3 hands=-',
    }


def _pr(number: int, head: str, base: str, sha: str) -> dict[str, object]:
    return {
        'number': number,
        'title': 't',
        'state': 'open',
        'body': '',
        'html_url': f'u/{number}',
        'user': {'login': 'x'},
        'head': {'ref': head, 'sha': sha},
        'base': {'ref': base},
    }


# --- trial merges ---------------------------------------------------------------------------------


def test_a_trial_merge_names_behind_and_conflicts_without_touching_the_tree(tmp_path: Path) -> None:
    _, work = clone_pair(tmp_path)
    lane = advance(work, 'integrate/main', 'x.txt', 'ours\n')
    run_git(work, 'checkout', '-q', '-B', 'feat/a', 'origin/main')
    child = commit(work, 'x.txt', 'theirs\n')
    found = trial(work, 'origin/integrate/main', child)
    assert (found.behind, found.conflicts) == (1, ('x.txt',))
    assert git_out(work, 'status', '--porcelain') == ''
    assert trial(work, 'origin/integrate/main', lane).clean


def _child(tmp_path: Path) -> Path:
    _, work = clone_pair(tmp_path)
    advance(work, 'integrate/main', 'i.txt', 'i\n')
    advance(work, 'feat/other', 'o.txt', 'o\n')
    run_git(work, 'checkout', '-q', '-B', 'feat/mine', 'origin/main')
    commit(work, 'm.txt', 'm\n')
    return work


def test_sync_merges_integration_only_and_never_another_lane(tmp_path: Path) -> None:
    work = _child(tmp_path)
    _, merged = forgesync.sync(work, POLICY)
    assert merged == ('origin/integrate/main',)
    assert (work / 'i.txt').exists()
    assert not (work / 'o.txt').exists(), "another lane's work never arrives sideways"
    with pytest.raises(ValueError, match='DOWNSTREAM-SYNCS-INTEGRATION'):
        forgesync.sync(work, POLICY, ['origin/feat/other'])


def test_a_watched_ref_is_merged_after_integration(tmp_path: Path) -> None:
    work = _child(tmp_path)
    forgesync.watch(work, 'feat/mine', 'origin/feat/other')
    assert forgesync.upstreams(work, 'feat/mine', POLICY) == ('origin/integrate/main', 'origin/feat/other')
    _, merged = forgesync.sync(work, POLICY)
    assert merged == ('origin/integrate/main', 'origin/feat/other')
    forgesync.unwatch(work, 'feat/mine', 'origin/feat/other')
    assert forgesync.upstreams(work, 'feat/mine', POLICY) == ('origin/integrate/main',)
    assert git_out(work, 'status', '--porcelain') == '', 'the opt-in is git config, never a file'


def test_sync_stops_on_a_conflict_naming_files_and_merges_nothing(tmp_path: Path) -> None:
    _, work = clone_pair(tmp_path)
    advance(work, 'integrate/main', 'x.txt', 'ours\n')
    run_git(work, 'checkout', '-q', '-B', 'feat/mine', 'origin/main')
    head = commit(work, 'x.txt', 'theirs\n')
    found, merged = forgesync.sync(work, POLICY)
    assert merged == ()
    assert found.conflicting[0][1].conflicts == ('x.txt',)
    assert git_out(work, 'rev-parse', 'HEAD') == head
    assert git_out(work, 'status', '--porcelain') == ''


def test_sync_refuses_on_the_trunk_and_on_integration(tmp_path: Path) -> None:
    _, work = clone_pair(tmp_path)
    for branch in ('main', 'integrate/main'):
        run_git(work, 'checkout', '-q', '-B', branch, 'origin/main')
        with pytest.raises(ValueError, match='not a child branch'):
            forgesync.sync(work, POLICY)


# --- comments, retarget and the integration tick on both backends ---------------------------------


@pytest.mark.parametrize(('forge', 'api'), [(GITEA, GAPI), (GITHUB, HAPI)])
def test_one_comment_is_updated_never_duplicated(server, forge: Forge, api: str) -> None:
    existing = {'id': 9, 'body': f'{marker(Marker.INTEGRATION)}\nold', 'html_url': 'c/9'}
    answer('GET', f'{api}/issues/4/comments', (200, [{'id': 1, 'body': 'hi', 'html_url': 'c/1'}, existing]))
    answer('PATCH', f'{api}/issues/comments/9', (200, {'id': 9, 'body': 'x', 'html_url': 'c/9'}))
    built = client(forge, Loopback(server))
    assert comment_upsert(built, 4, kind=Marker.INTEGRATION, text='new')[0] == 'updated'
    assert [r['method'] for r in Recorder.received if r['method'] != 'GET'] == ['PATCH']
    existing['body'] = f'{marker(Marker.INTEGRATION)}\nnew'
    assert comment_upsert(built, 4, kind=Marker.INTEGRATION, text='new')[0] == 'unchanged'
    assert [r['method'] for r in Recorder.received if r['method'] != 'GET'] == ['PATCH'], 'nothing written twice'


@pytest.mark.parametrize(('forge', 'api'), [(GITEA, GAPI), (GITHUB, HAPI)])
def test_the_tick_retargets_a_trunk_pr_and_reports_each_child_once(
    server, tmp_path: Path, forge: Forge, api: str
) -> None:
    _, work = clone_pair(tmp_path)
    advance(work, 'integrate/main', 'i.txt', 'i\n')
    pr_head = advance(work, 'feat/pr', 'p.txt', 'p\n')
    lane = advance(work, 'feat/lane', 'l.txt', 'l\n')
    statuses = f'{api}/commits/{{}}/statuses' if forge is GITHUB else f'{api}/statuses/{{}}'  # both LIST endpoints
    for sha in (pr_head, lane):
        answer('GET', statuses.format(sha), (200, []))
    answer('GET', f'{api}/pulls', (200, [_pr(4, 'feat/pr', 'main', pr_head)]))
    answer('PATCH', f'{api}/pulls/4', (200, _pr(4, 'feat/pr', 'integrate/main', pr_head)))
    answer('POST', f'{api}/issues/4/comments', (201, {'id': 2, 'body': 'x', 'html_url': 'c/2'}))
    answer('GET', f'{api}/issues/4/comments', (200, []))
    answer('GET', f'{api}/issues', (200, []))
    answer('POST', f'{api}/statuses/{lane}', (201, {'context': CONTEXT, 'state': 'pending', 'description': 'd'}))
    built = client(forge, Loopback(server))
    lines = tick(work, built, POLICY, fetch_pull=lambda _r, _m, _n: pr_head).lines
    writes = [(r['method'], r['path']) for r in Recorder.received if r['method'] != 'GET']
    assert ('PATCH', f'{api}/pulls/4') in writes
    assert Recorder.received[[r['method'] for r in Recorder.received].index('PATCH')]['body'] == {
        'base': 'integrate/main'
    }
    comments = [r['body']['body'] for r in Recorder.received if r['path'] == f'{api}/issues/4/comments' and r['body']]
    assert retarget_note(POLICY) in comments[0]
    assert marker(Marker.INTEGRATION) in comments[1]
    assert 'behind `integrate/main` by 1; clean' in comments[1]
    assert 'syncs from: `origin/integrate/main`' in comments[1]
    assert ('POST', f'{api}/statuses/{lane}') in writes, 'a child without a PR gets a commit status'
    assert not any(r['path'] == f'{api}/statuses/{pr_head}' and r['method'] == 'POST' for r in Recorder.received)
    assert len(lines) == 3


def test_a_merged_child_is_reported_at_its_merge(tmp_path: Path) -> None:
    _, work = clone_pair(tmp_path)
    lane = advance(work, 'feat/a', 'a.txt', 'a\n')
    run_git(work, 'checkout', '-q', '-B', 'integ', 'origin/integrate/main')
    commit(work, 'i.txt', 'i\n')
    run_git(work, 'merge', '-q', '--no-ff', '--no-edit', lane)
    merge = git_out(work, 'rev-parse', 'HEAD')
    assert merged_at(work, 'integ', lane) == merge


# --- run records on the GitHub backend ------------------------------------------------------------


def test_github_run_records_are_assets_of_one_release(server, tmp_path: Path) -> None:
    record = tmp_path / f'run-{"a" * 40}-linux-r1.json.gz'
    record.write_bytes(b'gz')
    answer('GET', f'{HAPI}/releases', (200, []), (200, [{'id': 77, 'tag_name': RECORDS_TAG}]))
    answer('POST', f'{HAPI}/releases', (201, {'id': 77}))
    asset = {'id': 5, 'name': record.name, 'browser_download_url': 'https://github.com/d/5'}
    answer('POST', f'{HAPI}/releases/77/assets', (201, asset))
    answer('GET', f'{HAPI}/releases/77/assets', (200, []), (200, [asset]))  # none held yet, then the listing
    loop = Loopback(server)
    built = client(GITHUB, loop)
    assert attach(built, record).url == 'https://github.com/d/5'
    assert 'uploads.github.com' in loop.asked
    created = next(r for r in Recorder.received if r['path'] == f'{HAPI}/releases' and r['method'] == 'POST')
    assert created['body']['tag_name'] == RECORDS_TAG
    upload = next(r for r in Recorder.received if r['path'].startswith(f'{HAPI}/releases/77/assets?'))
    assert upload['raw'] == b'gz'
    assert [item.id for item in listing(built)] == [5]


def test_the_policy_declares_integration_and_trunk(tmp_path: Path) -> None:
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.dev_lab.integrator]\nintegration = "stage"\ntrunk = "stable"\n', encoding='utf-8'
    )
    assert load_policy(tmp_path) == Policy(integration='stage', trunk='stable')


# --- a pushed lane gets its PR --------------------------------------------------------------------


def _closed(number: int, head: str, *, merged: bool) -> dict[str, object]:
    return _pr(number, head, 'integrate/main', 'f' * 40) | {'state': 'closed', 'merged': merged}


@pytest.mark.parametrize(('forge', 'api'), [(GITEA, GAPI), (GITHUB, HAPI)])
def test_only_a_pushed_unlanded_lane_without_a_pr_gets_one(server, tmp_path: Path, forge: Forge, api: str) -> None:
    _, work = clone_pair(tmp_path)
    advance(work, 'pr/new', 'n.txt', 'n\n', 'feat(n): the newest subject')
    landed = advance(work, 'pr/landed', 'l.txt', 'l\n')
    run_git(work, 'push', '-q', '--no-verify', 'origin', f'{landed}:refs/heads/integrate/main')
    advance(work, 'pr/open', 'o.txt', 'o\n')
    advance(work, 'pr/refused', 'r.txt', 'r\n')
    advance(work, 'feat/mine', 'm.txt', 'm\n')
    advance(work, 'pr/relock-1', 'k.txt', 'k\n')
    run_git(work, 'fetch', '-q', 'origin')
    declared = (work / 'pyproject.toml').read_text(encoding='utf-8')
    (work / 'pyproject.toml').write_text(f"{declared}[tool.dev_lab.branchset]\ntrunk = 'main'\n", encoding='utf-8')
    closed = [_closed(7, 'pr/refused', merged=False), _closed(8, 'pr/new', merged=True)]
    answer('GET', f'{api}/pulls', (200, closed))
    answer('POST', f'{api}/pulls', (201, _pr(9, 'pr/new', 'integrate/main', '')))
    answer('GET', f'{api}/pulls/9', (200, _pr(9, 'pr/new', 'integrate/main', '') | {'node_id': 'N9'}))
    answer('POST', '/graphql', (200, {'data': {}}))
    built = client(forge, Loopback(server))
    lines, opened = open_lanes(work, built, POLICY, {'pr/open'})
    creates = [r['body'] for r in Recorder.received if (r['method'], r['path']) == ('POST', f'{api}/pulls')]
    assert [(c['head'], c['base'], c['title']) for c in creates] == [
        ('pr/new', 'integrate/main', 'feat(n): the newest subject')
    ], 'landed, open-PR, owner-closed, relock and non-ephemeral lanes get none; a MERGED closed PR blocks nothing'
    assert 'Opened by the forge' in creates[0]['body']
    assert [(branch, pr) for branch, _sha, pr in opened] == [('pr/new', 9)]
    assert OWNER_CLOSED.format(branch='pr/refused', number=7) in lines
    graphql = [r for r in Recorder.received if r['path'] == '/graphql']
    assert len(graphql) == (1 if forge is GITHUB else 0), 'GitHub puts the opened PR on auto-merge'
    assert any('auto-merge enabled' in line for line in lines) is (forge is GITHUB)


def test_a_repo_without_ephemeral_lanes_lists_no_closed_pr(server, tmp_path: Path) -> None:
    _, work = clone_pair(tmp_path)
    advance(work, 'pr/new', 'n.txt', 'n\n')
    built = client(GITEA, Loopback(server))
    assert open_lanes(work, built, POLICY, set()) == ([], []), 'no branch set declared: no namespace to open from'
    assert Recorder.received == []
