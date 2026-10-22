"""HOOKS-ARE-WIRED over planted repositories: a missing shim is reported, an install makes it live.

Planted controls: a declared stage with no shim must report ABSENT and UNPROTECTED (and name the
remedy); an older shim of ours is STALE and replaced; somebody else's file is FOREIGN and refused.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from lab_commons.dev import hook_install
from lab_commons.dev.famtests.hookinstall import (
    assert_declared_hooks_are_installed,
    assert_stages_are_declared,
)
from lab_commons.dev.hook_install import (
    ABSENT,
    FOREIGN,
    INSTALL_COMMAND,
    INSTALLED,
    PROTECTED,
    SHIM_MARKER,
    STALE,
    UNPROTECTED,
    HookInstallError,
    hook_installation,
    hooks_dir,
    install,
    report_installation,
    shim,
)

_GIT = shutil.which('git') or 'git'
_LAYER = '[[tool.lab_commons.hooks.pre-push]]\nid = "admission"\nrun = ["python", "-m", "x"]\nalways_run = true\n'


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / 'repo'
    root.mkdir()
    subprocess.run([_GIT, 'init', '-q', str(root)], check=True, capture_output=True)
    (root / 'pyproject.toml').write_text(_LAYER, encoding='utf-8')
    return root


def test_a_missing_shim_is_reported_absent_and_the_checkout_unprotected(repo: Path, capsys) -> None:
    """PLANTED CONTROL: nothing installed -- every declared stage must name itself absent."""
    report = hook_installation(repo)
    assert {stage.stage for stage in report.stages} == {'pre-commit', 'commit-msg', 'pre-push'}
    assert {stage.status for stage in report.stages} == {ABSENT}
    assert report.verdict == UNPROTECTED
    assert report_installation(['--repo', str(repo)]) == 1
    assert INSTALL_COMMAND in capsys.readouterr().out
    with pytest.raises(AssertionError, match='not live'):
        assert_declared_hooks_are_installed(root=repo)


def test_install_writes_one_shim_per_declared_stage_and_is_idempotent(repo: Path) -> None:
    assert install(repo).verdict == PROTECTED
    directory = hooks_dir(repo)
    assert (directory / 'pre-push').read_text(encoding='utf-8') == shim('pre-push')
    assert install(repo).verdict == PROTECTED
    assert report_installation(['--repo', str(repo)]) == 0
    assert_declared_hooks_are_installed(root=repo)


def test_a_shim_runs_the_stage_through_the_checkout_venv() -> None:
    text = shim('pre-push')
    assert text.startswith('#!/bin/sh\n')
    assert SHIM_MARKER in text
    assert '.venv/Scripts/python.exe' in text
    assert '.venv/bin/python' in text
    assert '-m lab_commons.dev.githooks run pre-push "$@"' in text


def test_an_older_shim_of_ours_is_stale_and_replaced(repo: Path) -> None:
    directory = hooks_dir(repo)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'pre-commit').write_text(f'#!/bin/sh\n{SHIM_MARKER}\nold\n', encoding='utf-8')
    by_stage = {stage.stage: stage.status for stage in hook_installation(repo).stages}
    assert by_stage['pre-commit'] == STALE
    assert install(repo).verdict == PROTECTED
    assert {stage.status for stage in hook_installation(repo).stages} == {INSTALLED}


def test_somebody_elses_hook_is_refused_and_left_alone(repo: Path) -> None:
    directory = hooks_dir(repo)
    directory.mkdir(parents=True, exist_ok=True)
    mine = '#!/bin/sh\necho mine\n'
    (directory / 'commit-msg').write_text(mine, encoding='utf-8')
    assert {s.stage: s.status for s in hook_installation(repo).stages}['commit-msg'] == FOREIGN
    with pytest.raises(HookInstallError, match='did not write'):
        install(repo)
    assert (directory / 'commit-msg').read_text(encoding='utf-8') == mine
    assert not (directory / 'pre-commit').exists(), 'a refused install writes nothing'


def test_the_stage_pin_reds_in_both_directions(repo: Path) -> None:
    assert_stages_are_declared(root=repo, declared_stages=frozenset({'pre-commit', 'commit-msg', 'pre-push'}))
    with pytest.raises(AssertionError, match='Added and not pinned'):
        assert_stages_are_declared(root=repo, declared_stages=frozenset({'pre-commit', 'commit-msg'}))


def _git_out(repo: Path, *args: str) -> str:
    return subprocess.run(
        [_GIT, '-C', str(repo), *args], check=True, capture_output=True, text=True, encoding='utf-8'
    ).stdout.strip()


def test_a_linked_worktree_installs_into_its_own_git_dir(repo: Path, tmp_path: Path) -> None:
    subprocess.run([_GIT, '-C', str(repo), 'add', '-A'], check=True, capture_output=True)
    subprocess.run(
        [_GIT, '-C', str(repo), '-c', 'user.email=t@e', '-c', 'user.name=t', 'commit', '-qm', 'i', '--no-verify'],
        check=True,
        capture_output=True,
    )
    lane = tmp_path / 'lane'
    subprocess.run([_GIT, '-C', str(repo), 'worktree', 'add', '-q', str(lane)], check=True, capture_output=True)
    done = install(lane)
    assert done.verdict == PROTECTED
    own = Path(_git_out(lane, 'rev-parse', '--absolute-git-dir')) / 'hooks'
    assert done.hooks_dir.resolve() == own.resolve()
    assert _git_out(lane, 'config', '--worktree', 'core.hooksPath') == own.as_posix()
    assert sorted(path.name for path in lane.iterdir()) == ['.git', 'pyproject.toml']  # nothing in the tree
    shared = subprocess.run(
        [_GIT, '-C', str(repo), 'config', '--local', 'core.hooksPath'], check=False, capture_output=True
    )
    assert shared.returncode == 1  # the shared config is untouched
    assert hook_install.hook_installation(repo).verdict == UNPROTECTED  # so is the main checkout
    assert install(lane).hooks_dir == done.hooks_dir


def _config(repo: Path, key: str) -> str:
    done = subprocess.run(
        [_GIT, '-C', str(repo), 'config', '--get', key], capture_output=True, text=True, encoding='utf-8', check=False
    )
    return done.stdout.strip()


def test_install_stops_git_tracking_another_branch_and_pushes_each_under_its_own_name(repo: Path) -> None:
    """A lane cut from a remote branch tracks NOTHING, and its first bare push sets its OWN upstream.

    PLANTED CONTROL: before the install git's defaults are in force (nothing set).
    """
    assert {key: _config(repo, key) for key in hook_install.BRANCH_DEFAULTS} == dict.fromkeys(
        hook_install.BRANCH_DEFAULTS, ''
    )
    install(repo)
    assert {key: _config(repo, key) for key in hook_install.BRANCH_DEFAULTS} == hook_install.BRANCH_DEFAULTS
    assert hook_install.BRANCH_DEFAULTS == {
        'branch.autoSetupMerge': 'false',
        'push.default': 'current',
        'push.autoSetupRemote': 'true',
    }
