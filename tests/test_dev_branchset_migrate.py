"""#1115: a retired branchset key on a merge's BASE never blocks the PR that migrates it, and the migration has a door.

Each acquittal stands beside its refusal: base retired + head clean is judged by the head; both retired refuses
naming the migration line and the ``--migrate`` door; a clean base is judged by the base even when the head is broken.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.dev import branchset
from dev_lab.dev.branchset import BranchSetKeyRetired, merge_branchset, migrate_text

_TABLE = '[tool.dev_lab.branchset]\ntrunk = "main"\nsessions = ["integrate/main"]\n'
RETIRED = _TABLE + 'max_idle_hours = 12\n'
CLEAN = _TABLE + 'max_idle = "12 h"\n'


def test_a_retired_base_with_a_clean_head_is_judged_by_the_head() -> None:
    declared = merge_branchset(RETIRED, 'pyproject.toml at integrate/main', lambda: CLEAN, 'pyproject.toml at abc')
    assert declared.max_idle == 12 * 3600.0


def test_both_retired_refuses_naming_the_line_and_the_door() -> None:
    with pytest.raises(BranchSetKeyRetired, match=r'write max_idle = "12 h".*dev_lab\.dev\.branchset --migrate'):
        merge_branchset(RETIRED, 'base', lambda: RETIRED, 'head')


def _unread() -> str:
    msg = 'the head was read for a clean base'
    raise AssertionError(msg)


def test_a_clean_base_is_judged_by_the_base_never_the_head() -> None:
    """PLANTED CONTROL: the head is consulted only when the base is retired -- a broken head changes nothing."""
    assert merge_branchset(CLEAN, 'base', _unread, 'head').trunk == 'main'


def test_migrate_rewrites_the_retired_key_and_is_idempotent() -> None:
    text = '[project]\nmax_idle_hours = 3\n' + RETIRED + '[tool.other]\nx = 1\n'
    once = migrate_text(text)
    assert once == '[project]\nmax_idle_hours = 3\n' + CLEAN + '[tool.other]\nx = 1\n'
    assert migrate_text(once) == once


def test_the_migrate_door_rewrites_a_checkout_and_touches_nothing_else(tmp_path: Path) -> None:
    (tmp_path / 'pyproject.toml').write_text(RETIRED, encoding='utf-8')
    assert branchset.main(['--migrate', str(tmp_path)]) == 0
    assert (tmp_path / 'pyproject.toml').read_text(encoding='utf-8') == CLEAN
    assert branchset.main(['--migrate', str(tmp_path)]) == 0
    assert (tmp_path / 'pyproject.toml').read_text(encoding='utf-8') == CLEAN
