"""A REQUEST IS A JOB ON THE PART PATH: admitted by its need-set, run through its DECLARED producer only.

End to end against a REAL loopback forge and a REAL git repository (the declaration is read AT the
request's sha), and through :func:`forgeproduce.produce` for the result a request posts.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import test_dev_forgetick
from _box_fake import ended, record
from _forge_fake import Recorder, answer, git_out, run_git
from test_dev_forgetick import API, LATER, PRODUCE, RETIRED_TABLE, _declare, _origin, _tick

from lab_commons.box import Capacity
from lab_commons.compute.learned import LOCAL, Run, run_of
from lab_commons.compute.model import REQUEST, Demand, Resources, Supply
from lab_commons.dev import forgeproduce
from lab_commons.dev.forgeclaim import MINE, REFUSED_AT_COMMIT, Claim, Work
from lab_commons.dev.forgerequest import (
    UNADMITTED,
    UndeclaredRequest,
    declared_request,
    git_sources,
    parse_body,
    request_body,
    request_context,
    unreachable_source,
    unserved,
)
from lab_commons.dev.forgeschedule import NOT_ADMITTED
from lab_commons.dev.platformparts import origin_url
from lab_commons.hpc.declared import OutdatedKit

server = test_dev_forgetick.server  # the loopback forge fixture, shared

ME = Claim('G', 'alice', LATER)
ARGV = ('-m', 'solver', 'golden', 'regenerate', '--reference', 'femm')
GOLDENS = (
    PRODUCE
    + '[tool.lab_commons.requests.femm_goldens]\n'
    + 'argv = ["-m", "solver", "golden", "regenerate", "--reference", "femm"]\n'
    + 'needs = ["femm", "windows"]\n'
    + 'cpu = 2\n'
    + 'mem_gb = 3.5\n'
    + 'wall_h = 72\n'
)
FEMM_HOST = Supply(
    'G', Resources(cpu=4.0, mem_gb=16.0, femm=1.0, windows=1.0), frozenset({'cpu', 'mem_gb', 'femm', 'windows'})
)
PLAIN_HOST = Supply('G', Resources(cpu=4.0), frozenset({'cpu', 'windows'}))


def _one_core(_wanted: object, needs: frozenset[str]) -> Demand:
    """A request measured at one core, one seat of each need: it fits a four-core host."""
    return Demand({'cpu': 1, **dict.fromkeys(needs, 1.0)})


def _locked(repo: Path) -> None:
    """Stage a ``uv.lock``: the next declared commit pins every dependency revision (R1)."""
    (repo / 'uv.lock').write_text('version = 1', encoding='utf-8')
    run_git(repo, 'add', 'uv.lock')


def _request(repo: Path, tips: dict[str, str], producer: str, *, locked: bool = True) -> str:
    """Pin a request (issue 9) to the commit declaring GOLDENS; the integration head moves past it, DONE."""
    if locked:
        _locked(repo)
    pinned = _declare(repo, tips, GOLDENS)
    run_git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'after')
    head = git_out(repo, 'rev-parse', 'HEAD')
    run_git(repo, 'update-ref', 'refs/remotes/origin/integrate/main', head)
    done = {'id': 1, 'context': 'tests/base', 'status': 'success', 'description': 'scope=full ran=1'}
    answer('GET', f'{API}/statuses/{head}', (200, [done]))
    _ask(producer, pinned)
    answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    return pinned


def _ask(producer: str, sha: str, *, body: str = '', author: str = 'bob') -> None:
    """Issue 9 asks for *producer* at *sha* (*body* appended), authored by *author*."""
    issue = {
        'number': 9,
        'body': request_body(producer, sha) + body,
        'created_at': '2026-10-10T00:00:00Z',
        'labels': [{'name': 'forge:request'}],
        'user': {'login': author},
    }
    answer('GET', f'{API}/issues', (200, [issue]))


def test_a_declared_request_is_admitted_and_claimed_where_its_needs_are_present(server, tmp_path: Path) -> None:
    repo, tips = _origin(tmp_path)
    sha = _request(repo, tips, 'femm_goldens')
    mine = {'id': 2, 'context': 'request/9', 'status': 'pending', 'description': ME.description()}
    answer('GET', f'{API}/statuses/{sha}', (200, []), (200, [mine]))
    answer('POST', f'{API}/statuses/{sha}', (201, {}))
    report = _tick(repo, server, supply=FEMM_HOST, demand=_one_core)
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
    report = _tick(repo, server, supply=PLAIN_HOST, demand=_one_core)
    assert report.claimed == ()
    assert not [r for r in Recorder.received if r['method'] == 'POST']
    (waiting,) = [item for item in report.queue if item.candidate.kind == REQUEST]
    assert waiting.blocked == f'{NOT_ADMITTED}: lacking femm'


def test_an_undeclared_producer_name_is_refused_not_run(server, tmp_path: Path) -> None:
    """A request names a producer; it never carries a command. A name the sha does not declare is refused.

    The defect is the commit's own, so it is settled ONCE on the request's own context, never claimed or
    left waiting. PLANTED CONTROL: a declared name is claimed (the test above).
    """
    repo, tips = _origin(tmp_path)
    sha = _request(repo, tips, 'rm_rf')
    answer('GET', f'{API}/statuses/{sha}', (200, []))
    answer('POST', f'{API}/statuses/{sha}', (201, {}))
    report = _tick(repo, server, supply=FEMM_HOST, demand=_one_core)
    assert report.claimed == ()
    assert report.queue == ()
    (posted,) = [r for r in Recorder.received if r['method'] == 'POST']
    assert (posted['body']['state'], posted['body']['context']) == ('error', request_context(9))
    assert posted['body']['description'].startswith(REFUSED_AT_COMMIT)
    assert '[tool.lab_commons.requests.rm_rf]' in posted['body']['description']


def test_a_request_is_admitted_at_the_size_its_row_declares_never_the_whole_host(server, tmp_path: Path) -> None:
    """S1 (live 2026-10-16): three requests each asked a host's WHOLE card and admitted nowhere busy.

    No demand is injected: the tick sizes the request from its own row (``cpu``, ``mem_gb``).
    """
    repo, tips = _origin(tmp_path)
    sha = _request(repo, tips, 'femm_goldens')
    mine = {'id': 2, 'context': 'request/9', 'status': 'pending', 'description': ME.description()}
    answer('GET', f'{API}/statuses/{sha}', (200, []), (200, [mine]))
    answer('POST', f'{API}/statuses/{sha}', (201, {}))
    (claimed,) = _tick(repo, server, supply=FEMM_HOST).claimed
    assert dict(claimed.demand) == {'cpu': 2, 'mem_gb': 3.5, 'femm': 1.0, 'windows': 1.0}
    assert claimed.wall_s == 72 * 3600, 'S5: the wall its row declares, not the 24 h every box part gets'
    held = forgeproduce.boxed(claimed, ['py'], Capacity(cpu=8, mem_bytes=32 * 1024**3, seats={}), tmp_path / 'o.json')
    assert held[held.index('--wall') + 1] == str(72 * 3600)


def test_an_unsized_request_row_is_refused_by_name(tmp_path: Path) -> None:
    """PLANTED CONTROL: the row above without its size is refused, never sized as the whole host."""
    repo, tips = _origin(tmp_path)
    unsized = _declare(repo, tips, GOLDENS.replace('cpu = 2\n', ''))
    with pytest.raises(UndeclaredRequest, match=r'unsized.*cpu'):
        declared_request(repo, unsized, 'femm_goldens')
    zero = _declare(repo, tips, GOLDENS.replace('mem_gb = 3.5', 'mem_gb = 0'))
    with pytest.raises(UndeclaredRequest, match=r'unsized.*mem_gb'):
        declared_request(repo, zero, 'femm_goldens')
    unbounded = _declare(repo, tips, GOLDENS.replace('wall_h = 72', ''))
    with pytest.raises(UndeclaredRequest, match=r'unsized.*wall_h'):
        declared_request(repo, unbounded, 'femm_goldens')


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
    item = Work('issue/9', sha, 'femm+windows', MINE, ME, argv=ARGV, request='request/9')
    forgeproduce.produce(
        tmp_path, item, client=lambda _r: client, spawn=lambda argv, **_k: record(argv, ended(code)) or _Proc(code),
        clock=lambda: LATER,
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


def test_a_table_this_kit_does_not_know_is_the_readers_defect_never_the_requests(tmp_path: Path) -> None:
    """PLANTED CONTROL: a retired table is the commit's own defect -- refused as an undeclared request."""
    repo, tips = _origin(tmp_path)
    newer = _declare(repo, tips, GOLDENS + '[tool.lab_commons.tomorrow]\nrows = 1\n')
    with pytest.raises(OutdatedKit):
        declared_request(repo, newer, 'femm_goldens')
    older = _declare(repo, tips, GOLDENS + f'{RETIRED_TABLE}\nrows = 1\n')
    with pytest.raises(UndeclaredRequest, match='retired'):
        declared_request(repo, older, 'femm_goldens')


def test_a_request_run_is_learned_under_its_producer_name(tmp_path: Path) -> None:
    """S1: what a request's run measured sizes ITS next run, never the test part of its need-set."""
    item = Work('issue/9', 'a' * 40, 'femm+windows', MINE, ME, argv=ARGV, request='request/9', producer='femm_goldens')
    repo, _tips = _origin(tmp_path)
    forgeproduce.learn_box_run(repo, item, Run(peak_mem_gb=4.0, cpu_s=7200.0, wall_s=3600.0), killed=False)
    url = origin_url(repo)
    assert run_of(url, 'femm_goldens', {'femm', 'windows'}) == Run(4.0, 7200.0, 3600.0)
    assert run_of(url, LOCAL, {'femm', 'windows'}) is None


def test_a_request_at_a_sha_without_a_lock_is_refused_by_name(server, tmp_path: Path) -> None:
    """R1: an unlocked sha builds whatever its floating dependencies resolve to that day -- not reproducible.

    PLANTED CONTROL: the same request at a locked sha is claimed (the first test of this file).
    """
    repo, tips = _origin(tmp_path)
    sha = _request(repo, tips, 'femm_goldens', locked=False)
    answer('GET', f'{API}/statuses/{sha}', (200, []))
    answer('POST', f'{API}/statuses/{sha}', (201, {}))
    report = _tick(repo, server, supply=FEMM_HOST, demand=_one_core)
    assert report.claimed == ()
    (posted,) = [r for r in Recorder.received if r['method'] == 'POST']
    assert (posted['body']['state'], posted['body']['context']) == ('error', request_context(9))
    assert posted['body']['description'].startswith(f'{REFUSED_AT_COMMIT} {sha[:12]} commits no uv.lock')


def _orphan(repo: Path, sha: str) -> str:
    """A commit of *sha*'s tree on no ref origin keeps: a requester's unpushed (or since deleted) work."""
    return git_out(repo, 'commit-tree', f'{sha}^{{tree}}', '-m', 'unpushed')


def test_a_request_at_a_sha_origin_does_not_serve_is_refused_by_name(server, tmp_path: Path) -> None:
    """R4: a serve host fetches origin; a sha no origin ref contains is one it can never build.

    PLANTED CONTROL: the same tree at a sha origin serves is claimed (the first test of this file).
    """
    repo, tips = _origin(tmp_path)
    sha = _orphan(repo, _request(repo, tips, 'femm_goldens'))
    _ask('femm_goldens', sha)
    assert unserved(repo, sha) == f'origin serves no ref containing {sha[:12]}: push it where origin keeps it'
    answer('GET', f'{API}/statuses/{sha}', (200, []))
    answer('POST', f'{API}/statuses/{sha}', (201, {}))
    report = _tick(repo, server, supply=FEMM_HOST, demand=_one_core)
    assert report.claimed == ()
    (posted,) = [r for r in Recorder.received if r['method'] == 'POST']
    assert posted['body']['description'] == f'{REFUSED_AT_COMMIT} {unserved(repo, sha)}'
    assert unserved(repo, tips['topic/a']) == ''


def _sourced(repo: Path, tips: dict[str, str], *urls: str) -> str:
    """A declared, locked commit whose lock fetches each of *urls* by git."""
    pinned = '0' * 40
    rows = ''.join(
        f'[[package]]\nname = "p{n}"\nsource = {{ git = "{url}?rev=main#{pinned}" }}\n' for n, url in enumerate(urls)
    )
    (repo / 'uv.lock').write_text(rows, encoding='utf-8')
    run_git(repo, 'add', 'uv.lock')
    return _declare(repo, tips, GOLDENS)


def test_every_git_source_a_locked_sha_fetches_is_probed_before_a_claim(server, tmp_path: Path) -> None:
    """R2: a host without the credential a private source needs cannot build the tree; it says so, unclaimed.

    The refusal is THIS host's, not the commit's: another host holding the credential serves it, so the
    request waits naming the source. PLANTED CONTROL: a source this host reaches does not block it.
    """
    repo, tips = _origin(tmp_path)
    missing = (tmp_path / 'no-such-repo.git').as_uri()
    sha = _sourced(repo, tips, repo.as_uri(), missing)
    assert git_sources(repo, sha) == (repo.as_uri(), missing)
    why = unreachable_source(repo, sha)
    assert why.startswith(f'this host cannot fetch {missing}: ')
    _ask('femm_goldens', sha)
    answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    done = {'id': 1, 'context': 'tests/base', 'status': 'success', 'description': 'scope=full ran=1'}
    answer('GET', f'{API}/statuses/{sha}', (200, [done]))  # the head's own part is done
    report = _tick(repo, server, supply=FEMM_HOST, demand=_one_core)
    assert report.claimed == ()
    assert not [r for r in Recorder.received if r['method'] == 'POST'], 'nothing refused on the commit'
    (waiting,) = [item for item in report.queue if item.candidate.kind == REQUEST]
    assert waiting.blocked == why
    assert unreachable_source(repo, _sourced(repo, tips, repo.as_uri())) == ''


def test_a_submodule_is_a_git_source_and_a_relative_one_resolves_against_origin(tmp_path: Path) -> None:
    repo, tips = _origin(tmp_path)
    modules = (
        '[submodule "a"]\n\tpath = a\n\turl = ../dep.git\n[submodule "b"]\n\tpath = b\n\turl = https://h/x/b.git\n'
    )
    (repo / '.gitmodules').write_text(modules, encoding='utf-8')
    run_git(repo, 'add', '.gitmodules')
    sha = _sourced(repo, tips)
    assert git_sources(repo, sha) == ('https://forge.example.org/o/dep.git', 'https://h/x/b.git')


def _branch(repo: Path, sha: str, ref: str) -> str:
    """A commit of *sha*'s tree on origin's *ref* alone: served, but on neither integrate/main nor main."""
    off = git_out(repo, 'commit-tree', f'{sha}^{{tree}}', '-m', 'lane work')
    run_git(repo, 'update-ref', f'refs/remotes/origin/{ref}', off)
    return off


def test_a_request_off_the_trunks_runs_only_for_an_author_this_host_allows(server, tmp_path: Path) -> None:
    """X1: a request runs a sha's code on someone else's box; only reviewed code, or a trusted author, may.

    PLANTED CONTROL: the same sha is claimed once its author is in this host's ``[requests] authors``.
    """
    repo, tips = _origin(tmp_path)
    sha = _branch(repo, _request(repo, tips, 'femm_goldens'), 'feat/x')
    _ask('femm_goldens', sha, author='mallory')
    done = {'id': 1, 'context': 'tests/base', 'status': 'success', 'description': 'scope=full ran=1'}
    answer('GET', f'{API}/statuses/{sha}', (200, [done]))  # its own part, as a served branch, is done
    report = _tick(repo, server, supply=FEMM_HOST, demand=_one_core, authors=())
    assert report.claimed == ()
    assert not [r for r in Recorder.received if r['method'] == 'POST'], 'another host may allow the author'
    (waiting,) = [item for item in report.queue if item.candidate.kind == REQUEST]
    assert waiting.blocked == (
        f"{sha[:12]} is on neither integrate/main nor main, and mallory is not in this host's [requests] authors"
    )
    mine = {'id': 2, 'context': 'request/9', 'status': 'pending', 'description': ME.description()}
    answer('GET', f'{API}/statuses/{sha}', (200, [done]), (200, [done, mine]))
    answer('POST', f'{API}/statuses/{sha}', (201, {}))
    (claimed,) = _tick(repo, server, supply=FEMM_HOST, demand=_one_core, authors=('mallory',)).claimed
    assert claimed.sha == sha


def test_a_request_no_host_admits_is_said_once_on_its_issue(server, tmp_path: Path) -> None:
    """S2: a request waiting past the declared hours gets ONE comment naming why, never silence.

    PLANTED CONTROL: once the issue carries that comment, the next tick posts nothing.
    """
    repo, tips = _origin(tmp_path)
    sha = _request(repo, tips, 'femm_goldens')
    answer('GET', f'{API}/statuses/{sha}', (200, []))
    comments = f'{API}/issues/9/comments'
    said = {'id': 5, 'body': 'x', 'html_url': 'u', 'user': {'login': 'alice'}}
    answer('GET', comments, (200, []))
    answer('POST', comments, (201, said))
    _tick(repo, server, supply=PLAIN_HOST, demand=_one_core)
    (posted,) = [r for r in Recorder.received if r['method'] == 'POST']
    assert posted['path'] == comments
    assert UNADMITTED in posted['body']['body']
    assert 'G: not admitted: lacking femm' in posted['body']['body']
    Recorder.received.clear()
    answer('GET', comments, (200, [{**said, 'body': posted['body']['body']}]))
    _tick(repo, server, supply=PLAIN_HOST, demand=_one_core)
    assert not [r for r in Recorder.received if r['method'] == 'POST'], 'said once'
