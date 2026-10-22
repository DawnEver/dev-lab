"""The per-test CELL recorder (plan A1.1): a Record per process, one pytest mapping, flaky never overwrites."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from dev_lab.dev.test_outcomes import OUTCOMES_DIR_VAR, CellRecorder, RetiredOutcomes, read_cells
from lab_commons.outcomes import Status


def _report(nodeid: str, when: str, outcome: str, longrepr: object = None, **extra: object) -> SimpleNamespace:
    keywords = dict.fromkeys(extra.pop('marks', ()), 1)
    return SimpleNamespace(
        nodeid=nodeid, when=when, outcome=outcome, duration=0.1, longrepr=longrepr, keywords=keywords, **extra
    )


def _test(recorder: CellRecorder, nodeid: str, *phases: tuple[str, str, object]) -> None:
    """Feed one test's setup/call/teardown reports; a phase not given passed."""
    given = {when: (outcome, longrepr) for when, outcome, longrepr in phases}
    for when in ('setup', 'call', 'teardown'):
        outcome, longrepr = given.get(when, ('passed', None))
        recorder.pytest_runtest_logreport(_report(nodeid, when, outcome, longrepr))


def _words(directory: Path) -> dict[str, str]:
    cells, _ = read_cells(directory)
    return {node: one.word() for node, one in cells.items()}


def test_the_recorder_writes_one_cell_per_test_into_its_processes_record(tmp_path: Path) -> None:
    recorder = CellRecorder(tmp_path / 'cells.jsonl', frozenset({'femm'}))
    _test(recorder, 'a::passes')
    _test(recorder, 'a::fails', ('call', 'failed', 'E   assert 1 == 2'))
    _test(recorder, 'a::teardown_breaks', ('teardown', 'failed', 'E   RuntimeError: boom'))
    skipped = ('a.py', 3, 'Skipped: no femm')
    recorder.pytest_runtest_logreport(_report('a::no_femm', 'setup', 'skipped', skipped, marks=('femm',)))
    recorder.pytest_runtest_logreport(_report('a::no_femm', 'teardown', 'passed'))
    _test(recorder, 'a::expected', ('call', 'skipped', 'AssertionError'))
    assert _words(tmp_path) == {
        'a::passes': 'ok',
        'a::fails': 'rejected',
        'a::teardown_breaks': 'error',
        'a::no_femm': 'unavailable',
        'a::expected': 'rejected/expected-rejected',
    }
    cells, _ = read_cells(tmp_path)
    assert cells['a::no_femm'].why == 'no femm', 'a skip keeps its reason in its cell'
    lines = [json.loads(line) for line in (tmp_path / 'cells.jsonl').read_text().splitlines()]
    assert {line['kind'] for line in lines} == {'outcome'}, 'one outcome event per test, written at its teardown'


def test_a_test_decided_both_ways_in_one_run_is_flaky_never_overwritten(tmp_path: Path) -> None:
    """A single run's conclusion is DECIDED: the Record refuses the second decision and a flaky event says so."""
    recorder = CellRecorder(tmp_path / 'cells.jsonl')
    _test(recorder, 'a::rerun', ('call', 'failed', 'E   assert 0'))
    _test(recorder, 'a::rerun')  # a rerun plugin's second attempt
    cells, flaky = read_cells(tmp_path)
    assert flaky == {'a::rerun'}
    assert cells['a::rerun'].status is Status.REJECTED, 'the first decision stands'
    kinds = [json.loads(line)['kind'] for line in (tmp_path / 'cells.jsonl').read_text().splitlines()]
    assert kinds == ['outcome', 'flaky']


def test_two_processes_disagreeing_on_an_id_make_it_flaky_and_agreeing_ones_merge(tmp_path: Path) -> None:
    """The xdist controller and a worker both see a worker's reports: agreement is one cell, disagreement flaky."""
    for name, outcome in (('cells-gw0.jsonl', 'passed'), ('cells.jsonl', 'passed'), ('cells-gw1.jsonl', 'failed')):
        recorder = CellRecorder(tmp_path / name)
        _test(recorder, 'a::same')
        _test(recorder, 'a::split', ('call', outcome, 'E   x' if outcome == 'failed' else None))
    cells, flaky = read_cells(tmp_path)
    assert set(cells) == {'a::same', 'a::split'}
    assert flaky == {'a::split'}


def test_no_directory_reads_as_none_recorded(tmp_path: Path) -> None:
    assert read_cells(tmp_path / 'absent') == ({}, frozenset())


def test_a_directory_of_the_retired_word_files_is_refused_by_name(tmp_path: Path) -> None:
    """Regenerable: no dual-format reading, the verify re-runs."""
    (tmp_path / 'outcomes-gw0.json').write_text('{"a::t": "passed"}\n', encoding='utf-8')
    with pytest.raises(RetiredOutcomes, match=r'retired per-test word files \(outcomes-gw0\.json\)'):
        read_cells(tmp_path)


def test_the_recorder_is_a_hashable_plugin(tmp_path: Path) -> None:
    """Pytest >= 8.4 keeps registered plugins in a set; a value-equality dataclass is unhashable there."""
    recorder = CellRecorder(tmp_path / 'cells.jsonl')
    assert {recorder} == {recorder}
    assert len({recorder, CellRecorder(tmp_path / 'cells.jsonl')}) == 2


def test_a_real_pytest_run_maps_its_skips_by_the_declaring_marker(tmp_path: Path) -> None:
    """End to end through ``-p``: a resource-marked skip is UNAVAILABLE, a plain skip is refused by name."""
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.lab_commons.tests]\nresources = ["femm"]\n[tool.pytest.ini_options]\nmarkers = ["femm: x"]\n',
        encoding='utf-8',
    )
    (tmp_path / 'test_s.py').write_text(
        'import pytest\n\n'
        '@pytest.mark.femm\ndef test_needs_femm():\n    pytest.skip("no femm here")\n\n'
        '@pytest.mark.not_applicable\ndef test_posix_only():\n    pytest.skip("posix only")\n\n'
        'def test_undeclared():\n    pytest.skip("whatever")\n\n'
        '@pytest.mark.xfail(reason="issue 7", strict=True)\ndef test_known():\n    assert False\n',
        encoding='utf-8',
    )
    out = tmp_path / 'out'
    subprocess.run(
        [sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', '-p', 'dev_lab.dev.test_outcomes'],
        cwd=tmp_path,
        env={**os.environ, OUTCOMES_DIR_VAR: str(out)},
        capture_output=True,
        check=False,
    )
    assert _words(out) == {
        'test_s.py::test_needs_femm': 'unavailable',
        'test_s.py::test_posix_only': 'not_applicable',
        'test_s.py::test_undeclared': 'rejected',
        'test_s.py::test_known': 'rejected/expected-rejected',
    }
    cells, _ = read_cells(out)
    assert cells['test_s.py::test_undeclared'].why.startswith('XFAIL-NOT-SKIP'), 'PLANTED CONTROL: refused by name'
