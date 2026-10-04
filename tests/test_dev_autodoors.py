"""AUTO-MODE-RUNS-THE-DOORS: one table, two renderings, and no raw destructive verb in either."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from lab_commons.dev.autodoors import (
    CODEX_RULES_REL,
    DOOR_MODULES,
    claude_rows,
    codex_rules,
    main,
    promises_raw,
    script_doors,
)
from lab_commons.dev.famtests.visibility import plant_checkout

_GIT = shutil.which('git') or 'git'
_SCRIPTS = ('scripts/gate/runner.py', 'scripts/hooks/with-retry.sh')


def test_every_row_is_narrow_and_one_per_door() -> None:
    rows = claude_rows(_SCRIPTS)
    assert len(rows) == len(DOOR_MODULES) + len(_SCRIPTS)
    assert 'Bash(.venv/*/python* -m lab_commons.dev.branchset *)' in rows
    assert 'Bash(sh scripts/hooks/with-retry.sh *)' in rows
    assert not any('*' in row.removeprefix('Bash(.venv/*/python*').removesuffix(' *)') for row in rows)


def test_codex_and_claude_render_the_same_doors() -> None:
    text = codex_rules(_SCRIPTS)
    assert text.count('prefix_rule(') == len(claude_rows(_SCRIPTS))
    for module in DOOR_MODULES:
        assert f'"-m", "{module}"' in text
    assert '"sh", "scripts/hooks/with-retry.sh"' in text


def test_no_rendering_allows_a_raw_destructive_verb_and_the_scan_sees_one() -> None:
    body = '\n'.join(line for line in codex_rules(_SCRIPTS).splitlines() if not line.startswith('#'))
    assert promises_raw(' '.join(claude_rows(_SCRIPTS))) == ()
    assert promises_raw(body) == ()
    assert promises_raw('Bash(git push origin --delete x)') == ('--delete', 'git push')


@pytest.mark.skipif(shutil.which('codex') is None, reason='codex CLI not installed on this box')
def test_the_real_codex_engine_allows_a_door_and_not_a_raw_verb(tmp_path: Path) -> None:
    rules = tmp_path / 'doors.rules'
    rules.write_text(codex_rules(_SCRIPTS), encoding='utf-8')
    codex = shutil.which('codex') or 'codex'

    def decision(*argv: str) -> str:
        done = subprocess.run(
            [codex, 'execpolicy', 'check', '--rules', str(rules), *argv],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=False,
            timeout=120,
        )
        return done.stdout

    assert '"decision":"allow"' in decision('.venv/bin/python', '-m', 'lab_commons.dev.worktrees', '--prune')
    assert '"decision":"allow"' not in decision('git', 'push', 'origin', '--delete', 'x')


def test_script_doors_are_the_tracked_entry_points(tmp_path: Path) -> None:
    work = plant_checkout(tmp_path, trunk='main').work
    (work / 'scripts' / 'hooks').mkdir(parents=True)
    guard = "if __name__ == '__main__':\n    pass\n"
    (work / 'scripts' / 'door.py').write_text(guard, encoding='utf-8')
    (work / 'scripts' / 'helper.py').write_text('X = 1\n', encoding='utf-8')
    (work / 'scripts' / 'hooks' / 'with-retry.sh').write_text('#!/bin/sh\n', encoding='utf-8')
    (work / 'scripts' / 'untracked.py').write_text(guard, encoding='utf-8')
    subprocess.run([_GIT, 'add', 'scripts/door.py', 'scripts/helper.py', 'scripts/hooks'], cwd=work, check=True)
    assert script_doors(work, shell_doors=('scripts/hooks/with-retry.sh',)) == (
        'scripts/door.py',
        'scripts/hooks/with-retry.sh',
    )
    assert main(['--repo', str(work)]) == 1
    assert main(['--repo', str(work), '--write']) == 0
    assert (work / CODEX_RULES_REL).is_file()
    assert main(['--repo', str(work)]) == 0
    assert main(['--repo', str(work), '--shell-door', 'scripts/hooks/with-retry.sh']) == 1, 'a new door is stale'
