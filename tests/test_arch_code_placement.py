"""lab-commons holds itself to ``CODE-IN-CODE-ROOTS`` and ``SCRATCH-ARCHIVED-OR-PROMOTED``.

The authoring repo of a rule may not be its worst adopter: this tree's code lives under ``src/``
and ``tests/`` only, and its one-offs follow the same lifecycle as every adopter's.
"""

from __future__ import annotations

from pathlib import Path

from lab_commons.dev.codeplace import misplaced_code, overdue_scratch

_ROOT = Path(__file__).resolve().parents[1]

#: This repo's code roots: the package and its tests, plus the one-off and archive homes.
CODE_ROOTS = ('src/', 'tests/', 'scratch/', '.claude/memory/')
#: How long a one-off may wait in ``scratch/`` before it is archived or promoted.
SCRATCH_MAX_AGE_DAYS = 3.0

#: Directories this walk does not enter, and `pruned_paths` exists for exactly this: A WORKTREE IS
#: A REAL SECOND TREE with its own `src/`, and it is judged by the run that happens inside it. This
#: guard used to walk into them, so every open worktree was reported as code outside the code roots
#: -- a reading that says nothing about this tree and everything about which branches happen to be
#: checked out on this box. `test_dev_codeplace` already drives the parameter; this file, which is
#: the repo's own self-check, did not.
PRUNED = ('.claude/worktrees',)


def test_no_code_file_lives_outside_a_code_root() -> None:
    found = misplaced_code(_ROOT, code_roots=CODE_ROOTS, pruned_paths=PRUNED)
    assert not found, f'code outside {list(CODE_ROOTS)}: {found[:10]}'


def test_no_scratch_file_outlives_its_time() -> None:
    late = overdue_scratch(_ROOT / 'scratch', root=_ROOT, max_age_days=SCRATCH_MAX_AGE_DAYS)
    assert not late, f'archive or promote these one-offs: {late[:10]}'
