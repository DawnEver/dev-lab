"""THE INSTALL-DOOR CENSUS, pure DATA -- one row per door of THIS repo, plus the one it SHARES.

The machinery is `doorcensus.py` and the seam is the one `test_arch_registry_data_is_separate.py`
names for `_rule_rows.py`: a table edited through the module that checks it drifts away from what it
describes, because the same edit that adds a row can relax the check that would have refused it and
the diff looks like one change. Nothing here computes; the readers are all one module over.

THE KIT'S OWN DOORS ONLY. Every other repo declares its doors -- with its own name and its own
paths -- in its own tests and calls :func:`lab_commons.dev.doorcensus.assert_census` over its own
checkout. A table here naming a consumer's files was a fact about another repo stored in this one,
and it went stale against the real tree the day a path was renamed under it.

Every number here is re-derived by `assert_census` from THIS repo's WORKING TREE, so a row that stops
being true REDS rather than ageing quietly into prose.
"""

from __future__ import annotations

from lab_commons.dev.doorcensus import DoorRow, SharedDoor

__all__ = [
    'DOORS',
    'DOOR_FLOOR',
    'REPO_FLOOR',
    'SHARED',
]

#: One row per repo per door file. ``commands`` and ``deliveries`` are compared by EQUALITY, never as
#: a floor: a floor is ``declared <= live`` and is satisfied by every shorter declaration, which is
#: exactly how ``lab-commons`` recorded 9 while delivering 16, and a consumer 28 while delivering
#: 30, both green.
DOORS: tuple[DoorRow, ...] = (
    DoorRow(
        repo='lab-commons',
        path='Makefile',
        commands=14,
        deliveries=frozenset({'INERT'}),
        why=(
            'The kit declares no floating requirement -- it IS the kit -- so every command here is '
            'INERT by the SUBJECT being absent rather than by the commands being safe. This row is '
            'the one that acquires teeth on the day a bare `git+` requirement lands in this '
            'manifest, which is why the guard is pointed here rather than waived: a waiver would '
            'have had to be noticed and removed by hand. 14 since 2026-10-01: `install-dev` now also '
            'runs `hook_install --install`, a door added, not a delivery changed.'
        ),
    ),
    DoorRow(
        repo='lab-commons',
        path='.github/workflows/ci.yml',
        commands=0,
        deliveries=frozenset(),
        why=(
            'ZERO IS THE MEASUREMENT, not a miss. This file is a thin caller: its only job is `uses: '
            './.github/workflows/python-verify.yml`, and every command of substance is in that '
            'reusable workflow. A repo-level floor cannot tell a file that legitimately holds no '
            'command from a file the scan stopped reading, and this row is where that distinction '
            'is recorded -- if a `run:` step is ever inlined here, the count moves and this reds.'
        ),
    ),
    DoorRow(
        repo='lab-commons',
        path='.github/workflows/python-verify.yml',
        commands=3,
        deliveries=frozenset({'INERT'}),
        why=(
            'THE ROW THAT LIES WHEN READ ALONE, and the SHARED entry below is its other half. All '
            'three commands here consume a lock, and they read INERT only because this repo declares '
            'no floating requirement. This workflow RUNS in every caller checkout, where the kit IS '
            'floating -- so the honest classification is the SharedDoor row, and this one exists to '
            'pin that the file still holds exactly those three commands.'
        ),
    ),
)

#: A door stored in this repo and RUN in its callers, classified against what every caller floats.
#: There is one today, and finding it is what this table was added for.
SHARED: tuple[SharedDoor, ...] = (
    SharedDoor(
        repo='lab-commons',
        path='.github/workflows/python-verify.yml',
        caller_floats=('lab-commons',),
        deliveries=frozenset({'INERT', 'REVERTS'}),
        why=(
            'THE FINDING. This reusable workflow holds `uv sync --python X $extra_flags` and two '
            '`uv run make ...` steps, and all three are lock-consuming. Scanned at home against '
            'lab-commons` empty floating set they classify INERT; scanned against a caller`s '
            '(`lab-commons`, which every caller floats by calling it) they are REVERTS, and no caller '
            'could see the file because it is not in its tree. Two of the three were remedied with '
            '`--no-sync`, which is also the correct fix on its own terms: `uv run` with no `--extra` '
            're-syncs WITHOUT the extras the preceding step just installed, and that is the prune '
            'shape measured taking one environment from 113 distributions to 30. The remaining '
            '`uv sync` is survivable only because no `uv.lock` is ever checked out, which '
            '`assert_no_tracked_lock` asserts rather than assumes.'
        ),
    ),
)

#: How few repos this census must read. It reads exactly one -- the repo it runs in -- and a run
#: that read none has measured nothing.
REPO_FLOOR: int = 1

#: How few rows it may read. MEASURED 2026-10-02 at 3 (the kit's three door files); set at that
#: count because a table this small has no slack to give -- one row lost is one door unwatched.
DOOR_FLOOR: int = 3
