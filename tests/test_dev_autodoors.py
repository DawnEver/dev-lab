"""AUTO-MODE-RUNS-THE-DOORS: one table, two renderings, and no raw destructive verb in either."""

from __future__ import annotations

import shutil
import subprocess
from fnmatch import fnmatchcase
from pathlib import Path

import pytest

from lab_commons.dev.autodoors import (
    CODEX_RULES_REL,
    DOOR_MODULES,
    claude_rows,
    codex_rules,
    doors,
    main,
    promises_raw,
    script_doors,
)
from lab_commons.dev.famtests.visibility import plant_checkout

_GIT = shutil.which('git') or 'git'
_SCRIPTS = ('scripts/gate/runner.py', 'scripts/hooks/with-retry.sh')


@pytest.mark.parametrize(
    'interpreter',
    [
        '.venv/Scripts/python.exe',
        './.venv/bin/python',
        '.claude/worktrees/lane/.venv/Scripts/python.exe',
        '.claude/worktrees/lane/.venv/bin/python',
    ],
)
def test_dependency_doors_admit_each_checkout_interpreter_without_an_installer_wildcard(interpreter: str) -> None:
    """THE LAUNCHER MAY BE ANOTHER CHECKOUT'S INTERPRETER, and the row says which directory may vary.

    The spelling that varies is a WORKTREE's, so it is anchored on the one directory that rule
    WORKTREES-STAY-INSIDE pins (``.claude/worktrees/``) and wildcards only the worktree's name --
    never the whole invocation prefix, which is the shape every consumer's allow guard refuses.
    """
    rows = claude_rows(('scripts/gate/dep_sync.py',))
    globs = [row.removeprefix('Bash(').removesuffix(')') for row in rows]
    assert any(fnmatchcase(f'{interpreter} scripts/gate/dep_sync.py --sync', pattern) for pattern in globs)
    assert any(fnmatchcase(f'{interpreter} -m lab_commons.dev.dep --bootstrap lane', pattern) for pattern in globs)
    assert not any(fnmatchcase(f'{interpreter} -m pip install arbitrary', pattern) for pattern in globs)
    assert not any(fnmatchcase(f'{interpreter} -m lab_commons.dev.dep --sync', pattern) for pattern in globs)
    assert not any(
        fnmatchcase(f'{interpreter} -c arbitrary scripts/gate/dep_sync.py --sync', pattern) for pattern in globs
    )
    assert not any(
        fnmatchcase(f'{interpreter} -c arbitrary -m lab_commons.dev.dep --bootstrap lane', pattern) for pattern in globs
    )


def test_an_interpreter_spelled_by_an_absolute_path_is_not_admitted_and_that_is_the_decision() -> None:
    """WHAT THE ANCHOR COSTS, pinned here rather than found by an agent in auto mode.

    A row that does not lead with ``*`` cannot admit ``C:/repo/.claude/worktrees/lane/.venv/...``:
    the command's first character is a drive letter or a root, and this file is TRACKED IN GIT, so
    no rendering of it can name the one on the box reading it. The previous spelling bought that
    coverage with a leading wildcard -- which permits ANY invocation prefix, i.e. exactly the
    widening the consumers' allow guard refuses -- and the price is paid here instead: an agent
    reaching for another checkout's interpreter that way is prompted once, and the road it can take
    without a prompt is the REPO-RELATIVE one ``docs-src/dev/fanout.md`` spells anyway. Both
    directions are asserted, because a narrowing whose replacement is also refused would be a
    deletion wearing a docstring.
    """
    rows = claude_rows(('scripts/gate/dep_sync.py',))
    globs = [row.removeprefix('Bash(').removesuffix(')') for row in rows]
    absolute = 'C:/repo/.claude/worktrees/lane/.venv/Scripts/python.exe'
    assert not any(fnmatchcase(f'{absolute} scripts/gate/dep_sync.py --sync', pattern) for pattern in globs)
    assert any(
        fnmatchcase(
            '.claude/worktrees/lane/.venv/Scripts/python.exe scripts/gate/dep_sync.py --sync',
            pattern,
        )
        for pattern in globs
    )


def test_bootstrap_is_a_specific_shared_door_in_both_client_renderings() -> None:
    assert '"-m", "lab_commons.dev.dep", "--bootstrap"' in codex_rules()


def test_cross_checkout_script_permissions_are_derived_from_the_supplied_doors() -> None:
    """A WORKTREE's interpreter is spelled from the worktrees directory, never from a bare ``*/``."""
    rows = claude_rows(('tools/check_lane.py',))
    assert 'Bash(.claude/worktrees/*/.venv/Scripts/python.exe tools/check_lane.py *)' in rows
    assert 'Bash(.claude/worktrees/*/.venv/bin/python tools/check_lane.py *)' in rows
    assert not any(row.startswith('Bash(*') for row in rows), 'a door row leads with a wildcard'
    assert not any('scripts/gate/dep_sync.py' in row for row in rows)
    assert not any('untracked_installer.py' in row for row in rows)


def test_every_row_is_narrow_and_one_per_door() -> None:
    sibling_push = 'Bash(sh */scripts/hooks/with-retry.sh push *)'
    rows = claude_rows(_SCRIPTS)
    assert sibling_push in rows
    rows = {row: why for row, why in rows.items() if row != sibling_push}
    assert set(rows.values()) == set(doors(_SCRIPTS).values())
    assert 'Bash(.venv/*/python* -m lab_commons.dev.branchset *)' in rows
    assert 'Bash(sh scripts/hooks/with-retry.sh *)' in rows
    assert all(any(row.endswith(f' {" ".join(argv)} *)') for (_runner, *argv) in doors(_SCRIPTS)) for row in rows)


def test_codex_and_claude_render_the_same_doors() -> None:
    text = codex_rules(_SCRIPTS)
    assert text.count('prefix_rule(') == len(doors(_SCRIPTS))
    for module in DOOR_MODULES:
        assert f'"-m", "{module}"' in text
    assert '"sh", "scripts/hooks/with-retry.sh"' in text


def test_no_rendering_allows_a_raw_destructive_verb_and_the_scan_sees_one() -> None:
    body = '\n'.join(line for line in codex_rules(_SCRIPTS).splitlines() if not line.startswith('#'))
    assert promises_raw(' '.join(claude_rows(_SCRIPTS))) == ()
    assert promises_raw(body) == ()
    assert promises_raw('Bash(git push origin --delete x)') == ('--delete',)


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


def test_a_main_session_publishes_through_the_wrapper_where_there_is_one() -> None:
    """MAIN-SESSION-PUBLISHES: ff-merge and the wrapper's push, own repo and sibling; no raw push row."""
    globs = [row.removeprefix('Bash(').removesuffix(')') for row in claude_rows(_SCRIPTS)]
    for command in (
        'sh scripts/hooks/with-retry.sh push origin main',
        'sh C:/w/sib/scripts/hooks/with-retry.sh push origin main',
        'git merge --ff-only lane/x',
        'git -C C:/w/sib merge --ff-only lane/x',
    ):
        assert any(fnmatchcase(command, pattern) for pattern in globs), command
    assert not any(fnmatchcase('git push origin main', pattern) for pattern in globs)
    assert not any(fnmatchcase('sh C:/w/sib/scripts/hooks/with-retry.sh fetch', pattern) for pattern in globs)
    assert not any(fnmatchcase('git merge lane/x', pattern) for pattern in globs)


def test_a_repo_without_a_wrapper_pushes_through_netverb_never_raw() -> None:
    """GIT-NETWORK-VERB refuses a raw push, so no rendering promises one; netverb is the road."""
    globs = [row.removeprefix('Bash(').removesuffix(')') for row in claude_rows(())]
    netverb_push = '.venv/Scripts/python.exe -m lab_commons.dev.netverb -- git push origin main'
    assert any(fnmatchcase(netverb_push, g) for g in globs)
    assert not any(fnmatchcase('git push origin main', g) for g in globs)
    assert not any(fnmatchcase('git -C ../sib push origin main', g) for g in globs)
    assert promises_raw(' '.join(globs)) == ()
    assert promises_raw('Bash(git push --force origin *)') == ('--force',)
