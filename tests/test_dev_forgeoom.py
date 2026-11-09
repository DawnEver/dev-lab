"""A task Slurm killed OUT_OF_MEMORY teaches every file it ran the limit it died at, in the record every host folds."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

from lab_commons.hpc.testcells import TestCell
from lab_commons.outcomes import Cell, Reason, Status

from dev_lab.dev.forgealarm import RUN
from dev_lab.dev.forgeoom import OOM_BUDGET, budget_alarm, budget_spent, floor_record, oom_floors, raised
from dev_lab.dev.forgerunstate import Killed

_A, _B, _C = 'tests/a.py', 'tests/b.py', 'tests/c.py'


def test_a_one_file_oom_task_floors_its_file_at_its_ask_and_a_timeout_floors_none() -> None:
    """Ada 2026-10-27: every run re-asked 1 GB for multi-file items whose last run died at 1 GB.

    The limit is a floor, ungrown (the next plan multiplies it by its safety once). PLANTED CONTROL: the
    TIMEOUT task's file is not floored -- its wall, not its memory, killed it.
    """
    jobs = [
        Killed('7_0', 'OUT_OF_MEMORY', 1024, 1100, 3600, 900),
        Killed('7_1', 'TIMEOUT', 2048, 500, 3600, 3602),
        Killed('8_0', 'OUT_OF_MEMORY', 4096, 4200, 3600, 60),
    ]
    items = {
        '7_0': [{'ids': [f'{_A}::t1']}, {'ids': [f'{_B}::t']}],
        '7_1': [{'ids': [f'{_C}::t']}],
        '8_0': [{'ids': [f'{_B}::u']}],
    }
    assert oom_floors(jobs, items) == {_B: 4096.0}


def test_a_multi_file_oom_task_floors_none_of_its_files() -> None:
    """Ada 2026-11-09: five files each learned 200181 MB, one array task's ask credited to every file it ran.

    A task's ask is the memory of ALL its files together, so it says nothing of any one file; only a task that
    ran ONE file measured that file alone. PLANTED CONTROL: the one-file task still floors its file.
    """
    jobs = [
        Killed('9_0', 'OUT_OF_MEMORY', 200181, 200000, 3600, 900),
        Killed('9_1', 'OUT_OF_MEMORY', 2048, 2000, 60, 30),
    ]
    items = {
        '9_0': [{'ids': [f'{_A}::t1', f'{_B}::t2']}],
        '9_1': [{'ids': [f'{_C}::t1']}, {'ids': [f'{_C}::t2']}],
    }
    assert oom_floors(jobs, items) == {_C: 2048.0}


def test_a_floor_only_raises_a_known_peak() -> None:
    """A file already known heavier keeps its peak; only the floors above what is known are returned."""
    assert raised({_A: 2000.0, _B: 500.0}, {_A: 1024.0, _B: 1024.0, _C: 1024.0}) == {_B: 1024.0, _C: 1024.0}


def test_the_record_carries_the_floor_so_its_fold_does_not_lower_it(tmp_path: Path) -> None:
    """The record is folded WHOLE into every host's table; a floor kept only locally is lowered by that fold."""
    path = tmp_path / 'run-a-base-1.json.gz'
    path.write_bytes(gzip.compress(json.dumps({'sha': 'a', 'peaks_mb': {_A: 700.0, _B: 3000.0}}).encode()))
    floor_record(path, {_A: 1024.0, _B: 1024.0})
    record = json.loads(gzip.decompress(path.read_bytes()))
    assert record == {'sha': 'a', 'peaks_mb': {_A: 1024.0, _B: 3000.0}}


def test_an_id_past_its_growth_budget_raises_one_named_run_alarm(tmp_path: Path) -> None:
    """RETRY BUDGET: a lone id grows at most twice a run (lab_commons OOM_ROUNDS), then settles OUT_OF_MEMORY.

    Nothing more is asked for it; a human is told once, by a ``run`` alarm about ``oom-budget`` naming each
    id and why. PLANTED CONTROL: a record with no such cell raises nothing.
    """
    why = Reason('out_of_memory', 'killed for memory alone in 3 rounds')
    cells = {
        f'{_A}::t': TestCell(Cell(Status.OUT_OF_MEMORY, reason=why)).to_plain(),
        f'{_B}::t': TestCell(Cell(Status.OK)).to_plain(),
    }
    path = tmp_path / 'run.json.gz'
    path.write_bytes(gzip.compress(json.dumps({'cells': cells}).encode('utf-8')))
    spent = budget_spent(path)
    assert set(spent) == {f'{_A}::t'}
    alarm = budget_alarm('https://g/r.git', 'a' * 40, spent)
    assert alarm is not None
    assert (alarm.kind, alarm.about) == (RUN, OOM_BUDGET)
    assert f'{_A}::t' in alarm.body
    assert 'alone in 3 rounds' in alarm.body
    assert budget_alarm('https://g/r.git', 'a' * 40, {}) is None
    assert budget_spent(tmp_path / 'gone.json.gz') == {}, 'an unreadable record names none'
