"""THE LOCAL-ADMISSION SCANNER, on a planted source and on this repo's own trees.

This repo IS the single source, so :mod:`lab_commons.dev.admission` is exempt -- and every other file
here, the famtest bodies included, must hold no copy of the rule.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest

from lab_commons.dev import floors
from lab_commons.dev.famtests import localadmission

ROOT: Final = Path(__file__).resolve().parents[1]
ROOTS: Final = (('src/lab_commons', '*.py'), ('tests', '*.py'))

#: The single source itself, and this scanner, whose planted control carries the shape as data.
EXEMPT: Final = ('src/lab_commons/dev/admission.py', 'src/lab_commons/dev/famtests/localadmission.py')

#: MEASURED 2026-10-04: 334 files over :data:`ROOTS`; set below the population.
FILE_FLOOR: Final = 300


def test_the_scanner_still_convicts() -> None:
    localadmission.assert_the_scanner_still_convicts()


def test_no_file_in_this_repo_keeps_a_local_admission_rule() -> None:
    scan = localadmission.take_scan(ROOT, roots=ROOTS, exempt=EXEMPT)
    localadmission.assert_no_local_admission(scan, floor=FILE_FLOOR)


def test_the_single_source_itself_would_convict_without_its_exemption() -> None:
    scan = localadmission.take_scan(ROOT, roots=(('src/lab_commons/dev', 'admission.py'),))
    with pytest.raises(localadmission.LocalAdmission):
        localadmission.assert_no_local_admission(scan, floor=1)


def test_a_walk_that_read_nothing_is_refused() -> None:
    with pytest.raises(floors.FloorUnmet):
        localadmission.assert_no_local_admission(localadmission.AdmissionScan(0, ()), floor=1)
