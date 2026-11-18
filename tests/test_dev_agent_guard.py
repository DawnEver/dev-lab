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
import re
import subprocess
import venv
from pathlib import Path

import pytest

from dev_lab.dev import agent_guard, agent_wiring, agenthooks, hook_adoption, native_session
from dev_lab.dev.githooks import bash_executable
from dev_lab.dev.hook_adoption import HookAdoption, render
from dev_lab.dev.hooks import DENY_RULES, Remedy, UnremediedRule
from dev_lab.dev.jsrun import node_path
from dev_lab.dev.plugin_settings import DISABLED_PLUGINS, live_disabled_plugins


def _row(command: str) -> dict[str, object]:
    """The settings row the install writes for *command*, its declared timeout included."""
    [timeout] = {row.timeout for row in agent_wiring.rows() if row.command == command}
    return {'type': 'command', 'command': command, 'timeout': timeout}


_ENGINE = _row(agent_wiring.HOOK_COMMAND)
#: The PreToolUse dispatcher: the codeplace write hook before every write. A shell call meets the engine alone.
_PRE = {
    'matcher': 'Write|Edit|MultiEdit|NotebookEdit',
    'hooks': [_row(agent_wiring.dispatch_command('PreToolUse'))],
}

# THE ENGINE RUNS ON THE LOCKED NODE (dev.jsrun), so this file needs no host resource and runs on every part.

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
    path = repo / agent_wiring.RULES_REL
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
    settings = (repo / agent_wiring.SETTINGS_REL).read_text(encoding='utf-8')
    actions = agent_guard.install_guard(repo)
    assert all('already' in action for action in actions), actions
    assert (repo / agent_wiring.SETTINGS_REL).read_text(encoding='utf-8') == settings


def test_a_hand_written_engine_is_foreign_and_refuses_to_be_overwritten(repo: Path) -> None:
    """STATE THREE: FOREIGN. Overwriting somebody's hook is a deletion, so it takes an explicit act."""
    engine = repo / agent_wiring.ENGINE_REL
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
    engine = repo / agent_wiring.ENGINE_REL
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
    settings = repo / agent_wiring.SETTINGS_REL
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
    assert pre[2:] == [{'matcher': 'Bash|PowerShell', 'hooks': [_ENGINE]}, _PRE]


def test_wiring_that_runs_the_engine_with_other_arguments_is_stale(repo: Path) -> None:
    """A matcher naming the engine but a DIFFERENT rules file enforces something else entirely."""
    settings = repo / agent_wiring.SETTINGS_REL
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
    path = repo / agent_wiring.RULES_REL
    path.parent.mkdir(parents=True)
    path.write_text('[ {"name": ', encoding='utf-8')
    assert agent_guard.guard_installation(repo).by_part['rules'].status == agent_guard.STALE


# The shell the tool runs a hook line in, found as the hooks find it: a serve host's scheduled task has
# ``git`` on PATH but no bash (G, 2026-10-24), so a bare lookup would test the PATH rather than the guard.
_SHELL = bash_executable()


def _wired_line(repo: Path) -> str:
    """The installed hook command line, verbatim: the tool's shell runs it with ``$CLAUDE_PROJECT_DIR`` set."""
    settings = json.loads((repo / agent_wiring.SETTINGS_REL).read_text(encoding='utf-8'))
    return settings['hooks']['PreToolUse'][0]['hooks'][0]['command']


def _run_hook(repo: Path, line: str, command: str, *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run the hook EXACTLY as the tool would: the wired line in a POSIX shell, from the session cwd."""
    where = cwd or repo
    payload = {'tool_name': 'Bash', 'tool_input': {'command': command}, 'cwd': str(where)}
    node = node_path().parent.as_posix()
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
    assert (repo / agent_wiring.ENGINE_REL).is_file(), 'the wiring names a path that is not there'
    assert (repo / agent_wiring.RULES_REL).is_file(), 'the wiring names a path that is not there'

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
    (repo / agent_wiring.ENGINE_REL).unlink()
    done = _run_hook(repo, _wired_line(repo), 'git status')
    assert done.returncode == 2, (done.returncode, done.stderr)
    assert 'fail closed' in done.stderr
    assert 'dev_lab.dev.agent_guard --install' in done.stderr
    assert 'hook_install' not in done.stderr, 'the git-hook installer does not restore the agent guard'


_REPAIR = 'node "$CLAUDE_PROJECT_DIR/.claude/hooks/py.js" -m dev_lab.dev.agent_guard --install'


@pytest.mark.parametrize('part', [agent_wiring.ENGINE_REL, agent_wiring.RULES_REL])
def test_a_missing_engine_or_rules_share_one_policy_the_repair_passes(repo: Path, part: str) -> None:
    """dev-lab #639: either part gone refuses every command but the reinstall, naming it."""
    _declare(repo)
    agent_guard.install_guard(repo)
    (repo / part).unlink()
    refused = _run_hook(repo, _wired_line(repo), 'git status')
    assert refused.returncode == 2, (refused.returncode, refused.stderr)
    assert 'dev_lab.dev.agent_guard --install' in refused.stderr
    assert _run_hook(repo, _wired_line(repo), _REPAIR).returncode == 0, 'the guard refused its own repair'
    smuggled = _run_hook(repo, _wired_line(repo), f'git status; {_REPAIR}')
    assert smuggled.returncode == 2, 'PLANTED CONTROL: a command riding along with the repair is still refused'


def test_the_repair_passes_even_a_crashing_engine(repo: Path) -> None:
    _declare(repo)
    agent_guard.install_guard(repo)
    (repo / agent_wiring.ENGINE_REL).write_text('process.exit(1);\n', encoding='utf-8')
    assert _run_hook(repo, _wired_line(repo), f'{_REPAIR} --force').returncode == 0


def test_an_engine_that_crashes_fails_closed_with_a_blocking_exit(repo: Path) -> None:
    """PLANTED CONTROL: the file is there but the engine dies -- still a blocking exit, never an allowed command."""
    _declare(repo)
    agent_guard.install_guard(repo)
    (repo / agent_wiring.ENGINE_REL).write_text('process.exit(1);\n', encoding='utf-8')
    done = _run_hook(repo, _wired_line(repo), 'git status')
    assert done.returncode == 2, (done.returncode, done.stderr)
    assert 'engine exited 1' in done.stderr


def test_the_wiring_matches_every_shell_tool(repo: Path) -> None:
    """A Bash-only matcher leaves the PowerShell tool unguarded, so the install names both."""
    agent_guard.install_guard(repo)
    settings = json.loads((repo / agent_wiring.SETTINGS_REL).read_text(encoding='utf-8'))
    matchers = [entry['matcher'] for entry in settings['hooks']['PreToolUse']]
    assert matchers == ['Bash|PowerShell', _PRE['matcher']]


def test_the_install_ships_the_launcher_and_keeps_one_already_there(tmp_path: Path) -> None:
    """Absent: written. Present: the repo's own door, left as it is."""
    agent_guard.install_guard(tmp_path)
    assert (tmp_path / agent_wiring.LAUNCHER_REL).read_text(encoding='utf-8') == agent_guard.launcher_source()
    other = tmp_path / 'other'
    (other / agent_wiring.LAUNCHER_REL).parent.mkdir(parents=True)
    (other / agent_wiring.LAUNCHER_REL).write_text('// the repo own launcher\n', encoding='utf-8')
    agent_guard.install_guard(other)
    assert (other / agent_wiring.LAUNCHER_REL).read_text(encoding='utf-8') == '// the repo own launcher\n'


def test_the_stray_hook_never_blocks_a_checkout_without_a_venv(tmp_path: Path) -> None:
    """A hook never blocks on a missing venv (decision 7, 2026-10-22): no interpreter, exit 0 and silent."""
    agent_guard.install_guard(tmp_path)
    # The wired line calls a bare `node`, as the tool's shell would; the locked one stands in for the host's.
    node = node_path().parent.as_posix()
    env = {**os.environ, 'CLAUDE_PROJECT_DIR': str(tmp_path), 'PATH': f'{node}{os.pathsep}{os.environ["PATH"]}'}
    done = subprocess.run(
        [_SHELL, '-c', agent_wiring.dispatch_command('Stop')],
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


def test_the_install_turns_off_every_disabled_plugin_and_keeps_a_repo_own() -> None:
    """Ruling 2026-11-05: the forge's PR review is the one review, so the wiring turns sharp-review off."""
    own = {'enabledPlugins': {'rust-analyzer-lsp@claude-plugins-official': True, 'sharp-review@cc-market': True}}
    after = agent_guard.wire_settings(own)
    assert after['enabledPlugins'] == {
        'rust-analyzer-lsp@claude-plugins-official': True,
        **dict.fromkeys(DISABLED_PLUGINS, False),
    }
    assert own['enabledPlugins']['sharp-review@cc-market'] is True, 'the input was mutated'
    assert live_disabled_plugins(after) == []


@pytest.mark.parametrize('planted', [{'sharp-review@cc-market': True}, {}, None])
def test_a_settings_file_enabling_or_omitting_a_disabled_plugin_is_stale(repo: Path, planted: object) -> None:
    """PLANTED CONTROL: the check convicts an enabled plugin AND an absent entry (the user's file enables it)."""
    _declare(repo)
    agent_guard.install_guard(repo)
    settings = repo / agent_wiring.SETTINGS_REL
    document = json.loads(settings.read_text(encoding='utf-8'))
    assert agent_guard.guard_installation(repo).by_part['wiring'].status == agent_guard.INSTALLED
    if planted is None:
        del document['enabledPlugins']
    else:
        document['enabledPlugins'] = planted
    settings.write_text(json.dumps(document), encoding='utf-8')
    wiring = agent_guard.guard_installation(repo).by_part['wiring']
    assert wiring.status == agent_guard.STALE
    assert 'sharp-review@cc-market' in wiring.detail
    agent_guard.install_guard(repo)
    assert agent_guard.guard_installation(repo).by_part['wiring'].status == agent_guard.INSTALLED


def test_the_rules_file_is_written_from_the_repos_declared_adoption(repo: Path) -> None:
    """``python -m dev_lab.dev.hook_adoption --adoption <module>``: the renderer a relock re-runs (forge sync).

    PLANTED CONTROL: before the render the file is absent, so a pass is the write and not a reader of nothing.
    """
    module = repo / 'scripts' / 'deny_rules.py'
    module.parent.mkdir(parents=True)
    module.write_text(
        'from dev_lab.dev.hook_adoption import HookAdoption\n'
        'from dev_lab.dev.hooks import Remedy\n'
        "ADOPTION = HookAdoption(app_name='planted', "
        "remedies={'BARE-TEST-INVOCATION': Remedy('verdict-entry-point', 'python -m dev_lab.dev.verify')}, "
        "declared_absent=frozenset({'NETWORK-VERB', 'PUSH-NO-VERIFY', 'RAW-PROCESS-KILL'}))\n",
        encoding='utf-8',
    )
    assert not (repo / agent_wiring.RULES_REL).exists()
    assert hook_adoption.main(['--repo', str(repo), '--adoption', 'scripts/deny_rules.py']) == 0
    assert (repo / agent_wiring.RULES_REL).read_text(encoding='utf-8') == render(ADOPTION)


def test_a_declared_adoption_modules_local_rules_survive_the_render(repo: Path) -> None:
    """A module's ``LOCAL_RULES`` -- rows the family registry cannot hold -- render after the family rows.

    PLANTED CONTROL: the planted row is absent from the family render, so a pass is the local half and not a
    re-render of the registry alone, which would delete it (a downstream repo's 2026-11-10 forge-sync refusal).
    """
    waived = frozenset({'BARE-TEST-INVOCATION', 'NETWORK-VERB', 'PUSH-NO-VERIFY', 'RAW-PROCESS-KILL'})
    module = repo / 'scripts' / 'deny_rules.py'
    module.parent.mkdir(parents=True)
    module.write_text(
        'from dev_lab.dev.hook_adoption import HookAdoption\n'
        'from dev_lab.dev.hooks import DenyRule\n'
        f"ADOPTION = HookAdoption(app_name='planted', declared_absent=frozenset({sorted(waived)!r}))\n"
        "LOCAL_RULES = (DenyRule(id='PLANTED-LOCAL', pattern='planted-verb', "
        "hazard='a planted hazard', remedy='run the planted door'),)\n",
        encoding='utf-8',
    )
    family = HookAdoption(app_name='planted', declared_absent=waived)
    assert 'PLANTED-LOCAL' not in [row['name'] for row in json.loads(render(family))]
    assert hook_adoption.main(['--repo', str(repo), '--adoption', 'scripts/deny_rules.py']) == 0
    names = [row['name'] for row in json.loads((repo / agent_wiring.RULES_REL).read_text(encoding='utf-8'))]
    assert names[-1] == 'PLANTED-LOCAL'


def test_a_local_rule_shadowing_a_family_rule_is_refused() -> None:
    """A local row reusing a family id is the fork the split exists to prevent; the render refuses it."""
    with pytest.raises(UnremediedRule, match=DENY_RULES[0].id):
        render(HookAdoption(app_name='planted'), local=(DENY_RULES[0],))


def _venv_with_dev_lab_at(root: Path, installed: str, locked: str) -> dict[str, str]:
    """*root* a checkout whose venv holds a dev-lab at *installed* and whose ``uv.lock`` pins *locked*."""
    agent_guard.install_guard(root)
    venv.EnvBuilder(with_pip=False).create(root / '.venv')
    site = next((root / '.venv').glob('**/site-packages'))
    info = site / 'dev_lab-0.dist-info'
    info.mkdir()
    (info / 'METADATA').write_text('Metadata-Version: 2.1\nName: dev-lab\nVersion: 0\n', encoding='utf-8')
    origin = {'url': 'https://example.invalid/dev-lab.git', 'vcs_info': {'vcs': 'git', 'commit_id': installed}}
    (info / 'direct_url.json').write_text(json.dumps(origin), encoding='utf-8')
    pin = f'source = {{ git = "{origin["url"]}#{locked}" }}'
    # Text mode: CRLF on Windows, as a checked-out lock may be -- the launcher reads both.
    (root / 'uv.lock').write_text(f'[[package]]\nname = "dev-lab"\nversion = "0"\n{pin}\n', encoding='utf-8')
    node = node_path().parent.as_posix()
    return {
        **os.environ,
        'CLAUDE_PROJECT_DIR': str(root),
        'CLAUDE_CODE_SESSION_ID': 'planted',
        'PATH': f'{node}{os.pathsep}{os.environ["PATH"]}',
    }


def _bind(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_SHELL, '-c', agent_wiring.dispatch_command('UserPromptSubmit')],
        input='{}', capture_output=True, text=True, encoding='utf-8', env=env, check=False,
    )  # fmt: skip


def test_a_stale_venv_names_its_fix_and_records_the_wall(tmp_path: Path) -> None:
    """2026-11-13: a venv behind its lock failed a hook with only ``No module named``; now cause, door, wall, exit 0."""
    done = _bind(_venv_with_dev_lab_at(tmp_path, 'a' * 40, 'b' * 40))
    assert done.returncode == 0, done.stderr
    [line] = done.stderr.splitlines()
    assert 'aaaaaaaaaa is behind' in line, line
    assert "lock's bbbbbbbbbb" in line, line
    assert f'-m dev_lab.dev.dep --bootstrap {tmp_path}' in line, line
    [wall] = [
        json.loads(raw)
        for path in tmp_path.glob('output/logs/*/*/*/walls/walls.jsonl')
        for raw in path.read_text(encoding='utf-8').splitlines()
    ]
    assert (wall['rule'], wall['remedy_present'], wall['session']) == ('VENV-FOLLOWS-THE-LOCK', True, 'planted')


def test_a_stale_venv_missing_a_verb_names_its_fix_and_lets_the_prompt_through(tmp_path: Path) -> None:
    """2026-11-16: an older dev-lab whose argparse lacks the hook's verb exited 2 and blocked every prompt."""
    env = _venv_with_dev_lab_at(tmp_path, 'a' * 40, 'b' * 40)
    probe = 'import sys; sys.stderr.write("error: argument verb: invalid choice: \'bind\'\\n"); sys.exit(2)'
    done = subprocess.run(
        [str(node_path()), str(tmp_path / agent_wiring.LAUNCHER_REL), '-c', probe],
        input='{}', capture_output=True, text=True, encoding='utf-8', env=env, cwd=tmp_path, check=False,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    assert 'bind missing' in done.stderr
    assert '-m dev_lab.dev.dep --bootstrap' in done.stderr
    current = _venv_with_dev_lab_at(tmp_path / 'current', 'c' * 40, 'c' * 40)
    same = subprocess.run(
        [str(node_path()), str(tmp_path / 'current' / agent_wiring.LAUNCHER_REL), '-c', probe],
        input='{}', capture_output=True, text=True, encoding='utf-8', env=current, cwd=tmp_path / 'current',
        check=False,
    )  # fmt: skip
    assert same.returncode == 0, 'dev-lab #639: a current venv lacking the verb is a wiring fault, never a block'
    assert 'behind' not in same.stderr
    assert 'agent_guard --install' in same.stderr, 'a current venv is told to re-render the wiring'


def test_the_stale_python_launcher_keeps_the_native_codex_wall_identity(tmp_path: Path) -> None:
    env = _venv_with_dev_lab_at(tmp_path, 'a' * 40, 'b' * 40)
    env.pop('CLAUDE_CODE_SESSION_ID', None)
    env.pop('CLAUDE_PROJECT_DIR', None)
    env['CODEX_THREAD_ID'] = 'native-codex'
    done = subprocess.run(
        [str(node_path()), str(tmp_path / agent_wiring.LAUNCHER_REL), '-m', 'dev_lab.dev.forgefeed', 'inbox'],
        input='{}', capture_output=True, text=True, encoding='utf-8', env=env, cwd=tmp_path, check=False,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    assert '-m dev_lab.dev.dep --bootstrap' in done.stderr
    [wall] = [
        json.loads(raw)
        for path in tmp_path.glob('output/logs/*/*/*/walls/walls.jsonl')
        for raw in path.read_text(encoding='utf-8').splitlines()
    ]
    assert (wall['rule'], wall['remedy_present'], wall['session']) == ('VENV-FOLLOWS-THE-LOCK', True, 'native-codex')


@pytest.mark.parametrize(
    ('value', 'accepted'),
    [
        ('é_9.-', True),
        ('𐐀' * 128, True),
        ('Ⅳ²', True),
        ('a' * 128, True),
        ('𐐀' * 129, False),
        ('valid\n', False),
        ('e\u0301', False),
        ('x\u200b', False),
        ('role:integrator', False),
    ],
)
def test_the_installed_node_launcher_and_python_share_the_exact_native_identity_grammar(
    tmp_path: Path, value: str, *, accepted: bool
) -> None:
    agent_guard.install_guard(tmp_path)
    env = {**os.environ, 'CODEX_THREAD_ID': value}
    for field in ('CLAUDE_CODE_SESSION_ID', 'CLAUDE_PROJECT_DIR', 'CODEX_SESSION_ID'):
        env.pop(field, None)
    done = subprocess.run(
        [str(node_path()), str(tmp_path / agent_wiring.LAUNCHER_REL)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
    )
    if accepted:
        assert native_session.session_of({'CODEX_THREAD_ID': value}) == value
        assert done.returncode == 0, done.stderr
        assert 'no .venv interpreter' in done.stderr
    else:
        with pytest.raises(ValueError, match='Door:'):
            native_session.session_of({'CODEX_THREAD_ID': value})
        assert done.returncode == 1
        assert 'native session' in done.stderr
        assert 'Door:' in done.stderr
        assert value not in done.stderr


@pytest.mark.parametrize('contents', [None, '{', '{}', '[]'])
def test_the_installed_launcher_refuses_a_missing_or_corrupt_identity_companion(
    tmp_path: Path, contents: str | None
) -> None:
    agent_guard.install_guard(tmp_path)
    catalog = (tmp_path / agent_wiring.LAUNCHER_REL).with_name('native_session.json')
    if contents is None:
        catalog.unlink()
    else:
        catalog.write_text(contents, encoding='utf-8')
    done = subprocess.run(
        [str(node_path()), str(tmp_path / agent_wiring.LAUNCHER_REL)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
    )
    assert done.returncode == 1
    assert 'native session catalog' in done.stderr
    assert 'Door:' in done.stderr


def test_a_missing_module_from_a_current_venv_lets_the_prompt_through_naming_itself(tmp_path: Path) -> None:
    """dev-lab #639: a venv matching its lock but missing the module still never blocks; it is no stale-venv wall."""
    done = _bind(_venv_with_dev_lab_at(tmp_path, 'c' * 40, 'c' * 40))
    assert done.returncode == 0, done.stderr
    [line] = done.stderr.splitlines()
    assert '(dev_lab' in line, line
    assert '-m dev_lab.dev.dep --bootstrap' in line, line
    assert 'behind' not in done.stderr
    assert not list(tmp_path.glob('output/logs/*/*/*/walls/walls.jsonl'))


def _ours(settings: dict) -> list[dict]:
    return [h for es in settings['hooks'].values() for e in es for h in e['hooks'] if h in _RENDERED]


_RENDERED = [_row(row.command) for row in agent_wiring.rows()]


def test_settings_carry_the_engine_and_one_dispatcher_row_per_event() -> None:
    """dev-lab #640: a settings row names only its event, so no handler a lagging venv lacks is ever named.

    PLANTED CONTROL: a module path in a rendered row other than the dispatcher's would be a row naming a handler.
    """
    after = agent_guard.wire_settings({})
    commands = [h['command'] for h in _ours(after)]
    assert len(commands) == 1 + len(agent_wiring.events())
    dispatched = [c for c in commands if c != agent_wiring.HOOK_COMMAND]
    assert all(c.endswith(f'-m {agent_wiring.DISPATCH_MODULE} {c.split()[-1]}') for c in dispatched), dispatched
    assert {c.split()[-1] for c in dispatched} == set(agent_wiring.events())
    for wire in agent_wiring.WIRING:
        assert not any(wire.module in c for c in commands), f'a rendered row names the handler {wire.name}'


def test_a_rows_matcher_derives_from_its_handlers_and_its_timeout_is_the_ceiling() -> None:
    """The matcher is the union of the handlers' tools (none when one sees every call); the bound is the ceiling."""
    by_event = {row.event: row for row in agent_wiring.rows() if row.command != agent_wiring.HOOK_COMMAND}
    assert by_event['PreToolUse'].matcher == 'Write|Edit|MultiEdit|NotebookEdit'
    assert by_event['UserPromptSubmit'].matcher is None
    for event, row in by_event.items():
        assert row.timeout == agent_wiring.HOOK_TIMEOUT_S, event


@pytest.mark.parametrize('tool', agent_wiring.SHELL_TOOLS)
def test_a_shell_call_meets_exactly_one_pre_tool_command_the_engine(tool: str) -> None:
    """ONE interpreter per shell call: every PreToolUse check of a command is an engine row, never a Python handler.

    PLANTED CONTROL: the codeplace write hook's row does match a Write call, so the matcher test can say yes.
    """
    pre = agent_guard.wire_settings({})['hooks']['PreToolUse']

    def commands_for(name: str) -> list[str]:
        return [
            hook['command']
            for entry in pre
            if 'matcher' not in entry or re.fullmatch(entry['matcher'], name)
            for hook in entry['hooks']
        ]

    assert commands_for(tool) == [agent_wiring.HOOK_COMMAND]
    assert agent_wiring.dispatch_command('PreToolUse') in commands_for('Write')


def test_the_renderer_owns_every_launcher_row_and_keeps_foreign_hooks() -> None:
    """No retired-wire list: any launcher row running a dev_lab.dev module is ours, removed unless rendered.

    Planted: a retired handler, a hand-wired cwd-relative codeplace row beside a repo's own launcher script, a
    foreign hook. Only the foreign hook and the repo's own script survive; wiring twice changes nothing.
    """
    own = {'type': 'command', 'command': 'node .claude/hooks/py.js scripts/hooks/doc_principles.py'}
    foreign = {'type': 'command', 'command': 'node log.js'}
    retired = {'type': 'command', 'command': 'node "$CLAUDE_PROJECT_DIR/.claude/hooks/py.js" -m dev_lab.dev.pushwatch'}
    hand = {'type': 'command', 'command': 'node .claude/hooks/py.js -m dev_lab.dev.codeplace'}
    planted = {
        'hooks': {
            'PreToolUse': [{'matcher': 'Edit|Write', 'hooks': [own, hand]}],
            'PostToolUse': [{'matcher': 'Bash|PowerShell', 'hooks': [foreign, retired]}],
            'Notification': [{'hooks': [retired]}],
        }
    }
    after = agent_guard.wire_settings(planted)
    assert agent_guard.wire_settings(after) == after
    assert after['hooks']['PreToolUse'][0] == {'matcher': 'Edit|Write', 'hooks': [own]}
    assert after['hooks']['PostToolUse'][0] == {'matcher': 'Bash|PowerShell', 'hooks': [foreign]}
    assert 'Notification' not in after['hooks'], 'an event left with no hook stays as an empty list'
    assert sorted(map(json.dumps, _ours(after))) == sorted(map(json.dumps, _RENDERED))
    assert planted['hooks']['PostToolUse'][0]['hooks'] == [foreign, retired], 'the input was mutated'


def test_a_drifted_or_extra_owned_row_is_stale_and_the_install_restores_it(repo: Path) -> None:
    """The report reads what the renderer writes. PLANTED: a stripped timeout, a lost event, an extra handler row."""
    _declare(repo)
    agent_guard.install_guard(repo)
    path = repo / agent_wiring.SETTINGS_REL
    rendered = json.loads(path.read_text(encoding='utf-8'))
    extra = {'type': 'command', 'command': 'node "$CLAUDE_PROJECT_DIR/.claude/hooks/py.js" -m dev_lab.dev.handback'}
    plants = {
        'timeout': lambda s: s['hooks']['Stop'][-1]['hooks'][0].pop('timeout'),
        'event': lambda s: s['hooks'].pop('SubagentStop'),
        'extra': lambda s: s['hooks']['Stop'].append({'hooks': [extra]}),
    }
    for name, plant in plants.items():
        settings = json.loads(json.dumps(rendered))
        plant(settings)
        path.write_text(json.dumps(settings), encoding='utf-8')
        part = agent_guard.guard_installation(repo).by_part['wiring']
        assert part.status == agent_guard.STALE, name
        agent_guard.install_guard(repo)
        assert agent_guard.guard_installation(repo).by_part['wiring'].status == agent_guard.INSTALLED, name


# ------------------------------------------------------------------------------------- a repo's own declared wires


def _declare_wire(repo: Path, module: str, row: str) -> None:
    """The repo declares one ``[[tool.dev_lab.agent_hooks]]`` row, its handler a module at the repo's root."""
    (repo / 'pyproject.toml').write_text(
        f'[[tool.dev_lab.agent_hooks]]\nmodule = "{module}"\n{row}\n', encoding='utf-8'
    )
    (repo / f'{module}.py').write_text('def main(argv):\n    return 0\n', encoding='utf-8')


def test_rows_derive_matcher_from_the_family_and_the_repo_declaration(repo: Path) -> None:
    _declare_wire(repo, 'planted_guard_wire_a', 'events = ["PreToolUse", "PreCompact"]\ntools = ["Read"]\ntimeout = 1')
    family = {row.event: row for row in agent_wiring.rows()}
    merged = {row.event: row for row in agent_wiring.rows(repo)}
    assert merged['PreToolUse'].matcher == f'{family["PreToolUse"].matcher}|Read'
    assert merged['PreToolUse'].timeout == family['PreToolUse'].timeout == agent_wiring.HOOK_TIMEOUT_S
    assert merged['PreCompact'] == agent_wiring.Row(
        'PreCompact', 'Read', agent_wiring.dispatch_command('PreCompact'), agent_wiring.HOOK_TIMEOUT_S
    )
    assert 'PreCompact' not in family, 'PLANTED CONTROL: the family alone serves no such event'


def test_the_drift_check_counts_a_repo_declared_wire_and_the_install_renders_it(repo: Path) -> None:
    _declare(repo)
    agent_guard.install_guard(repo)
    assert agent_guard.guard_installation(repo).by_part['wiring'].status == agent_guard.INSTALLED
    _declare_wire(repo, 'planted_guard_wire_b', 'events = ["PreCompact"]')
    part = agent_guard.guard_installation(repo).by_part['wiring']
    assert part.status == agent_guard.STALE
    assert 'PreCompact' in part.detail
    agent_guard.install_guard(repo)
    assert agent_guard.guard_installation(repo).by_part['wiring'].status == agent_guard.INSTALLED
    settings = json.loads((repo / agent_wiring.SETTINGS_REL).read_text(encoding='utf-8'))
    [entry] = settings['hooks']['PreCompact']
    assert entry['hooks'][0]['command'] == agent_wiring.dispatch_command('PreCompact')


def test_a_refused_declaration_is_stale_by_name_and_the_install_refuses_it(repo: Path) -> None:
    _declare(repo)
    agent_guard.install_guard(repo)
    (repo / 'pyproject.toml').write_text(
        '[[tool.dev_lab.agent_hooks]]\nevents = ["Stop"]\nmodule = "missing_guard_wire"\n', encoding='utf-8'
    )
    part = agent_guard.guard_installation(repo).by_part['wiring']
    assert part.status == agent_guard.STALE
    assert 'missing_guard_wire' in part.detail
    with pytest.raises(agent_wiring.WireRefused, match='missing_guard_wire'):
        agent_guard.install_guard(repo)
