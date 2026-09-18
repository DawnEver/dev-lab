"""The controls for :mod:`lab_commons.dev.famtests.untimedwaits` -- every distinction, both ways.

A LINT THAT HAS NEVER BEEN SHOWN TO FIRE PROVES NOTHING WHEN IT IS GREEN, and one that refuses every
subprocess it sees gets deleted rather than obeyed. Every arm below is planted against in both
directions, over a real tree, through the published surface.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lab_commons.dev import floors
from lab_commons.dev.famtests.untimedwaits import (
    BLOCKING,
    WAITERS,
    UnboundedWait,
    UntimedScan,
    assert_every_wait_is_bounded,
    assert_the_scanner_still_convicts,
    take_scan,
    untimed_waits,
)

_ROOTS = (('tests', 'test_*.py'), ('scripts', '*.py'))


def _plant(root: Path, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding='utf-8')


def test_an_unbounded_run_is_named_and_a_bounded_one_is_not(tmp_path: Path) -> None:
    _plant(tmp_path, 'tests/test_a.py', 'import subprocess\nsubprocess.run(["x"], check=False)\n')
    _plant(tmp_path, 'tests/test_b.py', 'import subprocess\nsubprocess.run(["x"], check=False, timeout=5)\n')
    scan = untimed_waits(tmp_path, roots=_ROOTS, exempt=())
    assert scan.offenders == ('tests/test_a.py:2: run() waits with no timeout=',)
    assert scan.files_read == 2, 'both files were READ -- only one of them offends'


@pytest.mark.parametrize('call', sorted(BLOCKING))
def test_every_blocking_subprocess_call_is_covered(call: str, tmp_path: Path) -> None:
    """A named SET, not a count: a member silently dropped from BLOCKING is a hole with no symptom."""
    _plant(tmp_path, 'tests/test_x.py', f'import subprocess\nsubprocess.{call}(["x"])\n')
    assert untimed_waits(tmp_path, roots=_ROOTS, exempt=()).offenders == (
        f'tests/test_x.py:2: {call}() waits with no timeout=',
    )


@pytest.mark.parametrize('waiter', sorted(WAITERS))
def test_every_waiter_is_covered_and_a_positional_ceiling_acquits_it(waiter: str, tmp_path: Path) -> None:
    """The asymmetry that only a second root could find: a positional ceiling counts for a WAITER."""
    _plant(tmp_path, 'scripts/a.py', f'p = start()\np.{waiter}()\n')
    assert untimed_waits(tmp_path, roots=_ROOTS, exempt=()).offenders == (
        f'scripts/a.py:2: {waiter}() waits with no timeout=',
    )
    _plant(tmp_path, 'scripts/a.py', f'p = start()\np.{waiter}(5)\n')
    assert untimed_waits(tmp_path, roots=_ROOTS, exempt=()).offenders == ()


def test_a_positional_argument_does_NOT_acquit_a_blocking_call(tmp_path: Path) -> None:
    """The other half of the asymmetry: ``run`` takes the COMMAND positionally, never the ceiling."""
    _plant(tmp_path, 'tests/test_x.py', 'import subprocess\nsubprocess.run(["x"])\n')
    assert untimed_waits(tmp_path, roots=_ROOTS, exempt=()).offenders != ()


def test_popen_itself_is_not_an_offender(tmp_path: Path) -> None:
    """``Popen`` returns immediately; the ceiling belongs on the wait that follows, not on the start."""
    _plant(tmp_path, 'tests/test_x.py', 'import subprocess\np = subprocess.Popen(["x"])\n')
    assert untimed_waits(tmp_path, roots=_ROOTS, exempt=()).offenders == ()


def test_a_same_named_call_on_something_else_is_not_convicted(tmp_path: Path) -> None:
    """``other.run(...)`` is not a subprocess, and a lint that says it is fires on ordinary code."""
    _plant(tmp_path, 'tests/test_x.py', 'runner.run(["x"])\n')
    assert untimed_waits(tmp_path, roots=_ROOTS, exempt=()).offenders == ()


def test_the_declared_roots_decide_the_walk_and_an_absent_tree_is_skipped(tmp_path: Path) -> None:
    """``roots`` is a repo fact: an undeclared tree is not read, and an absent declared one is not fatal."""
    _plant(tmp_path, 'tests/test_x.py', 'import subprocess\nsubprocess.run(["x"])\n')
    _plant(tmp_path, 'tests/helper.py', 'import subprocess\nsubprocess.run(["x"])\n')
    _plant(tmp_path, 'other/z.py', 'import subprocess\nsubprocess.run(["x"])\n')
    scan = untimed_waits(tmp_path, roots=_ROOTS, exempt=())
    assert scan.files_read == 1, 'only the declared glob in the declared tree is read'
    assert [hit.split(':')[0] for hit in scan.offenders] == ['tests/test_x.py']


def test_an_exempt_file_is_neither_read_nor_reported(tmp_path: Path) -> None:
    _plant(tmp_path, 'tests/test_guard.py', 'import subprocess\nsubprocess.run(["x"])\n')
    scan = untimed_waits(tmp_path, roots=_ROOTS, exempt=('tests/test_guard.py',))
    assert scan.offenders == ()
    assert scan.files_read == 0


def test_a_file_that_does_not_parse_is_skipped_and_not_counted(tmp_path: Path) -> None:
    """It cannot be read, so it must not inflate the floor that says the tree WAS read."""
    _plant(tmp_path, 'tests/test_broken.py', 'def (:\n')
    assert untimed_waits(tmp_path, roots=_ROOTS, exempt=()).files_read == 0


def test_the_arm_binds_BOTH_sides_of_its_floor_before_it_looks_at_an_offender() -> None:
    """A scan pointed at a tree that moved reports exactly what a bounded tree reports."""
    empty = UntimedScan(files_read=0, offenders=())
    with pytest.raises(floors.FloorUnmet):
        assert_every_wait_is_bounded(empty, floor=10, headroom=5)
    outgrown = UntimedScan(files_read=400, offenders=())
    with pytest.raises(floors.SlackFloor):
        assert_every_wait_is_bounded(outgrown, floor=10, headroom=5)
    with pytest.raises(floors.FloorMisdeclared):
        assert_every_wait_is_bounded(UntimedScan(files_read=12, offenders=()), floor=10, headroom=0)


def test_the_arm_raises_on_an_offender_and_passes_a_bounded_tree(tmp_path: Path) -> None:
    _plant(tmp_path, 'tests/test_a.py', 'import subprocess\nsubprocess.run(["x"], timeout=5)\n')
    _plant(tmp_path, 'tests/test_b.py', 'import subprocess\nsubprocess.run(["x"], timeout=5)\n')
    assert_every_wait_is_bounded(take_scan(tmp_path, roots=_ROOTS, exempt=()), floor=2, headroom=4)
    _plant(tmp_path, 'tests/test_c.py', 'import subprocess\nsubprocess.run(["x"])\n')
    with pytest.raises(UnboundedWait, match='INCONCLUSIVE'):
        assert_every_wait_is_bounded(take_scan(tmp_path, roots=_ROOTS, exempt=()), floor=2, headroom=4)


def test_the_planted_control_convicts_through_the_shipped_scanner(tmp_path: Path) -> None:
    assert_the_scanner_still_convicts(tmp_path, roots=_ROOTS)


def test_the_control_refuses_an_empty_root_declaration(tmp_path: Path) -> None:
    """A control handed nothing to walk would plant nothing, find nothing and pass in triumph."""
    with pytest.raises(AssertionError, match='walk nothing'):
        assert_the_scanner_still_convicts(tmp_path, roots=())
