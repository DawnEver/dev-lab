"""BARE-INTERPRETER refuses `uv run`/`uvx` and BARE-PYTHON hints a bare `python`/`py`, through the REAL engine.

The split (toolchain plan P3, user 2026-10-23): `uv run` may SYNC the checkout's environment, which is harm,
so it is refused; a bare `python` only runs somebody else's interpreter, so it is said and runs.

One owner (:mod:`dev_lab.dev.venvpath`) spells the interpreter; the deny row's remedy, the settings
allow row and these tests all read it. A repo CLI behind `uv run` is opened per repo, never in the base.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.dev import agenthooks
from dev_lab.dev._deny_interpreter_row import INTERPRETER_REMEDY
from dev_lab.dev.allow_adoption import AllowAdoption, derived_entries, self_refused
from dev_lab.dev.hook_adoption import HookAdoption, render
from dev_lab.dev.hooks import DENY_RULES, Remedy, rules_by_id
from dev_lab.dev.venvpath import (
    INTERPRETER_ALLOW_ENTRY,
    INTERPRETER_RULE,
    VENV_INTERPRETER_GLOB,
    current_os_name,
    remedy_interpreter,
)


def test_a_missing_worktree_environment_is_bootstrapped_not_borrowed() -> None:
    assert '--bootstrap' in INTERPRETER_REMEDY
    assert '<main>/' not in INTERPRETER_REMEDY
    assert 'shared environment' not in INTERPRETER_REMEDY


def _absolute_interpreter(root: Path) -> str:
    """The exit as the engine prints it: the checkout's interpreter by ABSOLUTE path, never the bare token."""
    return remedy_interpreter(root, os_name=current_os_name())


#: A consumer's own opening: its user-facing CLI runs through `uv run`, by user directive.
CLI_OPENING = Remedy('repo-cli', 'uv run mycli run cases/x', allow=r'^\s*uv\s+run\s+mycli\b')


def _rules(tmp_path: Path, remedies: dict[str, Remedy]) -> Path:
    path = tmp_path / 'deny-rules.json'
    path.write_text(render(HookAdoption(app_name='suite', remedies=remedies)), encoding='utf-8')
    return path


@pytest.mark.parametrize(
    'command',
    [
        'uv run python x.py',
        'uv run -m dev_lab.dev.verify',
        'uvx python',
        'timeout 60 uv run python x.py',
        'foo && uv run python x',
        'bash -c "cd sub && uv run python x"',
        'uv run python - <<EOF\nprint(1)\nEOF',
        'uv run mycli run cases/x',
    ],
)
@pytest.mark.workstation
def test_a_reflex_spelling_is_refused_with_the_owner_spelled_exit(tmp_path: Path, command: str) -> None:
    """REFUSAL-NAMES-THE-REMEDY: both concrete layouts and the allow row, read off the owner."""
    (tmp_path / '.git').mkdir()
    reason = agenthooks.decide(command, _rules(tmp_path, {}), cwd=tmp_path)
    assert reason is not None, f'allowed: {command!r}'
    assert _absolute_interpreter(tmp_path) in reason, reason
    assert INTERPRETER_ALLOW_ENTRY in reason


@pytest.mark.parametrize('command', ['python x.py', 'python3 -c "print(1)"', 'py -3 x.py', 'cd sub && python x.py'])
@pytest.mark.workstation
def test_a_bare_python_is_hinted_with_the_owner_spelled_exit_and_still_runs(tmp_path: Path, command: str) -> None:
    """A hint refuses nothing, and it names the same exit the refusal does."""
    rules = _rules(tmp_path, {})
    (tmp_path / '.git').mkdir()
    assert agenthooks.decide(command, rules, cwd=tmp_path) is None, f'refused: {command!r}'
    reason = agenthooks.decide(command, rules, cwd=tmp_path, hint=True)
    assert reason is not None, f'not hinted: {command!r}'
    assert 'BARE-PYTHON' in reason
    assert _absolute_interpreter(tmp_path) in reason, reason


@pytest.mark.parametrize(
    'command',
    [
        '.venv/Scripts/python.exe -m dev_lab.dev.verify',
        '.venv/bin/python x.py',
        'C:/work/repo/.venv/Scripts/python.exe -V',
        'git commit -m "uv run python is refused now"',
        # MEASURED 2026-10-03: the `\|` inside a quoted grep PATTERN was split as a pipe, and the
        # half after it read as a `uv run` command. A quoted argument is never a command position.
        'grep -n "bump-api-version\\|uv run --no-sync" a.yaml b.py',
        "grep -n 'x|uv run python' src/a.py",
        'echo "a; python x.py"',
    ],
)
@pytest.mark.workstation
def test_the_venv_spelling_is_allowed(tmp_path: Path, command: str) -> None:
    """The exit itself must not be refused, or the rule seals the road it names."""
    assert agenthooks.decide(command, _rules(tmp_path, {})) is None, command


@pytest.mark.workstation
def test_a_repo_cli_is_opened_only_by_that_repos_delta(tmp_path: Path) -> None:
    """The per-repo opening: `uv run <its cli>` passes there, and `uv run python` still does not."""
    rules = _rules(tmp_path, {INTERPRETER_RULE: CLI_OPENING})
    assert agenthooks.decide('uv run mycli run cases/x', rules) is None
    assert agenthooks.decide('uv run python x.py', rules) is not None
    base = tmp_path / 'base'
    base.mkdir()
    assert agenthooks.decide('uv run mycli run cases/x', _rules(base, {})) is not None


def test_the_settings_allow_row_is_the_owner_spelling_in_every_block() -> None:
    """The settings row is DERIVED from the owner for every adopter, and it does not refuse itself."""
    assert f'Bash({VENV_INTERPRETER_GLOB} *)' == INTERPRETER_ALLOW_ENTRY
    adoption = HookAdoption(app_name='suite', remedies={})
    assert derived_entries(adoption)[INTERPRETER_ALLOW_ENTRY] == (INTERPRETER_RULE,)
    assert self_refused(AllowAdoption(app_name='suite', adoption=adoption)) == ()
    assert INTERPRETER_RULE in rules_by_id(DENY_RULES)
