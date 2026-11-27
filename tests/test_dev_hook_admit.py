"""HOOKS-ARE-WIRED, the refusing half: a history-writing git verb is refused in an unwired checkout, by name.

Planted controls on both sides: a WIRED tree admits every verb, an UNWIRED one is refused for each of
commit, merge, push, cherry-pick and rebase (and netverb's push), and a read verb is never asked about.
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from dev_lab.dev import _deny_hookswired_row, _hook_admit, hook_install
from dev_lab.dev.hooks import DENY_RULES, denies, rules_by_id

_GIT = shutil.which('git') or 'git'
_LAYER = '[[tool.dev_lab.hooks.pre-push]]\nid = "admission"\nrun = ["python", "-m", "x"]\nalways_run = true\n'
_LINES = (
    'git commit -m x',
    'git merge --no-ff lane/a',
    'git push origin HEAD',
    'git cherry-pick abc123',
    'git rebase origin/main',
    'python -m dev_lab.dev.netverb -- git push origin HEAD',
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / 'repo'
    root.mkdir()
    subprocess.run([_GIT, 'init', '-q', str(root)], check=True, capture_output=True)
    (root / 'pyproject.toml').write_text(_LAYER, encoding='utf-8')
    return root


def _payload(command: str, cwd: Path) -> dict[str, object]:
    return {'tool_name': 'Bash', 'tool_input': {'command': command}, 'cwd': str(cwd)}


@pytest.mark.parametrize('command', _LINES)
def test_an_unwired_checkout_is_refused_by_name_for_each_verb(repo: Path, command: str) -> None:
    """PLANTED CONTROL: nothing installed -- every history-writing verb is refused, naming both doors."""
    said = _hook_admit.admit(_payload(command, repo), hook_install.unwired, 'py')
    assert said is not None
    assert said.startswith(f'{_hook_admit.RULE_ID}: {repo.resolve().as_posix()}')
    assert f'py -m dev_lab.dev.dep --bootstrap {repo.resolve().as_posix()}' in said
    assert '-m dev_lab.dev.hook_install --repo' in said
    assert '--install' in said


@pytest.mark.parametrize('command', _LINES)
def test_a_wired_checkout_admits_every_verb(repo: Path, command: str) -> None:
    hook_install.install(repo)
    assert _hook_admit.admit(_payload(command, repo), hook_install.unwired, 'py') is None


def test_the_tree_judged_is_the_one_the_verb_runs_in(repo: Path, tmp_path: Path) -> None:
    """``-C``, ``cd`` and netverb's ``--cwd`` name the tree; the session cwd is wired and admits nothing for it."""
    wired = tmp_path / 'wired'
    wired.mkdir()
    subprocess.run([_GIT, 'init', '-q', str(wired)], check=True, capture_output=True)
    (wired / 'pyproject.toml').write_text(_LAYER, encoding='utf-8')
    hook_install.install(wired)
    for command in (
        f'git -C {repo.as_posix()} commit -m x',
        f'cd {repo.as_posix()} && git commit -m x',
        f'python -m dev_lab.dev.netverb --cwd {repo.as_posix()} -- git push',
    ):
        assert _hook_admit.admit(_payload(command, wired), hook_install.unwired, 'py') is not None, command
    assert _hook_admit.admit(_payload('git commit -m x', wired), hook_install.unwired, 'py') is None


@pytest.mark.parametrize('command', ['git status', 'git log -n 3', 'git fetch origin', 'echo git commit'])
def test_a_verb_that_writes_no_history_is_never_judged(repo: Path, command: str) -> None:
    assert _hook_admit.admit(_payload(command, repo), hook_install.unwired, 'py') is None


def test_the_admit_door_exits_one_with_the_refusal(repo: Path) -> None:
    payload = json.dumps(_payload('git commit -m x', repo)).encode()
    out = io.BytesIO()
    assert hook_install.report_installation(['--admit'], stdin=io.BytesIO(payload), stdout=out) == 1
    assert out.getvalue().decode().startswith(_hook_admit.RULE_ID)
    hook_install.install(repo)
    assert hook_install.report_installation(['--admit'], stdin=io.BytesIO(payload), stdout=io.BytesIO()) == 0


def test_the_row_asks_the_installer_and_prefilters_every_verb() -> None:
    row = rules_by_id(DENY_RULES)[_hook_admit.RULE_ID]
    assert row.asks == 'dev_lab.dev.hook_install'
    for command in _LINES:
        assert denies((row,), command) == _hook_admit.RULE_ID, command
    for command in ('git status', 'git log -n 3', 'git commit-tree x', 'echo "git push"'):
        assert denies((row,), command) is None, command
    assert _deny_hookswired_row.HOOKS_ARE_WIRED['id'] == _hook_admit.RULE_ID
