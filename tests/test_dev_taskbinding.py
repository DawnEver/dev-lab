"""A SESSION KEEPS ITS ONE TASK (D5): its branches derive from the user's binding as ``pr/<task>/<feature>``."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from dev_lab.dev import forgecli, taskbinding
from dev_lab.dev.branchset import FAMILY_EPHEMERAL, BranchSet
from dev_lab.dev.sessionbranch import rename_remedy

_SESSION = '1d9000bd-6cd0-42ab-873f-102cd963e53d'
_GIT = shutil.which('git') or 'git'


def _task(root: Path, slug: str = 'toolchain') -> None:
    folder = root / '.claude' / 'tasks' / slug
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'TASK.md').write_text('---\nauthority: a1\nstatus: open\n---\n', encoding='utf-8')


def test_a_tasks_heads_are_nested_under_it_and_never_the_bare_task() -> None:
    assert taskbinding.head_for('toolchain', 'a') == 'pr/toolchain/a'
    assert taskbinding.under('pr/toolchain/a', 'toolchain')
    assert taskbinding.under('pr/toolchain/a/b', 'toolchain')
    for other in ('pr/toolchain', 'pr/toolchain/', 'pr/toolchainx/a', 'pr/other/a', 'toolchain/a', 'pr/a'):
        assert not taskbinding.under(other, 'toolchain'), other


def test_origin_admits_a_nested_task_head_by_the_family_glob() -> None:
    """ORIGIN-HOLDS-ONLY-DECLARED-BRANCHES: fnmatch's `*` crosses `/`, so `pr/*` admits `pr/<task>/<feature>`."""
    declared = BranchSet(trunk='main', sessions=frozenset({'integrate/main'}), ephemeral=FAMILY_EPHEMERAL)
    assert declared.admits('pr/toolchain/a')
    assert not declared.admits('lane/toolchain/a'), 'planted control: local fan-out stays undeclared'


def test_git_refuses_a_bare_task_branch_beside_its_heads(tmp_path: Path) -> None:
    """Why a task never publishes a bare `pr/<task>`: the ref would have to be a file and a directory at once."""
    subprocess.run([_GIT, 'init', '-q', '-b', 'main', str(tmp_path)], check=True)
    subprocess.run(
        [_GIT, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'seed'],
        cwd=tmp_path, check=True,
    )  # fmt: skip
    subprocess.run([_GIT, 'branch', 'pr/toolchain/a'], cwd=tmp_path, check=True)
    bare = subprocess.run([_GIT, 'branch', 'pr/toolchain'], cwd=tmp_path, capture_output=True, check=False)
    assert bare.returncode != 0


def test_the_rename_remedy_names_the_bound_tasks_head() -> None:
    assert 'git branch -m fix/x pr/x`' in rename_remedy('fix/x'), 'unbound: the flat pr/<feature> head'
    bound = rename_remedy('fix/x', 'toolchain')
    assert 'git branch -m fix/x pr/toolchain/x`' in bound
    assert 'push -u origin pr/toolchain/x' in bound


def test_pr_create_suggests_the_bound_tasks_head(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = {'CLAUDE_CODE_SESSION_ID': _SESSION}
    assert forgecli._task_head_advice('pr/x', env) == (), 'planted control: unbound, nothing suggested'
    _task(tmp_path)
    assert taskbinding.bind({'session_id': _SESSION, 'prompt': 'task: toolchain'}, root=tmp_path) == 'toolchain@a1'
    [said] = forgecli._task_head_advice('pr/x', env)
    assert 'pr/toolchain/<feature>' in said
    assert 'git branch -m pr/x pr/toolchain/x' in said
    assert forgecli._task_head_advice('pr/toolchain/x', env) == ()
    monkeypatch.setenv('CLAUDE_CODE_SESSION_ID', _SESSION)
    assert forgecli._task_head_advice('pr/x', None) == (said,), 'the process environment is the default'


def test_status_names_the_door_when_unbound(capsys: pytest.CaptureFixture[str]) -> None:
    assert taskbinding.main(['status']) == 0
    assert '`task: <slug>`' in capsys.readouterr().out
