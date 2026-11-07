"""AUTO-MODE-RUNS-THE-DOORS: one table, two renderings, and no raw destructive verb in either."""

from __future__ import annotations

import re
import shutil
import subprocess
from fnmatch import fnmatchcase
from pathlib import Path

import pytest

from dev_lab.dev.agentpolicy import INTERPRETERS, POLICY, USER
from dev_lab.dev.autodoors import (
    CODEX_RULES_REL,
    claude_rows,
    codex_rules,
    doors,
    main,
    promises_raw,
    script_doors,
)
from dev_lab.dev.famtests.visibility import plant_checkout
from dev_lab.dev.venvpath import VENV_INTERPRETER_GLOB

_GIT = shutil.which('git') or 'git'
_SCRIPTS = ('scripts/gate/runner.py', 'scripts/hooks/with-retry.sh')


@pytest.mark.parametrize('interpreter', ['.venv/Scripts/python.exe', '.venv/bin/python'])
def test_a_script_door_is_one_row_under_the_one_anchored_interpreter_glob(interpreter: str) -> None:
    """User ruling 2026-11-07: never six interpreter spellings -- one literal per layout, never the glob.

    PLANTED CONTROLS: an installer through the same interpreter, another verb of the dependency door, and a door
    reached through another checkout's interpreter (worktree or absolute) are not admitted -- that is prompted once.
    """
    rows = claude_rows(('scripts/gate/dep_sync.py',))
    assert [row for row in rows if 'dep_sync' in row] == [
        f'Bash({head} scripts/gate/dep_sync.py *)' for head in INTERPRETERS
    ]
    globs = [row.removeprefix('Bash(').removesuffix(')') for row in rows]
    assert any(fnmatchcase(f'{interpreter} scripts/gate/dep_sync.py --sync', pattern) for pattern in globs)
    assert any(fnmatchcase(f'{interpreter} -m dev_lab.dev.dep --bootstrap lane', pattern) for pattern in globs)
    for refused in (
        f'{interpreter} -m pip install arbitrary',
        f'{interpreter} -m dev_lab.dev.dep --sync',
        f'{interpreter} -c arbitrary scripts/gate/dep_sync.py --sync',
        f'.claude/worktrees/lane/{interpreter} scripts/gate/dep_sync.py --sync',
        f'C:/repo/{interpreter} scripts/gate/dep_sync.py --sync',
    ):
        assert not any(fnmatchcase(refused, pattern) for pattern in globs), refused
    assert not any(row.startswith('Bash(*') for row in rows), 'a door row leads with a wildcard'
    assert f'Bash({VENV_INTERPRETER_GLOB} *)' not in rows, 'the blanket interpreter row is deleted'


def test_bootstrap_is_a_specific_shared_door_in_both_client_renderings() -> None:
    assert '"-m", "dev_lab.dev.dep", "--bootstrap"' in codex_rules()


def test_every_row_is_narrow_and_one_per_door() -> None:
    sibling_push = 'Bash(sh */scripts/hooks/with-retry.sh push *)'
    rows = claude_rows(_SCRIPTS)
    assert sibling_push in rows
    rows = {row: why for row, why in rows.items() if row != sibling_push}
    assert set(rows.values()) == set(doors(_SCRIPTS).values())
    assert 'Bash(.venv/bin/python -m dev_lab.dev.branchset *)' in rows
    assert 'Bash(sh scripts/hooks/with-retry.sh *)' in rows
    assert all(any(row.endswith(f' {" ".join(argv)} *)') for (_runner, *argv) in doors(_SCRIPTS)) for row in rows)


def test_codex_and_claude_render_the_same_doors() -> None:
    text = codex_rules(_SCRIPTS)
    assert text.count('prefix_rule(') == len(doors(_SCRIPTS))
    for door in POLICY:
        if door.argv[:2] == ('python', '-m') and door.actor != USER:
            assert f'"-m", "{door.argv[2]}"' in text
    assert '"sh", "scripts/hooks/with-retry.sh"' in text


def test_no_rendering_allows_a_raw_destructive_verb_and_the_scan_sees_one() -> None:
    body = '\n'.join(line for line in codex_rules(_SCRIPTS).splitlines() if not line.startswith('#'))
    assert promises_raw(' '.join(claude_rows(_SCRIPTS))) == ()
    assert promises_raw(body) == ()
    assert promises_raw('Bash(git push origin --delete x)') == ('--delete',)


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
    """NETWORK-VERB refuses a raw push, so no rendering promises one; netverb is the road."""
    globs = [row.removeprefix('Bash(').removesuffix(')') for row in claude_rows(())]
    netverb_push = '.venv/Scripts/python.exe -m dev_lab.dev.netverb -- git push origin main'
    assert any(fnmatchcase(netverb_push, g) for g in globs)
    assert not any(fnmatchcase('git push origin main', g) for g in globs)
    assert not any(fnmatchcase('git -C ../sib push origin main', g) for g in globs)
    assert promises_raw(' '.join(globs)) == ()
    assert promises_raw('Bash(git push --force origin *)') == ('--force',)


def test_each_bounded_verb_renders_one_row_naming_its_verb_and_no_sibling_verb() -> None:
    """A POLICY door admits its bounded verb and NOT the same module's other verbs (planted control)."""
    globs = [row.removeprefix('Bash(').removesuffix(')') for row in claude_rows(())]
    for _runner, *argv in (door.argv for door in POLICY if door.argv[:1] == ('python',) and door.actor != USER):
        assert any(fnmatchcase(f'.venv/Scripts/python.exe {" ".join(argv)} x', g) for g in globs), argv
    assert not any(fnmatchcase('.venv/Scripts/python.exe -m dev_lab.dev.forge serve', g) for g in globs)
    assert not any(fnmatchcase('.venv/Scripts/python.exe -m dev_lab.dev.hpcaccount deploy --remove', g) for g in globs)
    assert promises_raw(' '.join(globs)) == ()


#: Where an agent is TOLD to run a forge verb: the docs and the rules registry's prose.
_TOLD = ('docs-src', 'src/dev_lab/dev/_rule_rows*.py', 'src/dev_lab/dev/forgedraft.py', 'README.md')
_FORGE_PR_VERB = re.compile(r'forge pr ([a-z][a-z-]*)')


def test_every_forge_pr_verb_an_agent_is_told_to_run_is_a_door() -> None:
    """FORGE-DOORS-ARE-CONSENT: every `forge pr <verb>` the docs tell an agent to run is a POLICY door.

    So no classifier stands between the agent and it and the user is never handed it (incident 2026-11-04, `pr ready`).
    """
    root = Path(__file__).resolve().parents[1]
    told: set[str] = set()
    for pattern in _TOLD:
        for path in root.glob(f'{pattern}/**/*.md' if pattern == 'docs-src' else pattern):
            told.update(_FORGE_PR_VERB.findall(path.read_text('utf-8')))
    assert {'create', 'ready', 'close-landed'} <= told, told  # floor: the scan reads the docs
    doors_ = {door.argv[4] for door in POLICY if door.argv[2:4] == ('dev_lab.dev.forge', 'pr')}
    assert told - doors_ == set()
    globs = [row.removeprefix('Bash(').removesuffix(')') for row in claude_rows(())]
    assert not any(fnmatchcase('.venv/Scripts/python.exe -m dev_lab.dev.forge pr view 3', g) for g in globs)
