"""``lab_commons.dev.durations`` -- every arm driven GREEN and, where reachable, driven RED.

WHICH READING THIS REPO CANNOT TAKE, AND IT IS RECORDED RATHER THAN SKIPPED. ``pytest-xdist`` is NOT
installed here (measured 2026-09-19 -- this repo declares no ``timeout`` and no ``-n`` either), so
the LIVE arm of
:func:`~lab_commons.dev.durations.assert_the_crash_marker_is_what_the_scheduler_writes` skips in this
tree and is live in the sibling repos that shard. The claim is driven anyway, twice, on source handed
straight to the reader: once carrying the sentence and once reworded. Its FLOOR -- source that was
never read, which trivially contains no marker either -- is driven separately, because that is the
green this arm would otherwise report most confidently.

THE ONE THING NO TEST HERE CAN DO is stand up four xdist workers, wedge one past a wall and observe
the controller file it at ~0.0s. The evidence for that is the consumer's: wdg-lab measured it on
2026-09-19 when this mechanism first ran, five tests the wall had just convicted entering the ledger
as the five fastest in the suite. What IS driven here is the arm that answers it, with the exact
sentence the installed xdist 3.8.0 writes at ``xdist/dsession.py:436``, quoted from that source.
"""

from __future__ import annotations

import json
import types
from dataclasses import dataclass
from pathlib import Path

import pytest

from lab_commons.dev import floors
from lab_commons.dev.durations import (
    CRASH_MARKER,
    FAST,
    SLOW,
    Finding,
    Ledger,
    LedgerInconclusive,
    Recorder,
    Row,
    assert_the_crash_marker_is_what_the_scheduler_writes,
    assert_the_ledger_is_evidence,
    assert_the_readings_still_convict,
    ledger_path,
    marked_but_fast,
    module_of,
    over,
    phase_seconds,
    read,
    unmarked_but_slow,
    write,
)

#: A bar and a ceiling an order of magnitude apart, as the module's own docstring asks a consumer to
#: choose them. Arguments here, never constants the kit closes over.
_BAR = 60.0
_CEILING = 5.0

_WEDGE = 'tests/integration/test_planted_wedge.py'
_QUICK = 'tests/unit/test_planted_fast.py'


# -- the readings ----------------------------------------------------------------------------------


def test_the_shipped_control_passes() -> None:
    """The kit's own five-claim control, on this repo's chosen pair of bars."""
    assert_the_readings_still_convict(bar=_BAR, ceiling=_CEILING)


def test_the_control_refuses_bars_that_leave_nothing_to_plant() -> None:
    """A ceiling at or above the bar makes every module slow and fast at once -- and plants nothing."""
    with pytest.raises(AssertionError, match='no room to plant'):
        assert_the_readings_still_convict(bar=_BAR, ceiling=_BAR)
    with pytest.raises(AssertionError, match='no room to plant'):
        assert_the_readings_still_convict(bar=_BAR, ceiling=0.0)


def test_a_module_over_the_bar_with_no_marker_is_convicted_with_its_reading() -> None:
    """EQUALITY on the finding, not membership, and the finding carries the number that convicted."""
    seconds = {f'{_WEDGE}::test_a': _BAR + 1.0, f'{_QUICK}::test_b': 0.01}
    assert unmarked_but_slow(seconds, frozenset(), bar=_BAR) == (
        Finding(module=_WEDGE, seconds=_BAR + 1.0, verdict=SLOW),
    )


def test_the_marker_and_not_the_duration_is_what_acquits() -> None:
    """A module the ledger clocks far over the bar is clean once it declares the marker."""
    seconds = {f'{_WEDGE}::test_a': _BAR * 100}
    assert unmarked_but_slow(seconds, frozenset({_WEDGE}), bar=_BAR) == ()


def test_the_mirror_convicts_a_waiver_nobody_uses_and_acquits_the_unmeasured() -> None:
    """The ratchet's other side. ABSENCE OF EVIDENCE CONVICTS NOBODY, which is the subtle half."""
    marked = frozenset({'tests/a/test_fast.py', 'tests/a/test_mixed.py', 'tests/a/test_unmeasured.py'})
    seconds = {
        'tests/a/test_fast.py::test_a': 0.2,
        'tests/a/test_mixed.py::test_a': 0.2,
        'tests/a/test_mixed.py::test_b': _CEILING + 1.0,
    }
    found = marked_but_fast(seconds, marked, ceiling=_CEILING)
    assert found == (Finding(module='tests/a/test_fast.py', seconds=0.2, verdict=FAST),)
    assert found[0].verdict == FAST


def test_a_module_keeps_its_marker_on_the_strength_of_one_expensive_test() -> None:
    """The mirror reads the WORST row per module; a mean would delete the marker a module earned."""
    marked = frozenset({'tests/a/test_mixed.py'})
    seconds = {'tests/a/test_mixed.py::test_a': 0.01, 'tests/a/test_mixed.py::test_b': _BAR}
    assert marked_but_fast(seconds, marked, ceiling=_CEILING) == ()


def test_over_folds_a_nodeid_to_its_module() -> None:
    """The unit is the MODULE, because a module-level ``pytestmark`` cannot be attributed to a nodeid."""
    assert over({f'{_WEDGE}::TestC::test_a': _BAR}, bar=_BAR) == frozenset({_WEDGE})
    assert over({f'{_WEDGE}::test_a': _BAR - 0.001}, bar=_BAR) == frozenset()


def test_module_of_spells_a_path_the_way_a_corpus_does() -> None:
    """A Windows-separated nodeid must fold to the same name a POSIX corpus scan produces."""
    assert module_of('tests\\unit\\test_a.py::test_x') == 'tests/unit/test_a.py'
    assert module_of('tests/unit/test_a.py::test_x') == 'tests/unit/test_a.py'
    assert module_of('tests/unit/test_a.py') == 'tests/unit/test_a.py'


def test_a_finding_prints_as_one_repair_shaped_line() -> None:
    """A refusal a reader can sort and act on without re-running the scan."""
    assert str(Finding(module=_WEDGE, seconds=61.5, verdict=SLOW)) == f'{_WEDGE}: 61.500s -- unmarked-but-slow'


# -- THE DEFECT THAT REFUTES THE MECHANISM IN ITS OWN DATA ------------------------------------------


def test_a_killed_worker_is_filed_at_the_wall_and_not_at_the_zero_reported_for_it() -> None:
    """THE ARM THE WHOLE MODULE EXISTS FOR, with the sentence xdist actually writes.

    Without it the tests the wall just convicted enter the ledger as the FASTEST in the suite, and a
    durations guard then acquits exactly what the wall caught.
    """
    longrepr = f"worker 'gw1' {CRASH_MARKER} '{_WEDGE}::test_a'"
    assert phase_seconds(duration=0.0, failed=True, longrepr=longrepr, wall=300.0) == 300.0


def test_the_wall_is_a_lower_bound_and_never_overwrites_a_longer_reading() -> None:
    """``max`` and not an assignment: a crash reporting longer than the wall keeps its own number."""
    longrepr = f'worker {CRASH_MARKER} x'
    assert phase_seconds(duration=900.0, failed=True, longrepr=longrepr, wall=300.0) == 900.0


def test_an_ordinary_fast_failure_is_not_filed_at_the_wall() -> None:
    """The mirror fabrication: filing every fast failure at the wall marks the whole suite slow."""
    assert phase_seconds(duration=0.0, failed=True, longrepr='assert 1 == 2', wall=300.0) == 0.0


def test_a_passing_test_carrying_the_words_is_not_read_as_a_crash() -> None:
    """The arm keys on a FAILED report as well as on the text, so a test ABOUT crashes is not caught."""
    longrepr = f'worker {CRASH_MARKER} x'
    assert phase_seconds(duration=0.1, failed=False, longrepr=longrepr, wall=300.0) == 0.1


def test_a_repo_with_no_wall_files_a_crash_at_what_it_reported() -> None:
    """A zero wall invents nothing. A repo with no wall has no lower bound, and that is the honest read."""
    longrepr = f'worker {CRASH_MARKER} x'
    assert phase_seconds(duration=0.0, failed=True, longrepr=longrepr, wall=0.0) == 0.0


def test_the_marker_check_reads_the_source_it_is_handed() -> None:
    """THE CONTROL FOR THE READER ITSELF, both ways, on source shaped like the real scheduler's.

    A scheduler whose source carries the sentence passes; one whose source does not is convicted with
    the consequence named. The claim -- "a detector and its subject must not agree only with each
    other" -- is exactly what goes silent when the scheduler rewords, so it is driven rather than
    asserted in prose.
    """
    carrying = f'msg = f"worker {{worker.gateway.id!r}} {CRASH_MARKER} {{nodeid!r}}"\n'
    assert_the_crash_marker_is_what_the_scheduler_writes(scheduler_source=carrying, where='planted/carrying.py')

    with pytest.raises(AssertionError, match='no longer writes'):
        assert_the_crash_marker_is_what_the_scheduler_writes(
            scheduler_source='msg = "worker died"\n',
            where='planted/reworded.py',
        )


def test_the_marker_check_refuses_source_it_never_read() -> None:
    """THE FLOOR ON THIS READING, and it is not a formality: '' contains no marker either.

    An empty string trivially lacks the marker, so without this arm the strongest-looking green the
    function can report is the one where the caller's ``importorskip`` was skipped and nothing was
    read at all. INCONCLUSIVE and clean are separate exception types for exactly that reason.
    """
    for blank in ('', '   \n\t'):
        with pytest.raises(LedgerInconclusive, match='INCONCLUSIVE rather than clean'):
            assert_the_crash_marker_is_what_the_scheduler_writes(scheduler_source=blank, where='planted/empty.py')


def test_the_marker_is_what_the_real_scheduler_writes_where_one_is_installed() -> None:
    """THE LIVE READING, taken wherever a scheduler exists -- skipped HERE, and that is measured.

    This repo does not install ``pytest-xdist`` (it declares no ``timeout`` and no ``-n`` either), so
    the reading cannot be taken in this tree. It is expressed as an ``importorskip`` rather than
    silently omitted because the sibling repos that DO shard run this same file, and there the arm is
    live against xdist's own source -- which is the only place the detector and its subject are
    checked against each other rather than against a plant.
    """
    dsession = pytest.importorskip('xdist.dsession')
    assert_the_crash_marker_is_what_the_scheduler_writes(
        scheduler_source=Path(dsession.__file__).read_text(encoding='utf-8'),
        where=dsession.__file__,
    )


# -- the ledger ------------------------------------------------------------------------------------


def test_a_targeted_run_does_not_clobber_the_ledger(tmp_path: Path) -> None:
    """THE OTHER DEFECT THE CONSUMER FOUND BY RUNNING IT. Every narrow run would break the guard.

    A full run, then a one-file run. If the second REPLACED the first, the next full run would red on
    the consumer's floor for a reason with nothing to do with the suite.
    """
    write(tmp_path, [Row('a::t', 10.0), Row('b::t', 20.0)], selector='all')
    write(tmp_path, [Row('b::t', 21.0)], selector='b')
    assert read(tmp_path).seconds == {'a::t': 10.0, 'b::t': 21.0}


def test_the_merge_keeps_the_max_so_a_quick_rerun_cannot_acquit(tmp_path: Path) -> None:
    """A test slow on one run and quick on the next IS slow; the row is a worst-observed cost."""
    write(tmp_path, [Row('a::t', 90.0)], selector='all')
    write(tmp_path, [Row('a::t', 0.1)], selector='all')
    assert read(tmp_path).seconds == {'a::t': 90.0}


def test_each_worker_writes_its_own_file_and_read_merges_them(tmp_path: Path) -> None:
    """Under ``-n`` the victim of the wall is a worker, so there are several files and one reading."""
    write(tmp_path, [Row('a::t', 1.0)], selector='all', worker='gw0')
    write(tmp_path, [Row('b::t', 2.0)], selector='all', worker='gw1')
    assert read(tmp_path).seconds == {'a::t': 1.0, 'b::t': 2.0}
    assert ledger_path(tmp_path, worker='gw0').is_file()
    assert ledger_path(tmp_path, worker='gw1').is_file()


def test_a_worker_does_not_fold_its_siblings_rows_into_its_own_file(tmp_path: Path) -> None:
    """A correction to the consumer's half: four files each claiming to have measured everything.

    ``max`` makes that harmless to :func:`read` and ruinous to anyone opening ONE file to find out
    what ONE worker did.
    """
    write(tmp_path, [Row('a::t', 1.0)], selector='all', worker='gw0')
    write(tmp_path, [Row('b::t', 2.0)], selector='all', worker='gw1')
    payload = json.loads(ledger_path(tmp_path, worker='gw1').read_text(encoding='utf-8'))
    assert set(payload['seconds']) == {'b::t'}


def test_the_selector_travels_with_the_rows(tmp_path: Path) -> None:
    """Rows mean nothing without what the run SELECTED -- the waiver arm is evidence-gated on it."""
    write(tmp_path, [Row('a::t', 1.0)], selector='not slow', worker='gw0')
    write(tmp_path, [Row('b::t', 2.0)], selector='all', worker='gw1')
    assert read(tmp_path).selector == 'all | not slow'


def test_an_absent_ledger_is_empty_rather_than_an_error(tmp_path: Path) -> None:
    """An absent ledger and a ledger of nothing are one fact; the FLOOR is what refuses both."""
    assert read(tmp_path) == Ledger(selector='', seconds={})


def test_an_empty_ledger_is_refused_rather_than_read_as_clean(tmp_path: Path) -> None:
    """THE FLOOR. A killed run and a clean suite report the same empty result."""
    with pytest.raises(floors.FloorUnmet):
        assert_the_ledger_is_evidence(ledger=read(tmp_path), floor=200, headroom=400, what='test duration')


def test_a_ledger_the_suite_outgrew_reds_on_the_floors_other_side(tmp_path: Path) -> None:
    """A ratchet has two sides: a floor the population outgrew is a waiver nothing uses."""
    write(tmp_path, [Row(f'm{i}::t', 1.0) for i in range(50)], selector='all')
    assert_the_ledger_is_evidence(ledger=read(tmp_path), floor=40, headroom=20, what='test duration')
    with pytest.raises(floors.SlackFloor):
        assert_the_ledger_is_evidence(ledger=read(tmp_path), floor=5, headroom=10, what='test duration')


# -- the runner's half -------------------------------------------------------------------------------


@dataclass
class _Report:
    """The four attributes :class:`Recorder` reads off a pytest report, and nothing else."""

    nodeid: str
    duration: float
    failed: bool = False
    longrepr: str = ''


class _Config:
    """A stand-in for ``config``: an ini table and the ``-m`` selector, as the recorder reads them."""

    def __init__(self, *, timeout: object, selector: str = '', worker: str | None = None) -> None:
        """Bind the three answers; *timeout* of ``KeyError`` makes ``getini`` raise as pytest does."""
        self._timeout = timeout
        self._selector = selector
        if worker is not None:
            self.workerinput = {'workerid': worker}

    def getini(self, name: str) -> object:
        """The ini value, raising ``ValueError`` for an unregistered key exactly as pytest does."""
        if name != 'timeout' or isinstance(self._timeout, KeyError):
            msg = f'unknown configuration value: {name!r}'
            raise ValueError(msg)
        return self._timeout

    def getoption(self, name: str) -> str:
        """The ``-m`` selector this run was given."""
        return self._selector if name == '-m' else ''


def test_the_recorder_sums_all_three_phases(tmp_path: Path) -> None:
    """A four-minute FIXTURE costs the box four minutes; attributing it to zero hides half a test."""
    recorder = Recorder(root=tmp_path)
    recorder.pytest_runtest_logreport(_Report(nodeid='a::t', duration=240.0))
    recorder.pytest_runtest_logreport(_Report(nodeid='a::t', duration=1.0))
    assert recorder.seconds == {'a::t': 241.0}


def test_the_recorder_binds_the_wall_the_runner_enforces(tmp_path: Path) -> None:
    """A second spelling of the wall is a second thing to keep in step, so it is READ, not declared."""
    recorder = Recorder(root=tmp_path)
    recorder.pytest_configure(_Config(timeout=300))
    assert recorder.wall == 300.0
    recorder.pytest_runtest_logreport(
        _Report(nodeid='a::t', duration=0.0, failed=True, longrepr=f'worker {CRASH_MARKER} x')
    )
    assert recorder.seconds == {'a::t': 300.0}


def test_a_repo_with_no_timeout_setting_does_not_explode(tmp_path: Path) -> None:
    """``ValueError`` is caught BY NAME -- a bare except would swallow what it exists to tolerate."""
    recorder = Recorder(root=tmp_path)
    recorder.pytest_configure(_Config(timeout=KeyError()))
    assert recorder.wall == 0.0


def test_the_recorder_writes_one_ledger_naming_its_selector_and_worker(tmp_path: Path) -> None:
    """The whole runner half, end to end, with no pytest in the loop."""
    recorder = Recorder(root=tmp_path)
    config = _Config(timeout=300, selector='not slow', worker='gw2')
    recorder.pytest_configure(config)
    recorder.pytest_runtest_logreport(_Report(nodeid='a::t', duration=3.0))
    written = recorder.pytest_sessionfinish(types.SimpleNamespace(config=config))

    assert written == ledger_path(tmp_path, worker='gw2')
    ledger = read(tmp_path)
    assert ledger.seconds == {'a::t': 3.0}
    assert ledger.selector == 'not slow'


def test_an_unselected_run_records_the_selector_as_all(tmp_path: Path) -> None:
    """``'all'`` and not ``''``: an empty selector reads as a run that selected nothing."""
    recorder = Recorder(root=tmp_path)
    config = _Config(timeout=300)
    recorder.pytest_runtest_logreport(_Report(nodeid='a::t', duration=1.0))
    recorder.pytest_sessionfinish(types.SimpleNamespace(config=config))
    assert read(tmp_path).selector == 'all'
