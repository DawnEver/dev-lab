"""VERDICT-AS-STATUS: ``dev_lab.dev.forgestatus`` against a REAL loopback server and REAL git repos.

The evidence is what the server RECORDED. Both forges are one table of cases, because the claim is
one normalized ``CommitStatus`` whichever forge answered; only the request shape differs.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from _forge_fake import Loopback, Recorder, answer, client, credential_env, make_repo, run_git, serve
from lab_commons.outcomes import Conclusion

from dev_lab.dev.forge import Forge
from dev_lab.dev.forgestatus import (
    DESCRIPTION_LIMIT,
    CommitStatus,
    head_sha,
    main,
    state_for,
    status_history,
    status_list,
    status_post,
    verdict_commit,
)
from dev_lab.dev.logref import LogRef
from dev_lab.dev.treedirt import status_paths
from dev_lab.dev.verdict import Proof, Result, Selector, Verdict


@pytest.fixture
def server() -> Iterator[ThreadingHTTPServer]:
    yield from serve()


CASES = (
    pytest.param(Forge('forge.example.org', 'o', 'r'), '/api/v1/repos/o/r', id='gitea'),
    pytest.param(Forge('github.com', 'o', 'r'), '/repos/o/r', id='github'),
)

_SHA = 'a' * 40


def _verdict(tmp_path: Path, outcome: Conclusion) -> Verdict:
    log = tmp_path / 'v.log'
    log.write_text('ran\n', encoding='utf-8')
    selector = Selector(spec='verify', node_ids=('x',))
    if outcome is Conclusion.INCONCLUSIVE:
        result = Result.inconclusive('x went silent', proof=Proof.of(selector, []))
    else:
        result = Result.settled(proof=Proof.of(selector, ['x']), failures=['x'] if outcome is Conclusion.FAIL else [])
    return Verdict(tree='sha256:' + 'b' * 64, env='env:1', selector=selector, result=result, log=LogRef.of(log))


def test_pass_is_success_fail_is_failure_and_inconclusive_is_error() -> None:
    # User ruling 2026-10-04: a lane may push an INCONCLUSIVE tree, so every pushed tree carries its
    # verdict -- a non-success state the trunk's protection still refuses.
    assert state_for(Conclusion.PASS) == 'success'
    assert state_for(Conclusion.FAIL) == 'failure'
    assert state_for(Conclusion.INCONCLUSIVE) == 'error'


@pytest.mark.parametrize(('forge', 'root'), CASES)
def test_status_post_sends_state_context_and_a_description_that_fits(server, forge, root) -> None:
    answer('POST', f'{root}/statuses/{_SHA}', (201, {'context': 'tests/linux', 'state': 'success', 'description': 'd'}))
    posted = status_post(
        client(forge, Loopback(server)),
        _SHA,
        context='tests/linux',
        state='success',
        description='x' * (DESCRIPTION_LIMIT - 1),
    )
    sent = Recorder.received[-1]
    assert (sent['method'], sent['path']) == ('POST', f'{root}/statuses/{_SHA}')
    assert sent['body'] == {'state': 'success', 'context': 'tests/linux', 'description': 'x' * (DESCRIPTION_LIMIT - 1)}
    assert posted == CommitStatus('tests/linux', 'success', 'd', '')


def test_a_state_outside_the_four_is_refused_before_anything_is_sent(server) -> None:
    with pytest.raises(ValueError, match='one of'):
        status_post(client(CASES[0].values[0], Loopback(server)), _SHA, context='c', state='skipped', description='')
    assert Recorder.received == []


def test_gitea_list_keeps_the_newest_status_per_context_and_reads_status_as_state(server) -> None:
    root = '/api/v1/repos/o/r'
    answer(
        'GET',
        f'{root}/statuses/{_SHA}',
        (
            200,
            [
                {'id': 3, 'context': 'tests/linux', 'status': 'success', 'description': 'new'},
                {'id': 1, 'context': 'tests/linux', 'status': 'failure', 'description': 'old'},
                {'id': 2, 'context': 'tests/windows', 'status': 'pending', 'description': 'h'},
            ],
        ),
    )
    listed = status_list(client(Forge('forge.example.org', 'o', 'r'), Loopback(server)), _SHA)
    assert listed == (
        CommitStatus('tests/linux', 'success', 'new', ''),
        CommitStatus('tests/windows', 'pending', 'h', ''),
    )


def test_github_reads_the_status_list_with_its_creator_newest_per_context(server) -> None:
    """D11: the combined endpoint carries no creator, so the LIST is read. PLANTED: the older post is superseded."""
    listed = [
        {
            'id': 2,
            'context': 'tests/linux',
            'state': 'success',
            'description': 'd',
            'creator': {'login': 'github-actions[bot]'},
        },
        {
            'id': 1,
            'context': 'tests/linux',
            'state': 'failure',
            'description': 'old',
            'creator': {'login': 'maintainer'},
        },
    ]
    answer('GET', f'/repos/o/r/commits/{_SHA}/statuses', (200, listed))
    (one,) = status_list(client(Forge('github.com', 'o', 'r'), Loopback(server)), _SHA)
    assert one == CommitStatus('tests/linux', 'success', 'd', '')
    assert one.creator == 'github-actions[bot]'


# --------------------------------------------------------------------------------------------
# which commit a verdict is about


def test_only_a_clean_unmoved_tree_names_a_commit() -> None:
    assert verdict_commit(_SHA, _SHA, (), ()) == _SHA
    assert verdict_commit(_SHA, _SHA, ('M src/a.py',), ('M src/a.py',)) is None, 'dirty before the run'
    assert verdict_commit(_SHA, _SHA, (), ('?? src/new.py',)) is None, 'the tree moved during the run'
    assert verdict_commit(_SHA, 'c' * 40, (), ()) is None, 'HEAD moved during the run'
    assert verdict_commit(None, None, (), ()) is None, 'no commit at all'
    assert verdict_commit(_SHA, _SHA, None, ()) is None, 'an unreadable status is not a clean one'


def test_head_sha_and_status_paths_read_a_real_checkout(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, 'https://forge.example.org/o/r.git')
    assert head_sha(repo) is None
    (repo / 'a.txt').write_text('a\n', encoding='utf-8')
    run_git(repo, 'add', 'a.txt')
    run_git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'a')
    assert head_sha(repo) is not None
    assert len(head_sha(repo) or '') == 40
    assert status_paths(repo) == ()


# --------------------------------------------------------------------------------------------
# history and links


def test_an_inconclusive_verdict_names_itself_in_the_error_description(tmp_path: Path) -> None:
    verdict = _verdict(tmp_path, Conclusion.INCONCLUSIVE)
    assert state_for(verdict.result.outcome) == 'error'
    assert 'result=inconclusive' in verdict.line()[:DESCRIPTION_LIMIT]


def test_a_target_url_is_sent_only_when_given(server) -> None:
    forge = Forge('forge.example.org', 'o', 'r')
    answer('POST', f'/api/v1/repos/o/r/statuses/{_SHA}', (201, {'context': 'c', 'state': 'success'}))
    status_post(client(forge, Loopback(server)), _SHA, context='c', state='success', description='d', target_url='u')
    status_post(client(forge, Loopback(server)), _SHA, context='c', state='success', description='d')
    assert Recorder.received[0]['body']['target_url'] == 'u'
    assert 'target_url' not in Recorder.received[1]['body']


@pytest.mark.parametrize(
    ('forge', 'path'),
    [
        (Forge('forge.example.org', 'o', 'r'), f'/api/v1/repos/o/r/statuses/{_SHA}'),
        (Forge('github.com', 'o', 'r'), f'/repos/o/r/commits/{_SHA}/statuses'),
    ],
)
def test_history_is_every_post_oldest_first_with_its_creator(server, forge, path) -> None:
    posts = [
        {'id': 9, 'context': 'tests/linux', 'status': 'pending', 'creator': {'login': 'bob'}},
        {'id': 4, 'context': 'tests/linux', 'status': 'pending', 'creator': {'login': 'alice'}},
    ]
    answer('GET', path, (200, posts))
    history = status_history(client(forge, Loopback(server)), _SHA)
    assert [(s.id, s.creator) for s in history] == [(4, 'alice'), (9, 'bob')]


@pytest.mark.parametrize(
    'call',
    [
        lambda built: status_history(built, ''),
        lambda built: status_list(built, ''),
        lambda built: status_post(built, '', context='tests/linux', state='pending', description='d'),
    ],
)
def test_an_empty_sha_is_refused_before_any_url_is_formatted(server, call) -> None:
    """``statuses/`` with no sha is a request the forge refuses -- and one such read exited a whole tick."""
    with pytest.raises(ValueError, match='no commit sha'):
        call(client(Forge('forge.example.org', 'o', 'r'), Loopback(server)))
    assert Recorder.received == [], 'refused before the forge was asked'


# --------------------------------------------------------------------------------------------
# the CLI


def test_the_cli_posts_and_lists_with_json(server, tmp_path: Path, capsys) -> None:
    repo = make_repo(tmp_path, 'https://f.example/o/r.git')
    answer('POST', f'/api/v1/repos/o/r/statuses/{_SHA}', (201, {'context': 'lab/test', 'state': 'pending'}))
    argv = ['post', _SHA, '--context', 'lab/test', '--state', 'pending', '--description', 'probe', '--json']
    assert main(argv, cwd=repo, env=credential_env(tmp_path), transport=Loopback(server)) == 0
    assert json.loads(capsys.readouterr().out)['context'] == 'lab/test'
    assert (
        Recorder.received[-1]['headers']['Authorization'] == 'Basic dTpU'
    )  # u:T, the helper's username and secret, as git presents them
    assert not Recorder.received[-1]['body']['description'].startswith('['), 'status writes carry no provenance'
    answer('GET', f'/api/v1/repos/o/r/statuses/{_SHA}', (200, [{'id': 1, 'context': 'lab/test', 'status': 'pending'}]))
    assert main(['list', _SHA], cwd=repo, env=credential_env(tmp_path), transport=Loopback(server)) == 0
    assert 'lab/test  pending' in capsys.readouterr().out


def test_the_cli_reports_a_refusal_and_exits_nonzero(server, tmp_path: Path, capsys) -> None:
    repo = make_repo(tmp_path, 'https://f.example/o/r.git')
    answer('GET', f'/api/v1/repos/o/r/statuses/{_SHA}', (404, {'message': 'nope'}))
    assert main(['list', _SHA], cwd=repo, env=credential_env(tmp_path), transport=Loopback(server)) == 1
    assert 'REFUSED' in capsys.readouterr().err


# --------------------------------------------------------------------------------------------
# #1102: every page of a commit's statuses is read -- merge-ready reposts and their ``#k`` continuations
# bury a part's status pages deep, and a first-page read never sees it


def _status_path(forge: Forge, root: str) -> str:
    return f'{root}/commits/{_SHA}/statuses' if forge.host == 'github.com' else f'{root}/statuses/{_SHA}'


def _page_param(forge: Forge) -> str:
    return 'per_page' if forge.host == 'github.com' else 'limit'


def _reposts(first: int, count: int) -> list[dict]:
    return [
        {'id': first + n, 'context': 'tests/merge-ready', 'state': 'pending', 'status': 'pending'} for n in range(count)
    ]


@pytest.mark.parametrize(('forge', 'root'), CASES)
def test_a_part_posted_behind_a_hundred_reposts_is_read(server, forge, root) -> None:
    """PLANTED: 120 merge-ready reposts, newest first, then the part on page 3 -- a first-page read misses it."""
    path, size = _status_path(forge, root), 50
    part = {'id': 1, 'context': 'tests/base', 'state': 'success', 'status': 'success'}
    every = [*reversed(_reposts(2, 120)), part]
    for page in range(1, 4):
        listed = every[(page - 1) * size : page * size]
        answer('GET', f'{path}?{_page_param(forge)}={size}&page={page}', (200, listed))
    built = client(forge, Loopback(server))
    assert {status.context for status in status_list(built, _SHA)} == {'tests/base', 'tests/merge-ready'}
    assert len(status_history(built, _SHA)) == 121


@pytest.mark.parametrize(('forge', 'root'), CASES)
def test_a_pager_answering_full_full_partial_reads_all_three_pages(server, forge, root) -> None:
    path, size = _status_path(forge, root), 50
    for page, count in ((1, size), (2, size), (3, 7)):
        answer('GET', f'{path}?{_page_param(forge)}={size}&page={page}', (200, _reposts(page * 1000, count)))
    assert len(status_history(client(forge, Loopback(server)), _SHA)) == 2 * size + 7
    assert [r['path'].rsplit('page=', 1)[1] for r in Recorder.received] == ['1', '2', '3']


@pytest.mark.parametrize(('forge', 'root'), CASES)
def test_a_server_ignoring_paging_is_read_once_and_never_loops(server, forge, root) -> None:
    """A forge answering its whole listing to every page (and every size) ends at the repeated page."""
    whole = _reposts(1, 60)
    answer('GET', _status_path(forge, root), (200, whole))
    assert len(status_history(client(forge, Loopback(server)), _SHA)) == 60
    assert len(Recorder.received) <= 3


def test_the_cli_lists_with_json_and_the_created_time_as_iso_text(server, tmp_path: Path, capsys) -> None:
    """#1102's second defect: ``CommitStatus.created`` is a datetime, which ``json.dumps`` refused."""
    repo = make_repo(tmp_path, 'https://f.example/o/r.git')
    posted = {'id': 1, 'context': 'lab/test', 'status': 'success', 'created_at': '2026-11-20T10:00:00Z'}
    answer('GET', f'/api/v1/repos/o/r/statuses/{_SHA}', (200, [posted]))
    assert main(['list', _SHA, '--json'], cwd=repo, env=credential_env(tmp_path), transport=Loopback(server)) == 0
    (listed,) = json.loads(capsys.readouterr().out)
    assert listed['created'].startswith('2026-11-20T10:00:00')
