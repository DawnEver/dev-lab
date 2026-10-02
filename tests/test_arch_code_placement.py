"""lab-commons holds itself to ``CODE-IN-CODE-ROOTS`` and ``SCRATCH-ARCHIVED-OR-PROMOTED``.

The authoring repo of a rule may not be its worst adopter: this tree declares its placement in
``[tool.lab_commons.placement]`` exactly as every adopter does -- no extra roots, so the family map
alone -- and its one-offs follow the same lifecycle as every adopter's.
"""

from __future__ import annotations

from pathlib import Path

from lab_commons.dev.codeplace import declared_misplaced, overdue_scratch

_ROOT = Path(__file__).resolve().parents[1]

#: How long a one-off may wait in ``scratch/`` before it is archived or promoted.
SCRATCH_MAX_AGE_DAYS = 3.0


def test_no_code_file_lives_outside_a_code_root() -> None:
    found = declared_misplaced(_ROOT)
    assert not found, f'code outside the declared placement: {found[:10]}'


def test_no_scratch_file_outlives_its_time() -> None:
    late = overdue_scratch(_ROOT / 'scratch', root=_ROOT, max_age_days=SCRATCH_MAX_AGE_DAYS)
    assert not late, f'archive or promote these one-offs: {late[:10]}'
