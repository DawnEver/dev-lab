"""The forge's PR-head statuses: terminal verdicts latch, errors retry, and the tick stays bounded and isolated."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from _branch_repos import clone_pair
from _forge_fake import git_out, run_git
from _forge_state import StateForge

from dev_lab.dev import forgeheadgate, prcurrent, sessionbranch
from dev_lab.dev.forgeintegration import tick
from dev_lab.dev.forgestatus import CommitStatus
from dev_lab.dev.lanepolicy import Policy
from dev_lab.dev.lockcheck import UNRESOLVED

_DECLARED = Policy(integration='integrate/main')  # every repo declares its integration branch (D83)

if TYPE_CHECKING:
    from collections.abc import Callable

_SHA = 'a' * 40


class _Statuses:
    """A status store keyed by sha, patched over the module's two forge calls."""

    def __init__(self) -> None:
        self.posts: dict[str, list[tuple[str, str, str]]] = {}

    def post(self, _client: object, sha: str, *, context: str, state: str, description: str) -> None:
        self.posts.setdefault(sha, []).append((context, state, description))

    def listed(self, _client: object, sha: str) -> tuple[CommitStatus, ...]:
        latest = {context: (state, text) for context, state, text in self.posts.get(sha, [])}
        return tuple(CommitStatus(context=c, state=s, description=t, url='') for c, (s, t) in latest.items())


@pytest.fixture
def statuses(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _Statuses:
    store = _Statuses()
    monkeypatch.setattr(forgeheadgate, 'status_post', store.post)
    monkeypatch.setattr(forgeheadgate, 'status_list', store.listed)
    monkeypatch.setattr(sessionbranch, 'head_refusals', lambda *_a: [])
    monkeypatch.setattr(prcurrent, 'head_refusals', lambda *_a: [])
    monkeypatch.setattr(forgeheadgate, 'lag_verdict', lambda *_a: ('success', 'within the limit'))

    class _Tree:
        def __enter__(self) -> Path:
            return tmp_path

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr(forgeheadgate, 'detached_worktree', lambda _root, _sha: _Tree())
    monkeypatch.setattr(forgeheadgate, 'merge_base', lambda _root, head, _integration: head)
    return store


def _reads(*answers: tuple[str, ...]) -> Callable[[Path], tuple[str, ...]]:
    queue = list(answers)
    return lambda _tree: queue.pop(0)


@pytest.mark.usefixtures('statuses')
def test_an_error_is_re_judged_and_a_verdict_latches(tmp_path: Path) -> None:
    """SR-20261024-001: only success/failure are terminal; an error (or pending) is judged again on the same sha."""
    read = _reads((f'{UNRESOLVED}: timeout',), (), ())
    assert forgeheadgate.judge(tmp_path, None, _SHA, 'pr/x', integration='integrate/main', read=read) == [
        'session-branch: success',
        'pr-current: success',
        'lock/fresh: error',
        'lock/lag: success',
    ]
    assert forgeheadgate.judge(tmp_path, None, _SHA, 'pr/x', integration='integrate/main', read=read) == [
        'lock/fresh: success'
    ]
    assert forgeheadgate.judge(tmp_path, None, _SHA, 'pr/x', integration='integrate/main', read=read) == [], (
        'CONTROL: a verdict latches'
    )


@pytest.mark.usefixtures('statuses')
def test_a_checkout_that_fails_is_an_error_and_is_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(_root: Path, _sha: str) -> None:
        msg = 'disk full'
        raise OSError(msg)

    monkeypatch.setattr(forgeheadgate, 'detached_worktree', broken)
    assert forgeheadgate.judge(tmp_path, None, _SHA, 'pr/x', integration='integrate/main', read=_reads()) == [
        'session-branch: success',
        'pr-current: success',
        'lock/fresh: error',
        'lock/lag: success',
    ]
    assert forgeheadgate.judge(tmp_path, None, _SHA, 'pr/x', integration='integrate/main', read=_reads()) == [
        'lock/fresh: error'
    ], 'retried'


def _judge(tmp_path: Path, branch: str = 'pr/x') -> list[str]:
    return forgeheadgate.judge(tmp_path, None, _SHA, branch, integration='integrate/main', read=_reads((), ()))


def test_session_branch_is_the_push_rows_own_judge(
    tmp_path: Path, statuses: _Statuses, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ONE JUDGE, TWO CALLERS: the status says what :func:`sessionbranch.head_refusals` refuses, as ``failure``.

    PLANTED CONTROL: the same head with no refusal is ``success``.
    """
    refused = 'ORIGIN-HOLDS-ONLY-DECLARED-BRANCHES: not lane/x'

    def refusals(_root: Path, _sha: str, branch: str) -> list[str]:
        return [refused] if branch == 'lane/x' else []

    monkeypatch.setattr(sessionbranch, 'head_refusals', refusals)
    _judge(tmp_path, 'lane/x')
    assert statuses.posts[_SHA][0] == ('session-branch', 'failure', refused)
    statuses.posts.clear()
    _judge(tmp_path, 'pr/x')
    assert statuses.posts[_SHA][0][:2] == ('session-branch', 'success'), 'CONTROL'


def test_session_branch_reads_the_push_line_of_a_created_head(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The forge's caller hands :func:`sessionbranch.refusals` the pre-push line creating ``refs/heads/<branch>``."""
    lines: list[str] = []
    monkeypatch.setattr(sessionbranch, 'refusals', lambda _root, text: lines.append(text) or [])
    assert sessionbranch.head_refusals(tmp_path, _SHA, 'pr/x') == []
    assert lines == [f'refs/heads/pr/x {_SHA} refs/heads/pr/x {"0" * 40}']


def test_pr_current_is_volatile_and_posts_only_a_change(
    tmp_path: Path, statuses: _Statuses, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``pr-current`` reads integration's moving tip: a ``success`` does not latch; an unchanged one is not reposted.

    PLANTED CONTROL: ``session-branch``, not volatile, latches after its first verdict.
    """
    answers: list[list[str]] = [[], [], ['PR-HEAD-IS-CURRENT: behind; run forge sync']]
    monkeypatch.setattr(prcurrent, 'head_refusals', lambda *_a: answers.pop(0))
    assert 'pr-current: success' in _judge(tmp_path)
    again = _judge(tmp_path)
    assert not any(line.startswith(('pr-current', 'session-branch')) for line in again), 'unchanged, latched'
    assert 'pr-current: failure' in _judge(tmp_path), 'integration moved: the success did not latch'
    assert len(statuses.posts[_SHA]) == len({context for context, _s, _d in statuses.posts[_SHA]}) + 1


def test_pr_current_judges_only_what_the_row_judges(tmp_path: Path) -> None:
    """A machine branch and a non-``pr/`` head are not judged, so nothing is fetched for them.

    PLANTED CONTROL: a ``pr/`` head is fetched and judged.
    """
    fetched: list[str] = []

    def fetch(_root: Path, branch: str) -> str:
        fetched.append(branch)
        return 'offline'

    for branch in ('pr/relock', 'integrate/main'):
        assert prcurrent.head_refusals(tmp_path, _SHA, branch, 'integrate/main', fetch=fetch) == []
    assert fetched == []
    (why,) = prcurrent.head_refusals(tmp_path, _SHA, 'pr/x', 'integrate/main', fetch=fetch, read=lambda _t: ())
    assert 'could not be fetched' in why
    assert fetched == ['integrate/main'], 'CONTROL'


def test_the_gates_wait_until_each_stands_success() -> None:
    """The merge reads :func:`forgeheadgate.gates_wait`: absent, ``error`` and ``failure`` wait.

    PLANTED CONTROL: every gate ``success`` is ``None``, and ``lock/lag`` failing alone does not wait (an alarm).
    """

    def status(context: str, state: str) -> CommitStatus:
        return CommitStatus(context=context, state=state, description='why', url='')

    assert forgeheadgate.gates_wait(()) == 'session-branch is not yet judged; pr-current is not yet judged'
    for state in ('failure', 'error', 'pending'):
        waits = forgeheadgate.gates_wait((status('session-branch', 'success'), status('pr-current', state)))
        assert waits == f'pr-current is {state}: why'
    green = (status('session-branch', 'success'), status('pr-current', 'success'), status('lock/lag', 'failure'))
    assert forgeheadgate.gates_wait(green) is None


def test_lock_lag_reads_the_heads_own_lock(tmp_path: Path) -> None:
    """``lock/lag`` is :func:`relock.floating_lag` on the head's lock at :data:`LAG_LIMIT`.

    PLANTED CONTROLS: no lock is ``success``; an uncounted sibling is ``error``, never a pass.
    """
    _, work = clone_pair(tmp_path)
    head = git_out(work, 'rev-parse', 'HEAD')
    assert forgeheadgate.lag_verdict(work, head)[0] == 'success', 'CONTROL: no uv.lock, nothing floats'
    (work / 'uv.lock').write_text('version = 1\n', encoding='utf-8')
    run_git(work, 'add', 'uv.lock')
    run_git(work, 'commit', '-q', '--no-verify', '-m', 'build: lock')
    head = git_out(work, 'rev-parse', 'HEAD')
    seen: list[int] = []

    def lag(answer: tuple[str, ...]) -> Callable[..., tuple[str, ...]]:
        return lambda _text, limit: seen.append(limit) or answer

    behind = 'uv.lock pins dev-lab 21 commits behind its integrate/main (limit 20)'
    assert forgeheadgate.lag_verdict(work, head, lag=lag((behind,))) == ('failure', behind)
    assert forgeheadgate.lag_verdict(work, head, lag=lag(()))[0] == 'success'
    assert forgeheadgate.lag_verdict(work, head, lag=lag((f'{UNRESOLVED}: dev-lab: offline',)))[0] == 'error'
    assert set(seen) == {forgeheadgate.LAG_LIMIT}


def _head(work: Path, branch: str) -> str:
    run_git(work, 'checkout', '-q', '-B', 'tmp', 'origin/main')
    (work / f'{branch.replace("/", "_")}.txt').write_text(branch, encoding='utf-8')
    run_git(work, 'add', '-A')
    run_git(work, 'commit', '-q', '--no-verify', '-m', f'feat: {branch}')
    run_git(work, 'push', '-q', '--no-verify', 'origin', f'HEAD:refs/heads/{branch}')
    run_git(work, 'checkout', '-q', '--detach')
    return git_out(work, 'rev-parse', 'HEAD')


def _two_pulls(tmp_path: Path) -> tuple[Path, StateForge, dict[int, str]]:
    _, work = clone_pair(tmp_path)
    forge = StateForge()
    heads = {}
    for branch in ('pr/a', 'pr/b'):
        sha = _head(work, branch)
        heads[forge.add_pull(branch, 'integrate/main', sha=sha)] = sha
    return work, forge, heads


def test_a_gate_that_raises_for_one_head_leaves_the_tick_and_the_next_head(tmp_path: Path) -> None:
    """SR-20261024-002: a raise is one line for that head; the next head is still judged and the tick finishes."""
    work, forge, heads = _two_pulls(tmp_path)
    first, second = sorted(heads)
    judged: list[str] = []

    def gate(_root: Path, _client: object, head: str, _branch: str, *, integration: str) -> list[str]:
        assert integration == 'integrate/main'
        if head == heads[first]:
            msg = 'boom'
            raise RuntimeError(msg)
        judged.append(head)
        return ['lock/fresh: success']

    done = tick(work, forge, _DECLARED, fetch_pull=lambda _r, _m, n: heads[n], host='h1', gate=gate)
    assert judged == [heads[second]]
    assert any('pr/a' in line and 'gate raised RuntimeError: boom' in line for line in done.lines), done.lines
    assert len(done.said) == len(heads), 'every child still got its integration feedback'


def test_a_draft_head_is_never_gated(tmp_path: Path) -> None:
    """A DRAFT RUNS NOTHING (user ruling 2026-11-05): no lock resolution is spent on a draft's head.

    A Gitea draft is its ``WIP:`` title. PLANTED CONTROL: the ready PR's head is still judged.
    """
    work, forge, heads = _two_pulls(tmp_path)
    draft, ready = sorted(heads)
    forge.pulls[draft]['title'] = 'WIP: t'
    judged: list[str] = []

    def gate(_root: Path, _client: object, head: str, _branch: str, *, integration: str) -> list[str]:
        assert integration == 'integrate/main'
        judged.append(head)
        return ['lock/fresh: success']

    tick(work, forge, _DECLARED, fetch_pull=lambda _r, _m, n: heads[n], host='h1', gate=gate)
    assert judged == [heads[ready]]


def test_the_gate_runs_after_the_tick_work_within_a_budget_oldest_first(tmp_path: Path) -> None:
    """SR-20261024-003: the gate runs once every child is said, oldest PR first, and stops at the per-tick budget."""
    work, forge, heads = _two_pulls(tmp_path)
    first = min(heads)
    clock = iter([0.0, 0.0, forgeheadgate.TICK_BUDGET_S])
    order: list[str] = []

    def gate(_root: Path, _client: object, head: str, _branch: str, *, integration: str) -> list[str]:
        assert integration == 'integrate/main'
        order.append(head)
        return ['lock/fresh: success']

    done = tick(
        work, forge, _DECLARED, fetch_pull=lambda _r, _m, n: heads[n], host='h1', gate=gate,
        monotonic=lambda: next(clock),
    )  # fmt: skip
    assert order == [heads[first]], 'the oldest is judged; the budget is spent before the second'
    assert any('pr/b' in line and 'gate waits for the next tick' in line for line in done.lines), done.lines
    gated = next(i for i, line in enumerate(done.lines) if 'lock/fresh' in line)
    published = max(i for i, line in enumerate(done.lines) if ' -- ' in line)
    assert gated > published, 'the gate runs after every child is published'
