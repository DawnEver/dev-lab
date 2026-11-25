"""The per-test CELL recorder (plan A1.1): a Record per process, one pytest mapping, flaky never overwrites."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import IO

import pytest
from lab_commons.outcomes import Conclusion, Status

from dev_lab.dev import verifysteps
from dev_lab.dev.test_outcomes import (
    DEAD_WORKER_KIND,
    FAILURE_NAMES,
    OUTCOMES_DIR_VAR,
    CellRecorder,
    RetiredOutcomes,
    read_cells,
    recorded_failures,
)


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


def test_real_stage_directories_preserve_full_ids_and_union_with_the_existing_record_codec(tmp_path: Path) -> None:
    identities = ('tests/a.py::test_a[white space - [a]]', 'tests/a.py::test_a[white space - [b]]')
    for stage, node in zip(('parallel', 'serial'), identities, strict=True):
        recorder = CellRecorder(tmp_path / stage / 'cells-gw0.jsonl')
        _test(recorder, node, ('call', 'failed', 'E   assert False'))
    cells, flaky = read_cells(tmp_path)
    assert set(cells) == set(identities)
    assert all(one.red for one in cells.values())
    assert flaky == frozenset()


def test_a_same_identity_disagreeing_across_stages_is_still_flaky(tmp_path: Path) -> None:
    node = 'tests/a.py::test_a[one identity - [space]]'
    _test(CellRecorder(tmp_path / 'parallel' / 'cells.jsonl'), node)
    _test(CellRecorder(tmp_path / 'serial' / 'cells.jsonl'), node, ('call', 'failed', 'E   assert False'))
    cells, flaky = read_cells(tmp_path)
    assert set(cells) == {node}
    assert flaky == {node}


@pytest.mark.parametrize('unexpected', ['other-stage', 'root-flat'])
def test_mixed_or_unknown_record_layout_is_refused_instead_of_silently_ignoring_a_stage(
    tmp_path: Path, unexpected: str
) -> None:
    _test(CellRecorder(tmp_path / 'parallel' / 'cells.jsonl'), 'tests/a.py::test_a')
    path = tmp_path / 'cells.jsonl' if unexpected == 'root-flat' else tmp_path / unexpected / 'cells.jsonl'
    _test(CellRecorder(path), 'tests/a.py::test_hidden')
    with pytest.raises(ValueError, match=r'stage|layout|mixed'):
        read_cells(tmp_path)


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


def _crash(nodeid: str, worker: str = 'gw0') -> SimpleNamespace:
    """The ONE report xdist files for a test whose worker died (``xdist/dsession.py::handle_crashitem``)."""
    return _report(nodeid, '???', 'failed', f'worker {worker!r} crashed while running {nodeid!r}')


def test_a_test_whose_worker_died_is_recorded_when_the_scheduler_files_it(tmp_path: Path) -> None:
    """A test whose worker died is a cell at once: no teardown will ever come to write it.

    MEASURED 2026-11-21, ci.yml run 44962572687, tests/base@windows: two tests each held a worker to the
    600 s ceiling, the 3600 s wall then cut the session before its summary, and NOTHING named either.
    A dead worker's test gets one report, phase ``???``, and no teardown ever follows it: a recorder that
    writes only at teardown drops exactly the test a cut run most needs named.
    """
    recorder = CellRecorder(tmp_path / 'cells.jsonl')
    recorder.pytest_runtest_logreport(_crash('a::wedged'))
    cells, flaky = read_cells(tmp_path)
    assert set(cells) == {'a::wedged'}
    assert cells['a::wedged'].status is Status.ERROR, 'no answer about the test: its process is gone'
    assert 'crashed while running' in cells['a::wedged'].why
    assert cells['a::wedged'].cell.reason.kind == DEAD_WORKER_KIND, 'the phase spelling ??? is no reason kind'
    assert flaky == frozenset()


def test_planted_control_a_live_tests_failed_phase_still_waits_for_its_teardown(tmp_path: Path) -> None:
    recorder = CellRecorder(tmp_path / 'cells.jsonl')
    recorder.pytest_runtest_logreport(_report('a::fails', 'setup', 'passed'))
    recorder.pytest_runtest_logreport(_report('a::fails', 'call', 'failed', 'E   assert 0'))
    assert read_cells(tmp_path) == ({}, frozenset()), 'its teardown may yet be the worse phase'


def test_the_failures_a_cut_run_recorded_are_named_dead_workers_first(tmp_path: Path) -> None:
    recorder = CellRecorder(tmp_path / 'parallel' / 'cells.jsonl')
    _test(recorder, 'a::passes')
    for index in range(FAILURE_NAMES + 2):
        _test(recorder, f'a::fails[{index:02}]', ('call', 'failed', 'E   assert 0'))
    recorder.pytest_runtest_logreport(_crash('z::wedged'))
    (said,) = recorded_failures(tmp_path)
    assert said.index('z::wedged') < said.index('a::fails[00]'), 'the test that held the worker leads'
    assert f'{FAILURE_NAMES + 3} test(s) recorded failing' in said
    assert 'a::fails[00]' in said
    assert f'a::fails[{FAILURE_NAMES + 1:02}]' not in said, 'the list is bounded'
    assert '3 more' in said
    assert tmp_path.as_posix() in said, 'and the rest are where the reason says'
    assert 'a::passes' not in said


def test_planted_control_a_run_that_recorded_no_failure_adds_no_reason(tmp_path: Path) -> None:
    recorder = CellRecorder(tmp_path / 'parallel' / 'cells.jsonl', frozenset({'femm'}))
    _test(recorder, 'a::passes')
    recorder.pytest_runtest_logreport(
        _report('a::no_femm', 'setup', 'skipped', ('a.py', 3, 'Skipped: x'), marks=('femm',))
    )
    recorder.pytest_runtest_logreport(_report('a::no_femm', 'teardown', 'passed'))
    assert recorded_failures(tmp_path) == ()
    assert recorded_failures(tmp_path / 'absent') == ()


def test_a_cut_verify_names_what_it_recorded_failing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Through the real ``run_verify``: the wall cut the session, so its only named failures are the cells."""
    (tmp_path / 'pyproject.toml').write_text('[tool.dev_lab.parts]\noutput = "out/logs"\n', 'utf-8')
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'tests' / 'test_one.py').write_text('def test_one():\n    pass\n', 'utf-8')

    def cut(_command: list[str], *, handle: IO[str], extra_env: dict[str, str], **_where: object) -> int:
        recorder = CellRecorder(Path(extra_env[OUTCOMES_DIR_VAR]) / 'cells.jsonl')
        _test(recorder, 'tests/test_one.py::test_red', ('call', 'failed', 'E   assert 0'))
        recorder.pytest_runtest_logreport(_crash('tests/test_one.py::test_wedged'))
        handle.write('.F[gw0] node down: Not properly terminated\nF\nreplacing crashed worker gw0\n')
        return 4294967295  # what the box returns for a pytest it killed at the wall, on Windows

    monkeypatch.setattr(verifysteps, 'LINT_STEPS', ())
    monkeypatch.setattr(verifysteps, 'boxed', lambda _root, argv, **_k: (argv, None))
    monkeypatch.setattr(verifysteps, '_tee', cut)
    verdict = verifysteps.run_verify(tmp_path, ('tests/test_one.py',), hooks=False)
    assert verdict.result.outcome is Conclusion.INCONCLUSIVE, verdict.result
    said = str(verdict.result)
    assert 'tests/test_one.py::test_wedged' in said
    assert 'tests/test_one.py::test_red' in said


def test_planted_control_a_settled_verify_adds_no_reason(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / 'pyproject.toml').write_text('[tool.dev_lab.parts]\noutput = "out/logs"\n', 'utf-8')
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'tests' / 'test_one.py').write_text('def test_one():\n    assert 0\n', 'utf-8')

    def ran(_command: list[str], *, handle: IO[str], extra_env: dict[str, str], **_where: object) -> int:
        recorder = CellRecorder(Path(extra_env[OUTCOMES_DIR_VAR]) / 'cells.jsonl')
        _test(recorder, 'tests/test_one.py::test_one', ('call', 'failed', 'E   assert 0'))
        handle.write('FAILED tests/test_one.py::test_one - assert 0\n1 failed in 0.1s\n')
        return 1

    monkeypatch.setattr(verifysteps, 'LINT_STEPS', ())
    monkeypatch.setattr(verifysteps, 'boxed', lambda _root, argv, **_k: (argv, None))
    monkeypatch.setattr(verifysteps, '_tee', ran)
    verdict = verifysteps.run_verify(tmp_path, ('tests/test_one.py',), hooks=False)
    assert verdict.result.outcome is Conclusion.FAIL, verdict.result
    assert verdict.result.failures == ('tests/test_one.py::test_one',)
    assert 'recorded failing' not in str(verdict.result)


def test_a_real_worker_death_is_a_cell_and_the_session_still_ends_on_its_own(tmp_path: Path) -> None:
    """End to end under xdist: the scheduler's own report reaches the recorder, and recording it breaks nothing."""
    (tmp_path / 'test_d.py').write_text(
        'import os\n\ndef test_dies():\n    os._exit(1)\n\ndef test_lives():\n    pass\n', encoding='utf-8'
    )
    out = tmp_path / 'out'
    done = subprocess.run(
        [sys.executable, '-m', 'pytest', '-q', '-n', '1', '-p', 'no:cacheprovider', '-p', 'dev_lab.dev.test_outcomes'],
        cwd=tmp_path,
        env={**os.environ, OUTCOMES_DIR_VAR: str(out)},
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=False,
        timeout=300,
    )
    assert 'INTERNALERROR' not in done.stdout + done.stderr, done.stdout + done.stderr
    assert done.returncode == 1, done.stdout + done.stderr
    cells, flaky = read_cells(out)
    assert _words(out) == {'test_d.py::test_dies': 'error', 'test_d.py::test_lives': 'ok'}
    assert cells['test_d.py::test_dies'].cell.reason.kind == DEAD_WORKER_KIND
    assert flaky == frozenset()
