"""A git call against a throwaway repository never reaches the caller's (2026-11-10 core.bare flip).

Planted control: ``GIT_DIR`` names a live NON-bare repository, as it does inside a git hook. Each throwaway
``init`` must leave that repository's ``core.bare`` false and initialise the throwaway instead.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from dev_lab.dev import drift, gitenv, locklag, syncpins
from dev_lab.dev.forge import _GIT
from dev_lab.ops import upgrade


def _git(cwd: Path, *argv: str) -> str:
    env = gitenv.unlocated()
    done = subprocess.run(
        [_GIT, '-C', str(cwd), *argv], capture_output=True, text=True, encoding='utf-8', check=True, env=env
    )
    return done.stdout.strip()


@pytest.fixture
def caller(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A non-bare repository that GIT_DIR names, as a hook's environment does."""
    repo = tmp_path / 'caller'
    repo.mkdir()
    _git(repo, 'init', '-q', '-b', 'main')
    monkeypatch.setenv('GIT_DIR', str(repo / '.git'))
    return repo


@pytest.fixture
def upstream(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / 'upstream'
    repo.mkdir()
    _git(repo, 'init', '-q', '-b', 'main')
    (repo / 'uv.lock').write_text('lock\n', encoding='utf-8')
    _git(repo, 'add', 'uv.lock')
    _git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'one')
    return repo, _git(repo, 'rev-parse', 'HEAD')


def _bare(repo: Path) -> str:
    return _git(repo, 'config', '--file', str(repo / '.git' / 'config'), 'core.bare')


@pytest.mark.usefixtures('caller')
def test_unlocated_drops_every_repository_locator() -> None:
    assert 'GIT_DIR' not in gitenv.unlocated()
    assert 'GIT_DIR' in os.environ


def test_the_lock_lag_read_leaves_the_caller_non_bare(caller: Path, upstream: tuple[Path, str]) -> None:
    repo, sha = upstream
    assert locklag._commits_behind(str(repo), 'main', sha) == 0
    assert _bare(caller) == 'false'


@pytest.mark.parametrize('git', [drift._git, syncpins._git], ids=['drift', 'syncpins'])
def test_a_cache_init_leaves_the_caller_non_bare(caller: Path, tmp_path: Path, git: Callable[..., object]) -> None:
    cache = tmp_path / 'cache.git'
    cache.mkdir()
    git(cache, 'init', '-q', '--bare')
    assert _bare(caller) == 'false'
    assert (cache / 'HEAD').is_file()


def test_the_upgrade_scratch_fetch_leaves_the_caller_non_bare(caller: Path, upstream: tuple[Path, str]) -> None:
    repo, sha = upstream
    assert upgrade.fetch_lock(str(repo), 'main') == (sha, 'lock\n')
    assert _bare(caller) == 'false'
