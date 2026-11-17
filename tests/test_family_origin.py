"""``family check`` reads every member's content from ``origin/<integration>``, never the working tree.

MEASURED 2026-11-10: the dev-lab primary checkout stood 723 commits behind its origin, and the horizontal comparison
named it as lacking ``AGENTS.md`` and ``merge-tick.yml`` -- both long landed on its integration branch. A checkout's
working tree is whatever a session last left there; the member's fact is what its integration branch holds.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from dev_lab.dev.family.origin import Snapshot, snapshot

_GIT = shutil.which('git') or 'git'
MANIFEST = "[tool.dev_lab.integrator]\nintegration = 'integrate/main'\ntrunk = 'main'\n"


def _git(root: Path, *args: str) -> str:
    return subprocess.run([_GIT, *args], cwd=root, check=True, capture_output=True, text=True, encoding='utf-8').stdout


def _member(tmp_path: Path) -> tuple[Path, Path]:
    """A bare origin whose integrate/main carries AGENTS.md, and a clone whose working tree predates it."""
    seed = tmp_path / 'seed'
    seed.mkdir()
    _git(seed, 'init', '-q', '-b', 'integrate/main')
    _git(seed, 'config', 'user.email', 'a@example.invalid')
    _git(seed, 'config', 'user.name', 'a')
    (seed / 'pyproject.toml').write_text(MANIFEST, encoding='utf-8')
    _git(seed, 'add', 'pyproject.toml')
    _git(seed, 'commit', '-q', '-m', 'one')
    bare = tmp_path / 'origin.git'
    _git(tmp_path, 'clone', '-q', '--bare', str(seed), str(bare))
    clone = tmp_path / 'clone'
    _git(tmp_path, 'clone', '-q', str(bare), str(clone))
    (seed / 'AGENTS.md').write_text('x', encoding='utf-8')
    (seed / '.github' / 'workflows').mkdir(parents=True)
    (seed / '.github' / 'workflows' / 'merge-tick.yml').write_text('x', encoding='utf-8')
    _git(seed, 'add', '.')
    _git(seed, 'commit', '-q', '-m', 'two')
    _git(seed, 'push', '-q', str(bare), 'integrate/main')
    return clone, bare


def _fetch(root: Path) -> None:
    _git(root, 'fetch', '-q', 'origin')


def test_the_snapshot_is_the_integration_branch_after_a_fetch_not_the_stale_working_tree(tmp_path: Path) -> None:
    clone, _ = _member(tmp_path)
    assert not (clone / 'AGENTS.md').exists()  # PLANTED CONTROL: the working tree is stale
    held = snapshot(clone, fetch=_fetch)
    assert held.rev == 'origin/integrate/main'
    assert held.has('AGENTS.md')
    assert held.names('.github/workflows') == {'merge-tick.yml'}
    assert 'integrate/main' in held.manifest


def test_without_the_fetch_the_old_origin_ref_shows_the_old_tree(tmp_path: Path) -> None:
    """PLANTED CONTROL for the fetch: the snapshot reads the ref, so skipping the fetch reads the stale ref."""
    clone, _ = _member(tmp_path)
    assert not snapshot(clone, fetch=lambda _root: None).has('AGENTS.md')


def test_a_member_whose_fetch_fails_or_never_fetched_is_unread_never_lacking(tmp_path: Path) -> None:
    clone, _ = _member(tmp_path)

    def refused(_root: Path) -> None:
        msg = 'network down'
        raise OSError(msg)

    with pytest.raises(OSError, match='network down'):
        snapshot(clone, fetch=refused)
    lone = tmp_path / 'lone'
    lone.mkdir()
    _git(lone, 'init', '-q')
    (lone / 'pyproject.toml').write_text(MANIFEST, encoding='utf-8')
    with pytest.raises(OSError, match='origin'):
        snapshot(lone, fetch=lambda _root: None)


def test_a_snapshot_is_plain_data() -> None:
    held = Snapshot('origin/x', frozenset({'a/b.yml', 'a/c/d.yml', 'AGENTS.md'}), '')
    assert held.names('a') == {'b.yml'}
    assert held.has('AGENTS.md')
    assert not held.has('a')
