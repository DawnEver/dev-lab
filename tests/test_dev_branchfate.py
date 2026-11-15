"""TWO-FATES (user ruling 2026-11-15): a local branch or worktree is merged-and-cleaned, or cleaned; none lingers.

Every planted state below gets exactly one verdict with a reason, and each refusal side has its planted control:
a live process, a live session and an origin-owned lane are kept and touched in nothing, archive included.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from dev_lab.dev.branchfate import settle
from dev_lab.dev.branchset import BranchSet, apply_local
from dev_lab.dev.famtests.visibility import commit, plant_checkout

_GIT = shutil.which('git') or 'git'
_DECLARED = BranchSet(trunk='main', sessions=frozenset())
_NOBODY = {'occupied': lambda _path: False, 'runtimes': {}}


def _run(cwd: Path, *args: str) -> str:
    return subprocess.run(
        [_GIT, *args], cwd=cwd, check=True, capture_output=True, text=True, encoding='utf-8', timeout=60
    ).stdout


def _heads(work: Path) -> set[str]:
    return set(_run(work, 'branch', '--format=%(refname:short)').split())


def _lane(work: Path, tmp_path: Path, name: str, *, dirty: bool = False, untracked: bool = False) -> Path:
    """An UNMERGED, never-pushed lane checked out in its own worktree."""
    tree = tmp_path / name.replace('/', '-')
    _run(work, 'worktree', 'add', '-q', '-b', name, str(tree))
    _run(tree, 'config', 'user.email', 'a@b.invalid')
    commit(tree, f'{tree.name}.txt')
    if dirty:
        (tree / 'base.txt').write_text('uncommitted tracked work', encoding='utf-8')
    if untracked:
        (tree / 'notes.md').write_text('untracked scratch', encoding='utf-8')
    return tree


def _archives(work: Path) -> list[Path]:
    return sorted(work.glob('output/worktree-archive/*/*/manifest.json'))


def test_an_abandoned_lane_is_archived_losslessly_then_cleaned(tmp_path: Path) -> None:
    work = plant_checkout(tmp_path, trunk='main').work
    tree = _lane(work, tmp_path, 'lane/gone', dirty=True, untracked=True)
    tip = _run(work, 'rev-parse', 'lane/gone').strip()

    lines = settle(work, ('refs/remotes/origin/main',), quiet_s=0, **_NOBODY) or ()

    assert any(line.startswith('abandoned lane/gone') for line in lines), lines
    assert not tree.exists()
    assert 'lane/gone' not in _heads(work)
    [manifest_path] = _archives(work)
    saved = manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    assert manifest['branch'] == 'lane/gone'
    assert manifest['sha'] == tip
    assert all(Path(saved / rel).is_file() for rel in manifest['files'])
    assert 'untracked/notes.md' in manifest['files']
    assert 'dirty.patch' in manifest['files']
    _run(work, 'fetch', '-q', str(saved / 'branch.bundle'), 'refs/heads/lane/gone:refs/heads/restored')
    assert _run(work, 'rev-parse', 'restored').strip() == tip, 'the bundle restores the very tip'
    assert 'uncommitted tracked work' in (saved / 'dirty.patch').read_text(encoding='utf-8')


def test_a_branch_with_no_worktree_is_archived_then_deleted(tmp_path: Path) -> None:
    work = plant_checkout(tmp_path, trunk='main').work
    _run(work, 'switch', '-q', '-c', 'lost')
    commit(work, 'lost.txt')
    _run(work, 'switch', '-q', 'main')

    lines = settle(work, ('refs/remotes/origin/main',), quiet_s=0, **_NOBODY) or ()

    assert any(line.startswith('abandoned lost') for line in lines), lines
    assert 'lost' not in _heads(work)
    assert len(_archives(work)) == 1


def test_a_merged_but_dirty_tree_is_archived_then_cleaned(tmp_path: Path) -> None:
    """Reclaim keeps a landed tree with a tracked change forever; this door saves the change and ends it."""
    work = plant_checkout(tmp_path, trunk='main').work
    tree = tmp_path / 'merged-dirty'
    _run(work, 'worktree', 'add', '-q', '-b', 'merged-dirty', str(tree))
    (tree / 'base.txt').write_text('a stray edit', encoding='utf-8')

    lines = settle(work, ('refs/remotes/origin/main',), quiet_s=0, **_NOBODY) or ()

    assert any(line.startswith('merged    merged-dirty') for line in lines), lines
    assert not tree.exists()
    assert 'merged-dirty' not in _heads(work)
    assert len(_archives(work)) == 1, 'the stray edit is saved before the tree goes'


def test_owned_states_are_kept_with_their_owner_and_never_archived(tmp_path: Path) -> None:
    """PLANTED CONTROLS: a live process, a live session, a lock and an origin lane each keep their tree."""
    work = plant_checkout(tmp_path, trunk='main').work
    busy = _lane(work, tmp_path, 'lane/busy')
    fresh = _lane(work, tmp_path, 'lane/fresh')
    locked = _lane(work, tmp_path, 'lane/locked')
    _run(work, 'worktree', 'lock', '--reason', 'held by hand', str(locked))
    pushed = _lane(work, tmp_path, 'pr/open')
    _run(pushed, 'push', '-q', 'origin', 'pr/open')

    def occupied(path: Path) -> bool:
        return path.resolve() == busy.resolve()

    lines = settle(work, ('refs/remotes/origin/main',), quiet_s=0, occupied=occupied, runtimes={}) or ()
    live = settle(work, ('refs/remotes/origin/main',), quiet_s=3600, occupied=occupied, runtimes={}) or ()

    owned = {line.split()[1]: line for line in lines if line.startswith('owned')}
    assert set(owned) == {'lane/busy', 'lane/locked', 'pr/open'}, lines
    assert 'live' in owned['lane/busy']
    assert 'locked' in owned['lane/locked']
    assert 'origin' in owned['pr/open']
    assert any(line.startswith('abandoned lane/fresh') for line in lines), 'the control: an idle lane does go'
    assert all(p.exists() for p in (busy, locked, pushed))
    assert not fresh.exists()
    assert len(_archives(work)) == 1, 'nothing of an owned tree is archived'
    assert not any(line.startswith('abandoned') for line in live), 'a session active within the window is an owner'


def test_apply_local_gives_every_local_branch_one_of_two_fates(tmp_path: Path) -> None:
    work = plant_checkout(tmp_path, trunk='main').work
    _run(work, 'branch', 'landed')
    _lane(work, tmp_path, 'lane/idle')

    lines = apply_local(work, _DECLARED, occupied=lambda _path: False, quiet_s=0) or ()

    assert any(line.startswith('deleted  local   landed') for line in lines), lines
    assert any(line.startswith('abandoned lane/idle') for line in lines), lines
    assert _heads(work) == {'main'}
