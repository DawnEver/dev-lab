"""A REQUEST IS A JOB ON THE PART PATH: admitted by its need-set, run through its DECLARED producer only.

End to end against a REAL loopback forge and a REAL git repository (the declaration is read AT the
request's sha), and through :func:`forgeproduce.produce` for the result a request posts.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import test_dev_forgetick
from _forge_fake import Recorder, answer, git_out, run_git
from test_dev_forgetick import API, LATER, PRODUCE, _declare, _origin, _tick

from lab_commons.compute.model import REQUEST, Resources, Supply
from lab_commons.dev import forgeproduce
from lab_commons.dev.forgeclaim import MINE, Claim, Work
from lab_commons.dev.forgerequest import (
    UndeclaredRequest,
    declared_request,
    parse_body,
    request_body,
    request_context,
)
from lab_commons.dev.forgeschedule import NOT_ADMITTED

server = test_dev_forgetick.server  # the loopback forge fixture, shared

ME = Claim('G', 'alice', LATER)
ARGV = ('-m', 'motronics', 'golden', 'regenerate', '--reference', 'femm')
GOLDENS = (
    PRODUCE
    + '[tool.lab_commons.requests.femm_goldens]\n'
    + 'argv = ["-m", "motronics", "golden", "regenerate", "--reference", "femm"]\n'
    + 'needs = ["femm", "windows"]\n'
)
FEMM_HOST = Supply('G', Resources(cpu=4.0, femm=1.0, windows=1.0), frozenset({'cpu', 'femm', 'windows'}))
PLAIN_HOST = Supply('G', Resources(cpu=4.0), frozenset({'cpu', 'windows'}))


def _request(repo: Path, tips: dict[str, str], producer: str) -> str:
    """Pin a request (issue 9) to the commit declaring GOLDENS; the integration head moves past it, DONE."""
    pinned = _declare(repo, tips, GOLDENS)
    run_git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'after')
    head = git_out(repo, 'rev-parse', 'HEAD')
    run_git(repo, 'update-ref', 'refs/remotes/origin/integrate/main', head)
    done = {'id': 1, 'context': 'tests/base', 'status': 'success', 'description': 'scope=full ran=1'}
    answer('GET', f'{API}/statuses/{head}', (200, [done]))
    issue = {
        'number': 9,
        'body': request_body(producer, pinned),
        'created_at': '2026-10-10T00:00:00Z',
        'labels': [{'name': 'forge:request'}],
        'user': {'login': 'bob'},
    }
    answer('GET', f'{API}/issues', (200, [issue]))
    answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    return pinned


def test_a_declared_request_is_admitted_and_claimed_where_its_needs_are_present(server, tmp_path: Path) -> None:
    repo, tips = _origin(tmp_path)
    sha = _request(repo, tips, 'femm_goldens')
    mine = {'id': 2, 'context': 'request/9', 'status': 'pending', 'description': ME.description()}
    answer('GET', f'{API}/statuses/{sha}', (200, []), (200, [mine]))
    answer('POST', f'{API}/statuses/{sha}', (201, {}))
    report = _tick(repo, server, supply=FEMM_HOST)
    (claimed,) = report.claimed
    assert (claimed.ref, claimed.sha, claimed.state, claimed.context) == ('issue/9', sha, MINE, 'request/9')
    assert claimed.platform == 'femm+windows', 'its need-set, spelled as a part is'
    assert claimed.argv == ARGV
    posted = next(r for r in Recorder.received if r['method'] == 'POST')
    assert posted['body'] == {'state': 'pending', 'context': 'request/9', 'description': ME.description()}
    assert any(line.startswith('produce request/9:') for line in report.lines)


def test_a_host_lacking_a_needed_resource_does_not_admit_it(server, tmp_path: Path) -> None:
    """PLANTED CONTROL: the request above, on a host where femm is not present."""
    repo, tips = _origin(tmp_path)
    sha = _request(repo, tips, 'femm_goldens')
    answer('GET', f'{API}/statuses/{sha}', (200, []))
    report = _tick(repo, server, supply=PLAIN_HOST)
    assert report.claimed == ()
    assert not [r for r in Recorder.received if r['method'] == 'POST']
    (waiting,) = [item for item in report.queue if item.candidate.kind == REQUEST]
    assert waiting.blocked == f'{NOT_ADMITTED}: lacking femm'


def test_an_undeclared_producer_name_is_refused_not_run(server, tmp_path: Path) -> None:
    """A request names a producer; it never carries a command. A name the sha does not declare is refused."""
    repo, tips = _origin(tmp_path)
    sha = _request(repo, tips, 'rm_rf')
    answer('GET', f'{API}/statuses/{sha}', (200, []))
    report = _tick(repo, server, supply=FEMM_HOST)
    assert report.claimed == ()
    assert not [r for r in Recorder.received if r['method'] == 'POST']
    assert any('[tool.lab_commons.requests.rm_rf]' in why for why in report.refused)


def test_a_declaration_is_read_at_the_sha_and_refuses_a_malformed_row(tmp_path: Path) -> None:
    repo, tips = _origin(tmp_path)
    sha = _declare(repo, tips, GOLDENS)
    found = declared_request(repo, sha, 'femm_goldens')
    assert (found.argv, found.needs, found.part) == (ARGV, frozenset({'femm', 'windows'}), 'femm+windows')
    bad = _declare(repo, tips, '[tool.lab_commons.requests.x]\nargv = "rm -rf /"\n')
    with pytest.raises(UndeclaredRequest, match=r'argv'):
        declared_request(repo, bad, 'x')
    with pytest.raises(UndeclaredRequest, match=r'declares no'):
        declared_request(repo, sha, 'x')


class _Forge:
    def __init__(self) -> None:
        self.posts: list[tuple[str, str, str]] = []

    def post(self, _client, _sha, *, context, state, description, target_url='') -> None:
        self.posts.append((context, state, description))

    def history(self, _client, _sha) -> tuple[SimpleNamespace, ...]:
        return tuple(SimpleNamespace(context=c, state=s, description=d) for c, s, d in self.posts)


class _Proc:
    def __init__(self, code: int) -> None:
        self.code, self.pid = code, None
        self.stdout = iter(['regenerated 45 goldens\n'])

    def wait(self, timeout: float | None = None) -> int:
        return self.code


def _produce(monkeypatch, tmp_path: Path, code: int) -> tuple[_Forge, list]:
    forge, said, comments = _Forge(), [], []
    client = SimpleNamespace(
        answered='Sat, 10 Oct 2026 12:00:00 GMT', whoami=lambda: 'alice',
        issue_comment=lambda n, body: comments.append(('comment', n, body)),
        issue_close=lambda n: comments.append(('close', n)),
    )  # fmt: skip
    sha = 'a' * 40
    forge.post(None, sha, context='request/9', state='pending', description=ME.description())
    monkeypatch.setattr(forgeproduce, 'status_post', forge.post)
    monkeypatch.setattr(forgeproduce, 'status_history', forge.history)
    monkeypatch.setattr(forgeproduce, 'open_tree', lambda _r, _s: SimpleNamespace(path=tmp_path, python='py'))
    monkeypatch.setattr(forgeproduce, 'close_tree', lambda _r, _s, **_kw: 'removed')
    item = Work('issue/9', sha, 'femm+windows', MINE, ME, argv=ARGV, context='request/9')
    forgeproduce.produce(
        tmp_path, item, client=lambda _r: client, spawn=lambda *_a, **_k: _Proc(code), clock=lambda: LATER,
        say=said.append, lease=LATER - LATER, renew_s=1.0, fetch=lambda _r: None,
    )  # fmt: skip
    return forge, comments


def test_a_finished_request_posts_its_result_and_closes(monkeypatch, tmp_path: Path) -> None:
    forge, comments = _produce(monkeypatch, tmp_path, 0)
    assert forge.posts[-1][:2] == ('request/9', 'success')
    (kind, number, body), closed = comments
    assert (kind, number, closed) == ('comment', 9, ('close', 9))
    assert 'regenerated 45 goldens' in body, 'the log travels with the result'


def test_a_failed_request_is_a_failure_on_record_never_silent(monkeypatch, tmp_path: Path) -> None:
    forge, comments = _produce(monkeypatch, tmp_path, 1)
    assert forge.posts[-1][:2] == ('request/9', 'failure')
    assert [c[0] for c in comments] == ['comment'], 'a failed request stays open, its failure stated'
    crashed, _ = _produce(monkeypatch, tmp_path, -9)
    assert crashed.posts[-1] == ('request/9', 'error', 'released: producer crashed (exit -9)')


def test_a_request_is_named_by_its_issue_and_its_body_names_no_command() -> None:
    assert request_context(9) == 'request/9'
    body = 'producer = "x; rm -rf /"\nsha = "HEAD"\n'
    assert parse_body(body) == ('', ''), 'a name or a sha, nothing else'
