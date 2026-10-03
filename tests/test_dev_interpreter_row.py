"""BARE-INTERPRETER: the reflex spellings are refused through the REAL engine, with the owner's exit.

One owner (:mod:`lab_commons.dev.venvpath`) spells the interpreter; the deny row's remedy, the settings
allow row and these tests all read it. A repo CLI behind `uv run` is opened per repo, never in the base.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lab_commons.dev import agenthooks
from lab_commons.dev.allow_adoption import AllowAdoption, derived_entries, self_refused
from lab_commons.dev.hook_adoption import HookAdoption, render
from lab_commons.dev.hooks import DENY_RULES, Remedy, rules_by_id
from lab_commons.dev.venvpath import INTERPRETER_ALLOW_ENTRY, INTERPRETER_RULE, VENV_INTERPRETER_GLOB, VENV_LAYOUTS

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
        'uv run -m lab_commons.dev.verify',
        'uvx python',
        'python x.py',
        'python3 -c "print(1)"',
        'py -3 x.py',
        'timeout 60 uv run python x.py',
        'cd sub && python x.py',
        'uv run python - <<EOF\nprint(1)\nEOF',
        'uv run mycli run cases/x',
    ],
)
def test_a_reflex_spelling_is_refused_with_the_owner_spelled_exit(tmp_path: Path, command: str) -> None:
    """REFUSAL-NAMES-THE-REMEDY: both concrete layouts and the allow row, read off the owner."""
    reason = agenthooks.decide(command, _rules(tmp_path, {}))
    assert reason is not None, f'allowed: {command!r}'
    for layout in VENV_LAYOUTS.values():
        assert '/'.join(layout) in reason, reason
    assert INTERPRETER_ALLOW_ENTRY in reason


@pytest.mark.parametrize(
    'command',
    [
        '.venv/Scripts/python.exe -m lab_commons.dev.verify',
        '.venv/bin/python x.py',
        'C:/work/repo/.venv/Scripts/python.exe -V',
        'git commit -m "uv run python is refused now"',
    ],
)
def test_the_venv_spelling_is_allowed(tmp_path: Path, command: str) -> None:
    """The exit itself must not be refused, or the rule seals the road it names."""
    assert agenthooks.decide(command, _rules(tmp_path, {})) is None, command


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
