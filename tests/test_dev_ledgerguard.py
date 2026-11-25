"""LEDGER-WRITES-THROUGH-ITS-DOOR: both halves refuse a direct write onto a task file and nothing else."""

from __future__ import annotations

import contextlib
import io
import json
import re
from pathlib import Path

import pytest
from lab_commons.home import part

from dev_lab.dev import codeplace, ledgerguard
from dev_lab.dev._deny_ledger_row import LEDGER_WRITES_THROUGH_ITS_DOOR as ROW
from dev_lab.dev.taskledger import LEDGER_DIR
from dev_lab.dev.venvpath import running_interpreter


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
    assert ledgerguard.DOOR.replace('{python}', running_interpreter()) in said
    assert '{python}' not in said


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


@pytest.mark.parametrize('name', ['new-task/TASK.md', 'toolchain/NOTES.md', 'stray.txt', '.git/config'])
def test_any_file_tool_write_inside_the_ledger_directory_is_refused(name: str) -> None:
    """The guard KNOWS the ledger directory (the folded second guard): any file in it, not only the shape."""
    said = ledgerguard.refuse_write(ledgerguard.ledger_dir() / name)
    assert said is not None
    assert said.startswith(ledgerguard.RULE_ID)


def test_the_ledger_directory_is_the_one_the_task_door_resolves() -> None:

    assert ledgerguard.ledger_dir() == part('repos') / LEDGER_DIR


@pytest.mark.parametrize(
    'command',
    [
        'mkdir ~/m/repos/tasks/new-task',
        'mkdir -p "C:\\m\\repos\\tasks\\archive\\2026-11-24"',
        'New-Item -ItemType Directory C:\\m\\repos\\tasks\\x',
        'rm -rf ~/m/repos/tasks/toolchain',
        'rmdir /srv/m/repos/tasks/old',
        'Remove-Item -Recurse C:\\m\\repos\\tasks\\toolchain',
        'mv ~/m/repos/tasks/a ~/m/repos/tasks/archive/2026-11-24/a',
        'mv draft ~/m/repos/tasks/new',
        'Move-Item x C:\\m\\repos\\tasks\\y',
        'rm ~/m/repos/tasks',
    ],
)
def test_the_shell_row_refuses_mkdir_rm_mv_into_the_ledger(command: str) -> None:
    """PLANTED CONTROL for the directory half: mkdir, rm and mv into the ledger directory are refused."""
    assert re.search(str(ROW['pattern']), command), command


@pytest.mark.parametrize(
    'command',
    [
        'ls ~/m/repos/tasks/toolchain',
        'git -C ~/m/repos/tasks push',
        'mkdir -p output/logs/26/11/24/tasks',
        'rm -rf ~/m/repos/tasks-old',
        'mv a b',
        'python -m dev_lab.dev.task close toolchain',
    ],
)
def test_the_shell_row_permits_what_does_not_write_the_ledger(command: str) -> None:
    assert not re.search(str(ROW['pattern']), command), command


def test_the_shell_row_refuses_and_permits_its_examples() -> None:
    pattern = re.compile(str(ROW['pattern']))
    assert [c for c in ROW['refuses'] if not pattern.search(c)] == []
    assert [c for c in ROW['permits'] if pattern.search(c)] == []
