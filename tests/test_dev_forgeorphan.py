"""An orphaned PR goes to the integrator: labeled once, commented once, listed every tick (forgeorphan)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from _forge_state import StateForge

from dev_lab.dev import forgeorphan
from dev_lab.dev.forgeorphan import LABEL, ORPHAN_AGE, PUSH_RELEASES, alarms, labels_of, release, take, taken

_NOW = datetime(2026, 11, 15, 12, tzinfo=UTC)
_BASE = 'integrate/main'


def _pull(monkeypatch: pytest.MonkeyPatch, age: timedelta) -> tuple[StateForge, int]:
    forge = StateForge()
    number = forge.add_pull('pr/x', _BASE, title='add x', sha='a' * 40)
    monkeypatch.setattr(forgeorphan.forgedraft, 'pushed', lambda _client, _sha: _NOW - age)
    return forge, number


def _nobody(_owners: object) -> bool:
    return False


def test_a_still_pr_with_no_live_owner_is_taken_once_labeled_and_commented(tmp_path: Path, monkeypatch) -> None:
    forge, number = _pull(monkeypatch, ORPHAN_AGE + timedelta(minutes=1))
    (line,) = take(tmp_path, forge, _BASE, now=_NOW, live=_nobody)
    assert f'#{number}' in line
    assert labels_of(forge, number) == (LABEL,)
    (comment,) = forge.comments[number]
    assert 'MERGE-OR-DELETE' in comment['body']
    assert PUSH_RELEASES in comment['body']
    assert take(tmp_path, forge, _BASE, now=_NOW, live=_nobody) == [], 'the label is the idempotency key'
    assert len(forge.comments[number]) == 1


def test_planted_controls_a_recent_head_or_a_live_owner_is_never_taken(tmp_path: Path, monkeypatch) -> None:
    forge, number = _pull(monkeypatch, ORPHAN_AGE - timedelta(minutes=1))
    assert take(tmp_path, forge, _BASE, now=_NOW, live=_nobody) == []
    forge, number = _pull(monkeypatch, ORPHAN_AGE * 7)
    assert take(tmp_path, forge, _BASE, now=_NOW, live=lambda _owners: True) == []
    assert labels_of(forge, number) == ()
    assert forge.comments[number] == []


def test_a_pr_into_another_base_is_not_the_integrators(tmp_path: Path, monkeypatch) -> None:
    forge, _ = _pull(monkeypatch, ORPHAN_AGE * 2)
    assert take(tmp_path, forge, 'other', now=_NOW, live=_nobody) == []


def test_every_held_pr_is_an_integration_alarm_and_the_door_lists_it(tmp_path: Path, monkeypatch, capsys) -> None:
    forge, number = _pull(monkeypatch, ORPHAN_AGE * 2)
    monkeypatch.setattr(forgeorphan, '_live', _nobody)
    (found,) = alarms(tmp_path, forge, _BASE, 'o/r', now=_NOW)
    assert f'#{number}' in found.subject
    assert [pull.number for pull in taken(forge, _BASE)] == [number]
    monkeypatch.setattr(forgeorphan, 'load_policy', lambda _root: type('P', (), {'integration': _BASE})())
    assert forgeorphan.main([], cwd=tmp_path, client=forge) == 0
    assert f'#{number} pr/x' in capsys.readouterr().out


def test_a_push_after_the_take_hands_the_pr_back_and_a_still_head_keeps_the_label(tmp_path: Path, monkeypatch) -> None:
    forge, number = _pull(monkeypatch, ORPHAN_AGE * 2)
    take(tmp_path, forge, _BASE, now=_NOW, live=_nobody)
    assert release(forge, _BASE) == [], 'PLANTED CONTROL: the head did not move, the label stays'
    assert labels_of(forge, number) == (LABEL,)
    forge.pulls[number]['head']['sha'] = 'b' * 40
    (line,) = release(forge, _BASE)
    assert f'#{number}' in line
    assert labels_of(forge, number) == ()
    assert 'Handed back' in forge.comments[number][-1]['body']
    assert release(forge, _BASE) == [], 'said once'
