"""A row: a part (need-set) qualified by the one OS it runs on -- ``base@windows`` -- and the OS this box is.

A bare part is its own row and runs where its needs say; a qualified row runs only on its OS
(:mod:`dev_lab.dev.jobparts` spells them, :mod:`dev_lab.dev.localpart` refuses a row of another OS).
"""

from __future__ import annotations

import sys
from typing import Final

from lab_commons.compute.probe import OS_NAMES, os_name
from lab_commons.hpc.needsets import PART_NAME

__all__ = ['ROW_SEPARATOR', 'is_row', 'row_part', 'row_system', 'this_platform']

#: Joins a part to the OS a row of it runs on, off its own runner: ``base@windows`` (:mod:`dev_lab.dev.jobparts`).
ROW_SEPARATOR: Final = '@'


def row_part(row: str) -> str:
    """The part (need-set) a row produces: *row* less any ``@<os>``; a bare part is its own row."""
    return row.partition(ROW_SEPARATOR)[0]


def row_system(row: str) -> str:
    """The OS *row* must run on, ``''`` when it names none (a bare part runs where its needs say)."""
    return row.partition(ROW_SEPARATOR)[2]


def is_row(name: str) -> bool:
    """Whether *name* is a part, or a part qualified by one OS resource (:data:`ROW_SEPARATOR`)."""
    part, separator, system = name.partition(ROW_SEPARATOR)
    return bool(PART_NAME.match(part)) and (not separator or system in OS_NAMES.values())


def this_platform() -> str:
    """The OS resource THIS box is (:func:`lab_commons.compute.probe.os_name`)."""
    return os_name(sys.platform)
