"""The installer and the verifier, over the THREE STATES a planted repo can be in.

THE STATES ARE THE SIBLING MECHANISM'S, on purpose: :mod:`lab_commons.dev.hook_install` distinguishes
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
import subprocess
from pathlib import Path

import pytest

from lab_commons.dev import agent_guard, agenthooks
from lab_commons.dev.hook_adoption import HookAdoption, render
from lab_commons.dev.hooks import Remedy

NODE = agenthooks.node_executable()

#: A minimal but REAL declaration: one rule with an exit that exists as a command.
ADOPTION = HookAdoption(
    app_name='planted',
    remedies={'BARE-TEST-INVOCATION': Remedy('verdict-entry-point', 'python -m lab_commons.dev.verify')},
    declared_absent=frozenset({'GIT-NETWORK-VERB', 'PUSH-NO-VERIFY', 'RAW-PROCESS-KILL'}),
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
    assert after['hooks']['Stop'] == planted['hooks']['Stop'], 'an unrelated event was lost'
    pre = after['hooks']['PreToolUse']
    assert pre[0] == planted['hooks']['PreToolUse'][0], 'an unrelated matcher was rewritten'
    commands = [hook['command'] for hook in pre[1]['hooks']]
    assert 'node theirs.js' in commands, "another agent's Bash hook was dropped"
    assert agent_guard.HOOK_COMMAND in commands, 'the guard was not wired'


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


def _ask(repo: Path, wired: list[str], command: str) -> str | None:
    """Run the hook EXACTLY as the tool would: the wired argv, from the repo, payload on stdin."""
    payload = {'tool_name': 'Bash', 'tool_input': {'command': command}, 'cwd': str(repo)}
    done = subprocess.run(
        [NODE, *wired[1:]],
        cwd=repo,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if not done.stdout.strip():
        return None
    return json.loads(done.stdout)['hookSpecificOutput']['permissionDecisionReason']


def test_the_installed_guard_actually_refuses_a_command(repo: Path) -> None:
    """THE POINT. Run WHAT WAS INSTALLED, through the argv the wiring names, and read the verdict.

    Driven through ``subprocess`` rather than through :func:`lab_commons.dev.agenthooks.decide`
    deliberately: ``decide`` runs the engine inside the PACKAGE, and this arm has to prove the copy
    in the planted repo works when invoked by the repo-relative command line that was written into
    its settings. Those are the two things an install can get wrong.
    """
    _declare(repo)
    agent_guard.install_guard(repo)
    settings = json.loads((repo / agent_guard.SETTINGS_REL).read_text(encoding='utf-8'))
    wired = settings['hooks']['PreToolUse'][0]['hooks'][0]['command'].split()
    assert (repo / wired[1]).is_file() and (repo / wired[2]).is_file(), 'the wiring names a path that is not there'

    denied = _ask(repo, wired, 'pytest tests/')
    assert denied is not None, 'the installed guard allowed a bare test line'
    assert 'lab_commons.dev.verify' in denied, denied
    assert _ask(repo, wired, 'git status') is None, 'the installed guard refused an ordinary command'
