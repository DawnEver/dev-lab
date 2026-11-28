"""THE STALL WATCH -- which RUNNING forge tasks of an account stopped progressing, read through its shell.

Split from :mod:`dev_lab.dev.forgeslurm` at the module-size band (2026-11-28): this is the READ, and
:meth:`dev_lab.dev.forgeslurm.SlurmCluster.stalled` cancels what it returns. The bound is the task's OWN
manifest: the per-test walls the item runner kills at (:class:`lab_commons.hpc.builds.ItemWall`), times
:data:`STALL_MULTIPLE` (Ada 2026-10-24..26: eight tasks ran 34-41 h on one hung test each).
"""

from __future__ import annotations

import contextlib
import json
import re
from collections.abc import Callable
from typing import Any, Final, cast

from dev_lab.dev.forgerunstate import Stalled
from dev_lab.dev.forgestuck import parse_duration, remote_path

__all__ = ['FORGE_JOB', 'STALL_MULTIPLE', 'stall_of', 'stalled_tasks']

#: A forge job's name (:func:`lab_commons.hpc.run.job_name`, and the schema-1 ``run-<sha12>``).
FORGE_JOB: Final = re.compile(r'run-[0-9a-f]{12}(-.+)?')
#: How many times its per-test walls a RUNNING task may go before it is STALLED: its round's stream silent past
#: this times its LONGEST wall, or the task running past this times the SUM of its walls. The item runner
#: (:mod:`lab_commons.hpc.pytest_item`) writes a line at every test's start and end and kills any test at its
#: wall, collection included, so a runner that works never comes near ONE times either; the second factor is
#: headroom for the poll, the kill, a pytest relaunch and two clocks, never a second chance for the test.
STALL_MULTIPLE: Final = 2.0
#: A login-node shell: one command and optional stdin in, its stdout out (:data:`lab_commons.hpc.cluster.Runner`).
type Shell = Callable[[str, str | None], str]
#: Every RUNNING task of the account: its id, name, elapsed time and work dir (the round's run dir), and the clock.
_RUNNING: Final = "date +%s; squeue -h --me -t RUNNING -o '%i|%j|%M|%Z'"


def stall_of(items: list[dict[str, Any]], *, idle_s: float, elapsed_s: float) -> str:
    """Why a task running *items* is stalled -- ``''`` when it is not, or when any of its ids declares no wall.

    *idle_s* is how long its round's stream has taken no line, *elapsed_s* how long it has run.
    """
    walls = [item.get('walls', {}).get(node) for item in items for node in item.get('ids', ())]
    if not walls or None in walls:
        return ''
    longest, total = max(walls), sum(walls)
    if idle_s > STALL_MULTIPLE * longest:
        return (
            f'its stream took no line for {idle_s / 60:.0f} min, past {STALL_MULTIPLE:g} x its longest test wall '
            f'({longest / 60:.0f} min)'
        )
    if elapsed_s > STALL_MULTIPLE * total:
        ran, bound = elapsed_s / 60, total / 60
        return f"it ran {ran:.0f} min, past {STALL_MULTIPLE:g} x the sum of its tests' walls ({bound:.0f} min)"
    return ''


def _last_started(text: str, items: set[object]) -> str:
    """The id the last ``start`` line of one of *items* names; ``''`` when none started."""
    last = ''
    for raw in text.splitlines():
        with contextlib.suppress(json.JSONDecodeError):
            line: object = json.loads(raw)
            if isinstance(line, dict):
                entry = cast('dict[str, object]', line)  # a JSON object's keys are strings
                if entry.get('item') in items and 'start' in entry:
                    last = str(entry['start'])
    return last


def stalled_tasks(shell: Shell) -> list[Stalled]:
    """Every RUNNING forge task of *shell*'s account past its stall bound (:func:`stall_of`), in queue order.

    A task's run dir is its Slurm work dir, so its manifest -- its items, their walls and stream -- is read
    from the task itself, never from a run file that may be gone. A task of a manifest without walls is
    never judged: nothing says what its tests may take. Nothing is cancelled here.
    """
    lines = shell(_RUNNING, None).splitlines()
    now = float(lines[0])
    manifests: dict[str, dict[str, Any]] = {}
    found: list[Stalled] = []
    for row in lines[1:]:
        job_id, name, elapsed, run_dir = row.split('|', 3)
        index = job_id.partition('_')[2]
        if not FORGE_JOB.fullmatch(name) or not index.isdigit():
            continue
        if run_dir not in manifests:
            manifests[run_dir] = json.loads(shell(f'cat {remote_path(run_dir)}/manifest.json', None))
        start, stop = manifests[run_dir]['shards'][int(index)]
        items = manifests[run_dir]['items'][start:stop]
        tree = run_dir.rsplit('/', 2)[0]  # <tree>/.lab-hpc/<run>
        streams = ' '.join(sorted({remote_path(f'{tree}/{item["stream"]}') for item in items}))
        stamps = [float(w) for w in shell(f'stat -c %Y {streams} 2>/dev/null || true', None).split() if w.isdigit()]
        elapsed_s = parse_duration(elapsed)
        idle_s = now - max(stamps) if stamps else elapsed_s
        if why := stall_of(items, idle_s=idle_s, elapsed_s=elapsed_s):
            started = shell(f'grep -hF \'"start"\' {streams} 2>/dev/null || true', None)
            last = _last_started(started, {item.get('item') for item in items})
            found.append(Stalled(job_id, name, tree.rsplit('/', 1)[-1], last, why))
    return found
