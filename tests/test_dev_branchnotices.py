"""FORGE NOTICES WHERE A SESSION ACTS ON ITS PR: one reader, for post-commit, pre-push and ``forge pr create``.

Real git and the stateful fake forge. Every voice has its planted control saying nothing: the same branch before the
forge found anything, another session, a non-``pr/*`` branch, a deletion, a failing or hanging forge.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from test_dev_forgenotice import SESSION, _part, _tick, _world

from lab_commons.dev import branchnotices

if TYPE_CHECKING:
    from lab_commons.dev.forgework import Client

_ZERO = '0' * 40


def _fresh(tmp_path: Path) -> dict:
    return {'cache_dir': tmp_path / 'cache'}


def test_a_pr_branch_hears_its_open_notices_for_this_session(tmp_path: Path) -> None:
    """PLANTED control: the same branch before the forge found anything says nothing."""
    work, forge, number, head = _world(tmp_path)
    assert branchnotices.report(work, ['pr/x'], SESSION, client=forge, **_fresh(tmp_path / 'a')) == ''
    _part(forge, head, 'failure')
    _tick(work, forge, head)
    said = branchnotices.report(work, ['pr/x'], SESSION, client=forge, **_fresh(tmp_path / 'b'))
    assert said.startswith(f'[pr-notices] {number}-{head[:12]}-red tests/base')
    assert len(said.splitlines()) == 1, 'one line per notice, no header'


def test_another_session_another_branch_or_no_session_hears_nothing(tmp_path: Path) -> None:
    """PLANTED control: the session on its own pr/* hears it (last line)."""
    work, forge, _, head = _world(tmp_path)
    _part(forge, head, 'failure')
    _tick(work, forge, head)
    seams = {'client': forge, **_fresh(tmp_path)}
    assert branchnotices.report(work, ['pr/x'], 'session_someone_else', **seams) == ''
    assert branchnotices.report(work, ['pr/x'], '', **seams) == ''
    assert branchnotices.report(work, ['lane/x'], SESSION, **seams) == ''
    assert branchnotices.report(work, ['pr/x'], SESSION, **seams) != ''


def test_a_push_names_its_pr_branches_and_a_deletion_names_none() -> None:
    """PLANTED control: the pushed pr/* ref is named."""
    assert branchnotices.pushed([f'refs/heads/pr/x {"a" * 40} refs/heads/pr/x {"1" * 40}']) == ['pr/x']
    assert branchnotices.pushed([f'(delete) {_ZERO} refs/heads/pr/x {"1" * 40}']) == []
    assert branchnotices.pushed([f'refs/heads/l {"a" * 40} refs/heads/lane/x {"1" * 40}']) == []


def test_a_run_of_commits_costs_one_forge_read_per_cache_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PLANTED control: past the window the forge is asked again."""
    work, forge, _, head = _world(tmp_path)
    _part(forge, head, 'failure')
    _tick(work, forge, head)
    real = branchnotices._from_forge
    calls: list[str] = []

    def counting(client: Client, branch: str, session: str) -> list[str]:
        calls.append(branch)
        return real(client, branch, session)

    monkeypatch.setattr(branchnotices, '_from_forge', counting)
    seams = {'client': forge, **_fresh(tmp_path)}
    first = branchnotices.lines_for(work, 'pr/x', SESSION, clock=lambda: 1000.0, **seams)
    assert first
    assert branchnotices.lines_for(work, 'pr/x', SESSION, clock=lambda: 1059.0, **seams) == first
    assert len(calls) == 1, 'served from the cache'
    branchnotices.lines_for(work, 'pr/x', SESSION, clock=lambda: 1061.0, **seams)
    assert len(calls) == 2


def test_a_failing_or_hanging_forge_is_silent_and_bounded(tmp_path: Path) -> None:
    """PLANTED control: a forge that answers is read (the first test); one that never answers costs the deadline."""

    class Down:
        repo = 'r'

        def call(self, *_a: object, **_k: object) -> object:
            raise OSError

    gate = threading.Event()

    class Hung(Down):
        def call(self, *_a: object, **_k: object) -> object:
            gate.wait(30)
            raise OSError

    assert branchnotices.report(tmp_path, ['pr/x'], SESSION, client=Down(), **_fresh(tmp_path)) == ''
    start = time.monotonic()
    assert branchnotices.report(tmp_path, ['pr/x'], SESSION, client=Hung(), deadline=0.2, **_fresh(tmp_path)) == ''
    assert time.monotonic() - start < 5
    gate.set()


def test_main_exits_zero_whatever_happens(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PLANTED control: a report that speaks, and one that raises, both exit 0 -- the row never fails a git verb."""
    monkeypatch.setattr(branchnotices, 'report', lambda *_a, **_k: 'something')
    assert branchnotices.main([str(tmp_path)]) == 0

    def boom(*_a: object, **_k: object) -> str:
        raise RuntimeError

    monkeypatch.setattr(branchnotices, 'report', boom)
    assert branchnotices.main([str(tmp_path)]) == 0
    assert branchnotices.main(['--no-such-flag']) == 0
