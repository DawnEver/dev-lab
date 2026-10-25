"""The installer and the verifier, over the THREE STATES a planted repo can be in.

THE STATES ARE THE SIBLING MECHANISM'S, on purpose: :mod:`dev_lab.dev.hook_install` distinguishes
declared-but-absent from present-but-stale from present-but-not-ours, and every one of those is a
different remedy. Planting them is what proves the verifier can TELL them apart -- a checker that
returns "not installed" for all three sends a reader to the wrong fix twice out of three times.

AND THE INSTALL IS PROVED BY RUNNING WHAT IT INSTALLED. The last arm does not assert that files
appeared; it feeds a denied command through the engine in the PLANTED repo, from the wiring the
installer wrote. That is the difference this whole module exists over -- a declared guard and a live
one are different things, and only one of them refuses anything.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from dev_lab.dev import agent_guard, agenthooks
from dev_lab.dev.githooks import bash_executable
from dev_lab.dev.hook_adoption import HookAdoption, render
from dev_lab.dev.hooks import Remedy

# THE ENGINE RUNS ON `node`, A REQUIREMENT OF THE HOST: the `node` marker assigns this file to the parts
# whose hosts have it ([tool.lab_commons.tests] resources). Where it runs and node is absent, `NoNode` still reds.
pytestmark = pytest.mark.workstation

#: A minimal but REAL declaration: one rule with an exit that exists as a command.
ADOPTION = HookAdoption(
    app_name='planted',
    remedies={'BARE-TEST-INVOCATION': Remedy('verdict-entry-point', 'python -m dev_lab.dev.verify')},
    declared_absent=frozenset({'NETWORK-VERB', 'PUSH-NO-VERIFY', 'RAW-PROCESS-KILL'}),
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """An empty tree standing in for a consumer repo. NOT this repo, and never a sibling's."""
    root = tmp_path / 'consumer'
    root.mkdir()
    return root


def _declare(repo: Path) -> None:
    """Write the repo's OWN rendered rules -- the half the installer deliberately does not write."""
    path = repo / agent_guard.RULES_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(ADOPTION), encoding='utf-8')


def test_an_untouched_repo_reports_nothing_declared(repo: Path) -> None:
    """STATE ONE: ABSENT. Not a pass and not a failure -- the absence of a question."""
    report = agent_guard.guard_installation(repo)
    assert report.verdict == agent_guard.NOTHING_DECLARED
    assert {part.status for part in report.parts} == {agent_guard.ABSENT}
    assert set(report.by_part) == set(agent_guard.PART_NAMES), 'a part stopped being reported by name'


def test_a_declaration_with_no_engine_reads_as_unguarded(repo: Path) -> None:
    """THE DEFECT THIS MODULE EXISTS FOR: rendered rules, no engine, no wiring -- an INERT guard."""
    _declare(repo)
    report = agent_guard.guard_installation(repo)
    assert report.verdict == agent_guard.UNGUARDED
    assert report.by_part['rules'].status == agent_guard.INSTALLED
    assert report.by_part['engine'].status == agent_guard.ABSENT
    assert report.by_part['wiring'].status == agent_guard.ABSENT


def test_installing_makes_it_guarded(repo: Path) -> None:
    """STATE TWO: INSTALLED. All three parts live, and the CLI says so with exit 0."""
    _declare(repo)
    agent_guard.install_guard(repo)
    report = agent_guard.guard_installation(repo)
    assert report.verdict == agent_guard.GUARDED, [(p.part, p.status, p.detail) for p in report.parts]
    assert agent_guard.report_guard(['--repo', str(repo)]) == 0


def test_installing_twice_changes_nothing(repo: Path) -> None:
    """An install is idempotent, and it SAYS which of the two it did rather than reporting success."""
    _declare(repo)
    agent_guard.install_guard(repo)
    settings = (repo / agent_guard.SETTINGS_REL).read_text(encoding='utf-8')
    actions = agent_guard.install_guard(repo)
    assert all('already' in action for action in actions), actions
    assert (repo / agent_guard.SETTINGS_REL).read_text(encoding='utf-8') == settings


def test_a_hand_written_engine_is_foreign_and_refuses_to_be_overwritten(repo: Path) -> None:
    """STATE THREE: FOREIGN. Overwriting somebody's hook is a deletion, so it takes an explicit act."""
    engine = repo / agent_guard.ENGINE_REL
    engine.parent.mkdir(parents=True)
    engine.write_text('// somebody else wrote this\nprocess.exit(0);\n', encoding='utf-8')
    assert agent_guard.guard_installation(repo).by_part['engine'].status == agent_guard.FOREIGN
    with pytest.raises(FileExistsError, match='force=True'):
        agent_guard.install_guard(repo)
    agent_guard.install_guard(repo, force=True)
    assert agent_guard.guard_installation(repo).by_part['engine'].status == agent_guard.INSTALLED


def test_an_edited_copy_of_the_shipped_engine_is_stale(repo: Path) -> None:
    """The fourth state, and the one a copy ROTS into: stamped as ours, no longer our bytes."""
    agent_guard.install_guard(repo)
    engine = repo / agent_guard.ENGINE_REL
    engine.write_text(engine.read_text(encoding='utf-8') + '\n// a local edit\n', encoding='utf-8')
    part = agent_guard.guard_installation(repo).by_part['engine']
    assert part.status == agent_guard.STALE, part.detail
    agent_guard.install_guard(repo)
    assert agent_guard.guard_installation(repo).by_part['engine'].status == agent_guard.INSTALLED


def test_unrelated_settings_survive_the_install(repo: Path) -> None:
    """NO CLOBBERING, and the three things that could be clobbered are each planted.

    An unrelated TOP-LEVEL key, an unrelated MATCHER, and another hook already on the Bash matcher.
    The last is the one a naive writer loses, because ours goes in the same list.
    """
    settings = repo / agent_guard.SETTINGS_REL
    settings.parent.mkdir(parents=True)
    planted = {
        'permissions': {'allow': ['Read']},
        'hooks': {
            'PreToolUse': [
                {'matcher': 'Write', 'hooks': [{'type': 'command', 'command': 'node other.js'}]},
                {'matcher': 'Bash', 'hooks': [{'type': 'command', 'command': 'node theirs.js'}]},
            ],
            'Stop': [{'matcher': '*', 'hooks': [{'type': 'command', 'command': 'node stop.js'}]}],
        },
    }
    settings.write_text(json.dumps(planted), encoding='utf-8')
    agent_guard.install_guard(repo)
    after = json.loads(settings.read_text(encoding='utf-8'))

    assert after['permissions'] == planted['permissions'], 'an unrelated settings key was lost'
    assert after['hooks']['Stop'][0] == planted['hooks']['Stop'][0], 'an unrelated event was lost'
    pre = after['hooks']['PreToolUse']
    assert pre[0] == planted['hooks']['PreToolUse'][0], 'an unrelated matcher was rewritten'
    assert pre[1] == planted['hooks']['PreToolUse'][1], "another agent's Bash hook was moved or widened"
    assert pre[2] == {'matcher': 'Bash|PowerShell', 'hooks': [{'type': 'command', 'command': agent_guard.HOOK_COMMAND}]}


def test_wiring_that_runs_the_engine_with_other_arguments_is_stale(repo: Path) -> None:
    """A matcher naming the engine but a DIFFERENT rules file enforces something else entirely."""
    settings = repo / agent_guard.SETTINGS_REL
    settings.parent.mkdir(parents=True)
    other = {
        'hooks': {
            'PreToolUse': [
                {'matcher': 'Bash', 'hooks': [{'type': 'command', 'command': 'node .claude/hooks/deny-commands.js x'}]}
            ]
        }
    }
    settings.write_text(json.dumps(other), encoding='utf-8')
    assert agent_guard.guard_installation(repo).by_part['wiring'].status == agent_guard.STALE
    agent_guard.install_guard(repo)
    assert agent_guard.guard_installation(repo).by_part['wiring'].status == agent_guard.INSTALLED


def test_unreadable_rules_are_stale_rather_than_present(repo: Path) -> None:
    """The engine FAILS OPEN on a broken rules file, so a present-but-unreadable one guards nothing."""
    path = repo / agent_guard.RULES_REL
    path.parent.mkdir(parents=True)
    path.write_text('[ {"name": ', encoding='utf-8')
    assert agent_guard.guard_installation(repo).by_part['rules'].status == agent_guard.STALE


# The shell the tool runs a hook line in, found as the hooks find it: a serve host's scheduled task has
# ``git`` on PATH but no bash (G, 2026-10-24), so a bare lookup would test the PATH rather than the guard.
_SHELL = bash_executable()


def _wired_line(repo: Path) -> str:
    """The installed hook command line, verbatim: the tool's shell runs it with ``$CLAUDE_PROJECT_DIR`` set."""
    settings = json.loads((repo / agent_guard.SETTINGS_REL).read_text(encoding='utf-8'))
    return settings['hooks']['PreToolUse'][0]['hooks'][0]['command']


def _run_hook(repo: Path, line: str, command: str, *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run the hook EXACTLY as the tool would: the wired line in a POSIX shell, from the session cwd."""
    where = cwd or repo
    payload = {'tool_name': 'Bash', 'tool_input': {'command': command}, 'cwd': str(where)}
    node = Path(agenthooks.node_executable()).parent.as_posix()
    return subprocess.run(
        [_SHELL, '-c', line],
        cwd=where,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=False,
        timeout=60,
        env={**os.environ, 'CLAUDE_PROJECT_DIR': repo.as_posix(), 'PATH': f'{node}{os.pathsep}{os.environ["PATH"]}'},
    )


def _ask(repo: Path, line: str, command: str, *, cwd: Path | None = None) -> str | None:
    """The hook's deny reason for *command*, or ``None`` when it allowed it; a blocking exit fails the test."""
    done = _run_hook(repo, line, command, cwd=cwd)
    assert done.returncode == 0, done.stderr
    if not done.stdout.strip():
        return None
    return json.loads(done.stdout)['hookSpecificOutput']['permissionDecisionReason']


def test_the_installed_guard_actually_refuses_a_command(repo: Path) -> None:
    """THE POINT. Run WHAT WAS INSTALLED, through the argv the wiring names, and read the verdict.

    Driven through ``subprocess`` rather than through :func:`dev_lab.dev.agenthooks.decide`
    deliberately: ``decide`` runs the engine inside the PACKAGE, and this arm has to prove the copy
    in the planted repo works when invoked by the repo-relative command line that was written into
    its settings. Those are the two things an install can get wrong.
    """
    _declare(repo)
    agent_guard.install_guard(repo)
    wired = _wired_line(repo)
    assert (repo / agent_guard.ENGINE_REL).is_file(), 'the wiring names a path that is not there'
    assert (repo / agent_guard.RULES_REL).is_file(), 'the wiring names a path that is not there'

    denied = _ask(repo, wired, 'pytest tests/')
    assert denied is not None, 'the installed guard allowed a bare test line'
    assert 'dev_lab.dev.verify' in denied, denied
    assert _ask(repo, wired, 'git status') is None, 'the installed guard refused an ordinary command'


def test_the_installed_guard_refuses_from_a_session_cwd_without_hooks(repo: Path) -> None:
    """THE 2026-10-20 INCIDENT: the hook runs in the SESSION's cwd, not the repo root.

    The wiring used to read `node .claude/hooks/deny-commands.js ...`, cwd-relative. From any session
    cwd that holds no `.claude/hooks/` (a subdirectory, a sibling repo) node exited 1 on
    MODULE_NOT_FOUND, which the tool treats as a NON-BLOCKING hook error -- so every command ran
    unjudged, and bare `python -m pytest` lines spawned eight xdist workers each and filled 55 GB.
    The wiring is anchored on `$CLAUDE_PROJECT_DIR`, so the cwd no longer decides whether it runs.
    """
    _declare(repo)
    agent_guard.install_guard(repo)
    elsewhere = repo / 'tests' / 'unit'
    elsewhere.mkdir(parents=True)
    denied = _ask(repo, _wired_line(repo), '.venv/Scripts/python.exe -m pytest -q tests/unit/x.py', cwd=elsewhere)
    assert denied is not None, 'from a cwd without .claude/hooks the guard failed open'


def test_a_missing_engine_fails_closed_with_a_blocking_exit(repo: Path) -> None:
    """2026-10-21: an engine that is not there made node exit 1 -- NON-blocking, so every command ran unjudged."""
    _declare(repo)
    agent_guard.install_guard(repo)
    (repo / agent_guard.ENGINE_REL).unlink()
    done = _run_hook(repo, _wired_line(repo), 'git status')
    assert done.returncode == 2, (done.returncode, done.stderr)
    assert 'fail closed' in done.stderr
    assert 'hook_install' in done.stderr


def test_an_engine_that_crashes_fails_closed_with_a_blocking_exit(repo: Path) -> None:
    """PLANTED CONTROL: the file is there but the engine dies -- still a blocking exit, never an allowed command."""
    _declare(repo)
    agent_guard.install_guard(repo)
    (repo / agent_guard.ENGINE_REL).write_text('process.exit(1);\n', encoding='utf-8')
    done = _run_hook(repo, _wired_line(repo), 'git status')
    assert done.returncode == 2, (done.returncode, done.stderr)
    assert 'engine exited 1' in done.stderr


def test_the_wiring_matches_every_shell_tool(repo: Path) -> None:
    """A Bash-only matcher leaves the PowerShell tool unguarded, so the install names both."""
    agent_guard.install_guard(repo)
    settings = json.loads((repo / agent_guard.SETTINGS_REL).read_text(encoding='utf-8'))
    matchers = [entry['matcher'] for entry in settings['hooks']['PreToolUse']]
    assert matchers == ['Bash|PowerShell']


def test_a_bash_only_wiring_is_stale_and_the_install_moves_only_our_hook(repo: Path) -> None:
    """The old wiring is STALE; the install widens OUR hook without widening anybody else's."""
    settings = repo / agent_guard.SETTINGS_REL
    settings.parent.mkdir(parents=True)
    ours = {'type': 'command', 'command': agent_guard.HOOK_COMMAND}
    theirs = {'type': 'command', 'command': 'node theirs.js'}
    old = {'hooks': {'PreToolUse': [{'matcher': 'Bash', 'hooks': [theirs, ours]}]}}
    settings.write_text(json.dumps(old), encoding='utf-8')
    assert agent_guard.guard_installation(repo).by_part['wiring'].status == agent_guard.STALE
    agent_guard.install_guard(repo)
    pre = json.loads(settings.read_text(encoding='utf-8'))['hooks']['PreToolUse']
    assert pre == [{'matcher': 'Bash', 'hooks': [theirs]}, {'matcher': 'Bash|PowerShell', 'hooks': [ours]}]
    assert agent_guard.guard_installation(repo).by_part['wiring'].status == agent_guard.INSTALLED


def test_the_install_wires_the_stray_census_after_every_shell_call_and_at_stop() -> None:
    """STRAY-FILE-REFUSED is live only when wired: PostToolUse on every shell tool, and Stop."""
    after = agent_guard.wire_settings({})
    stray = {'type': 'command', 'command': agent_guard.STRAY_COMMAND}
    assert after['hooks']['PostToolUse'] == [{'matcher': 'Bash|PowerShell', 'hooks': [stray]}]
    assert after['hooks']['Stop'] == [{'hooks': [stray]}]
    assert 'dev_lab.dev.codeplace stray' in agent_guard.STRAY_COMMAND


def test_wiring_the_stray_census_twice_adds_nothing_and_keeps_foreign_hooks() -> None:
    """Idempotent, and another author's PostToolUse/Stop hooks stay where they were."""
    planted = {
        'hooks': {
            'PostToolUse': [{'matcher': 'Bash|PowerShell', 'hooks': [{'type': 'command', 'command': 'node log.js'}]}],
            'Stop': [{'matcher': '*', 'hooks': [{'type': 'command', 'command': 'node stop.js'}]}],
        },
    }
    once = agent_guard.wire_settings(planted)
    assert agent_guard.wire_settings(once) == once
    stray = {'type': 'command', 'command': agent_guard.STRAY_COMMAND}
    assert once['hooks']['PostToolUse'] == [
        {'matcher': 'Bash|PowerShell', 'hooks': [{'type': 'command', 'command': 'node log.js'}, stray]}
    ]
    assert once['hooks']['Stop'] == [planted['hooks']['Stop'][0], {'hooks': [stray]}]
    assert planted['hooks']['Stop'] == [{'matcher': '*', 'hooks': [{'type': 'command', 'command': 'node stop.js'}]}]


def test_a_settings_file_already_running_the_guard_still_gets_the_stray_census() -> None:
    """Every exit of the wiring wires the census: our PreToolUse hook already present is the upgrade path."""
    ours = {'type': 'command', 'command': agent_guard.HOOK_COMMAND}
    old = {'hooks': {'PreToolUse': [{'matcher': 'Bash|PowerShell', 'hooks': [ours]}]}}
    after = agent_guard.wire_settings(old)
    stray = {'type': 'command', 'command': agent_guard.STRAY_COMMAND}
    assert after['hooks']['PostToolUse'] == [{'matcher': 'Bash|PowerShell', 'hooks': [stray]}]
    assert after['hooks']['Stop'] == [{'hooks': [stray]}]


def test_a_wiring_missing_the_stray_census_is_stale_and_the_install_upgrades_it(repo: Path) -> None:
    """The report reads the SAME wiring table the install writes, so a pre-census settings file is STALE."""
    settings = repo / agent_guard.SETTINGS_REL
    settings.parent.mkdir(parents=True)
    ours = {'type': 'command', 'command': agent_guard.HOOK_COMMAND}
    old = {'hooks': {'PreToolUse': [{'matcher': 'Bash|PowerShell', 'hooks': [ours]}]}}
    settings.write_text(json.dumps(old), encoding='utf-8')
    part = agent_guard.guard_installation(repo).by_part['wiring']
    assert part.status == agent_guard.STALE, part.detail
    assert 'PostToolUse' in part.detail
    agent_guard.install_guard(repo)
    assert agent_guard.guard_installation(repo).by_part['wiring'].status == agent_guard.INSTALLED


def test_the_stray_hook_spells_no_interpreter_and_runs_through_the_launcher() -> None:
    """One door resolves the venv per platform: a hook naming ``.venv`` drifts from it (motronics pins this)."""
    assert '.venv' not in agent_guard.STRAY_COMMAND
    assert agent_guard.STRAY_COMMAND.startswith('node ')
    assert agent_guard.LAUNCHER_REL in agent_guard.STRAY_COMMAND


def test_the_install_ships_the_launcher_and_keeps_one_already_there(tmp_path: Path) -> None:
    """Absent: written. Present: the repo's own door, left as it is."""
    agent_guard.install_guard(tmp_path)
    assert (tmp_path / agent_guard.LAUNCHER_REL).read_text(encoding='utf-8') == agent_guard.launcher_source()
    other = tmp_path / 'other'
    (other / agent_guard.LAUNCHER_REL).parent.mkdir(parents=True)
    (other / agent_guard.LAUNCHER_REL).write_text('// the repo own launcher\n', encoding='utf-8')
    agent_guard.install_guard(other)
    assert (other / agent_guard.LAUNCHER_REL).read_text(encoding='utf-8') == '// the repo own launcher\n'


def test_the_stray_hook_never_blocks_a_checkout_without_a_venv(tmp_path: Path) -> None:
    """A hook never blocks on a missing venv (decision 7, 2026-10-22): no interpreter, exit 0 and silent."""
    agent_guard.install_guard(tmp_path)
    env = {**os.environ, 'CLAUDE_PROJECT_DIR': str(tmp_path)}
    done = subprocess.run(
        [_SHELL, '-c', agent_guard.STRAY_COMMAND],
        input='{}',
        capture_output=True,
        text=True,
        encoding='utf-8',
        env=env,
        check=False,
    )
    assert (done.returncode, done.stdout) == (0, ''), done.stderr


def test_the_engine_reads_the_live_run_absent_key_python_writes() -> None:
    """``LIVE_RUN_ABSENT`` is written by ``run_engine`` and read by ``deny-commands.js``: one spelling, pinned here.

    The engine cannot import Python, so the two spellings are held equal by this test. PLANTED control: the
    engine reads SOME ``input.<key> === true`` gate, so a renamed key fails here rather than passing unread.
    """
    engine = (Path(agenthooks.__file__).parent / 'deny-commands.js').read_text(encoding='utf-8')
    assert f'input.{agenthooks.LIVE_RUN_ABSENT} === true' in engine
    assert 'input.dev_lab_renamed_key === true' not in engine, 'CONTROL: the probe is a literal match'
