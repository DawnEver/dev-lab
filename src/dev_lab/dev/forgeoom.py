"""AN OOM-KILLED TASK FLOORS EVERY FILE IT RAN AT THE LIMIT IT DIED AT -- in the record every host folds.

Measured 2026-10-20..27 (Ada, user1): 302 ``base`` tasks OUT_OF_MEMORY, ~10 per downstream run, the same
shape every run -- 1-2 GB tasks of multi-file items whose files' learned peaks were 0.5-0.8 GB. An item is ONE
pytest process over its files, so its memory is its combination's, not its heaviest file's; the run's retry
grows and bisects it, then the files re-measure alone or in smaller items, the growth is dropped
(:func:`lab_commons.hpc.gather.grown_after`) and a multi-file kill teaches no peak
(:meth:`lab_commons.compute.measured.Measured.learn`) -- so the NEXT run packs them together at the old ask and
dies the same way.

Here the kill is kept: each file of an OOM task's items is floored at the task's ask (ungrown -- the plan's
``policy.safety`` multiplies it once, :func:`lab_commons.compute.measured.task_gb`), never lowering a known peak.
It goes into the run RECORD, because the learned table is a cache of the forge's records, each folded whole
(:func:`lab_commons.compute.learned.learn_record`): a floor kept only locally is lowered by that fold. A file
that later finishes un-killed re-measures and replaces it (:meth:`~lab_commons.compute.measured.Measured.learn`).
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from lab_commons.compute import learned

from dev_lab.dev.forgerunstate import Killed
from dev_lab.dev.forgestuck import remote_path

__all__ = ['floor_record', 'learn_floors', 'oom_floors', 'raised', 'task_items']


def oom_floors(jobs: Sequence[Killed], items: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, float]:
    """``{file: MB}`` -- each file of an OUT_OF_MEMORY task's *items* (by task id) at that task's ask, the most."""
    floors: dict[str, float] = {}
    for job in jobs:
        if job.state != 'OUT_OF_MEMORY':
            continue
        for item in items.get(job.job, ()):
            for node in item.get('ids', ()):
                name = str(node).split('::', maxsplit=1)[0]
                floors[name] = max(floors.get(name, 0.0), float(job.asked_mb))
    return floors


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
