"""HOOKS-ARE-WIRED over planted repositories: a missing shim is reported, an install makes it live.

Planted controls: a declared stage with no shim must report ABSENT and UNPROTECTED (and name the
remedy); an older shim of ours is STALE and replaced; somebody else's file is FOREIGN and refused.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from dev_lab.dev import hook_install
from dev_lab.dev.famtests.hookinstall import (
    assert_declared_hooks_are_installed,
    assert_stages_are_declared,
)
from dev_lab.dev.hook_install import (
    ABSENT,
    FOREIGN,
    INSTALL_COMMAND,
    INSTALLED,
    PREDECESSOR_MARKER,
    PROTECTED,
    RETIRED_SHIMS_DIR,
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
_LAYER = '[[tool.dev_lab.hooks.pre-push]]\nid = "admission"\nrun = ["python", "-m", "x"]\nalways_run = true\n'


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
    assert {stage.stage for stage in report.stages} == {'pre-commit', 'commit-msg', 'post-commit', 'pre-push'}
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
    assert '-m dev_lab.dev.githooks run pre-push "$@"' in text


def test_an_older_shim_of_ours_is_stale_and_replaced(repo: Path) -> None:
    directory = hooks_dir(repo)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'pre-commit').write_text(f'#!/bin/sh\n{SHIM_MARKER}\nold\n', encoding='utf-8')
    by_stage = {stage.stage: stage.status for stage in hook_installation(repo).stages}
    assert by_stage['pre-commit'] == STALE
    assert install(repo).verdict == PROTECTED
    assert {stage.status for stage in hook_installation(repo).stages} == {INSTALLED}


def test_a_stale_shim_of_ours_is_live_for_the_property_and_still_reported_to_a_person(repo: Path, capsys) -> None:
    """A PR that changes the shim template met a host whose shims came from ITS serving checkout (2026-10-22, #273).

    A stale shim of ours still runs the stages, so the installed-hooks PROPERTY holds -- else a PR changing
    the shim could pass on no host. ``hook_install`` (no ``--install``) still names it stale for a person.
    PLANTED CONTROL: a FOREIGN file in a slot still fails the property.
    """
    install(repo)
    stale = hooks_dir(repo) / 'pre-commit'
    stale.write_text(f'#!/bin/sh\n{SHIM_MARKER}\nold\n', encoding='utf-8')
    assert_declared_hooks_are_installed(root=repo)
    assert report_installation(['--repo', str(repo)]) == 1
    assert STALE in capsys.readouterr().out
    stale.write_text('#!/bin/sh\necho mine\n', encoding='utf-8')
    with pytest.raises(AssertionError, match=FOREIGN):
        assert_declared_hooks_are_installed(root=repo)


def test_a_predecessor_shim_is_retired_as_a_record_and_replaced(repo: Path) -> None:
    """The predecessor kit's shim is our lineage: moved aside, never refused. PLANTED CONTROL: the next test."""
    directory = hooks_dir(repo)
    directory.mkdir(parents=True, exist_ok=True)
    old = f'#!/bin/sh\n{PREDECESSOR_MARKER}\nexec python -m lab_commons.dev.githooks run pre-commit\n'
    (directory / 'pre-commit').write_text(old, encoding='utf-8')
    assert {s.stage: s.status for s in hook_installation(repo).stages}['pre-commit'] == STALE
    assert install(repo).verdict == PROTECTED
    assert {stage.status for stage in hook_installation(repo).stages} == {INSTALLED}
    assert (repo / '.git' / RETIRED_SHIMS_DIR / 'pre-commit').read_text(encoding='utf-8') == old


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
    assert_stages_are_declared(
        root=repo, declared_stages=frozenset({'pre-commit', 'commit-msg', 'post-commit', 'pre-push'})
    )
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


def _commit(repo: Path) -> subprocess.CompletedProcess[str]:
    (repo / 'a.txt').write_text('a\n', encoding='utf-8')
    subprocess.run([_GIT, '-C', str(repo), 'add', 'a.txt'], check=True, capture_output=True)
    return subprocess.run(
        [_GIT, '-C', str(repo), '-c', 'user.email=t@e', '-c', 'user.name=t', 'commit', '-qm', 'feat: a'],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=False,
    )


def _install_with(repo: Path, fallback: str) -> None:
    install(repo)
    directory = hooks_dir(repo)
    for stage in ('pre-commit', 'commit-msg', 'pre-push'):
        (directory / stage).write_text(shim(stage, fallback), encoding='utf-8', newline='\n')


_REPO_ROW = '[[tool.dev_lab.hooks.commit-msg]]\nid = "repo-only"\nrun = ["python", "-m", "no_such_repo_module"]\n'


def test_no_venv_commits_through_the_recorded_interpreter_and_skips_repo_rows(repo: Path) -> None:
    """A row needing the repo's own env would fail here; under the recorded interpreter it is skipped."""
    (repo / 'pyproject.toml').write_text(_REPO_ROW, encoding='utf-8')
    _install_with(repo, sys.executable)
    done = _commit(repo)
    assert done.returncode == 0, done.stderr
    assert 'no_such_repo_module' not in done.stderr


def test_no_interpreter_anywhere_still_commits_with_one_line(repo: Path, tmp_path: Path) -> None:
    _install_with(repo, (tmp_path / 'gone' / 'python').as_posix())
    done = _commit(repo)
    assert done.returncode == 0, done.stderr
    lines = [line for line in done.stderr.splitlines() if '[githooks]' in line]
    assert len(lines) == 2  # pre-commit and commit-msg: one line each
    assert all('no lab_commons interpreter' in line for line in lines)


def test_a_checkout_venv_still_runs_the_hooks_and_its_refusal_blocks(repo: Path) -> None:
    """PLANTED CONTROL: the checkout's own venv wins over the fallback, and a failing hook still refuses."""
    venv = repo / '.venv' / 'bin'
    venv.mkdir(parents=True)
    fake = venv / 'python'
    fake.write_text('#!/bin/sh\necho venv-ran >&2\nexit 1\n', encoding='utf-8', newline='\n')
    fake.chmod(0o755)
    _install_with(repo, sys.executable)
    done = _commit(repo)
    assert done.returncode != 0
    assert 'venv-ran' in done.stderr


def test_a_shim_recording_another_interpreter_is_still_installed(repo: Path) -> None:
    _install_with(repo, '/elsewhere/python')
    assert {stage.status for stage in hook_installation(repo).stages} == {INSTALLED}


def test_a_retire_that_fails_leaves_the_new_shim_written_beside_the_slot(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The new shim is whole on disk BEFORE the predecessor moves: a crash between the two strands no hook."""
    directory = hooks_dir(repo)
    directory.mkdir(parents=True, exist_ok=True)
    old = f'#!/bin/sh\n{PREDECESSOR_MARKER}\nexec python -m lab_commons.dev.githooks run pre-commit\n'
    (directory / 'pre-commit').write_text(old, encoding='utf-8')

    def crash(_repo: Path, _path: Path) -> None:
        msg = 'disk full'
        raise OSError(msg)

    monkeypatch.setattr(hook_install, '_retire_predecessor', crash)
    with pytest.raises(OSError, match='disk full'):
        install(repo)
    assert (directory / 'pre-commit').read_text(encoding='utf-8') == old, 'the old hook still guards the slot'
    assert (directory / 'pre-commit.new').is_file(), 'the new shim was written first'
