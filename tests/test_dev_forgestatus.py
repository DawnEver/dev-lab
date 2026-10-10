"""VERDICT-AS-STATUS: ``lab_commons.dev.forgestatus`` against a REAL loopback server and REAL git repos.

The evidence is what the server RECORDED. Both forges are one table of cases, because the claim is
one normalized ``Status`` whichever forge answered; only the request shape differs.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from _forge_fake import Loopback, Recorder, answer, client, credential_env, make_repo, run_git, serve

from lab_commons.dev.forge import Forge
from lab_commons.dev.forgestatus import (
    DESCRIPTION_LIMIT,
    Status,
    head_sha,
    main,
    state_for,
    status_history,
    status_list,
    status_post,
    verdict_commit,
)
from lab_commons.dev.logref import LogRef
from lab_commons.dev.treedirt import status_paths
from lab_commons.dev.verdict import Outcome, Proof, Result, Selector, Verdict


@pytest.fixture
def server() -> Iterator[ThreadingHTTPServer]:
    yield from serve()


CASES = (
    pytest.param(Forge('forge.example.org', 'o', 'r'), '/api/v1/repos/o/r', id='gitea'),
    pytest.param(Forge('github.com', 'o', 'r'), '/repos/o/r', id='github'),
)

_SHA = 'a' * 40


def _verdict(tmp_path: Path, outcome: Outcome) -> Verdict:
    log = tmp_path / 'v.log'
    log.write_text('ran\n', encoding='utf-8')
    selector = Selector(spec='verify', node_ids=('x',))
    if outcome is Outcome.INCONCLUSIVE:
        result = Result.inconclusive('x went silent', proof=Proof.of(selector, []))
    else:
        result = Result.settled(proof=Proof.of(selector, ['x']), failures=['x'] if outcome is Outcome.FAIL else [])
    return Verdict(tree='sha256:' + 'b' * 64, env='env:1', selector=selector, result=result, log=LogRef.of(log))


def test_pass_is_success_fail_is_failure_and_inconclusive_is_error() -> None:
    # User ruling 2026-10-04: a lane may push an INCONCLUSIVE tree, so every pushed tree carries its
    # verdict -- a non-success state the trunk's protection still refuses.
    assert state_for(Outcome.PASS) == 'success'
    assert state_for(Outcome.FAIL) == 'failure'
    assert state_for(Outcome.INCONCLUSIVE) == 'error'


@pytest.mark.parametrize(('forge', 'root'), CASES)
def test_status_post_sends_state_context_and_a_truncated_description(server, forge, root) -> None:
    answer('POST', f'{root}/statuses/{_SHA}', (201, {'context': 'lab/gate', 'state': 'success', 'description': 'd'}))
    posted = status_post(
        client(forge, Loopback(server)), _SHA, context='lab/gate', state='success', description='x' * 500
    )
    sent = Recorder.received[-1]
    assert (sent['method'], sent['path']) == ('POST', f'{root}/statuses/{_SHA}')
    assert sent['body'] == {'state': 'success', 'context': 'lab/gate', 'description': 'x' * DESCRIPTION_LIMIT}
    assert posted == Status('lab/gate', 'success', 'd', '')


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
                {'id': 3, 'context': 'lab/gate', 'status': 'success', 'description': 'new'},
                {'id': 1, 'context': 'lab/gate', 'status': 'failure', 'description': 'old'},
                {'id': 2, 'context': 'lab/heavy', 'status': 'pending', 'description': 'h'},
            ],
        ),
    )
    listed = status_list(client(Forge('forge.example.org', 'o', 'r'), Loopback(server)), _SHA)
    assert listed == (Status('lab/gate', 'success', 'new', ''), Status('lab/heavy', 'pending', 'h', ''))


def test_github_list_reads_the_combined_status(server) -> None:
    combined = {'state': 'success', 'statuses': [{'context': 'lab/gate', 'state': 'success', 'description': 'd'}]}
    answer('GET', f'/repos/o/r/commits/{_SHA}/status', (200, combined))
    listed = status_list(client(Forge('github.com', 'o', 'r'), Loopback(server)), _SHA)
    assert listed == (Status('lab/gate', 'success', 'd', ''),)


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
    verdict = _verdict(tmp_path, Outcome.INCONCLUSIVE)
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


# --------------------------------------------------------------------------------------------
# the CLI


def test_the_cli_posts_and_lists_with_json(server, tmp_path: Path, capsys) -> None:
    repo = make_repo(tmp_path, 'https://f.example/o/r.git')
    answer('POST', f'/api/v1/repos/o/r/statuses/{_SHA}', (201, {'context': 'lab/test', 'state': 'pending'}))
    argv = ['post', _SHA, '--context', 'lab/test', '--state', 'pending', '--description', 'probe', '--json']
    assert main(argv, cwd=repo, env=credential_env(tmp_path), transport=Loopback(server)) == 0
    assert json.loads(capsys.readouterr().out)['context'] == 'lab/test'
    assert Recorder.received[-1]['headers']['Authorization'] == 'token T'
    assert not Recorder.received[-1]['body']['description'].startswith('['), 'status writes carry no provenance'
    answer('GET', f'/api/v1/repos/o/r/statuses/{_SHA}', (200, [{'id': 1, 'context': 'lab/test', 'status': 'pending'}]))
    assert main(['list', _SHA], cwd=repo, env=credential_env(tmp_path), transport=Loopback(server)) == 0
    assert 'lab/test  pending' in capsys.readouterr().out


def test_the_cli_reports_a_refusal_and_exits_nonzero(server, tmp_path: Path, capsys) -> None:
    repo = make_repo(tmp_path, 'https://f.example/o/r.git')
    answer('GET', f'/api/v1/repos/o/r/statuses/{_SHA}', (404, {'message': 'nope'}))
    assert main(['list', _SHA], cwd=repo, env=credential_env(tmp_path), transport=Loopback(server)) == 1
    assert 'REFUSED' in capsys.readouterr().err
