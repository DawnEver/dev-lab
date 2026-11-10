"""A git hook runs with GIT_DIR naming the repository pushing; a cache it creates must not inherit it.

MEASURED 2026-11-10 (a consumer repository): `git -C <tmp> init --bare` under the pre-push hook's GIT_DIR re-initialised
the REAL repository as bare (`core.bare = true`), and every worktree and the main checkout then failed "must be
run in a work tree". Each cache-making reader below runs with GIT_DIR pointing at a real repository; that
repository must stay non-bare and untouched.

Planted control: the same `init --bare` WITH the inherited GIT_DIR does flip it, so the check can say no.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from dev_lab.dev import drift, locklag, syncpins
from dev_lab.dev.forge import _GIT
from dev_lab.dev.lockcheck import unlocated_env


def _git(*argv: str, cwd: Path) -> str:
    return subprocess.run([_GIT, *argv], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def pushing(tmp_path, monkeypatch) -> Path:
    """A real repository, located the way a hook locates it: through GIT_DIR."""
    repo = tmp_path / 'pushing'
    repo.mkdir()
    _git('init', '-q', cwd=repo)
    monkeypatch.setenv('GIT_DIR', str(repo / '.git'))
    return repo


@pytest.fixture
def source(tmp_path) -> tuple[str, str]:
    """A dependency repository with one commit on main, as a file URL and that commit."""
    repo = tmp_path / 'dep'
    repo.mkdir()
    env = unlocated_env()
    for argv in (
        ['init', '-q', '-b', 'main'],
        ['-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'c'],
    ):
        subprocess.run([_GIT, *argv], cwd=repo, env=env, check=True)
    sha = subprocess.run([_GIT, 'rev-parse', 'HEAD'], cwd=repo, env=env, capture_output=True, text=True, check=True)
    return repo.as_uri(), sha.stdout.strip()


def _bare(repo: Path) -> str:
    return subprocess.run(
        [_GIT, '--git-dir', str(repo / '.git'), 'config', 'core.bare'],
        capture_output=True,
        text=True,
        check=False,
        env=unlocated_env(),
    ).stdout.strip()


def test_planted_an_inherited_git_dir_turns_the_pushing_repository_bare(pushing, tmp_path) -> None:
    cache = tmp_path / 'cache'
    cache.mkdir()
    subprocess.run([_GIT, '-C', str(cache), 'init', '-q', '--bare'], check=True)
    assert _bare(pushing) == 'true'


def test_the_lock_lag_count_leaves_the_pushing_repository_alone(pushing, source) -> None:
    url, sha = source
    assert locklag._commits_behind(url, 'main', sha) == 0
    assert _bare(pushing) == 'false'


def test_the_drift_cache_leaves_the_pushing_repository_alone(pushing, source, tmp_path) -> None:
    url, sha = source
    assert drift.lag('dep', url, sha, cache=tmp_path / 'cache', schemes=('file',)).behind == 0
    assert _bare(pushing) == 'false'


def test_the_ancestry_cache_leaves_the_pushing_repository_alone(pushing, source, tmp_path, monkeypatch) -> None:
    url, sha = source
    monkeypatch.setattr(syncpins, 'SCHEMES', ('file',))
    assert syncpins.ancestor(tmp_path / 'cache')('dep', url, sha, sha)
    assert _bare(pushing) == 'false'
