"""ISSUE-IS-INTENT: derived issue state from REAL remote-tracking refs and a REAL loopback forge.

The refs are planted with ``git update-ref refs/remotes/origin/...`` over real commits, which is
exactly what a fetch leaves behind -- so the derivation reads the same objects it reads in a lane,
and no network is involved (the module is fetch-free by contract).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from _forge_fake import Loopback, Recorder, answer, client, credential_env, git_out, make_repo, run_git, serve

from dev_lab.dev.forge import Forge
from dev_lab.dev.forgeissue import (
    DONE,
    IN_PROGRESS,
    READY,
    TODO,
    Claim,
    IssueComment,
    Lane,
    claim,
    claims_of,
    comments_since,
    derive,
    issue_comments,
    issue_status,
    lanes_for,
    main,
)
from dev_lab.dev.forgestatus import CommitStatus
from dev_lab.dev.forgework import Comment


@pytest.fixture
def server() -> Iterator[ThreadingHTTPServer]:
    yield from serve()


_FORGE = Forge('forge.example.org', 'o', 'r')
_ROOT = '/api/v1/repos/o/r'


def _commit(repo: Path, message: str) -> None:
    run_git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', message)


def _head(repo: Path) -> str:
    return git_out(repo, 'rev-parse', 'HEAD')


def _lanes_repo(tmp_path: Path) -> Path:
    """origin/main with ``Closes #3``; feat/x referencing #7; fix/8-typo by name; feat/y unrelated."""
    repo = make_repo(tmp_path, 'https://forge.example.org/o/r.git', branch='main')
    _commit(repo, 'feat: base\n\nCloses #3')
    run_git(repo, 'update-ref', 'refs/remotes/origin/main', _head(repo))
    run_git(repo, 'symbolic-ref', 'refs/remotes/origin/HEAD', 'refs/remotes/origin/main')
    for branch, message in (
        ('feat/x', 'feat: part one\n\nRefs #7'),
        ('fix/8-typo', 'fix: typo'),
        ('feat/y', 'feat: y'),
    ):
        run_git(repo, 'checkout', '-q', '-b', branch, 'origin/main')
        _commit(repo, message)
        run_git(repo, 'update-ref', f'refs/remotes/origin/{branch}', _head(repo))
    run_git(repo, 'checkout', '-q', 'main')
    return repo


def test_the_derived_state_table() -> None:
    lane = Lane('feat/x', 'a' * 40, ready=False)
    green = Lane('feat/x', 'a' * 40, ready=True)
    assert derive(is_open=True, closed_on_default=False, lanes=()) == TODO
    assert derive(is_open=True, closed_on_default=False, lanes=(lane,)) == IN_PROGRESS
    assert derive(is_open=True, closed_on_default=False, lanes=(lane, green)) == READY
    assert derive(is_open=True, closed_on_default=True, lanes=(lane,)) == DONE
    assert derive(is_open=False, closed_on_default=False, lanes=()) == DONE


def test_lanes_are_found_by_commit_reference_and_by_fix_branch_name(tmp_path: Path) -> None:
    repo = _lanes_repo(tmp_path)
    assert [name for name, _tip in lanes_for(repo, 7)[0]] == ['feat/x']
    assert [name for name, _tip in lanes_for(repo, 8)[0]] == ['fix/8-typo']
    assert lanes_for(repo, 9) == ((), False)
    assert lanes_for(repo, 3) == ((), True), 'Closes #3 on the default branch'
    assert lanes_for(repo, 70)[0] == (), '#7 is not #70'


def test_claims_keep_the_latest_per_claimant_and_read_the_provenance_line() -> None:
    comments = (
        Comment(1, '[host-a · codex · feat/x]\n\nclaim feat/x', 'u1'),
        Comment(2, 'looks good', 'u2'),
        Comment(3, '[host-a · codex · feat/x2]\n\nclaim feat/x2', 'u3'),
        Comment(4, '[G · claude · fix/7-a]\n\nclaim fix/7-a', 'u4'),
    )
    assert claims_of(comments) == (
        Claim('feat/x2', '[host-a · codex · feat/x2]', 'u3'),
        Claim('fix/7-a', '[G · claude · fix/7-a]', 'u4'),
    ), 'host-a/codex re-claimed, so only its latest counts; the provenance line is per branch, the claimant per agent'


def test_issue_status_derives_ready_from_a_green_gate_and_reports_conflicting_claims(server, tmp_path: Path) -> None:
    repo = _lanes_repo(tmp_path)
    issue = {'number': 7, 'title': 't', 'state': 'open', 'body': '', 'html_url': 'h', 'user': {'login': 'a'}}
    answer('GET', f'{_ROOT}/issues/7', (200, issue))
    answer(
        'GET',
        f'{_ROOT}/issues/7/comments',
        (
            200,
            [{'id': 1, 'body': 'claim feat/x', 'html_url': 'c1'}, {'id': 2, 'body': 'claim feat/z', 'html_url': 'c2'}],
        ),
    )
    asked: list[str] = []

    def gate(_client: object, sha: str) -> tuple[CommitStatus, ...]:
        asked.append(sha)
        return (CommitStatus('tests/base', 'success', 'scope=full ran=3 hands=-', ''),)

    state = issue_status(client(_FORGE, Loopback(server)), repo, 7, statuses=gate)
    assert state.state == READY
    assert [lane.branch for lane in state.lanes] == ['feat/x']
    assert asked == [state.lanes[0].tip], 'the parts are read on the LANE TIP, nowhere else'
    assert state.conflict, 'two unstamped claims naming two branches are a conflict for the human'


def test_claim_comments_claim_branch_with_the_provenance_stamp(server, tmp_path: Path) -> None:
    repo = make_repo(tmp_path, 'https://forge.example.org/o/r.git', branch='feat/x')
    answer('POST', f'{_ROOT}/issues/7/comments', (201, {'id': 5, 'body': 'b', 'html_url': 'c5'}))
    claim(client(_FORGE, Loopback(server), stamp='[host-a · codex · feat/x]'), repo, 7)
    assert Recorder.received[-1]['body'] == {'body': '[host-a · codex · feat/x]\n\nclaim feat/x'}


def test_a_detached_claim_with_no_branch_is_refused(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, 'https://forge.example.org/o/r.git', branch='main')
    _commit(repo, 'a')
    run_git(repo, 'checkout', '-q', '--detach')
    with pytest.raises(ValueError, match='names a branch'):
        claim(client(_FORGE, Loopback.__new__(Loopback)), repo, 7)


def test_the_cli_prints_status_as_json(server, tmp_path: Path, capsys) -> None:
    repo = _lanes_repo(tmp_path)
    issue = {'number': 9, 'title': 't', 'state': 'open', 'body': '', 'html_url': 'h', 'user': {'login': 'a'}}
    answer('GET', f'{_ROOT}/issues/9', (200, issue))
    answer('GET', f'{_ROOT}/issues/9/comments', (200, []))
    assert main(['status', '9', '--json'], cwd=repo, env=credential_env(tmp_path), transport=Loopback(server)) == 0
    assert json.loads(capsys.readouterr().out)['state'] == TODO


def _raw(cid: int, issue: str, body: str) -> dict[str, object]:
    return {'id': cid, 'body': body, 'user': {'login': 'bot'}, 'created_at': '2026-10-01T10:00:00Z', 'issue_url': issue}


def test_comments_since_reads_the_repo_wide_listing_and_names_each_issue(server) -> None:
    answer(
        'GET',
        f'{_ROOT}/issues/comments',
        (200, [_raw(4, 'https://forge.example.org/o/r/issues/12', 'hi'), _raw(5, 'https://x/repos/o/r/issues/3', '')]),
    )
    found = comments_since(client(_FORGE, Loopback(server)), '2026-10-01T09:00:00Z')
    assert found == (
        IssueComment(12, 4, 'bot', 'hi', '2026-10-01T10:00:00Z'),
        IssueComment(3, 5, 'bot', '', '2026-10-01T10:00:00Z'),
    )
    assert 'since=2026-10-01T09%3A00%3A00Z' in Recorder.received[-1]['path']


def test_issue_comments_passes_since_only_when_given(server) -> None:
    answer('GET', f'{_ROOT}/issues/7/comments', (200, [_raw(1, 'https://forge.example.org/o/r/issues/7', 'b')]))
    assert issue_comments(client(_FORGE, Loopback(server)), 7) == (
        IssueComment(7, 1, 'bot', 'b', '2026-10-01T10:00:00Z'),
    )
    assert 'since=' not in Recorder.received[-1]['path']


def test_the_cli_prints_comments_since_as_json(server, tmp_path: Path, capsys) -> None:
    repo = make_repo(tmp_path, 'https://forge.example.org/o/r.git')
    answer('GET', f'{_ROOT}/issues/comments', (200, [_raw(4, 'https://forge.example.org/o/r/issues/12', 'hi')]))
    argv = ['comments-since', '2026-10-01T09:00:00Z', '--json']
    assert main(argv, cwd=repo, env=credential_env(tmp_path), transport=Loopback(server)) == 0
    assert json.loads(capsys.readouterr().out) == [
        {'issue': 12, 'id': 4, 'author': 'bot', 'body': 'hi', 'created': '2026-10-01T10:00:00Z'}
    ]
    argv = ['comments', '12', '--since', '2026-10-01T09:00:00Z', '--json']
    answer('GET', f'{_ROOT}/issues/12/comments', (200, []))
    assert main(argv, cwd=repo, env=credential_env(tmp_path), transport=Loopback(server)) == 0
    assert json.loads(capsys.readouterr().out) == []


_THREE = [
    {**_raw(31, 'https://forge.example.org/o/r/issues/5', 'first'), 'user': {'login': 'a'}},
    {**_raw(32, 'https://forge.example.org/o/r/issues/5', 'second'), 'created_at': '2026-10-01T11:00:00Z'},
    {**_raw(33, 'https://forge.example.org/o/r/issues/5', 'third'), 'created_at': '2026-10-01T12:00:00Z'},
]
_ISSUE5 = {
    'number': 5,
    'title': 't',
    'state': 'open',
    'html_url': 'https://forge.example.org/o/r/issues/5',
    'body': '',
    'user': {'login': 'a'},
}


@pytest.mark.parametrize(('forge', 'root', 'page'), [
    (_FORGE, _ROOT, 'limit='),
    (Forge('github.com', 'o', 'r'), '/repos/o/r', 'per_page='),
])  # fmt: skip
def test_view_with_comments_returns_all_three_in_order_on_both_forges(
    server, tmp_path: Path, capsys, *, forge: Forge, root: str, page: str
) -> None:
    """PLANTED CONTROL: three comments on the fake forge come back as three, oldest first, on Gitea and GitHub."""
    repo = make_repo(tmp_path, f'https://{forge.host}/o/r.git')
    answer('GET', f'{root}/issues/5', (200, _ISSUE5))
    answer('GET', f'{root}/issues/5/comments', (200, _THREE))
    argv = ['view', '5', '--comments', '--json']
    assert main(argv, cwd=repo, env=credential_env(tmp_path), transport=Loopback(server)) == 0
    shown = json.loads(capsys.readouterr().out)
    assert [(c['id'], c['author'], c['created'], c['body']) for c in shown['comments']] == [
        (31, 'a', '2026-10-01T10:00:00Z', 'first'),
        (32, 'bot', '2026-10-01T11:00:00Z', 'second'),
        (33, 'bot', '2026-10-01T12:00:00Z', 'third'),
    ]
    assert shown['issue']['number'] == 5
    assert page in Recorder.received[-1]['path']


def test_view_last_keeps_the_newest_k_and_text_names_id_author_time(server, tmp_path: Path, capsys) -> None:
    repo = make_repo(tmp_path, 'https://forge.example.org/o/r.git')
    answer('GET', f'{_ROOT}/issues/5', (200, _ISSUE5))
    answer('GET', f'{_ROOT}/issues/5/comments', (200, _THREE))
    argv = ['view', '5', '--comments', '--last', '2']
    assert main(argv, cwd=repo, env=credential_env(tmp_path), transport=Loopback(server)) == 0
    out = capsys.readouterr().out
    assert 'first' not in out
    assert out.index('#32 bot 2026-10-01T11:00:00Z') < out.index('second') < out.index('#33 bot') < out.index('third')


def test_a_missing_issue_is_refused_by_name(server, tmp_path: Path, capsys) -> None:
    """PLANTED CONTROL: the fake answers 404 for issue 404, and the verb names the issue, not a stack."""
    repo = make_repo(tmp_path, 'https://forge.example.org/o/r.git')
    argv = ['view', '404', '--comments']
    assert main(argv, cwd=repo, env=credential_env(tmp_path), transport=Loopback(server)) == 2
    assert 'issue #404 does not exist on forge.example.org/o/r' in capsys.readouterr().err


def test_comment_view_reads_one_comment_by_id_and_refuses_a_missing_one(server, tmp_path: Path, capsys) -> None:
    repo = make_repo(tmp_path, 'https://forge.example.org/o/r.git')
    answer('GET', f'{_ROOT}/issues/comments/32', (200, _THREE[1]))
    argv = ['comment-view', '32', '--json']
    assert main(argv, cwd=repo, env=credential_env(tmp_path), transport=Loopback(server)) == 0
    assert json.loads(capsys.readouterr().out) == {
        'issue': 5,
        'id': 32,
        'author': 'bot',
        'body': 'second',
        'created': '2026-10-01T11:00:00Z',
    }
    assert main(['comment-view', '99'], cwd=repo, env=credential_env(tmp_path), transport=Loopback(server)) == 2
    assert 'comment 99 does not exist on forge.example.org/o/r' in capsys.readouterr().err
