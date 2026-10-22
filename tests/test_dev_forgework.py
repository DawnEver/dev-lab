"""``dev_lab.dev.forgework`` -- issue/PR verbs against a REAL loopback server and REAL git repos.

THE SAME DISCIPLINE AS ``test_dev_forge.py``: the evidence is what the SERVER recorded (method, path,
headers, decoded body), never the arguments the test passed. The one substitution is the transport,
which ignores the host it is asked for and connects to loopback -- and RECORDS that host, so the
backend's choice of API host is itself asserted rather than assumed.

Both forges are driven through ONE table of cases, because the claim under test is that the verbs
and the normalized results are identical across backends; only the request shape differs.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from _forge_fake import Loopback as _Loopback
from _forge_fake import Recorder as _Recorder
from _forge_fake import answer as _answer
from _forge_fake import client as _client
from _forge_fake import credential_env, serve
from _forge_fake import make_repo as _repo
from _forge_fake import run_git as _run

from dev_lab.dev import branchnotices, pradmit
from dev_lab.dev.forge import Forge, NoCredential
from dev_lab.dev.forgeclaim import forge_now
from dev_lab.dev.forgecli import issue_and_pr
from dev_lab.dev.forgework import (
    GITEA,
    GITHUB,
    Comment,
    ForgeCallFailed,
    Issue,
    PullRequest,
    backend_for,
    client_for,
    provenance,
)
from dev_lab.dev.netverb import Diagnosis, Disposition


@pytest.fixture
def server() -> Iterator[ThreadingHTTPServer]:
    yield from serve()


#: (forge, API host, path prefix, Authorization header) -- the only things that differ per backend.
CASES = (
    pytest.param(Forge('forge.example.org', 'o', 'r'), 'forge.example.org', '/api/v1/repos/o/r', 'token T', id='gitea'),
    pytest.param(Forge('github.com', 'o', 'r'), 'api.github.com', '/repos/o/r', 'Bearer T', id='github'),
)

_ISSUE = {
    'number': 7,
    'title': 'a bug',
    'state': 'open',
    'body': 'it broke',
    'html_url': 'https://x/o/r/issues/7',
    'user': {'login': 'alice'},
}
_PR = {
    'number': 9,
    'title': 'a fix',
    'state': 'open',
    'body': 'fixes it',
    'html_url': 'https://x/o/r/pulls/9',
    'user': {'login': 'alice'},
    'head': {'ref': 'feature'},
    'base': {'ref': 'main'},
}
_NORMAL_ISSUE = Issue(7, 'a bug', 'open', 'it broke', 'https://x/o/r/issues/7', 'alice')


# --------------------------------------------------------------------------------------------
# backend selection


def test_github_com_selects_the_github_backend_and_any_other_host_the_gitea_one() -> None:
    assert backend_for(Forge('github.com', 'o', 'r')) is GITHUB
    assert backend_for(Forge('gitea.example.org', 'o', 'r')) is GITEA
    assert backend_for(Forge('GitHub.com', 'o', 'r')) is GITHUB


@pytest.mark.parametrize('remote', ['https://forge.example.org/o/r.git', 'https://github.com/o/r.git'])
def test_the_token_is_the_git_credential_and_a_token_variable_is_never_read(tmp_path: Path, remote: str) -> None:
    """PLANTED CONTROL: the conventional token variables are set, the credential store is empty -- refused."""
    repo = _repo(tmp_path, remote)
    stored = 'from-git'
    assert client_for(repo, env=credential_env(tmp_path, stored)).token == stored
    empty = tmp_path / 'empty-gitconfig'
    empty.write_text('[credential]\n\thelper = "!f() { :; }; f"\n', encoding='utf-8')
    planted = {'GIT_CONFIG_GLOBAL': str(empty), 'GIT_CONFIG_SYSTEM': str(tmp_path / 'absent')}
    planted |= {'GITEA_TOKEN': 'from-env', 'GH_TOKEN': 'from-env', 'GITHUB_TOKEN': 'from-env'}
    with pytest.raises(NoCredential):
        client_for(repo, env=planted)


# --------------------------------------------------------------------------------------------
# each verb's request shape and normalized result, on both forges


@pytest.mark.parametrize(('forge', 'host', 'root', 'auth'), CASES)
def test_issue_list_reads_open_issues_and_drops_pull_requests(server, forge, host, root, auth) -> None:
    query = '?state=open&type=issues&limit=30' if forge.host != 'github.com' else '?state=open&per_page=30'
    _answer('GET', f'{root}/issues{query}', (200, [_ISSUE, {**_PR, 'pull_request': {}}]))
    transport = _Loopback(server)
    assert _client(forge, transport).issue_list() == (_NORMAL_ISSUE,)
    assert transport.asked == [host]
    assert _Recorder.received[0]['headers']['Authorization'] == auth


@pytest.mark.parametrize(('forge', 'host', 'root', 'auth'), CASES)
def test_issue_view_create_comment_close_send_one_shape_and_answer_one_shape(server, forge, host, root, auth) -> None:
    _answer('GET', f'{root}/issues/7', (200, _ISSUE))
    _answer('POST', f'{root}/issues', (201, _ISSUE))
    _answer('POST', f'{root}/issues/7/comments', (201, {'id': 3, 'body': 'hi', 'html_url': 'https://x/c/3'}))
    _answer('PATCH', f'{root}/issues/7', (200, {**_ISSUE, 'state': 'closed'}))
    transport = _Loopback(server)
    client = _client(forge, transport)
    assert client.issue_view(7) == _NORMAL_ISSUE
    assert client.issue_create('a bug', 'it broke') == _NORMAL_ISSUE
    assert client.issue_comment(7, 'hi') == Comment(3, 'hi', 'https://x/c/3')
    assert client.issue_close(7).state == 'closed'
    sent = [(r['method'], r['path'], r['body']) for r in _Recorder.received]
    assert sent == [
        ('GET', f'{root}/issues/7', None),
        ('POST', f'{root}/issues', {'title': 'a bug', 'body': 'it broke'}),
        ('POST', f'{root}/issues/7/comments', {'body': 'hi'}),
        ('PATCH', f'{root}/issues/7', {'state': 'closed'}),
    ]
    assert set(transport.asked) == {host}
    assert {r['headers']['Authorization'] for r in _Recorder.received} == {auth}


@pytest.mark.parametrize(('forge', 'host', 'root', 'auth'), CASES)
def test_pr_create_and_view(server, forge, host, root, auth) -> None:
    _answer('POST', f'{root}/pulls', (201, _PR))
    _answer('GET', f'{root}/pulls/9', (200, _PR))
    transport = _Loopback(server)
    client = _client(forge, transport)
    expected = PullRequest(9, 'a fix', 'open', 'fixes it', 'https://x/o/r/pulls/9', 'alice', 'feature', 'main')
    assert client.pr_create('a fix', 'fixes it', head='feature', base='main') == expected
    assert client.pr_view(9) == expected
    assert _Recorder.received[0]['body'] == {'title': 'a fix', 'body': 'fixes it', 'head': 'feature', 'base': 'main'}
    assert set(transport.asked) == {host}
    assert _Recorder.received[1]['headers']['Authorization'] == auth


def test_github_requests_carry_the_headers_its_api_demands(server) -> None:
    _answer('GET', '/repos/o/r/issues/7', (200, _ISSUE))
    _client(Forge('github.com', 'o', 'r'), _Loopback(server)).issue_view(7)
    headers = _Recorder.received[0]['headers']
    assert headers['Accept'] == 'application/vnd.github+json'
    assert headers['User-Agent']


# --------------------------------------------------------------------------------------------
# retry, then report -- netverb's diagnosis vocabulary, over HTTP


def test_a_transient_5xx_is_retried_and_recovers(server) -> None:
    _answer('GET', '/api/v1/repos/o/r/issues/7', (502, {'message': 'bad gateway'}), (200, _ISSUE))
    assert _client(Forge('f.example', 'o', 'r'), _Loopback(server)).issue_view(7) == _NORMAL_ISSUE
    assert len(_Recorder.received) == 2


def test_an_answered_refusal_is_not_retried_and_is_reported_with_its_diagnosis(server) -> None:
    _answer('POST', '/api/v1/repos/o/r/issues', (422, {'message': 'title is required'}))
    with pytest.raises(ForgeCallFailed, match='REFUSED') as caught:
        _client(Forge('f.example', 'o', 'r'), _Loopback(server)).issue_create('', '')
    assert len(_Recorder.received) == 1
    assert caught.value.report.disposition is Disposition.REFUSED
    assert caught.value.report.diagnosis is Diagnosis.FORGE_REFUSED
    assert 'title is required' in caught.value.report.attempts[-1].output


def test_a_failure_that_never_clears_stops_at_the_bound(server) -> None:
    _answer('GET', '/api/v1/repos/o/r/issues/7', (503, {'message': 'down'}))
    with pytest.raises(ForgeCallFailed) as caught:
        _client(Forge('f.example', 'o', 'r'), _Loopback(server)).issue_view(7)
    assert caught.value.report.disposition is Disposition.EXHAUSTED
    assert len(_Recorder.received) == 3


_STATUSES = '/api/v1/repos/o/r/statuses/abc'
_INVALID = {'message': 'invalid username, password or token'}


@pytest.mark.parametrize('code', [401, 403])
def test_a_refusal_whose_credential_still_authenticates_is_retried_and_names_no_re_store(server, code) -> None:
    """PLANTED CONTROL, the 2026-10-18 incident: one 401 while GET /user authenticates is not a bad credential."""
    _answer('GET', _STATUSES, (code, _INVALID), (200, []))
    _answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    assert _client(Forge('f.example', 'o', 'r'), _Loopback(server)).call('GET', _STATUSES) == []
    _answer('GET', _STATUSES, (code, _INVALID))
    with pytest.raises(ForgeCallFailed) as caught:
        _client(Forge('f.example', 'o', 'r'), _Loopback(server)).call('GET', _STATUSES)
    assert not caught.value.credential_refused
    assert caught.value.report.disposition is Disposition.EXHAUSTED
    assert 'auth login' not in str(caught.value)
    assert 'credential authenticates' in str(caught.value)
    assert 'retrying cannot change' not in str(caught.value)


@pytest.mark.parametrize('code', [401, 403])
def test_a_refusal_whose_credential_check_also_refuses_names_the_re_store_remedy(server, code) -> None:
    _answer('GET', _STATUSES, (code, _INVALID))
    _answer('GET', '/api/v1/user', (401, _INVALID))
    with pytest.raises(ForgeCallFailed) as caught:
        _client(Forge('f.example', 'o', 'r'), _Loopback(server)).call('GET', _STATUSES)
    assert caught.value.credential_refused
    assert caught.value.report.disposition is Disposition.REFUSED
    assert 'auth login' in str(caught.value)
    assert [r['path'] for r in _Recorder.received] == [_STATUSES, '/api/v1/user']


# --------------------------------------------------------------------------------------------
# a create whose response was LOST is not created twice


_DROPPED = (None, None)
_ME = (200, {'login': 'alice'})


def _ago(seconds: float) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat()


def _posts(path: str) -> int:
    return sum(1 for r in _Recorder.received if r['method'] == 'POST' and r['path'] == path)


@pytest.mark.parametrize(('forge', 'host', 'root', 'auth'), CASES)
def test_an_issue_that_landed_before_its_response_was_lost_is_returned_not_recreated(
    server, forge, host, root, auth
) -> None:
    del host, auth  # the shared case table; only the API root differs for this claim
    landed = {**_ISSUE, 'created_at': _ago(20)}
    _answer('POST', f'{root}/issues', _DROPPED, (201, {**_ISSUE, 'number': 8}))
    _answer('GET', f'{root.split("/repos/")[0]}/user', _ME)
    _answer('GET', f'{root}/issues', (200, [{**landed, 'number': 6, 'title': 'other'}, landed]))
    assert _client(forge, _Loopback(server)).issue_create('a bug', 'it broke') == _NORMAL_ISSUE
    assert _posts(f'{root}/issues') == 1, 'the retry re-created an issue the server had already applied'


def test_a_comment_and_a_pr_that_landed_are_returned_not_recreated(server) -> None:
    root = '/api/v1/repos/o/r'
    comment = {'id': 3, 'body': '[m · a]\n\nhi', 'html_url': 'u', 'user': {'login': 'alice'}, 'created_at': _ago(5)}
    _answer('POST', f'{root}/issues/7/comments', _DROPPED, (201, {**comment, 'id': 4}))
    _answer('POST', f'{root}/pulls', _DROPPED, (201, {**_PR, 'number': 10}))
    _answer('GET', '/api/v1/user', _ME)
    _answer('GET', f'{root}/issues/7/comments', (200, [comment]))
    _answer('GET', f'{root}/pulls', (200, [{**_PR, 'body': '[m · a]\n\nfixes it', 'created_at': _ago(5)}]))
    client = _client(Forge('f.example', 'o', 'r'), _Loopback(server), stamp='[m · a]')
    assert client.issue_comment(7, 'hi').id == 3
    assert client.pr_create('a fix', 'fixes it', head='feature', base='main').number == 9
    assert _posts(f'{root}/issues/7/comments') == 1
    assert _posts(f'{root}/pulls') == 1


def test_a_lost_create_with_no_matching_object_is_retried(server) -> None:
    """THE CONTROL: an old twin, another author's twin, or a different body is NOT the lost create."""
    root = '/api/v1/repos/o/r'
    stale = {**_ISSUE, 'created_at': _ago(3600)}
    theirs = {**_ISSUE, 'user': {'login': 'bob'}, 'created_at': _ago(5)}
    edited = {**_ISSUE, 'body': 'it broke badly', 'created_at': _ago(5)}
    _answer('POST', f'{root}/issues', _DROPPED, (201, _ISSUE))
    _answer('GET', '/api/v1/user', _ME)
    _answer('GET', f'{root}/issues', (200, [stale, theirs, edited]))
    assert _client(Forge('f.example', 'o', 'r'), _Loopback(server)).issue_create('a bug', 'it broke') == _NORMAL_ISSUE
    assert _posts(f'{root}/issues') == 2


def test_a_lost_create_that_cannot_be_checked_is_reported_not_blindly_retried(server) -> None:
    root = '/api/v1/repos/o/r'
    _answer('POST', f'{root}/issues', _DROPPED, (201, _ISSUE))
    _answer('GET', '/api/v1/user', (403, {'message': 'token lacks read:user'}))
    with pytest.raises(ForgeCallFailed):
        _client(Forge('f.example', 'o', 'r'), _Loopback(server)).issue_create('a bug', 'it broke')
    assert _posts(f'{root}/issues') == 1, 'a create nobody could check for was sent again'


# --------------------------------------------------------------------------------------------
# provenance


def test_provenance_names_machine_agent_and_branch_when_both_vars_are_set(tmp_path: Path) -> None:
    repo = _repo(tmp_path, 'https://f.example/o/r.git', branch='lane-x')
    env = {'HARNESS_MACHINE': 'host-a', 'HARNESS_AGENT': 'claude'}
    assert provenance(repo, env) == '[host-a · claude · lane-x]'


def test_no_provenance_without_both_vars(tmp_path: Path) -> None:
    repo = _repo(tmp_path, 'https://f.example/o/r.git')
    assert provenance(repo, {}) is None
    assert provenance(repo, {'HARNESS_MACHINE': 'host-a'}) is None
    assert provenance(repo, {'HARNESS_MACHINE': 'host-a', 'HARNESS_AGENT': ''}) is None


def test_a_detached_head_omits_the_branch(tmp_path: Path) -> None:
    repo = _repo(tmp_path, 'https://f.example/o/r.git')
    _run(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'x')
    _run(repo, 'checkout', '-q', '--detach')
    assert provenance(repo, {'HARNESS_MACHINE': 'host-a', 'HARNESS_AGENT': 'codex'}) == '[host-a · codex]'


def test_the_stamp_prefixes_every_created_body_and_comment_and_nothing_else(server) -> None:
    root = '/api/v1/repos/o/r'
    _answer('POST', f'{root}/issues', (201, _ISSUE))
    _answer('POST', f'{root}/issues/7/comments', (201, {'id': 3, 'body': 'x', 'html_url': 'u'}))
    _answer('POST', f'{root}/pulls', (201, _PR))
    _answer('PATCH', f'{root}/issues/7', (200, _ISSUE))
    client = _client(Forge('f.example', 'o', 'r'), _Loopback(server), stamp='[m · a · b]')
    client.issue_create('t', 'body')
    client.issue_comment(7, 'note')
    client.pr_create('t', 'desc', head='b', base='main')
    client.issue_close(7)
    bodies = [r['body'] for r in _Recorder.received]
    assert bodies[0]['body'] == '[m · a · b]\n\nbody'
    assert bodies[1]['body'] == '[m · a · b]\n\nnote'
    assert bodies[2]['body'] == '[m · a · b]\n\ndesc'
    assert bodies[3] == {'state': 'closed'}


# --------------------------------------------------------------------------------------------
# the CLI door


def test_the_cli_prints_the_normalized_result_as_json(server, tmp_path: Path, capsys) -> None:
    repo = _repo(tmp_path, 'https://f.example/o/r.git')
    _answer('GET', '/api/v1/repos/o/r/issues/7', (200, _ISSUE))
    env = credential_env(tmp_path)
    code = issue_and_pr(['issue', 'view', '7', '--json'], cwd=repo, env=env, transport=_Loopback(server))
    assert code == 0
    assert json.loads(capsys.readouterr().out)['number'] == 7


def test_the_cli_stamps_from_the_environment(server, tmp_path: Path, capsys) -> None:
    repo = _repo(tmp_path, 'https://f.example/o/r.git', branch='lane')
    _answer('POST', '/api/v1/repos/o/r/issues/7/comments', (201, {'id': 1, 'body': 'b', 'html_url': 'u'}))
    env = credential_env(tmp_path) | {'HARNESS_MACHINE': 'g', 'HARNESS_AGENT': 'claude'}
    assert (
        issue_and_pr(['issue', 'comment', '7', '--body', 'hello'], cwd=repo, env=env, transport=_Loopback(server)) == 0
    )
    assert _Recorder.received[0]['body'] == {'body': '[g · claude · lane]\n\nhello'}
    assert 'u' in capsys.readouterr().out


def test_the_cli_reports_a_refusal_and_exits_nonzero(server, tmp_path: Path, capsys) -> None:
    repo = _repo(tmp_path, 'https://f.example/o/r.git')
    _answer('GET', '/api/v1/repos/o/r/pulls/9', (404, {'message': 'nope'}))
    assert issue_and_pr(['pr', 'view', '9'], cwd=repo, env=credential_env(tmp_path), transport=_Loopback(server)) == 1
    assert 'REFUSED' in capsys.readouterr().err


def test_the_forge_module_is_the_cli_door() -> None:
    """``python -m dev_lab.dev.forge`` reaches these verbs, in a fresh interpreter."""
    done = subprocess.run(
        [sys.executable, '-m', 'dev_lab.dev.forge', 'issue', '--help'],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert all(verb in done.stdout for verb in ('list', 'view', 'create', 'comment', 'close'))


def test_the_forge_clock_is_the_date_the_forge_answered_with_not_the_hosts(server) -> None:
    """PLANTED CONTROL: the forge's Date is a year from this host's clock; a lease is judged on the forge's."""
    _Recorder.date = 'Sat, 10 Oct 2026 12:00:00 GMT'
    _answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    built = _client(Forge('forge.example.org', 'o', 'r'), _Loopback(server))
    built.clock = lambda: datetime(2027, 10, 10, tzinfo=UTC)
    assert forge_now(built) == datetime(2026, 10, 10, 12, tzinfo=UTC), 'read from an answer, never the host'
    _Recorder.date = 'Sat, 10 Oct 2026 12:05:00 GMT'
    built.whoami()
    assert forge_now(built) == datetime(2026, 10, 10, 12, 5, tzinfo=UTC), 'the latest answer is the clock'


def test_download_returns_the_raw_bytes_with_the_credential_and_a_refusal_raises(server) -> None:
    """PLANTED CONTROL: the same call on a path the server does not hold raises instead of returning a body."""
    forge = Forge('forge.example.org', 'o', 'r')
    transport = _Loopback(server)
    _answer('GET', '/attachments/u1', (200, {'k': 1}))
    got = _client(forge, transport).download('https://forge.example.org/attachments/u1')
    assert got == json.dumps({'k': 1}).encode()
    assert _Recorder.received[-1]['headers']['Authorization'] == 'token T'
    assert transport.asked[-1] == 'forge.example.org'
    with pytest.raises(ForgeCallFailed):
        _client(forge, transport).download('https://forge.example.org/attachments/absent')


def test_pr_create_asks_the_admission_first_and_a_refusal_writes_nothing(
    server, tmp_path: Path, capsys, monkeypatch
) -> None:
    """ONE-SESSION-ONE-PR / NO-STACKED-PRS: a refused head never reaches the forge. PLANTED CONTROL: admitted."""
    repo = _repo(tmp_path, 'https://f.example/o/r.git')
    argv = ['pr', 'create', '--title', 't', '--head', 'pr/b', '--base', 'integrate/main']
    monkeypatch.setattr(pradmit, 'create_refusal', lambda *_a, **_k: 'session s already has open PR #7 (pr/a)')
    assert issue_and_pr(argv, cwd=repo, env=credential_env(tmp_path), transport=_Loopback(server)) == 1
    assert 'REFUSED' in capsys.readouterr().err
    assert _Recorder.received == []
    monkeypatch.setattr(pradmit, 'create_refusal', lambda *_a, **_k: None)
    _answer('POST', '/api/v1/repos/o/r/pulls', (201, _PR))
    assert issue_and_pr(argv, cwd=repo, env=credential_env(tmp_path), transport=_Loopback(server)) == 0
    assert _Recorder.received


def test_pr_create_prints_the_heads_open_notices_for_this_session(server, tmp_path: Path, capsys, monkeypatch) -> None:
    """FORGE NOTICES at ``pr create`` (branchnotices). PLANTED CONTROL: no notice, nothing printed; exit 0 both."""
    repo = _repo(tmp_path, 'https://f.example/o/r.git')
    argv = ['pr', 'create', '--title', 't', '--head', 'pr/b', '--base', 'integrate/main']
    env = credential_env(tmp_path) | {'LAB_SESSION': 's1'}
    asked: list[tuple[list[str], str]] = []
    monkeypatch.setattr(pradmit, 'create_refusal', lambda *_a, **_k: None)
    monkeypatch.setattr(
        branchnotices, 'report', lambda _r, heads, session, **_k: asked.append((heads, session)) or 'NOTICE-LINE'
    )
    _answer('POST', '/api/v1/repos/o/r/pulls', (201, _PR))
    assert issue_and_pr(argv, cwd=repo, env=env, transport=_Loopback(server)) == 0
    assert asked == [(['pr/b'], 's1')]
    assert 'NOTICE-LINE' in capsys.readouterr().err
    monkeypatch.setattr(branchnotices, 'report', lambda *_a, **_k: '')
    assert issue_and_pr(argv, cwd=repo, env=env, transport=_Loopback(server)) == 0
    assert 'NOTICE-LINE' not in capsys.readouterr().err
