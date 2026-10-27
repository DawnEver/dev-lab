"""The shipped ENGINE, DRIVEN -- real command strings in, the real deny decision out.

NOTHING HERE IS MOCKED, and that is the whole design of this file. The engine is the one artefact in
this family whose correctness cannot be argued from Python: it decides what a shell line will
EXECUTE, and every defect it has had was a disagreement between that decision and a reader's belief
about it. So each arm builds a real ``deny-rules.json`` out of the shared registry, feeds a real hook
payload to ``node``, and asserts the verdict that comes back.

THE FIVE ARMS THAT ARE INCIDENTS RATHER THAN EXAMPLES:

* the WRAPPER case. ``timeout 900 pytest`` invokes two commands and anchoring at the first alone
  misses the second; six shapes slipped through when that was measured (2026-09-01).
* the HEREDOC EVASION, measured 2026-08-22: an agent ran pytest through ``python - <<EOF ...
  pytest.main([...]) ... EOF`` and disclosed it. A CLOSED incident, pinned here so it stays closed.
* the two CROSSED, measured 2026-09-17: ``uv run python - <<PY ... PY``. The heredoc arm asked only
  the segment's FIRST WORD whether it was an interpreter, so any wrapper in front of ``python`` put
  the body back into the data class and reopened the arm above. It was allowed by EVERY copy of the
  engine in this family; the one repo whose rules name ``uv run`` refused it for an unrelated
  reason, which is precisely what made the hole read as closed.
* the other side of the same coin -- a heredoc consumed by a SINK is DATA. ``cat > notes.md <<EOF``
  writing the words ``uv sync`` is documentation, and refusing it fired twice in one session while
  the author was recording why the rule is right.
* the FALSE POSITIVE, repaid 2026-09-17: a command that merely CONTAINS a denied word in a string
  (``grep -rn "pytest" src``) runs grep, and a guard that refuses the sentence describing it is not
  strict, it is imprecise.

THE FLOOR IS THE ROWS' OWN PROOF. Every registry row carries ``refuses``/``permits`` controls, and
:func:`test_every_registry_row_behaves_through_the_real_engine` drives all of them through ``node``
with a count floor -- so an empty registry, an engine that denied nothing, or one that denied
everything all red instead of reading as green.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

if os.name == 'nt':
    import _winapi

from dev_lab.dev import agenthooks
from dev_lab.dev.hook_adoption import HookAdoption, render
from dev_lab.dev.hooks import DENY_RULES, Remedy
from dev_lab.dev.metrics import REFUSAL, read

# THE ENGINE RUNS ON `node`, A REQUIREMENT OF THE HOST: the `node` marker assigns this file to the parts
# whose hosts have it ([tool.lab_commons.tests] resources). Where it runs and node is absent, `NoNode` still reds.
pytestmark = pytest.mark.workstation

#: An adoption that remedies EVERY rule needing a repo artefact, so the rendered file carries the
#: whole registry. The commands are this repo's own real ones where they exist; what matters to the
#: engine is the reason text, and what matters here is that no row is silently dropped.
ADOPTION = HookAdoption(
    app_name='lab-commons (suite)',
    remedies={
        'BARE-TEST-INVOCATION': Remedy('verdict-entry-point', '.venv/Scripts/python.exe -m dev_lab.dev.verify'),
        'PUSH-NO-VERIFY': Remedy('verdict-entry-point', '.venv/Scripts/python.exe -m dev_lab.dev.verify'),
        'NETWORK-VERB': Remedy('retry-wrapper', 'sh {root}/scripts/hooks/with-retry.sh push'),
        'RAW-PROCESS-KILL': Remedy('process-tree-killer', '.venv/Scripts/python.exe -m dev_lab.dev.stop --pid N'),
    },
)

#: The floor on the registry-wide scan below: rows times their own controls. MEASURED 2026-09-17 --
#: 7 rows carrying 24 ``refuses`` and 19 ``permits``. Set under the measurement on purpose: a floor
#: refuses an UNREAD registry, it is not a second pin on the count.
CONTROL_FLOOR = 30


@pytest.fixture(scope='module')
def rules(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A real ``deny-rules.json``, rendered from the shared registry exactly as a repo ships it."""
    path = tmp_path_factory.mktemp('rules') / 'deny-rules.json'
    path.write_text(render(ADOPTION), encoding='utf-8')
    return path


def test_the_package_ships_an_engine_and_it_carries_its_stamp() -> None:
    """The payload half: an engine that ships without its stamp cannot be told from a stranger's."""
    assert agenthooks.ENGINES, 'no engine ships in this package -- the registry would have nothing to run'
    for name in agenthooks.ENGINES:
        text = agenthooks.engine_path(name).read_text(encoding='utf-8')
        assert agenthooks.STAMP in text, f'{name} ships unstamped; agent_guard could not recognise an installed copy'


def test_a_plainly_denied_command_is_denied_with_its_remedy(rules: Path) -> None:
    """The base case, and the reason text must carry the EXIT -- a sealed road gets routed around."""
    reason = agenthooks.decide('pytest tests/', rules)
    assert reason is not None, 'a bare pytest line was allowed; the guard refuses nothing'
    assert 'dev_lab.dev.verify' in reason, f'denied with no exit to take: {reason!r}'


def test_an_ordinary_command_is_allowed(rules: Path) -> None:
    """The other side of the ratchet: a guard that denies everything is not a guard."""
    assert agenthooks.decide('git status --short', rules) is None


def test_a_denied_verb_behind_an_allowed_wrapper_is_still_denied(rules: Path) -> None:
    """THE WRAPPER CASE. A segment has as many command positions as it has wrappers."""
    for command in ('timeout 900 pytest tests/', 'nohup git push --force origin HEAD', 'env sudo pytest -q'):
        assert agenthooks.decide(command, rules) is not None, f'the wrapper hid the command: {command!r}'


def test_the_heredoc_evasion_stays_closed(rules: Path) -> None:
    """THE 2026-08-22 INCIDENT. The denied command sits in a NON-FIRST position inside the body."""
    command = 'python - <<EOF\nimport os\nprint(os.getcwd())\npytest.main(["-q", "tests"])\nEOF'
    reason = agenthooks.decide(command, rules)
    assert reason is not None, 'pytest ran through a heredoc body and the guard did not see it -- the evasion reopened'


def test_a_wrapper_cannot_hide_the_interpreter_that_consumes_a_heredoc(rules: Path) -> None:
    """THE 2026-08-22 EVASION, REOPENED BY A WRAPPER AND MEASURED 2026-09-17.

    A heredoc body is scanned only when its CONSUMER is an interpreter, and the consumer was read as
    the segment's FIRST WORD. So `uv run python - <<PY` and `timeout 900 python - <<PY` read as `uv`
    and `timeout`, the body was classified as data, and `pytest.main(...)` inside it was never seen.
    Both were ALLOWED by every copy of the engine in this family before this test existed; the repo
    whose rules happened to name `uv run` refused the first one for an UNRELATED reason, which is
    what made the hole look closed.

    The fix is not a new interpreter list: `commandPositions` already enumerates what a segment
    runs, and the heredoc test now asks ALL of them instead of position zero.
    """
    body = '\nimport os\nprint(os.getcwd())\npytest.main(["-q", "tests"])\nPY'
    for command in (
        'uv run python - <<PY' + body,
        'uvx python - <<PY' + body,
        'timeout 900 python - <<PY' + body,
        'nohup uv run python - <<PY' + body,
        # The plain wrapped invocations too. These are SHELL LINES, so they cannot live in the
        # registry row's `refuses` (whose examples are segments) -- this is their only home, and
        # `uv run pytest` was moved here out of that row rather than dropped.
        'uv run pytest',
        'uvx pytest -q',
    ):
        assert agenthooks.decide(command, rules) is not None, (
            f'a wrapper hid the interpreter and the heredoc body went unscanned: {command.splitlines()[0]!r}'
        )


#: THE 2026-10-20 INCIDENT LINES, verbatim, plus their sibling prefixes. SHELL LINES, so their home is
#: here rather than the registry row's segment-shaped `refuses`.
_PREFIXED_BARE_TESTS = (
    (
        'cd /d/Documents/MingyangBao/motronics-studio/.claude/worktrees/longrun-js && .venv/Scripts/python.exe'
        ' -m pytest -q -x tests/unit/hamilton/adapters/jmag/ -k "job_system or system_check or jobs"'
        ' -p no:cacheprovider 2>&1 | tail -5'
    ),
    'timeout 1200 .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/unit/x.py 2>&1 | grep passed',
    'export LAB_COMMONS_CONFIG=/d/x/machine.toml; .venv/Scripts/python.exe -m pytest -q tests/unit/x.py',
    'VAR=x python -m pytest',
    'nohup .venv/Scripts/python.exe -m pytest tests &',
    '(cd x && pytest)',
)


@pytest.mark.parametrize('command', _PREFIXED_BARE_TESTS)
def test_a_bare_test_line_behind_a_prefix_is_refused(rules: Path, command: str) -> None:
    """`cd ... &&`, `timeout N`, `export ...;`, `VAR=x`, `nohup ... &` and a subshell hide nothing."""
    assert agenthooks.decide(command, rules) is not None, f'a prefix hid the bare test line: {command!r}'


def test_the_measure_door_behind_the_same_prefixes_is_admitted(rules: Path) -> None:
    """THE OTHER SIDE: the verdict door is not caught by the same prefixes."""
    door = '.venv/Scripts/python.exe -m dev_lab.dev.verify -- tests/unit/x.py'
    for command in (door, f'cd /d/x && {door} 2>&1 | tail -5', f'timeout 1200 {door}'):
        assert agenthooks.decide(command, rules) is None, f'the measure door was refused: {command!r}'


def test_uv_run_is_a_wrapper_but_uv_itself_is_still_a_command(tmp_path: Path) -> None:
    """THE RATCHET'S OTHER SIDE.

    `uv run X` unwraps to X, but `uv sync`/`uv add`/`uv pip` are commands in their own right:
    stripping a bare `uv` would leave the segment reading `sync`, and a
    rule naming `uv sync` -- consumer-a ships one, this registry does not -- would go quiet.

    Driven through a rule this test writes, because the property belongs to the ENGINE and no
    shipped row depends on it yet. A consumer's rule must not be the only thing that notices.
    """
    uv_rule = tmp_path / 'uv-rules.json'
    uv_rule.write_text(
        json.dumps(
            [
                {
                    'name': 'UV-MUTATES',
                    'pattern': r'uv\s+(?:sync|add|pip)\b',
                    'matches': 'command',
                    'reason': 'mutates the shared venv',
                }
            ]
        ),
        encoding='utf-8',
    )
    for intact in ('uv sync', 'uv add ruff', 'uv pip install x', 'timeout 60 uv sync'):
        assert agenthooks.decide(intact, uv_rule) is not None, f'`uv` was unwrapped as a wrapper, hiding {intact!r}'
    assert agenthooks.decide('uv run python script.py', uv_rule) is None, '`uv run` is not a venv mutation'


def test_a_heredoc_consumed_by_a_sink_is_data_and_is_not_denied(rules: Path) -> None:
    """The other direction: a body a SINK consumes is documentation, and refusing it is imprecision."""
    command = 'cat > notes.md <<EOF\nWhy the rule exists: pytest tests/ has no verdict.\nEOF'
    assert agenthooks.decide(command, rules) is None, 'writing prose ABOUT a denied command was refused'


def test_a_command_that_merely_contains_a_denied_word_is_not_denied(rules: Path) -> None:
    """THE MEASURED FALSE POSITIVE. These run grep, git-log and git-commit -- not the named verb."""
    for command in (
        'grep -n "pytest" src/a.py',
        'git log --oneline -- tests/test_dev_verify.py',
        'git commit -m "mention a push in prose"',
        'echo "git push origin main"',
    ):
        assert agenthooks.decide(command, rules) is None, f'a string containing a denied word was refused: {command!r}'


def test_every_registry_row_behaves_through_the_real_engine(rules: Path) -> None:
    """THE SCAN, WITH ITS FLOOR: every row's own controls, driven through ``node``."""
    checked = 0
    wrong: list[str] = []
    shipped = {row['name'] for row in json.loads(rules.read_text(encoding='utf-8'))}
    for rule in DENY_RULES:
        if rule.id not in shipped:
            continue
        # A scoped row is judged where its scope holds -- inside a subagent -- and its refusals are
        # ALSO driven outside it, where this row must not be the one that fires (the planted control).
        agent = 'scan-agent' if rule.scope == 'subagent' else None
        for command in rule.refuses:
            checked += 1
            if rule.when == 'live-run':
                # No run is live in a scan tree: the row must stay SILENT (its live half is test_dev_liverun's).
                decided = agenthooks.decide(command, rules)
                if decided is not None and decided.startswith(f'{rule.id}:'):
                    wrong.append(f'{rule.id}: fired with no live run on {command!r}')
                continue
            # A hint row is SAID, unless a sibling refusal fires on the same command and wins (`git clone`).
            hint = rule.severity == 'hint'
            said_or_refused = agenthooks.decide(command, rules, agent_id=agent, hint=hint) or (
                hint and agenthooks.decide(command, rules, agent_id=agent)
            )
            if not said_or_refused:
                said = 'never HINTED on' if hint else 'ALLOWED'
                wrong.append(f'{rule.id}: the engine {said} a command the row says it fires on: {command!r}')
            outside = agenthooks.decide(command, rules) if agent else None
            if outside is not None and outside.startswith(f'{rule.id}:'):
                wrong.append(f'{rule.id}: the scoped row fired OUTSIDE a subagent on {command!r}')
        for command in rule.permits:
            checked += 1
            if agenthooks.decide(command, rules, agent_id=agent) is not None:
                wrong.append(f'{rule.id}: the engine DENIED a near-miss the row permits: {command!r}')
    assert checked >= CONTROL_FLOOR, (
        f'only {checked} controls reached the engine, below the {CONTROL_FLOOR} floor. Finding nothing wrong '
        f'in an unread registry is not a green result. Fix the corpus, do not lower the floor.'
    )
    assert wrong == [], '\n'.join(wrong)


def test_the_engine_fails_open_on_an_unreadable_rules_file(tmp_path: Path) -> None:
    """FAIL-OPEN BY CONSTRUCTION: a typo in the data file must not lock a session.

    Pinned because it is a property a reader would otherwise assume the opposite of, and because the
    honest report for it is ``None`` -- nothing was refused -- rather than an exception here.
    """
    broken = tmp_path / 'deny-rules.json'
    broken.write_text('[ {"name": "x", ', encoding='utf-8')
    assert agenthooks.decide('pytest tests/', broken) is None


# --------------------------------------------------------------------------------------------
# run_engine -- the ONE runner, and the path is how a caller says whose copy


def test_run_engine_drives_the_file_it_is_handed_and_not_the_shipped_one(rules: Path, tmp_path: Path) -> None:
    """THE POINT OF THE PATH. A stub at another location must decide, or the argument is decoration."""
    stub = tmp_path / 'stub-engine.js'
    stub.write_text(
        "let raw='';process.stdin.on('data',c=>{raw+=c;});process.stdin.on('end',()=>{"
        "process.stdout.write(JSON.stringify({hookSpecificOutput:{hookEventName:'PreToolUse',"
        "permissionDecision:'deny',permissionDecisionReason:'STUB-ENGINE'}}));});",
        encoding='utf-8',
    )
    assert agenthooks.run_engine(stub, 'echo hello', rules) == 'STUB-ENGINE'
    assert agenthooks.decide('echo hello', rules) is None, 'the shipped engine must be untouched by the stub'


def test_run_engine_refuses_an_absent_engine_or_rules_file_rather_than_allowing(rules: Path, tmp_path: Path) -> None:
    """``None`` MEANS ALLOWED, so a missing file must raise: silence here would read as permission."""
    with pytest.raises(agenthooks.EngineNotReadable, match='not a file'):
        agenthooks.run_engine(tmp_path / 'nothing.js', 'echo hello', rules)
    with pytest.raises(agenthooks.EngineNotReadable, match='not a file'):
        agenthooks.run_engine(agenthooks.engine_path(), 'echo hello', tmp_path / 'nothing.json')


def test_decide_is_run_engine_over_the_shipped_copy(rules: Path) -> None:
    """One runner, two spellings of WHOSE: a name reaches the wheel, a path reaches a checkout."""
    for command in ('pytest tests/', 'git status --short'):
        assert agenthooks.decide(command, rules) == agenthooks.run_engine(agenthooks.engine_path(), command, rules)


# --------------------------------------------------------------------------------------------
# DOORS PER REPO -- a refusal names the exit of the repo the COMMAND targets, not the session's
#
# MEASURED 2026-10-04: a session started in one repo refused commands an agent ran inside ANOTHER
# repo and named the first repo's runner and dated-path script, neither of which exists there. The
# rules come from the session root; the exit must come from the target.

SESSION_DOOR = 'python scripts/session_only/runner.py measure'
TARGET_DOOR = 'python -m target_only.verify'


@pytest.fixture
def two_repos(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A session repo whose rules name its own door, and a target repo declaring a different one."""
    session, target = tmp_path / 'session', tmp_path / 'target'
    for repo in (session, target):
        (repo / '.git').mkdir(parents=True)
    hooks = session / '.claude' / 'hooks'
    hooks.mkdir(parents=True)
    adoption = HookAdoption(
        app_name='session',
        remedies={
            'BARE-TEST-INVOCATION': Remedy('verdict-entry-point', SESSION_DOOR),
            'PUSH-NO-VERIFY': Remedy('verdict-entry-point', SESSION_DOOR),
        },
        declared_absent=frozenset({'NETWORK-VERB', 'RAW-PROCESS-KILL'}),
    )
    rules = hooks / 'deny-rules.json'
    rules.write_text(render(adoption), encoding='utf-8')
    (target / 'pyproject.toml').write_text(
        '[project]\nname = "t"\n\n[tool.dev_lab.doors]\n'
        f'BARE-TEST-INVOCATION = "{TARGET_DOOR}"\n'
        f"PUSH-NO-VERIFY = '{TARGET_DOOR}'\n\n[tool.other]\nx = 1\n",
        encoding='utf-8',
    )
    return session, target, rules


def _names_target_door(reason: str | None) -> bool:
    return reason is not None and TARGET_DOOR in reason and SESSION_DOOR not in reason


def test_a_refusal_in_another_repo_names_that_repos_door(two_repos: tuple[Path, Path, Path]) -> None:
    """Resolved from the call's cwd, a `cd X &&` prefix, and `git -C X` -- each one planted."""
    session, target, rules = two_repos
    assert _names_target_door(agenthooks.decide('pytest tests/', rules, cwd=target / 'src'))
    assert _names_target_door(agenthooks.decide(f'cd "{target.as_posix()}" && pytest -q', rules, cwd=session))
    assert _names_target_door(agenthooks.decide('cd ../target && pytest -q', rules, cwd=session))
    assert _names_target_door(
        agenthooks.decide(f'git -C {target.as_posix()} push --no-verify origin HEAD', rules, cwd=session)
    )


def test_a_refusal_in_the_session_repo_keeps_its_own_door(two_repos: tuple[Path, Path, Path]) -> None:
    """The fallback: no other repo named, so the session root's rows speak unchanged."""
    session, _target, rules = two_repos
    reason = agenthooks.decide('pytest tests/', rules, cwd=session)
    assert reason is not None
    assert SESSION_DOOR in reason
    assert TARGET_DOOR not in reason


def test_a_target_declaring_no_door_is_told_the_named_exit_is_not_its_own(
    two_repos: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    """A repo with no `[tool.dev_lab.doors]` row is not handed another repo's exit as if it were its own."""
    _session, _target, rules = two_repos
    bare = tmp_path / 'bare'
    (bare / '.git').mkdir(parents=True)
    reason = agenthooks.decide('pytest tests/', rules, cwd=bare)
    assert reason is not None
    assert 'declares no door' in reason, reason
    assert bare.as_posix().lower() in reason.lower(), reason


# --------------------------------------------------------------------------------------------
# Every shell tool, and the subagent scope


def test_the_powershell_tool_is_judged_like_bash(rules: Path) -> None:
    """THE BYPASS CLOSED: the engine used to exit on any tool but Bash, so PowerShell ran everything."""
    reason = agenthooks.decide('pytest tests/', rules, tool='PowerShell')
    assert reason is not None, 'a bare test line through the PowerShell tool was allowed'
    assert reason.startswith('BARE-TEST-INVOCATION')


def test_a_non_shell_tool_is_never_judged(rules: Path) -> None:
    """Only a tool that runs a command line is in scope; anything else stays fail-open."""
    assert agenthooks.decide('pytest tests/', rules, tool='Write') is None


def _scoped_rules(tmp_path: Path) -> Path:
    path = tmp_path / 'deny-rules.json'
    rows = [{'name': 'SCOPED', 'pattern': r'git\s+push\b', 'matches': 'command', 'scope': 'subagent', 'reason': 'S'}]
    path.write_text(json.dumps(rows), encoding='utf-8')
    return path


def test_a_subagent_scoped_rule_fires_only_inside_a_subagent(tmp_path: Path) -> None:
    """PLANTED CONTROL: the same command, refused with ``agent_id`` and allowed without it."""
    rules = _scoped_rules(tmp_path)
    assert agenthooks.decide('git push origin HEAD', rules, agent_id='a1') == 'S'
    assert agenthooks.decide('git push origin HEAD', rules) is None
    assert agenthooks.decide('git push origin HEAD', rules, agent_id='') is None, 'an empty id is no subagent'


def test_a_subagent_push_is_refused_and_the_main_session_keeps_its_own_door(rules: Path) -> None:
    """END TO END through the shipped engine: the same command, with and without ``agent_id``."""
    inside = agenthooks.decide('git push origin HEAD', rules, agent_id='a1')
    assert inside is not None
    assert inside.startswith('SUBAGENT-NO-PUSH:'), inside
    assert 'hand the commit SHA back' in inside
    assert agenthooks.decide('git push origin HEAD', rules) is None, 'the main session may push'
    outside = agenthooks.decide('git push origin HEAD', rules, hint=True)
    assert outside is not None
    assert outside.startswith('NETWORK-VERB:'), 'the main session lost its own (retry) door'


def test_a_subagent_is_refused_through_the_powershell_tool_too(rules: Path) -> None:
    reason = agenthooks.decide('git push origin HEAD', rules, tool='PowerShell', agent_id='a1')
    assert reason is not None
    assert reason.startswith('SUBAGENT-NO-PUSH:')


def test_a_subagent_keeps_its_targeted_measure(rules: Path) -> None:
    """The exit the refusal names must stay open: a targeted measure of the tests it touched."""
    assert (
        agenthooks.decide(
            '.venv/Scripts/python.exe scripts/gate/runner.py measure tests/test_x.py', rules, agent_id='a1'
        )
        is None
    )


def test_a_hook_skip_prefix_is_seen_by_the_engine(rules: Path) -> None:
    """``SKIP=`` is an env prefix the engine used to strip before any rule saw it."""
    reason = agenthooks.decide('SKIP=ruff git commit -m "x"', rules, agent_id='a1')
    assert reason is not None
    assert reason.startswith('SUBAGENT-NO-PUSH:')
    assert agenthooks.decide('SKIP=ruff git commit -m "x"', rules) is None, 'the main session was refused'


# --------------------------------------------------------------------------------------------
# HINTS -- the engine SPEAKS a hint row as context and never denies on it; a refusal still wins


def _rows(tmp_path: Path, *rows: dict) -> Path:
    path = tmp_path / 'deny-rules.json'
    path.write_text(json.dumps(list(rows)), encoding='utf-8')
    return path


_HINT = {'name': 'PLANTED-HINT', 'pattern': r'grep\s+-r', 'matches': 'command', 'severity': 'hint', 'reason': 'H'}
_DENY = {'name': 'PLANTED-DENY', 'pattern': r'rm\s+-rf', 'matches': 'command', 'reason': 'D'}


def test_a_hint_row_is_context_and_not_a_refusal(tmp_path: Path) -> None:
    rules = _rows(tmp_path, _HINT, _DENY)
    assert agenthooks.decide('grep -r x src', rules) is None
    assert agenthooks.decide('grep -r x src', rules, hint=True) == 'H'
    assert agenthooks.decide('git status', rules, hint=True) is None


def test_a_refusal_wins_over_a_hint_on_the_same_line(tmp_path: Path) -> None:
    """PLANTED CONTROL: the deny row alone refuses, and a hint beside it cannot open it."""
    rules = _rows(tmp_path, _HINT, _DENY)
    assert agenthooks.decide('grep -r x src && rm -rf build', rules) == 'D'
    assert agenthooks.decide('rm -rf build', rules) == 'D'


def _link_dir(link: Path, target: Path) -> None:
    """A directory link with no privilege: a junction on Windows, a symlink elsewhere."""
    if os.name == 'nt':
        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


def _tool(command: str, rules: Path, cwd: Path) -> str:
    """What the AGENT TOOL sends: a payload with no probe key -- the one call whose refusal is a metrics line."""
    payload = {'tool_name': 'Bash', 'tool_input': {'command': command}, 'cwd': str(cwd)}
    done = subprocess.run(
        [agenthooks.node_executable(), str(agenthooks.engine_path('deny-commands')), str(rules)],
        input=json.dumps(payload), capture_output=True, text=True, encoding='utf-8', check=True, timeout=60,
    )  # fmt: skip
    return json.loads(done.stdout)['hookSpecificOutput']['permissionDecisionReason']


def _lines(root: Path, count: int) -> list[dict[str, str]]:
    """*root*'s refusal lines once *count* arrived (the writer is detached), or as many as did in 60 s."""
    deadline = time.monotonic() + 60
    while len(read(REFUSAL, root=root)) < count and time.monotonic() < deadline:
        time.sleep(0.2)
    return read(REFUSAL, root=root)


def test_a_refusal_is_one_metrics_line_written_without_delaying_the_refusal(tmp_path: Path) -> None:
    """P0 metrics: the engine hands the TOOL's refusal to the one writer, detached; no venv, no line.

    A PROBE (:func:`agenthooks.run_engine`) is a test or a ``--check``, never an agent refused: it logs only to
    the root it names. The defect: guard suites probing a real checkout's rules wrote bursts of refusals into
    that checkout's live log, one per suite per row.
    """
    session = tmp_path / 'session'
    (session / '.git').mkdir(parents=True)
    hooks = session / '.claude' / 'hooks'
    hooks.mkdir(parents=True)
    rules = _rows(hooks, _DENY)
    assert _tool('rm -rf build', rules, session) == 'D'
    assert read(REFUSAL, root=session) == []
    _link_dir(session / '.venv', Path(sys.executable).parents[1])
    assert agenthooks.decide('rm -rf build', rules, cwd=session) == 'D'
    assert agenthooks.decide('rm -rf build', rules) == 'D'
    named = tmp_path / 'named'
    named.mkdir()
    assert agenthooks.decide('rm -rf build', rules, cwd=session, metrics_root=named) == 'D'
    assert [line['lab.rule.id'] for line in _lines(named, 1)] == ['PLANTED-DENY']
    assert _tool('rm -rf build', rules, session) == 'D'
    assert [(line['lab.rule.id'], line['error.type']) for line in _lines(session, 1)] == [
        ('PLANTED-DENY', 'agent-guard')
    ], 'the two probes logged nothing into the session checkout; the tool call did'
