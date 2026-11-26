"""The rules registry's MACHINE rows -- pure DATA, the same row shape as ``_rule_rows.py``.

Every rule about what the machine's shared state may see from a run: the environment a verdict cites and the
one box ledger every run claims on.
"""

from __future__ import annotations

ROWS: tuple[tuple[str, str, tuple[str | tuple[str, str], ...]], ...] = (
    (
        'ENV-MUTATION-THROUGH-THE-DOOR',
        (
            'No verdict may cite an environment it did not run in, so a dependency mutation goes through the '
            'shared door and is decided by STATE (which target environment is mutated, and whether a verdict is in '
            'flight for THAT environment), never by matching command TEXT: a mutation DURING a run is PREVENTED '
            'by exclusion, one BETWEEN runs is DETECTED by the key and remedied by RETIRING the verdict anchors, '
            'each worktree owns its environment (agents bootstrap and sync their own through the door without '
            'human approval, never mutating main from a lane), the box ledger stays machine-wide independently of '
            'environment exclusion, and a repo declaring no verdict anchors has that gap RENDERED, never silently '
            'skipped.'
        ),
        ('tests/test_dev_dep.py', 'tests/test_dev_dep_target.py'),
    ),
    (
        'ONE-BOX-ONE-LOCK',
        (
            # Why: a claim inside a kernel limit is never idle-but-held and never exceeded; a waiter starting anyway
            # is the harm, and blocking forever is a crash rendered as a hang; a reused pid would make a dead holder
            # immortal.
            'Every run on a machine DECLARES its demand -- cores, memory, a wall and tool seats -- on the ONE '
            'machine-wide box ledger every repo and session reaches (lab_commons.box, never a lock named in one '
            'tree), is admitted by the one rule on the MEASURED room (free now, less what held claims have not '
            'taken yet, less its [reserve] margins), and runs INSIDE a kernel limit sized to that claim that kills '
            'it past its memory or wall; a waiter holds nothing and gives up at its own queue ceiling, refused '
            'naming the dimension short and every holder with its deadline; a recorded holder is identified by '
            'more than its pid; and nothing is reserved, lent or preempted (user ruling 2026-10-14), priority '
            'ordering but never claiming.'
        ),
        (
            'tests/test_box.py',
            'tests/test_box_run_enforced.py',
            'tests/test_liveness.py',
        ),
    ),
)
