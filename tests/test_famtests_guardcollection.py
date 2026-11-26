"""dev-lab#599, first slice: a rule's test mechanism that collects nothing, or runs no verdict, is named."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.dev import guardcollection
from dev_lab.dev.famtests.guardcollection import (
    assert_every_guard_collects,
    assert_the_collection_control_still_convicts,
    mechanism_paths,
)
from dev_lab.dev.rules import RULES

_REPO = Path(__file__).resolve().parents[1]


def test_the_planted_control_convicts_exactly_the_dead_guards(tmp_path: Path) -> None:
    assert_the_collection_control_still_convicts(tmp_path)


def test_the_planted_control_reds_when_the_laundering_reader_goes_blind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PLANTED CONTROL of the control: collection alone cannot see a skip, so a blind AST reader reds it."""
    monkeypatch.setattr(guardcollection, 'laundered', lambda _text: '')
    with pytest.raises(AssertionError, match='must name exactly'):
        assert_the_collection_control_still_convicts(tmp_path)


@pytest.mark.parametrize(
    ('text', 'why'),
    [
        ('import pytest\npytest.skip("x", allow_module_level=True)\n', 'skips itself at module level'),
        ('import pytest\npytestmark = [pytest.mark.xfail(reason="r")]\n', 'pytestmark is xfail'),
        ('def test_a(:\n', 'does not parse'),
        ('import pytest\n@pytest.mark.skip\ndef test_a():\n    pass\n\ndef test_b():\n    pass\n', ''),
    ],
)
def test_laundering_is_read_whole_file_never_one_test(text: str, why: str) -> None:
    assert (why in guardcollection.laundered(text)) if why else guardcollection.laundered(text) == ''


def test_a_code_mechanism_is_not_judged_by_collection() -> None:
    assert guardcollection.is_test_file('tests/test_x.py')
    assert not guardcollection.is_test_file('src/dev_lab/dev/hook_install.py')
    assert guardcollection.zero_collection({'R': ('src/x.py',)}, counts={}, texts={'src/x.py': ''}) == ()


def test_every_guard_of_this_registry_collects_and_runs() -> None:
    # MEASURED 2026-11-26: 94 test-file mechanisms, every one collecting (101 with the 7 code mechanisms).
    assert_every_guard_collects(root=_REPO, mechanisms=mechanism_paths(RULES), floor=94)
