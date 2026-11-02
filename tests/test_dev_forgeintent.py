"""INTENT BEFORE ACTION FOR A LOCAL RUN: journaled before it starts, re-attached by the next serve after a crash.

A "crash" is a serve process that never reached its release: the journal it left is read by a fresh one. The
forge is a per-sha store of status posts; liveness is a seam (a set of pids). The planted controls: a producer
still ALIVE is never released (only a dead one is), and a run whose result is already on the forge is never
re-opened.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from _forge_fake import run_git

from dev_lab.dev import forgeintent, forgeproduce
from dev_lab.dev.forgeclaim import OPEN, Claim, Work, assess
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgestatus import CommitStatus
from dev_lab.dev.netverb import Attempt, Diagnosis, Report
from dev_lab.dev.producer import RETRYABLE
from dev_lab.dev.shatree import Tree

NOW = datetime(2026, 10, 16, 12, tzinfo=UTC)
LEASE = timedelta(hours=6)
ME = Claim('G', 'alice', NOW + LEASE)
SHA = 'a' * 40
CONTEXT = 'tests/windows'


class _Forge:
    """Every status post on one commit, ids ascending; :attr:`down` refuses every call."""

    def __init__(self) -> None:
        self.posts: list[CommitStatus] = []
        self.down = False

    def _gate(self) -> None:
        if self.down:
            attempt = Attempt(1, 1, 'connection refused', Diagnosis.TRANSIENT)
            raise ForgeCallFailed(Report(('POST', '/statuses'), (attempt,), 3))

    def post(self, _client, _sha, *, context, state, description, target_url='') -> CommitStatus:
        self._gate()
        made = CommitStatus(context, state, description, target_url, id=len(self.posts) + 1)
        self.posts.append(made)
        return made

    def history(self, _client, _sha) -> tuple[CommitStatus, ...]:
        self._gate()
        return tuple(self.posts)


@pytest.fixture
def forge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Forge:
    run_git(tmp_path, 'init', '-q')
    made = _Forge()
    for module in (forgeintent, forgeproduce):
        monkeypatch.setattr(module, 'status_post', made.post)
        monkeypatch.setattr(module, 'status_history', made.history)
        monkeypatch.setattr(module, 'close_tree', lambda _r, sha, _c, **_k: f'tree {sha[:12]}: removed')
    return made


_CLIENT = SimpleNamespace(answered=format_datetime(NOW, usegmt=True), whoami=lambda: 'alice')


def _claimed(root: Path, forge: _Forge, pid: int) -> None:
    """What a serve that crashed mid-run left: its claim on the forge and its intent on disk."""
    forge.post(None, SHA, context=CONTEXT, state='pending', description=ME.description())
    forgeintent.journal(root, forgeintent.Intent('integrate/main', SHA, 'windows', CONTEXT, ME.description(), pid))


def _reattach(root: Path, alive: set[int]) -> list[str]:
    return forgeintent.reattach(root, _CLIENT, lease=LEASE, say=lambda _l: None, alive=alive.__contains__)


def test_a_dead_producer_is_released_as_claimable_and_forgotten(forge: _Forge, tmp_path: Path) -> None:
    _claimed(tmp_path, forge, pid=4242)
    [line] = _reattach(tmp_path, alive=set())
    assert 'released as claimable' in line
    assert forge.posts[-1].state == 'error'
    assert forge.posts[-1].description.startswith(RETRYABLE), 'retryable: any host may take it again'
    other = Claim('H', 'bob', NOW + LEASE)
    assert assess(forge.posts, CONTEXT, me=other, now=NOW)[0] == OPEN, 'claimable now, not after the lease'
    assert forgeintent.journaled(tmp_path) == ()


def test_a_live_producer_is_watched_never_released(forge: _Forge, tmp_path: Path) -> None:
    """PLANTED CONTROL for the one above: the same intent, its pid alive."""
    _claimed(tmp_path, forge, pid=4242)
    [line] = _reattach(tmp_path, alive={4242})
    assert 'watching' in line
    assert [post.state for post in forge.posts] == ['pending', 'pending'], 'its lease renewed, nothing released'
    renewed = Claim.parse(forge.posts[-1].description)
    assert renewed is not None
    assert renewed.until == NOW + LEASE, 'renewed on the forge clock'
    assert len(forgeintent.journaled(tmp_path)) == 1, 'kept: the next tick watches again'


def test_a_run_that_already_posted_is_only_forgotten(forge: _Forge, tmp_path: Path) -> None:
    _claimed(tmp_path, forge, pid=4242)
    forge.post(None, SHA, context=CONTEXT, state='success', description='scope=full ran=7')
    [line] = _reattach(tmp_path, alive=set())
    assert 'forgotten' in line
    assert forge.posts[-1].state == 'success', 'a settled result is never re-opened'
    assert forgeintent.journaled(tmp_path) == ()


def test_a_forge_that_is_down_keeps_the_intent_for_the_next_tick(forge: _Forge, tmp_path: Path) -> None:
    _claimed(tmp_path, forge, pid=4242)
    forge.down = True
    [line] = _reattach(tmp_path, alive=set())
    assert 'kept' in line
    assert len(forgeintent.journaled(tmp_path)) == 1


class _Proc:
    """A producer: at spawn and while it runs, it reads what the journal says about it."""

    def __init__(self, root: Path, forge: _Forge) -> None:
        self.root, self.forge, self.pid, self.stdout = root, forge, 4242, iter(())
        self.seen: list[tuple[forgeintent.Intent, ...]] = []

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        self.seen.append(forgeintent.journaled(self.root))
        self.forge.post(None, SHA, context=CONTEXT, state='success', description='scope=full ran=7')
        return 0


def test_produce_journals_the_claim_before_the_tree_and_the_pid_once_spawned(
    forge: _Forge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[tuple[forgeintent.Intent, ...]] = []

    def open_tree(root: Path, sha: str, _context: str) -> Tree:
        opened.append(forgeintent.journaled(root))
        return Tree(root / sha[:12], root / 'python')

    monkeypatch.setattr(forgeproduce, 'open_tree', open_tree)
    proc = _Proc(tmp_path, forge)
    forge.post(None, SHA, context=CONTEXT, state='pending', description=ME.description())
    forgeproduce.produce(
        tmp_path, Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('verify',)), client=lambda _r: _CLIENT,
        spawn=lambda _argv, **_k: proc, clock=lambda: NOW, say=lambda _l: None, lease=LEASE, renew_s=1,
        fetch=lambda _r: None, meter=lambda _pid: lambda: None,
    )  # fmt: skip
    [[before]] = opened
    assert (before.sha, before.context, before.holder, before.pid) == (SHA, CONTEXT, ME.description(), 0)
    [[running]] = proc.seen
    assert running.pid == 4242, 'the pid a restarted host re-attaches to'
    assert forgeintent.journaled(tmp_path) == (), 'released: nothing is left to re-attach'
