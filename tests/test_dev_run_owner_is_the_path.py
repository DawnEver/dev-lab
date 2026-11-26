"""A run's owner is its checkout's resolved path, never the bare worktree name (the 2026-11-26 cross-repo kill).

PLANTED CONTROL: two repos, each with a worktree of the SAME name. A run in one is never matched, stopped or
reported as the other's -- and a run in the caller's own worktree still is, so the refusal is not a constant.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from lab_commons.census import Process

from dev_lab.dev.gitdirs import run_owner, same_owner
from dev_lab.dev.liverun import live_runs
from dev_lab.dev.stoprun import stop

_NAME = 'adopt-dev-lab-1126'
_RUN = 'python -m pytest -n 4 tests'


def _git(cwd: Path, *args: str) -> None:
    subprocess.run([shutil.which('git') or 'git', *args], cwd=cwd, check=True, capture_output=True)


def _repo_with_worktree(base: Path) -> Path:
    base.mkdir()
    _git(base, 'init', '-q')
    _git(base, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'root')
    tree = base / '.claude' / 'worktrees' / _NAME
    _git(base, 'worktree', 'add', '-q', '--detach', str(tree))
    return tree


@pytest.fixture
def twins(tmp_path: Path) -> tuple[Path, Path]:
    """``numerics/.claude/worktrees/<name>`` and ``optimi/.claude/worktrees/<name>``: one name, two owners."""
    mine, theirs = _repo_with_worktree(tmp_path / 'numerics'), _repo_with_worktree(tmp_path / 'optimi')
    assert mine.name == theirs.name
    return mine, theirs


def _table(cwd: Path) -> tuple[dict[int, tuple[int, str]], dict[int, str | None]]:
    return {50: (1, _RUN), 51: (50, 'python worker')}, {50: str(cwd), 51: str(cwd)}


def test_the_owner_is_the_full_path_so_same_named_worktrees_differ(twins: tuple[Path, Path]) -> None:
    mine, theirs = twins
    assert not same_owner(mine, theirs)
    assert same_owner(mine, mine / '.' / 'src' / '..')
    assert run_owner(mine).endswith(f'numerics/.claude/worktrees/{_NAME}')
    assert run_owner(theirs).endswith(f'optimi/.claude/worktrees/{_NAME}')


def test_another_repos_same_named_worktree_run_is_refused_naming_its_owner(twins: tuple[Path, Path]) -> None:
    mine, theirs = twins
    table, cwds = _table(theirs)
    killed: list[int] = []
    code, lines = stop(50, table, dry_run=False, kill=killed.append, checkout=mine, cwds=cwds)
    assert (code, killed) == (3, [])
    said = '\n'.join(lines)
    assert run_owner(theirs) in said
    assert run_owner(mine) in said
    assert 'ask the user' in said


def test_the_callers_own_run_is_still_stopped(twins: tuple[Path, Path]) -> None:
    mine, _ = twins
    table, cwds = _table(mine / 'tests')  # a run started from a subdirectory is still the checkout's
    killed: list[int] = []
    code, _ = stop(50, table, dry_run=False, kill=killed.append, checkout=mine, cwds=cwds)
    assert (code, killed) == (0, [51, 50])


def test_a_run_whose_owner_cannot_be_read_is_refused(twins: tuple[Path, Path]) -> None:
    mine, _ = twins
    table, _ = _table(mine)
    killed: list[int] = []
    code, lines = stop(50, table, dry_run=False, kill=killed.append, checkout=mine, cwds={50: None})
    assert (code, killed) == (3, [])
    assert 'unknown' in lines[0]


def test_a_live_run_in_the_twin_is_never_reported_as_ours(twins: tuple[Path, Path]) -> None:
    mine, theirs = twins

    def census(where: Path) -> tuple[Process, ...]:
        python = where / '.venv' / 'Scripts' / 'python.exe'  # the run's own interpreter, as a real one holds
        return (Process(70, 1, str(python), f'{python} -m pytest -n 4 tests', 600.0, str(where)),)

    assert live_runs(mine, census=lambda: census(theirs), me=1) == ()
    assert [one.pid for one in live_runs(mine, census=lambda: census(mine), me=1)] == [70]
