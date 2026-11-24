"""LEDGER-WRITES-THROUGH-ITS-DOOR: both halves refuse a direct write onto a task file and nothing else."""

from __future__ import annotations

import contextlib
import io
import json
import re
from pathlib import Path

import pytest

from dev_lab.dev import codeplace, ledgerguard
from dev_lab.dev._deny_ledger_row import LEDGER_WRITES_THROUGH_ITS_DOOR as ROW


@pytest.mark.parametrize(
    'path',
    [
        '/srv/machine/repos/tasks/toolchain/TASK.md',
        'C:\\m\\repos\\tasks\\toolchain\\JOURNAL.md',
        'repos/tasks/archive/2026-11-23/toolchain/JOURNAL.md',
        '.claude/tasks/old/TASK.md',
    ],
)
def test_a_ledger_file_is_refused_naming_the_door(path: str) -> None:
    said = ledgerguard.refuse_write(Path(path))
    assert said is not None
    assert said.startswith(ledgerguard.RULE_ID)
    assert ledgerguard.DOOR in said


@pytest.mark.parametrize('path', ['docs/TASK.md', 'repos/tasks/t/NOTES.md', 'tasks/TASK.md', 'x/TASK.md.bak'])
def test_another_file_is_not_a_ledger_file(path: str) -> None:
    """PLANTED CONTROL: the same names outside the ledger shape pass."""
    assert ledgerguard.refuse_write(Path(path)) is None


def test_the_write_hook_denies_a_ledger_write() -> None:
    payload = {'tool_input': {'file_path': '/m/repos/tasks/t/JOURNAL.md'}, 'cwd': '/m'}
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        codeplace.main([], stdin=io.StringIO(json.dumps(payload)))
    answer = json.loads(out.getvalue())['hookSpecificOutput']
    assert answer['permissionDecision'] == 'deny'
    assert ledgerguard.RULE_ID in answer['permissionDecisionReason']


def test_the_shell_row_refuses_and_permits_its_examples() -> None:
    pattern = re.compile(str(ROW['pattern']))
    assert [c for c in ROW['refuses'] if not pattern.search(c)] == []
    assert [c for c in ROW['permits'] if pattern.search(c)] == []
