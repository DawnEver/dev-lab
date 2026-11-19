"""AUTO-MODE-RUNS-THE-DOORS: one table, two renderings, and no raw destructive verb in either."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from fnmatch import fnmatchcase
from pathlib import Path

import pytest

from dev_lab.dev.agentpolicy import POLICY, USER
from dev_lab.dev.autodoors import (
    CODEX_RULES_REL,
    REFUSED_ACTS,
    ActDeclaredAsDoor,
    claude_rows,
    cli_doors,
    cli_modules,
    codex_rules,
    doors,
    main,
    promises_raw,
    script_doors,
)
from dev_lab.dev.doorrows import INTERPRETERS
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


_DESKTOP_READS = ('windows', 'capture', 'controls')
_DESKTOP_ACTS = ('press', 'set-value', 'close')


def test_the_desktop_tool_read_verbs_are_doors_and_its_acts_stay_prompted() -> None:
    """User ruling 2026-11-14 E6: the desktop tool's READ verbs run unprompted in both clients; acts stay prompted.

    PLANTED CONTROL: no rendered Claude row or Codex rule names an act verb, and a bare-module row (which would
    admit every verb) is absent.
    """
    rows = claude_rows()
    text = codex_rules()
    for verb in _DESKTOP_READS:
        for head in INTERPRETERS:
            assert f'Bash({head} -m lab_commons.desktop {verb} *)' in rows
        assert f'"-m", "lab_commons.desktop", "{verb}"' in text
    globs = [row.removeprefix('Bash(').removesuffix(')') for row in rows]
    for verb in _DESKTOP_ACTS:
        command = f'{INTERPRETERS[0]} -m lab_commons.desktop {verb} --window x'
        assert not any(fnmatchcase(command, pattern) for pattern in globs), verb
        assert f'"lab_commons.desktop", "{verb}"' not in text
    assert not any(row.endswith('-m lab_commons.desktop *)') for row in rows)


_CLI_TABLE = """
[tool.dev_lab.cli_doors]
acts = ["press"]
doors = [
    {verb = ["vendor", "windows"], why = "Read-only: the vendor tool's windows, listed."},
    {verb = ["vendor", "stalled"], why = "Read-only: whether the vendor tool waits on a dialog."},
]
"""


_PROJECT = '[project]\nname = "consumer-dist"\n[project.scripts]\nconsumer = "consumer.__main__:main"\n'


def _declare(tmp_path: Path, table: str) -> Path:
    (tmp_path / 'pyproject.toml').write_text(_PROJECT + table, encoding='utf-8')
    return tmp_path


def test_a_consumer_declares_its_read_only_cli_verbs_and_both_clients_render_them(tmp_path: Path) -> None:
    """DECISION 2026-11-15: a consumer's read-only CLI verbs are DATA in its pyproject, rendered like every door.

    PLANTED CONTROL: a sibling verb of the same CLI (an act) and the bare module stay unadmitted.
    """
    cli = cli_doors(_declare(tmp_path, _CLI_TABLE))
    assert [door.argv for door in cli] == [
        ('python', '-m', 'consumer', 'vendor', 'windows'),
        ('python', '-m', 'consumer', 'vendor', 'stalled'),
    ]
    rows = claude_rows(cli=cli)
    text = codex_rules(cli=cli)
    globs = [row.removeprefix('Bash(').removesuffix(')') for row in rows]
    for verb in ('windows', 'stalled'):
        for head in INTERPRETERS:
            assert f'Bash({head} -m consumer vendor {verb} *)' in rows
        assert f'"-m", "consumer", "vendor", "{verb}"' in text
    for refused in ('vendor press --window x', 'vendor close x', 'serve'):
        assert not any(fnmatchcase(f'{INTERPRETERS[0]} -m consumer {refused}', g) for g in globs), refused
    windows = f'Bash({INTERPRETERS[0]} -m consumer vendor windows *)'
    assert rows[windows] == "Read-only: the vendor tool's windows, listed."
    assert cli_doors(_declare(tmp_path, '')) == (), 'no table, no doors'


@pytest.mark.parametrize(('acts', 'verb'), [('["rerun"]', 'rerun'), ('[]', 'press'), ('[]', 'kill'), ('[]', 'push')])
def test_a_declared_cli_door_that_names_an_act_is_refused_by_name(tmp_path: Path, acts: str, verb: str) -> None:
    """An act is never a door: the repo's own `acts` list, and the fixed refusal list whatever the repo declares."""
    row = f'{{verb = ["vendor", "{verb}"], why = "x"}}'
    table = f'[tool.dev_lab.cli_doors]\nacts = {acts}\ndoors = [{row}]\n'
    assert (verb in REFUSED_ACTS) == (acts == '[]'), 'the repo-declared act is outside the fixed list'
    with pytest.raises(ActDeclaredAsDoor, match=verb):
        cli_doors(_declare(tmp_path, table))


@pytest.mark.parametrize('verb', ['[]', '["vendor *"]', '["a b"]', '["-c"]'])
def test_a_cli_door_that_would_admit_more_than_its_verb_is_refused(tmp_path: Path, verb: str) -> None:
    """No verb is the bare module, which admits every verb; a glob, a space or a flag widens the row."""
    table = f'[tool.dev_lab.cli_doors]\ndoors = [{{verb = {verb}, why = "x"}}]\n'
    with pytest.raises(ValueError, match='cli_doors'):
        cli_doors(_declare(tmp_path, table))


def test_the_module_comes_from_the_repo_s_own_project_scripts_never_the_row(tmp_path: Path) -> None:
    """User direction 2026-11-15: the module is the repo's OWN declaration, one source; a row names verbs only.

    PLANTED CONTROLS: the retired ``argv`` key, a script target that is no package ``__main__``, a repo with no
    script, and two modules with no ``script =`` choice are each refused by name.
    """
    row = '{verb = ["case", "list"], why = "Read-only: the cases, listed."}'
    table = f'[tool.dev_lab.cli_doors]\ndoors = [{row}]\n'
    assert cli_modules({'project': {'scripts': {'consumer': 'consumer.__main__:main'}}}) == {'consumer': 'consumer'}
    assert cli_doors(_declare(tmp_path, table))[0].argv == ('python', '-m', 'consumer', 'case', 'list')

    def refused(manifest: str, body: str, match: str) -> None:
        (tmp_path / 'pyproject.toml').write_text(manifest + body, encoding='utf-8')
        with pytest.raises(ValueError, match=match):
            cli_doors(tmp_path)

    retired = '[tool.dev_lab.cli_doors]\ndoors = [{argv = ["consumer", "case", "list"], why = "x"}]\n'
    refused(_PROJECT, retired, 'argv` is retired')
    refused('[project]\nname = "c"\n[project.scripts]\nc = "c.cli:main"\n', table, 'not a package __main__')
    refused('[project]\nname = "c"\n', table, 'declare the CLI there')
    two = '[project]\nname = "c"\n[project.scripts]\na = "a.__main__:main"\nb = "b.__main__:main"\n'
    refused(two, table, 'script = ')
    chosen = '[tool.dev_lab.cli_doors]\ndoors = [{verb = ["x"], why = "Read-only.", script = "b"}]\n'
    (tmp_path / 'pyproject.toml').write_text(two + chosen, encoding='utf-8')
    assert cli_doors(tmp_path)[0].argv == ('python', '-m', 'b', 'x')


def test_the_renderer_reads_the_declaration_from_the_repo(tmp_path: Path) -> None:
    work = plant_checkout(tmp_path, trunk='main').work
    _declare(work, _CLI_TABLE)
    assert main(['--repo', str(work), '--write']) == 0
    assert '"consumer", "vendor", "windows"' in (work / CODEX_RULES_REL).read_text(encoding='utf-8')


_ACT_TABLE = """
[tool.dev_lab.cli_doors]
doors = [
    {verb = ["vendor", "windows"], why = "Read-only: the vendor tool's windows, listed."},
    {verb = ["case", "run"], why = "Runs one case; writes only its output tree.", act = true},
]
"""


def test_an_act_row_renders_for_both_clients_and_is_labelled_as_acting(tmp_path: Path) -> None:
    """A repo declares a WRITING verb of its own CLI as a door, explicitly: ``act = true`` on the row.

    PLANTED CONTROLS: both literal interpreters render and never the ``.venv/*/python*`` glob; the read-only row's
    rendering is byte-identical to a table without the act row; every rendering of the act row says it writes.
    """
    cli = cli_doors(_declare(tmp_path, _ACT_TABLE))
    act = cli[1]
    assert act.argv == ('python', '-m', 'consumer', 'case', 'run')
    assert act.intent == 'Acts (writes): Runs one case; writes only its output tree.'
    rows = claude_rows(cli=cli)
    text = codex_rules(cli=cli)
    for head in INTERPRETERS:
        assert rows[f'Bash({head} -m consumer case run *)'] == act.intent
    assert f'pattern = [{json.dumps(list(INTERPRETERS))}, "-m", "consumer", "case", "run"]' in text
    assert f'justification = {json.dumps(act.intent)}' in text
    assert VENV_INTERPRETER_GLOB not in text
    assert not any(VENV_INTERPRETER_GLOB in row for row in rows)
    globs = [row.removeprefix('Bash(').removesuffix(')') for row in rows]
    assert not any(fnmatchcase(f'{INTERPRETERS[0]} -m consumer case delete x', g) for g in globs)
    read_only = cli_doors(_declare(tmp_path, _CLI_TABLE))[0]
    assert cli[0] == read_only, 'a read-only row is unchanged by an act row beside it'
    assert rows[f'Bash({INTERPRETERS[0]} -m consumer vendor windows *)'] == read_only.intent


@pytest.mark.parametrize(
    ('row', 'match'),
    [
        ('{verb = [], why = "Writes.", act = true}', 'at least one verb'),
        ('{verb = ["case", "delete"], why = "Writes.", act = true}', 'delete'),
        ('{verb = ["case", "rerun"], why = "Writes.", act = true}', 'rerun'),
        ('{verb = ["case", "run"], why = "Read-only: lists.", act = true}', 'read-only'),
        ('{verb = ["case", "run"], why = "Writes.", act = "yes"}', 'act'),
        ('{verb = ["case", "run"], why = "Writes.", actor = "main"}', 'SUBAGENT-NO-PUSH'),
        ('{verb = ["case", "run"], why = "Writes.", acts = true}', 'acts'),
    ],
)
def test_an_act_row_that_would_lie_or_widen_is_refused_by_name(tmp_path: Path, row: str, match: str) -> None:
    """Every lie or widening of an act row is refused naming its cause.

    A bare module, a refused or repo-declared act, a read-only claim on an act, a non-boolean marker, an
    unenforceable actor and an unknown key.
    """
    table = f'[tool.dev_lab.cli_doors]\nacts = ["rerun"]\ndoors = [{row}]\n'
    with pytest.raises((ValueError, TypeError), match=match):
        cli_doors(_declare(tmp_path, table))
