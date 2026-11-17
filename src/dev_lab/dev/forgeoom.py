"""AN OOM-KILLED ONE-FILE TASK FLOORS ITS FILE AT THE LIMIT IT DIED AT -- in the record every host folds.

Measured 2026-10-20..27 (Ada, user1): 302 ``base`` tasks OUT_OF_MEMORY, ~10 per downstream run, the same
shape every run -- 1-2 GB tasks of multi-file items whose files' learned peaks were 0.5-0.8 GB. An item is ONE
pytest process over its files, so its memory is its combination's, not its heaviest file's; the run's retry
grows and bisects it, then the files re-measure alone or in smaller items, the growth is dropped
(:func:`lab_commons.hpc.gather.grown_after`) and a multi-file kill teaches no peak
(:meth:`lab_commons.compute.measured.Measured.learn`) -- so the NEXT run packs them together at the old ask and
dies the same way.

Here the kill is kept: the file of an OOM task that ran ONE file is floored at the task's ask (ungrown -- the plan's
``policy.safety`` multiplies it once, :func:`lab_commons.compute.measured.task_gb`), never lowering a known peak.
It goes into the run RECORD, because the learned table is a cache of the forge's records, each folded whole
(:func:`lab_commons.compute.learned.learn_record`): a floor kept only locally is lowered by that fold. A file
that later finishes un-killed re-measures and replaces it (:meth:`~lab_commons.compute.measured.Measured.learn`).

A MULTI-FILE TASK'S ASK IS NO FILE'S FLOOR. Measured 2026-11-09 (Ada): five downstream test files each learned an
identical 200181 MB -- one array task's ask credited to every file it ran -- and inflated every later base ask.
The ask bounds the files' COMBINED memory; which file held it is unknown, and a share is no measurement either
(memory is not additive across one process's files, and one heavy file is the common case). Such a kill floors
the id it cut (``id_peaks_mb``, :meth:`~lab_commons.compute.measured.Measured.learn`) and is bisected on retry
until a one-file task says.

A LONE ID PAST ITS GROWTH BUDGET IS TOLD, NOT RE-ASKED. The run grows a lone killed id at most twice
(:data:`lab_commons.hpc.run.OOM_ROUNDS` rounds, then its cell settles ``out_of_memory``); past that nothing asks
again, and :func:`budget_alarm` raises ONE ``run`` alarm about :data:`OOM_BUDGET` naming each such id and why.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from lab_commons.compute import learned
from lab_commons.hpc.testcells import TestCell
from lab_commons.outcomes import Status

from dev_lab.dev.forgealarm import RUN, Alarm
from dev_lab.dev.forgerunstate import Killed
from dev_lab.dev.forgestuck import remote_path

__all__ = [
    'OOM_BUDGET',
    'budget_alarm',
    'budget_spent',
    'floor_record',
    'learn_floors',
    'oom_floors',
    'raised',
    'task_files',
    'task_items',
]

#: The ``about`` of the ``run`` alarm a lone id past its memory-growth budget raises.
OOM_BUDGET: Final = 'oom-budget'


def oom_floors(jobs: Sequence[Killed], items: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, float]:
    """``{file: MB}`` -- each one-file OUT_OF_MEMORY task's file (*items* by task id) at its ask, the most."""
    floors: dict[str, float] = {}
    for job in jobs:
        if job.state != 'OUT_OF_MEMORY':
            continue
        files = task_files(items.get(job.job, ()))
        if len(files) == 1:
            (name,) = files
            floors[name] = max(floors.get(name, 0.0), float(job.asked_mb))
    return floors


def task_files(items: Sequence[Mapping[str, Any]]) -> set[str]:
    """The test files one task's *items* ran."""
    return {str(node).split('::', maxsplit=1)[0] for item in items for node in item.get('ids', ())}


def raised(peaks_mb: Mapping[str, float], floors: Mapping[str, float]) -> dict[str, float]:
    """The *floors* above the known *peaks_mb*: a floor never lowers a peak."""
    return {name: mb for name, mb in floors.items() if mb > float(peaks_mb.get(name, 0.0))}


def floor_record(path: Path, floors: Mapping[str, float]) -> None:
    """Raise the gzipped record at *path*'s ``peaks_mb`` to *floors*; nothing raised leaves it untouched."""
    record = json.loads(gzip.decompress(path.read_bytes()).decode('utf-8'))
    peaks = dict(record.get('peaks_mb', {}))
    up = raised(peaks, floors)
    if up:
        path.write_bytes(gzip.compress(json.dumps({**record, 'peaks_mb': {**peaks, **up}}).encode('utf-8')))


def learn_floors(repo: str, floors: Mapping[str, float], record: Path | None) -> None:
    """Raise *repo*'s learned peaks to *floors* here, and in *record* (when given) for every host's fold."""
    learned.learn_peaks(repo, raised(learned.learned(repo).get('peaks_mb', {}), floors))
    if record is not None:
        floor_record(record, floors)


def task_items(
    state: Mapping[str, Any], shell: Callable[[str, None], str], tasks: Sequence[str]
) -> dict[str, list[dict[str, Any]]]:
    """``{task id: its items}`` for array *tasks* (``7_3``) of *state*'s rounds, each from its round's manifest."""
    found: dict[str, list[dict[str, Any]]] = {}
    manifests: dict[str, dict[str, Any]] = {}
    for task in tasks:
        base, _, index = task.partition('_')
        for one in state['rounds']:
            if base in {str(job) for job in one.get('job_ids', ())} and index.isdigit() and one.get('run_dir'):
                run_dir = one['run_dir']
                if run_dir not in manifests:
                    manifests[run_dir] = json.loads(shell(f'cat {remote_path(run_dir)}/manifest.json', None))
                start, stop = manifests[run_dir]['shards'][int(index)]
                found[task] = manifests[run_dir]['items'][start:stop]
    return found


def budget_spent(path: Path) -> dict[str, str]:
    """``{id: why}`` -- each id the gzipped record at *path* settled ``out_of_memory``: its growth budget spent.

    An unreadable record names none: the alarm is advisory, and publishing reads the record and says why it cannot.
    """
    try:
        cells = json.loads(gzip.decompress(path.read_bytes()).decode('utf-8')).get('cells') or {}
    except (OSError, ValueError):
        return {}
    spent = {}
    for node, plain in cells.items():
        cell = TestCell.from_plain(plain)
        if cell.status is Status.OUT_OF_MEMORY:
            spent[node] = cell.why or cell.word()
    return spent


def budget_alarm(repo: str, sha: str, spent: Mapping[str, str]) -> Alarm | None:
    """ONE ``run`` alarm about :data:`OOM_BUDGET` naming every id of *spent* and why; ``None`` when none."""
    if not spent:
        return None
    lines = '\n'.join(f'- {node}: {why}' for node, why in sorted(spent.items()))
    body = (
        f'{len(spent)} test(s) of {sha[:12]} were killed for memory past their growth budget and are no longer '
        f're-asked:\n{lines}\nRemedy: cut the test memory, or split it; its ask grows no further.'
    )
    subject = f'{len(spent)} test(s) of {sha[:12]} out of memory past the growth budget'
    return Alarm(RUN, repo, subject, body, about=OOM_BUDGET)
