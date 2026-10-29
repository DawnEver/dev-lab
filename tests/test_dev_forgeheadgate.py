"""The forge's PR-head statuses: terminal verdicts latch, errors retry, and the tick stays bounded and isolated."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from _branch_repos import clone_pair
from _forge_fake import git_out, run_git
from _forge_state import StateForge

from dev_lab.dev import forgeheadgate
from dev_lab.dev.forgeintegration import tick
from dev_lab.dev.forgestatus import CommitStatus
from dev_lab.dev.lanepolicy import Policy
from dev_lab.dev.lockcheck import UNRESOLVED

_DECLARED = Policy(integration='integrate/main')  # the integration flow is opt-in: these fixtures declare it

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
    monkeypatch.setattr(forgeheadgate, 'branchset_verdict', lambda *_a: ('success', 'pr/x is declared'))

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
        'branchset: success',
        'lock/fresh: error',
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
        'branchset: success',
        'lock/fresh: error',
    ]
    assert forgeheadgate.judge(tmp_path, None, _SHA, 'pr/x', integration='integrate/main', read=_reads()) == [
        'lock/fresh: error'
    ], 'retried'


@pytest.mark.usefixtures('statuses')
def test_a_branchset_error_is_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(forgeheadgate, 'branchset_verdict', lambda *_a: ('error', 'no readable branch set'))
    read = _reads((), ())
    assert (
        forgeheadgate.judge(tmp_path, None, _SHA, 'pr/x', integration='integrate/main', read=read)[0]
        == 'branchset: error'
    )
    assert forgeheadgate.judge(tmp_path, None, _SHA, 'pr/x', integration='integrate/main', read=read) == [
        'branchset: error'
    ]


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
