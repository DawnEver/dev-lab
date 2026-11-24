"""COST IS DERIVED (T3/H1, 2026-11-24): the ledger against the host's declared budget decides local or handed."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.dev import testcost
from dev_lab.dev.durations import CRASH_MARKER, Recorder, Row, write
from dev_lab.dev.testcost import Budget, plan

pytest_plugins = ['pytester']

_BUDGET = Budget(test_s=100.0, cores=8, memory_gb=32.0)


def test_a_test_measured_over_the_budget_is_handed_and_one_under_runs_here() -> None:
    """PLANTED CONTROL, both sides: the same plan keeps one test and hands the other."""
    planned = plan(['t::cheap', 't::dear'], {'t::cheap': 2.0, 't::dear': 100.0}, _BUDGET)
    assert planned.local == ('t::cheap',)
    assert planned.handed == ('t::dear',)


def test_a_measured_test_gets_a_deadline_derived_from_its_reading() -> None:
    planned = plan(['t::cheap'], {'t::cheap': 2.0}, _BUDGET)
    assert planned.deadlines['t::cheap'] == pytest.approx(
        max(testcost.DEADLINE_FLOOR_S, testcost.DEADLINE_FACTOR * 2.0), abs=1e-9
    )


def test_a_derived_deadline_never_exceeds_the_host_budget() -> None:
    planned = plan(['t::near'], {'t::near': 90.0}, _BUDGET)
    assert planned.deadlines['t::near'] == pytest.approx(_BUDGET.test_s, abs=1e-9)


def test_a_never_measured_test_runs_here_once_with_the_budget_as_its_deadline() -> None:
    """Its first run IS the measurement; a kill at the deadline is filed as cost >= deadline (durations)."""
    planned = plan(['t::new'], {}, _BUDGET)
    assert planned.local == ('t::new',)
    assert planned.deadlines['t::new'] == pytest.approx(_BUDGET.test_s, abs=1e-9)
    assert planned.unmeasured == ('t::new',)


def test_a_kill_at_the_deadline_makes_the_test_over_budget_next_time() -> None:
    """The ledger row a deadline kill leaves (filed AT the deadline) hands the test on the next plan."""
    filed = testcost.killed_at(_BUDGET.test_s)
    assert plan(['t::new'], {'t::new': filed}, _BUDGET).handed == ('t::new',)


@pytest.mark.parametrize(
    ('table', 'named'),
    [
        ({'cores': 8, 'memory_gb': 32}, 'test_s'),
        ({'test_s': 0, 'cores': 8, 'memory_gb': 32}, 'test_s'),
        ({'test_s': 60, 'cores': 'many', 'memory_gb': 32}, 'cores'),
    ],
)
def test_a_malformed_budget_is_refused_naming_the_key(table: dict[str, object], named: str) -> None:
    with pytest.raises(ValueError, match=named):
        testcost.budget_of(table)


def test_no_declared_budget_is_none_and_never_a_default() -> None:
    """dev-lab and repos declare no budget: absent in the family instance is absent here."""
    assert testcost.budget_of({}) is None


def test_a_hand_kept_cost_marker_is_refused_at_collection(pytester: pytest.Pytester) -> None:
    pytester.makepyfile('import pytest\n@pytest.mark.slow\ndef test_x():\n    pass\n')
    result = pytester.runpytest('-p', 'no:cacheprovider')
    result.stderr.fnmatch_lines(['*test_x*slow*retired*dev_lab.dev.testcost*'])
    assert result.ret != 0


def test_an_unmarked_test_collects(pytester: pytest.Pytester) -> None:
    """PLANTED CONTROL: the refusal is for the retired markers only."""
    pytester.makepyfile('def test_x():\n    pass\n')
    pytester.runpytest('-p', 'no:cacheprovider').assert_outcomes(passed=1)


class _Report:
    def __init__(self, nodeid: str, longrepr: str) -> None:
        self.nodeid, self.duration, self.failed, self.longrepr = nodeid, 0.0, True, longrepr


def test_a_kill_at_a_tests_own_deadline_is_filed_at_that_deadline(tmp_path: Path) -> None:
    """The ledger reads 'cost >= deadline' for the killed test; a test with no deadline falls back to the wall."""
    recorder = Recorder(root=tmp_path, wall=600.0, deadlines={'t::new': 45.0})
    recorder.pytest_runtest_logreport(_Report('t::new', f"worker 'gw0' {CRASH_MARKER} 't::new'"))
    recorder.pytest_runtest_logreport(_Report('t::old', f"worker 'gw1' {CRASH_MARKER} 't::old'"))
    assert recorder.seconds == {'t::new': testcost.killed_at(45.0), 't::old': 600.0}


def test_verify_runs_what_fits_and_hands_the_rest(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
    """End to end: a planted ledger and host budget -- the dear test is handed by name, the cheap one runs."""
    root = pytester.path
    pytester.makefile('.toml', pyproject='[tool.dev_lab.parts]\noutput = "out/logs"\n')
    machine = root / 'machine.toml'
    machine.write_text('[test_budget]\ntest_s = 100\ncores = 2\nmemory_gb = 4\n', encoding='utf-8')
    monkeypatch.setenv('LAB_COMMONS_CONFIG', str(machine))
    rows = [Row('test_sched.py::test_dear', 999.0), Row('test_sched.py::test_cheap', 0.1)]
    write(root, rows, selector='all', worker=None, tree='', env='')
    pytester.makepyfile(test_sched='def test_dear():\n    pass\ndef test_cheap():\n    pass\n')
    result = pytester.runpytest('-p', 'no:cacheprovider')
    result.assert_outcomes(passed=1, deselected=1)
    result.stdout.fnmatch_lines(['*handed to the forge: test_sched.py::test_dear*'])
