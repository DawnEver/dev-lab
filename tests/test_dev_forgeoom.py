"""A task Slurm killed OUT_OF_MEMORY teaches every file it ran the limit it died at, in the record every host folds."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

from dev_lab.dev.forgeoom import floor_record, oom_floors, raised
from dev_lab.dev.forgerunstate import Killed

_A, _B, _C = 'tests/a.py', 'tests/b.py', 'tests/c.py'


def test_an_oom_task_floors_every_file_of_its_items_at_its_ask_and_a_timeout_floors_none() -> None:
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
        '7_0': [{'ids': [f'{_A}::t1', f'{_A}::t2']}, {'ids': [f'{_B}::t']}],
        '7_1': [{'ids': [f'{_C}::t']}],
        '8_0': [{'ids': [f'{_B}::u']}],
    }
    assert oom_floors(jobs, items) == {_A: 1024.0, _B: 4096.0}


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
