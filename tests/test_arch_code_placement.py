"""lab-commons holds itself to ``CODE-IN-CODE-ROOTS``, ``SCRATCH-IS-NEVER-COMMITTED`` and ``STRAY-FILE-REFUSED``.

The authoring repo of a rule may not be its worst adopter: this tree declares its placement in
``[tool.dev_lab.placement]`` exactly as every adopter does -- no extra roots, so the family map
alone -- and its scratch holds exactly what every adopter's may: one tracked README.
"""

from __future__ import annotations

from pathlib import Path

from dev_lab.dev.codeplace import declared_misplaced, declared_strays
from dev_lab.dev.scratch import assert_scratch_never_committed

_ROOT = Path(__file__).resolve().parents[1]


def test_no_code_file_lives_outside_a_code_root() -> None:
    found = declared_misplaced(_ROOT)
    assert not found, f'code outside the declared placement: {found[:10]}'


def test_no_untracked_file_sits_outside_a_stray_root() -> None:
    found = declared_strays(_ROOT)
    assert not found, f'stage it, move it to output/logs/<yy>/<mm>/<dd>/<kind>/, or to scratch/: {found[:10]}'


def test_scratch_tracks_only_its_readme() -> None:
    assert_scratch_never_committed(_ROOT)
