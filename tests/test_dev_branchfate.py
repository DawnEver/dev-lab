"""TWO-FATES (user ruling 2026-11-15; D31 2026-11-17): a local branch or worktree is merged and cleaned, or listed.

Every planted state below gets exactly one verdict with a reason, and each refusal side has its planted control:
a live process, a live session and an origin-owned lane are kept; unlanded work is listed with its doors and
nothing is ever parked under ``output/``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

from dev_lab.dev.branchfate import ABANDONED_S, settle
from dev_lab.dev.branchset import BranchSet, apply_local
from dev_lab.dev.famtests.visibility import commit, plant_checkout

_GIT = shutil.which('git') or 'git'
_DECLARED = BranchSet(trunk='main', sessions=frozenset())
_NOBODY = {'occupied': lambda _path: False, 'runtimes': {}, 'abandoned_s': 0}


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


def _quiet_lane(work: Path, tmp_path: Path, name: str, hours: float) -> Path:
    """An unmerged lane whose tip commit and index were last touched *hours* ago."""
    tree = tmp_path / name.replace('/', '-')
    _run(work, 'worktree', 'add', '-q', '-b', name, str(tree))
    then = time.time() - hours * 3600
    (tree / 'lane.txt').write_text(name, encoding='utf-8')
    _run(tree, 'add', 'lane.txt')
    env = {**os.environ, 'GIT_COMMITTER_DATE': f'@{int(then)} +0000', 'GIT_AUTHOR_DATE': f'@{int(then)} +0000'}
    subprocess.run(
        [_GIT, 'commit', '-q', '-m', name], cwd=tree, check=True, capture_output=True, text=True,
        encoding='utf-8', env=env, timeout=60,
    )  # fmt: skip
    index = Path(_run(tree, 'rev-parse', '--path-format=absolute', '--git-path', 'index').strip())
    os.utime(index, (then, then))
    return tree


def _parked(work: Path) -> list[Path]:
    """Anything written under the main checkout's ``output/`` -- D31: a fate parks nothing there."""
    return sorted(p for p in (work / 'output').rglob('*') if p.is_file()) if (work / 'output').exists() else []


def test_an_unlanded_lane_with_uncommitted_work_is_listed_with_its_doors_and_touched_in_nothing(
    tmp_path: Path,
) -> None:
    """D31 (user, 2026-11-17): unlanded work is MERGED or the user discards it -- never parked, never removed."""
    work = plant_checkout(tmp_path, trunk='main').work
    tree = _lane(work, tmp_path, 'lane/gone', dirty=True, untracked=True)

    lines = settle(work, ('refs/remotes/origin/main',), quiet_s=0, **_NOBODY) or ()

    [line] = [one for one in lines if 'lane/gone' in one]
    assert line.startswith('unlanded  lane/gone'), lines
    assert 'land it through a PR' in line
    assert '--discard lane/gone --approved' in line
    assert (tree / 'notes.md').is_file()
    assert (tree / 'base.txt').read_text(encoding='utf-8') == 'uncommitted tracked work'
    assert 'lane/gone' in _heads(work)
    assert _parked(work) == []


def test_a_branch_with_no_worktree_and_unmerged_commits_is_listed_not_deleted(tmp_path: Path) -> None:
    work = plant_checkout(tmp_path, trunk='main').work
    _run(work, 'switch', '-q', '-c', 'lost')
    commit(work, 'lost.txt')
    _run(work, 'switch', '-q', 'main')

    lines = settle(work, ('refs/remotes/origin/main',), quiet_s=0, **_NOBODY) or ()

    assert any(line.startswith('unlanded  lost') and 'commits on no holder' in line for line in lines), lines
    assert 'lost' in _heads(work)
    assert _parked(work) == []


def test_a_merged_tree_with_a_stray_edit_is_kept_and_a_clean_merged_one_is_cleaned(tmp_path: Path) -> None:
    """PLANTED CONTROL: the clean landed tree still goes, branch and all; the dirty one is listed, not parked."""
    work = plant_checkout(tmp_path, trunk='main').work
    dirty, clean = tmp_path / 'merged-dirty', tmp_path / 'merged-clean'
    _run(work, 'worktree', 'add', '-q', '-b', 'merged-dirty', str(dirty))
    _run(work, 'worktree', 'add', '-q', '-b', 'merged-clean', str(clean))
    (dirty / 'base.txt').write_text('a stray edit', encoding='utf-8')

    lines = settle(work, ('refs/remotes/origin/main',), quiet_s=0, **_NOBODY) or ()

    assert any(line.startswith('unlanded  merged-dirty') and 'tracked changes' in line for line in lines), lines
    assert (dirty / 'base.txt').read_text(encoding='utf-8') == 'a stray edit'
    assert 'merged-dirty' in _heads(work)
    assert any(line.startswith('merged    merged-clean') for line in lines), lines
    assert not clean.exists()
    assert 'merged-clean' not in _heads(work)
    assert _parked(work) == []


def test_owned_states_are_kept_with_their_owner(tmp_path: Path) -> None:
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

    lines = settle(work, ('refs/remotes/origin/main',), quiet_s=0, abandoned_s=0, occupied=occupied, runtimes={}) or ()
    live = settle(work, ('refs/remotes/origin/main',), quiet_s=3600, occupied=occupied, runtimes={}) or ()

    owned = {line.split()[1]: line for line in lines if line.startswith('owned')}
    assert set(owned) == {'lane/busy', 'lane/locked', 'pr/open'}, lines
    assert 'live' in owned['lane/busy']
    assert 'locked' in owned['lane/locked']
    assert 'origin' in owned['pr/open']
    assert any(line.startswith('unlanded  lane/fresh') for line in lines), 'the control: an idle lane is listed'
    assert all(p.exists() for p in (busy, locked, pushed))
    assert fresh.exists(), 'D31: an unlanded lane is listed, never removed'
    assert _parked(work) == []
    assert not any(line.startswith('unlanded') for line in live), 'a session active within the window is an owner'


def test_apply_local_gives_every_local_branch_one_of_two_fates(tmp_path: Path) -> None:
    work = plant_checkout(tmp_path, trunk='main').work
    _run(work, 'branch', 'landed')
    _quiet_lane(work, tmp_path, 'lane/idle', hours=25)

    lines = apply_local(work, _DECLARED, occupied=lambda _path: False, quiet_s=0) or ()

    assert any(line.startswith('deleted  local   landed') for line in lines), lines
    assert any(line.startswith('unlanded  lane/idle') for line in lines), lines
    assert _heads(work) == {'main', 'lane/idle'}


def test_unmerged_work_is_abandoned_only_after_a_day_of_quiet(tmp_path: Path) -> None:
    """PLANTED BOTH SIDES of ABANDONED_S: 23 h quiet is still a paused session; 25 h is listed as unlanded."""
    assert ABANDONED_S == 24 * 3600
    work = plant_checkout(tmp_path, trunk='main').work
    paused = _quiet_lane(work, tmp_path, 'lane/paused', hours=23)
    gone = _quiet_lane(work, tmp_path, 'lane/gone', hours=25)

    lines = settle(work, ('refs/remotes/origin/main',), occupied=lambda _path: False, runtimes={}) or ()

    owned = [line for line in lines if line.startswith('owned') and 'lane/paused' in line]
    assert owned, lines
    assert 'quiet less than 24 h' in owned[0]
    assert any(line.startswith('unlanded  lane/gone') for line in lines), lines
    assert paused.exists()
    assert gone.exists()
    assert _parked(work) == []
