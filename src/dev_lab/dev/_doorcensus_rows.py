"""THE INSTALL-DOOR CENSUS, pure DATA -- one row per door of THIS repo.

The machinery is `doorcensus.py` and the seam is the one `test_arch_registry_data_is_separate.py`
names for `_rule_rows.py`: a table edited through the module that checks it drifts away from what it
describes, because the same edit that adds a row can relax the check that would have refused it and
the diff looks like one change. Nothing here computes; the readers are all one module over.

THE KIT'S OWN DOORS ONLY. Every other repo declares its doors -- with its own name and its own
paths -- in its own tests and calls :func:`dev_lab.dev.doorcensus.assert_census` over its own
checkout. A table here naming a consumer's files was a fact about another repo stored in this one,
and it went stale against the real tree the day a path was renamed under it.

Every number here is re-derived by `assert_census` from THIS repo's WORKING TREE, so a row that stops
being true REDS rather than ageing quietly into prose.
"""

from __future__ import annotations

from dev_lab.dev.doorcensus import DoorRow

__all__ = [
    'DOORS',
    'DOOR_FLOOR',
    'REPO_FLOOR',
]

#: One row per repo per door file. ``commands`` and ``deliveries`` are compared by EQUALITY, never as
#: a floor: a floor is ``declared <= live`` and is satisfied by every shorter declaration, which is
#: exactly how ``lab-commons`` recorded 9 while delivering 16, and a consumer 28 while delivering
#: 30, both green.
DOORS: tuple[DoorRow, ...] = (
    DoorRow(
        repo='dev-lab',
        path='Makefile',
        commands=14,
        deliveries=frozenset({'INERT', 'RESOLVES'}),
        why=(
            'The row acquired its teeth on 2026-11-03, as it said it would: the `review` group declares '
            'ai-lab as a bare `git+` requirement (c1bb741f, the lock names the commit), so the subject is '
            'no longer absent. RE-MEASURED then: the two `uv pip install -e` doors (`install`, '
            '`install-dev`) RESOLVE -- they re-resolve rather than serve a stale local resolution -- and '
            'the other twelve stay INERT; nothing reads UNLOCKED. 14 since 2026-10-01: `install-dev` '
            'also runs `hook_install --install`, a door added, not a delivery changed.'
        ),
    ),
)

#: How few repos this census must read. It reads exactly one -- the repo it runs in -- and a run
#: that read none has measured nothing.
REPO_FLOOR: int = 1

#: How few rows it may read: the Makefile, the one door file left once the reusable python-verify.yml
#: retired (2026-10-29); a table this small has no slack to give -- one row lost is one door unwatched.
DOOR_FLOOR: int = 1
