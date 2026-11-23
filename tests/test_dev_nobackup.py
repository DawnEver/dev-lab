"""NO-BACKUP-COPIES, the shell half: the deny row refuses every planted copy maker and permits its controls."""

from __future__ import annotations

import re

from dev_lab.dev._deny_nobackup_row import NO_BACKUP_COPIES
from dev_lab.dev._deny_rows import DENY_ROWS


def test_the_row_refuses_its_examples_and_permits_its_controls() -> None:
    pattern = re.compile(str(NO_BACKUP_COPIES['pattern']))
    assert [line for line in NO_BACKUP_COPIES['refuses'] if not pattern.search(str(line))] == []
    assert [line for line in NO_BACKUP_COPIES['permits'] if pattern.search(str(line))] == []


def test_the_row_is_registered() -> None:
    assert NO_BACKUP_COPIES in DENY_ROWS
