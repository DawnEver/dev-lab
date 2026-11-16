"""``forge sync`` refuses an unbound session BEFORE it merges or relocks (a consumer repo, 2026-11-16).

THE INCIDENT (2026-11-16): a sync merged and relocked dev-lab to a kit whose task gate (D5) then refused the sync's
own relock commit; the session saw only "committing the relocked uv.lock failed" -- a wall that named no door, after
the tree had already been rewritten. The task gate is now asked first: an unbound session is refused naming the
door (the user's ``task: <slug>`` prompt), and nothing is fetched, merged or relocked. The planted control is a bound
session, which goes on to fetch.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dev_lab.dev import forgesync

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import pytest

_DOOR = 'SESSION-COMMITS-UNDER-ITS-TASK: none is bound. Door: a prompt whose first line is `task: <slug>`'


_STOP = 'stop after the fetch: the control only needs to reach it'


def _fetch_counted(calls: list[str]) -> Callable[[Path], None]:
    def fetch(_: Path) -> None:
        calls.append('fetch')
        raise OSError(_STOP)

    return fetch


def test_an_unbound_session_is_refused_before_anything_moves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(forgesync, 'task_refusal', lambda _: _DOOR)
    calls: list[str] = []
    assert forgesync.main([], cwd=tmp_path, fetch=_fetch_counted(calls), door=lambda _: calls.append('relock')) == 2
    assert calls == []
    assert '`task: <slug>`' in capsys.readouterr().err


def test_planted_control_a_bound_session_goes_on_to_fetch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(forgesync, 'task_refusal', lambda _: None)
    monkeypatch.setattr(forgesync, 'load_policy', lambda _: object())
    monkeypatch.setattr(forgesync, '_current', lambda *_: 'pr/task/feature')
    calls: list[str] = []
    assert forgesync.main([], cwd=tmp_path, fetch=_fetch_counted(calls)) == 2
    assert calls == ['fetch']
