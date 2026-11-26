"""The controls for the memory famtest (dev-lab#646): an added entry passes, an edited one reds, both through git."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.dev.famtests import memoryadds as body
from dev_lab.dev.famtests.memoryadds import assert_memory_is_only_added, assert_the_memory_guard_still_convicts


def test_the_planted_control_convicts_an_edit_and_passes_an_add(tmp_path: Path) -> None:
    assert_the_memory_guard_still_convicts(tmp_path)


def test_the_planted_control_reds_when_the_guard_goes_blind(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PLANTED CONTROL of the control: a judgment that never refuses reds it."""
    monkeypatch.setattr(body, 'problems_between', lambda *_a: ())
    with pytest.raises(AssertionError, match='reads a constant'):
        assert_the_memory_guard_still_convicts(tmp_path)


def test_the_body_names_each_refusal_and_the_remedy(tmp_path: Path) -> None:
    assert_the_memory_guard_still_convicts(tmp_path)
    with pytest.raises(AssertionError, match='MEMORY-SHAPE: 1 refusal') as red:
        assert_memory_is_only_added(root=tmp_path, base='origin/integrate/main')
    assert 'an-entry.md' in str(red.value)
    assert 'never an edit' in str(red.value)
