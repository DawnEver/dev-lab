"""A code given IN ADVANCE is not made to wait on an ~11 s self-preflight its 30 s window cannot afford.

Measured 2026-11-23: ``sshhold open --plan P --digest D --code C`` re-ran the plan's preflight (ssh to the issuer, the
subject read: ~11 s) before sending a code that had already spent seconds in a chat, and the issuer called it "wrong
or outside its 30-second window". The guarantee stays -- no code is spent on a stale or blocked plan -- but a green
recorded for the SAME digest within :data:`~dev_lab.ops.consent.door.CODE_PREFLIGHT_FRESH_S` stands in for the
re-run. PLANTED CONTROLS: a fresh recorded green sends at once; a stale one re-runs; a blocked re-run refuses with
"no code used".
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev_lab.dev import sshholdplan
from dev_lab.dev.sshholdwire import HoldRefused
from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.consent.door import CODE_PREFLIGHT_FRESH_S, PREFLIGHT_FRESH_S, record_preflight
from dev_lab.ops.consent.plan import parsed

_PLAN = {'hosts': ['ops@h.example'], 'grants': [{'host': 'ops@h.example', 'action': 'ops.config', 'subject': 'a' * 64}]}


def _plan(tmp_path: Path, *, age: float | None) -> Path:
    path = tmp_path / 'p.plan.json'
    path.write_text(json.dumps(_PLAN), encoding='utf-8')
    if age is not None:
        record_preflight(parsed(_PLAN), home=tmp_path / 'home', now=1_000_000.0 - age)
    return path


def _offered(tmp_path: Path, plan: Path, reran: list[str], *, blocked: bool = False) -> str:
    def rerun(_plan: Path, _steps: Path | None) -> list[str]:
        reran.append('preflight')
        if blocked:
            msg = 'no code used: the preflight this door ran itself is not green now'
            raise ConsentRefused(msg)
        return ['preflight: GREEN']

    return sshholdplan.offered(
        plan, None, code_given=True, rerun=rerun, held=lambda _dest: False, home=tmp_path / 'home', now=1_000_000.0
    )


def test_a_fresh_recorded_green_sends_the_given_code_at_once(tmp_path: Path) -> None:
    reran: list[str] = []
    said = _offered(tmp_path, _plan(tmp_path, age=CODE_PREFLIGHT_FRESH_S / 2), reran)
    assert reran == []
    assert 'recorded green' in said


def test_a_stale_recorded_green_runs_the_preflight_again(tmp_path: Path) -> None:
    reran: list[str] = []
    _offered(tmp_path, _plan(tmp_path, age=CODE_PREFLIGHT_FRESH_S + 1), reran)
    assert reran == ['preflight']


def test_a_blocked_rerun_refuses_with_no_code_used(tmp_path: Path) -> None:
    with pytest.raises(HoldRefused, match='no code used'):
        _offered(tmp_path, _plan(tmp_path, age=None), [], blocked=True)


def test_a_code_asked_at_the_prompt_always_preflights_first(tmp_path: Path) -> None:
    reran: list[str] = []
    sshholdplan.offered(
        _plan(tmp_path, age=1.0), None, code_given=False, rerun=lambda _p, _s: reran.append('preflight') or [],
        held=lambda _dest: False, home=tmp_path / 'home', now=1_000_000.0,
    )  # fmt: skip
    assert reran == ['preflight']


def test_the_window_is_short_beside_the_backstop() -> None:
    assert CODE_PREFLIGHT_FRESH_S == 300.0
    assert CODE_PREFLIGHT_FRESH_S < PREFLIGHT_FRESH_S


def test_the_line_that_sends_the_code_says_how_long_after_it_was_given(tmp_path: Path) -> None:
    ticks = iter([100.0, 100.0])
    _, lines = sshholdplan.open_planned(
        1, '123456', _plan(tmp_path, age=None), 'abc', grant=lambda *_a: [], routes=lambda _dest: (),
        opener=lambda dest, *_a, **_k: f'{dest}: open', clock=lambda: next(ticks), held=lambda _d: False,
        received=87.5,
    )  # fmt: skip
    assert lines[0] == 'code sent to the issuer 12.5 s after it was given'
