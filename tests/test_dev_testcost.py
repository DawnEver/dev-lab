"""COST IS DERIVED (T3/H1, 2026-11-24): the ledger against the host's declared budget decides local or handed."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from lab_commons.compute import learned
from lab_commons.compute.model import REQUEST

from dev_lab.dev import testcost
from dev_lab.dev.durations import CRASH_MARKER, Recorder, Row, read, write
from dev_lab.dev.forgetake import ClaimPass
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


def test_a_host_whose_budget_a_part_exceeds_leaves_it_for_one_that_fits() -> None:
    """FORGE PLACEMENT, both sides: the same part is left by a small host and claimable by a large one."""
    costs = {'tests/test_a.py::test_long': 900.0, 'tests/test_a.py::test_short': 1.0}
    small, large = Budget(test_s=600.0, cores=4, memory_gb=8.0), Budget(test_s=3600.0, cores=32, memory_gb=128.0)
    why = testcost.beyond_budget(costs, small, part='base')
    assert 'tests/test_a.py::test_long' in why
    assert '600' in why
    assert testcost.beyond_budget(costs, large, part='base') == ''
    assert testcost.beyond_budget(costs, None, part='base') == ''


def test_the_claim_pass_asks_the_budget_for_a_part_and_never_for_a_request() -> None:
    asked: list[tuple[str, str]] = []

    def costs(repo: str, part: str) -> dict[str, float]:
        asked.append((repo, part))
        return {'t::long': 900.0}

    host = SimpleNamespace(repo='origin', part_costs=costs, test_budget=Budget(test_s=600.0, cores=4, memory_gb=8.0))
    part = SimpleNamespace(kind='part', platform='base')
    assert 'over this host test budget' in ClaimPass._beyond_test_budget(host, part)  # type: ignore[arg-type]
    request = SimpleNamespace(kind=REQUEST, platform='base')
    assert ClaimPass._beyond_test_budget(host, request) == ''  # type: ignore[arg-type]
    assert asked == [('origin', 'base')]


def test_part_costs_reads_the_ids_of_the_files_the_part_last_ran(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(learned, 'part_files', lambda _repo, _needs: ('tests/test_a.py',))
    monkeypatch.setattr(
        learned, 'learned', lambda _repo: {'durations': {'tests/test_a.py::t': 5.0, 'tests/test_b.py::t': 9.0}}
    )
    assert testcost.part_costs('origin', 'base') == {'tests/test_a.py::t': 5.0}


def test_a_deadline_kill_without_workers_still_leaves_its_ledger_row(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The thread-method timeout ends the WHOLE process; the watchdog's row is written first -- cost >= deadline."""
    root = pytester.path
    pytester.makefile('.toml', pyproject='[tool.dev_lab.parts]\noutput = "out/logs"\n')
    machine = root / 'machine.toml'
    machine.write_text('[test_budget]\ntest_s = 1\ncores = 1\nmemory_gb = 1\n', encoding='utf-8')
    monkeypatch.setenv('LAB_COMMONS_CONFIG', str(machine))
    pytester.makepyfile(test_hang='import time\ndef test_hang():\n    time.sleep(60)\n')
    pytester.runpytest_subprocess(
        '-p', 'no:cacheprovider', '-p', 'dev_lab.dev.durations', '-p', 'no:xdist', '-o', 'timeout_method=thread',
        timeout=120,
    )  # fmt: skip
    seconds = read(root).seconds
    assert seconds.get('test_hang.py::test_hang', 0.0) >= 1.0, f'no deadline row was written: {seconds}'


def test_a_test_that_ends_inside_its_deadline_is_filed_at_what_it_took(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PLANTED CONTROL: the watchdog is disarmed by a test that finishes; its row is its real cost."""
    root = pytester.path
    pytester.makefile('.toml', pyproject='[tool.dev_lab.parts]\noutput = "out/logs"\n')
    machine = root / 'machine.toml'
    machine.write_text('[test_budget]\ntest_s = 30\ncores = 1\nmemory_gb = 1\n', encoding='utf-8')
    monkeypatch.setenv('LAB_COMMONS_CONFIG', str(machine))
    pytester.makepyfile(test_quick='def test_quick():\n    pass\n')
    result = pytester.runpytest_subprocess('-p', 'no:cacheprovider', '-p', 'dev_lab.dev.durations', '-p', 'no:xdist')
    result.assert_outcomes(passed=1)
    assert read(root).seconds['test_quick.py::test_quick'] < 30.0


_FORGE = {'durations': {'t::forge': 900.0, 't::both': 3000.0}, 'floors': {'t::killed': 800.0}}


def test_the_local_plan_reads_the_forge_measurement_beside_this_hosts_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ONE READER: a test the forge measured is measured here too; this host's own newer reading wins its id.

    PLANTED CONTROL: with no forge origin the same root reads only its own ledger -- the forge ids are unmeasured.
    """
    (tmp_path / 'pyproject.toml').write_text('[tool.dev_lab.parts]\noutput = "out/logs"\n', encoding='utf-8')
    write(tmp_path, [Row('t::both', 2.0), Row('t::local', 1.0)], selector='all', worker=None, tree='', env='')
    monkeypatch.setattr(learned, 'learned', lambda repo: _FORGE if repo == 'origin' else {})
    seconds = testcost.measured_seconds(tmp_path, 'origin')
    assert seconds == {'t::forge': 900.0, 't::killed': 800.0, 't::both': 2.0, 't::local': 1.0}
    assert testcost.measured_seconds(tmp_path, None) == {'t::both': 2.0, 't::local': 1.0}


def test_an_id_the_forge_killed_is_priced_at_its_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    """A floor is 'cost >= floor' (lab_commons.compute.measured): the placement and the local plan both read it."""
    monkeypatch.setattr(learned, 'learned', lambda _repo: _FORGE)
    assert testcost.forge_seconds('origin') == {'t::forge': 900.0, 't::both': 3000.0, 't::killed': 800.0}
    monkeypatch.setattr(learned, 'part_files', lambda _repo, _needs: ('t',))
    assert testcost.part_costs('origin', 'base')['t::killed'] == pytest.approx(800.0, abs=1e-9)


def test_verify_hands_a_test_only_the_forge_measured(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end: no local reading, a forge reading over this host's budget -- the test is handed by name."""
    root = pytester.path
    pytester.makefile('.toml', pyproject='[tool.dev_lab.parts]\noutput = "out/logs"\n')
    machine = root / 'machine.toml'
    machine.write_text('[test_budget]\ntest_s = 100\ncores = 2\nmemory_gb = 4\n', encoding='utf-8')
    monkeypatch.setenv('LAB_COMMONS_CONFIG', str(machine))
    monkeypatch.setattr(testcost, 'origin_of', lambda _root: 'origin')
    monkeypatch.setattr(learned, 'learned', lambda _repo: {'durations': {'test_forge.py::test_dear': 999.0}})
    pytester.makepyfile(test_forge='def test_dear():\n    pass\ndef test_cheap():\n    pass\n')
    result = pytester.runpytest('-p', 'no:cacheprovider')
    result.assert_outcomes(passed=1, deselected=1)
    result.stdout.fnmatch_lines(['*handed to the forge: test_forge.py::test_dear*'])
