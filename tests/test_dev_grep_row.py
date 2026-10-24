"""RECURSIVE-GREP: a recursive grep is HINTED through the REAL engine, and its near-misses are not.

A hint, not a refusal, since P3 (2026-10-23): it is a style guard -- a slow walk, not harm -- and it misfired on
greps over one small directory. The engine sends it as ``additionalContext`` and runs the command.

A tree walk descends into every git-ignored directory (`.venv`, `output`, `target`) a repo carries;
the door is `git grep`, which reads the index. Measurements: ``docs-src/dev/refusals.md#recursive-grep``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.dev import agenthooks, disclosure
from dev_lab.dev.hook_adoption import HookAdoption, render
from dev_lab.dev.hooks import DENY_RULES, rules_by_id


@pytest.fixture(scope='module')
def rules(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The registry rendered exactly as a repo ships it."""
    path = tmp_path_factory.mktemp('rules') / 'deny-rules.json'
    path.write_text(render(HookAdoption(app_name='suite', remedies={})), encoding='utf-8')
    return path


@pytest.mark.parametrize(
    'command',
    [
        'grep -r pattern .',
        'grep -rn "TODO" src',
        'grep -nR x src tests',
        'grep --recursive -l x .',
        'grep -i -r x',
        'cd sub && grep -rl x .',
        'egrep -r "a|b" src',
    ],
)
@pytest.mark.workstation
def test_a_recursive_grep_is_hinted_with_the_git_grep_door_and_still_runs(rules: Path, command: str) -> None:
    """REFUSAL-NAMES-THE-REMEDY, as a hint: it names `git grep -n` and the built-in Grep tool, and refuses nothing."""
    assert agenthooks.decide(command, rules) is None, f'refused: {command!r}'
    reason = agenthooks.decide(command, rules, hint=True)
    assert reason is not None, f'not hinted: {command!r}'
    assert 'RECURSIVE-GREP' in reason
    assert 'git grep -n' in reason
    assert 'Grep tool' in reason


@pytest.mark.parametrize(
    'command',
    [
        'grep -n "x" src/a.py',
        'grep -c error build.log',
        'git log --oneline | grep fix',
        'git status --short | grep -v "^??"',
        'git grep -n pattern',
        'git grep -rn pattern -- src',
        'grep -e "-r" notes.txt',
        'grep --regexp=x a.py',
    ],
)
@pytest.mark.workstation
def test_a_grep_on_a_file_a_pipe_or_the_index_is_permitted(rules: Path, command: str) -> None:
    """The door itself and every non-walking grep must pass unhinted, or the hint cries wolf on the road it names."""
    assert agenthooks.decide(command, rules) is None, command
    assert agenthooks.decide(command, rules, hint=True) is None, command


def test_the_refusal_is_progressive() -> None:
    """INJECTED-TEXT-IS-PROGRESSIVE: the row's detail lives in the refusals page, under its id."""
    rule = rules_by_id(DENY_RULES)['RECURSIVE-GREP']
    root = Path(__file__).resolve().parents[1]
    assert 'recursive-grep' in disclosure.anchors((root / disclosure.REFUSALS_DOC).read_text(encoding='utf-8'))
    assert rule.needs is None
