"""HOLD: a label the merge tick honours, so a green PR is held on a forge that refuses its draft.

Driven through the stateful fake forge and the real merge decision (:func:`dev_lab.dev.forgemergeready.ready`).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _forge_state import StateForge
from _roles_fixtures import EVERY_CI, carry
from test_dev_forgemerge_ready import _hub_pr, _merge_ready, _pr

from dev_lab.dev import forgedraft, forgehold
from dev_lab.dev.forgehold import HOLD_LABEL, hold, release
from dev_lab.dev.forgemergeready import ready


def test_a_held_green_pr_is_not_merged_and_the_reason_names_the_release_door(tmp_path: Path) -> None:
    """THE PLANTED CONTROL: the same PR, released, is merged by the same decision."""
    work, forge, number, head = _hub_pr(tmp_path)
    hold(forge, number)
    said = ready(work, forge, number)
    assert forge.merges == [], 'a held PR was merged'
    state, description = _merge_ready(forge, head)
    assert state == 'pending'
    assert f'python -m dev_lab.dev.forge pr release {number}' in description
    assert 'merged' not in said
    release(forge, number)
    assert ready(work, forge, number).endswith('merged')
    assert [merged for merged, _ in forge.merges] == [number]


def test_on_gitea_the_merge_job_honours_the_hold_too(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work, forge, number, _head = _pr(tmp_path)
    carry(monkeypatch, EVERY_CI)  # the job merges where merge is bound to ci
    hold(forge, number)
    hold(forge, number)  # idempotent: one label, created once
    assert [one['name'] for one in forge.labels] == [HOLD_LABEL]
    ready(work, forge, number)
    assert forge.merges == []
    release(forge, number)
    assert ready(work, forge, number).endswith('; merged')


def test_the_doors_say_the_state_and_the_release_door(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _work, forge, number, _head = _pr(tmp_path)
    assert forgehold.main(['hold', str(number)], client=forge) == 0
    assert f'pr release {number}' in capsys.readouterr().out
    assert forgehold.main(['release', str(number)], client=forge) == 0
    assert 'released' in capsys.readouterr().out


def test_a_refused_draft_names_the_hold_door(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def refuse(_client: object, number: int) -> object:
        msg = f'#{number}: o does not have permission to convert the pull request to draft'
        raise ValueError(msg)

    monkeypatch.setattr(forgedraft, 'mark_draft', refuse)
    assert forgedraft.main(['draft', '28'], judge=lambda *_a: (), client=StateForge()) == 1
    assert '`python -m dev_lab.dev.forge pr hold 28`' in capsys.readouterr().out
