"""A worktree is a LEASE on a branch for one task: reclaimed once its content is landed and it holds nothing else.

Planted on a real repository, every criterion on both sides: a landed tree, a squash-landed one whose origin
ref is gone, go (their branch with them through ``branchset --apply``), and so does a landed tree holding only
IGNORED files (a ``.venv``, run outputs: regenerable). D31 (user, 2026-11-17): a landed tree holding an UNTRACKED,
NOT-IGNORED file is kept, listed with its doors, and nothing of it is parked anywhere. A tree with a modified
TRACKED file, an unlanded one, a pushed-but-unmerged one, a locked one, an occupied one and the main checkout
stay, each with its
reason, counted by reason on the summary line, and a kept tree is not touched. A reclaimable tree goes with its
run outputs: nothing moves into the main checkout's output/ (NO-BACKUP-COPIES, user 2026-11-23).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from lab_commons.census import Process

from dev_lab.dev.branchset import BranchSet, apply_local
from dev_lab.dev.famtests.visibility import commit, plant_checkout
from dev_lab.dev.reclaim import occupancy, reclaim, reclaimable, runtime_of

if sys.platform == 'win32':
    import _winapi  # a junction needs no symlink privilege

_GIT = shutil.which('git') or 'git'
_HOLDERS = ('origin/main',)
_LOG = Path('output/logs/26/10/25/run')
_GONE = {'landed', 'squashed', 'cache', 'notes', 'outputs', 'wrote'}
_KEPT = ('dirty', 'locked', 'occupied', 'open', 'pushed', 'untracked')


def _run(cwd: Path, *args: str) -> str:
    return subprocess.run(
        [_GIT, *args], cwd=cwd, check=True, capture_output=True, text=True, encoding='utf-8', timeout=60
    ).stdout


def _free(_: Path) -> bool:
    return False


def _planted(tmp_path: Path) -> Path:
    planted = plant_checkout(tmp_path, trunk='main')
    work = planted.work
    (work / '.gitignore').write_text('.claude/\n.venv/\noutput/\n', encoding='utf-8')
    _run(work, 'add', '.gitignore')
    _run(work, 'commit', '-q', '-m', 'ignore')
    _run(work, 'push', '-q', 'origin', 'main')
    home = work / '.claude' / 'worktrees'
    # landed: its commit reached origin/main
    _run(work, 'worktree', 'add', '-q', '-b', 'landed', str(home / 'landed'), 'origin/main')
    commit(home / 'landed', 'landed.txt')
    _run(home / 'landed', 'push', '-q', 'origin', 'landed:main')
    (home / 'landed' / '.venv').mkdir()
    (home / 'landed' / '.venv' / 'pyvenv.cfg').write_text('', encoding='utf-8')
    # squashed: two commits squash-merged on origin, then its origin ref deleted
    _run(work, 'worktree', 'add', '-q', '-b', 'squashed', str(home / 'squashed'), 'origin/main')
    commit(home / 'squashed', 's1.txt')
    commit(home / 'squashed', 's2.txt')
    _run(home / 'squashed', 'push', '-q', '-u', 'origin', 'squashed')
    _run(work, 'fetch', '-q', 'origin')
    _run(work, 'merge', '-q', '--ff-only', 'origin/main')
    _run(work, 'merge', '-q', '--squash', 'origin/squashed')
    _run(work, 'commit', '-q', '-m', 'squash')
    _run(work, 'push', '-q', 'origin', 'main')
    _run(work, 'push', '-q', 'origin', '--delete', 'squashed')
    _run(work, 'fetch', '-q', '--prune', 'origin')
    for name in ('dirty', 'locked', 'occupied', 'untracked', 'outputs'):
        _run(work, 'worktree', 'add', '-q', '--detach', str(home / name), 'origin/main')
    (home / 'dirty' / '.gitignore').write_text('changed\n', encoding='utf-8')
    _plant(home / 'untracked' / 'scratch' / 'probe.py', 'one-off')
    _plant(home / 'untracked' / 'loose.txt', 'untracked')
    _plant(home / 'outputs' / '.venv' / 'pyvenv.cfg', '')
    _plant(home / 'outputs' / _LOG / 'r.txt', 'result')
    _run(work, 'worktree', 'lock', str(home / 'locked'))
    _run(work, 'worktree', 'add', '-q', '-b', 'open', str(home / 'open'), 'origin/main')
    commit(home / 'open', 'open.txt')
    _plant(home / 'open' / 'loose.txt', 'untracked in an unlanded tree')
    _plant(home / 'open' / _LOG / 'o.txt', 'output of an unlanded tree')
    _run(work, 'worktree', 'add', '-q', '-b', 'pushed', str(home / 'pushed'), 'origin/main')
    commit(home / 'pushed', 'pushed.txt')
    _run(home / 'pushed', 'push', '-q', 'origin', 'pushed')
    (home / 'cache' / '__pycache__').mkdir(parents=True)
    (home / 'cache' / '__pycache__' / 'm.pyc').write_text('', encoding='utf-8')
    _plant(home / 'notes' / 'note.txt', 'agent output')
    _plant(home / 'wrote' / _LOG / 'n.txt', 'orphan result')
    (home / 'notes' / 'output' / 'logs').mkdir(parents=True)  # an EMPTY output tree is no defect
    _settled(work)
    return work


def _settled(work: Path) -> None:
    """Age every linked tree's index past the live-session window (``dev_lab.dev.reclaim.QUIET_S``)."""
    old = time.time() - 2 * 3600
    for index in (work / '.git' / 'worktrees').glob('*/index'):
        os.utime(index, (old, old))


def _plant(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def _occupied(path: Path) -> bool:
    return path.name == 'occupied'


def test_every_tree_is_judged_with_its_reason(tmp_path: Path) -> None:
    work = _planted(tmp_path)
    leases = {lease.path.name: lease for lease in reclaimable(work, _HOLDERS, occupied=_occupied) or ()}
    assert {n for n, lease in leases.items() if lease.reclaimable} == _GONE
    assert 'tracked changes' in leases['dirty'].reason
    assert leases['untracked'].reason.startswith('untracked work -- commit it on its branch'), leases['untracked']
    assert '--discard <branch> --approved' in leases['untracked'].reason
    assert 'loose.txt' in leases['untracked'].reason
    assert 'scratch/probe.py' in leases['untracked'].reason
    assert 'locked' in leases['locked'].reason
    assert 'live' in leases['occupied'].reason
    assert 'not landed' in leases['open'].reason
    assert 'not landed' in leases['pushed'].reason, 'pushed is not landed'
    assert work.resolve() not in {lease.path for lease in leases.values()}, 'the main checkout is never a lease'


def test_reclaim_removes_only_the_reclaimable_and_lists_the_rest(tmp_path: Path) -> None:
    work = _planted(tmp_path)
    home = work / '.claude' / 'worktrees'
    lines = reclaim(work, _HOLDERS, occupied=_occupied) or ()
    for gone in _GONE:
        assert not (home / gone).exists(), gone
        assert any(line.startswith('removed') and gone in line for line in lines)
    for kept in _KEPT:
        assert (home / kept).is_dir(), kept
        assert any(line.startswith('kept') and kept in line for line in lines)
    assert (home / 'open' / 'loose.txt').is_file(), 'CONTROL: an unlanded tree keeps its untracked files'
    assert (home / 'open' / _LOG / 'o.txt').is_file(), 'CONTROL: a kept tree keeps its outputs in place'
    assert not (work / _LOG / 'o.txt').exists(), 'CONTROL: a kept tree moves nothing home'
    assert not any('untracked files' in line for line in lines), lines
    assert (home / 'dirty' / '.gitignore').read_text(encoding='utf-8') == 'changed\n'
    assert (home / 'untracked' / 'loose.txt').is_file(), 'D31: untracked work stays in its tree'
    assert {p.relative_to(work).parts[:2] for p in (work / 'output').rglob('*') if p.is_file()} <= {('output', 'logs')}


def test_a_reclaimed_tree_goes_with_its_outputs_and_main_output_gains_nothing(tmp_path: Path) -> None:
    """NO-BACKUP-COPIES (user 2026-11-23): removing a tree deletes its output/; nothing moves into main's."""
    work = _planted(tmp_path)
    home = work / '.claude' / 'worktrees'
    before = sorted((work / 'output').rglob('*')) if (work / 'output').exists() else []
    lines = reclaim(work, _HOLDERS, occupied=_occupied) or ()
    for name in ('wrote', 'outputs'):
        assert not (home / name).exists(), lines
        assert any(line.startswith('removed') and name in line for line in lines), lines
    after = sorted((work / 'output').rglob('*')) if (work / 'output').exists() else []
    assert after == before, 'PLANTED CONTROL: two trees held run outputs, and main output/ gained none of them'
    assert not (home / 'notes').exists(), 'CONTROL: an empty output tree is deleted directly'


def test_the_summary_line_counts_every_kept_tree_by_reason(tmp_path: Path) -> None:
    work = _planted(tmp_path)
    census = reclaim(work, _HOLDERS, occupied=_occupied, apply=False) or ()
    kept = 'kept 6 (live 1, locked 1, not landed 2, tracked changes 1, untracked work 1)'
    assert census[-1] == f'summary  prunable 6, {kept}', census
    lines = reclaim(work, _HOLDERS, occupied=_occupied) or ()
    assert lines[-1] == f'summary  removed 6, {kept}', lines


def test_branchset_apply_reclaims_first_so_the_landed_branch_is_deleted(tmp_path: Path) -> None:
    work = _planted(tmp_path)
    lines = apply_local(work, BranchSet(trunk='main', sessions=frozenset()), occupied=_occupied) or ()
    assert any(line.startswith('removed') and 'landed' in line for line in lines)
    assert any(line.startswith('deleted  local   landed') for line in lines)
    heads = set(_run(work, 'branch', '--format=%(refname:short)').split())
    assert 'landed' not in heads
    assert {'open', 'pushed'} <= heads


def test_an_unreadable_root_is_none(tmp_path: Path) -> None:
    assert reclaimable(tmp_path, _HOLDERS, occupied=_free) is None
    assert reclaim(tmp_path, _HOLDERS, occupied=_free) is None


def test_a_tree_the_sweeps_own_ancestor_executes_from_is_kept(tmp_path: Path) -> None:
    """INCIDENT 2026-10-31: the sweep ran under ai-lab's ``runtime`` session, whose venv python IS its ancestor.

    The edit lock forgives the asker's own family; a removal cannot: it would delete the interpreter its own
    session runs on. A planted census: the sweep (pid 3) under a shell (2) under the tree's venv python (1).
    """
    tree = tmp_path / 'runtime'
    python = tree / '.venv' / 'Scripts' / 'python.exe'
    table = (
        Process(1, 0, str(python), f'{python} -m ai_lab.session', 9e4, str(tmp_path)),
        Process(2, 1, 'bash', 'bash', 9e4, str(tmp_path)),
        Process(3, 2, 'python', 'python -m dev_lab.dev.branchprune sweep --local', 1.0, str(tmp_path)),
    )
    assert occupancy(census=lambda: table, me=3)(tree), 'its own ancestor executes from the tree'
    assert not occupancy(census=lambda: table, me=3)(tmp_path / 'free'), 'CONTROL: a free tree is not in use'


def test_a_tree_a_live_process_holds_is_kept_and_a_free_one_still_goes(tmp_path: Path) -> None:
    """PLANTED LIVE PROCESS working in the landed tree, judged by the REAL census (the default occupancy)."""
    work = _planted(tmp_path)
    home = work / '.claude' / 'worktrees'
    held = home / 'landed'
    planted = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'], cwd=held)
    try:
        lines = reclaim(work, _HOLDERS) or ()
    finally:
        planted.kill()
        planted.wait()
    assert (held / 'landed.txt').is_file(), 'a tree in use is not touched'
    assert any(line.startswith('kept') and 'landed' in line and 'live' in line for line in lines), lines
    assert not (home / 'squashed').exists(), 'CONTROL: a free landed tree is still removed'


def test_a_removal_that_fails_partway_leaves_no_tracked_file_deleted(tmp_path: Path, monkeypatch) -> None:
    """PLANTED MID-REMOVAL FAILURE: the deleter takes a tracked file, then a held file refuses it."""
    work = _planted(tmp_path)
    home = work / '.claude' / 'worktrees'

    def half(path: Path) -> None:
        (path / '.git').unlink()
        for tracked in path.glob('*.txt'):
            tracked.unlink()
        raise PermissionError(13, 'access denied', str(path / '.venv' / 'Scripts' / 'python.exe'))

    monkeypatch.setattr('dev_lab.dev.reclaim.remove_tree', half)
    lines = reclaim(work, _HOLDERS, occupied=_free) or ()
    landed = home / 'landed'
    assert (landed / 'landed.txt').is_file(), 'a tracked file was left deleted'
    assert _run(landed, 'status', '--porcelain', '--untracked-files=no') == '', 'the tree is not HEAD again'
    assert any(line.startswith('FAILED') and 'landed' in line and 'restored' in line for line in lines), lines


def test_a_tree_held_past_the_census_is_refused_before_anything_is_deleted(tmp_path: Path) -> None:
    """A process the census cannot see (``occupied`` says free) still holds the tree: the move-aside refuses."""
    work = _planted(tmp_path)
    held = work / '.claude' / 'worktrees' / 'landed'
    planted = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'], cwd=held)
    try:
        lines = reclaim(work, _HOLDERS, occupied=_free) or ()
    finally:
        planted.kill()
        planted.wait()
    if os.name != 'nt':  # POSIX deletes under a working process; there is nothing to refuse
        assert not held.exists()
        return
    assert (held / 'landed.txt').is_file(), 'a held tree lost a tracked file'
    assert any(line.startswith('kept') and 'in use' in line and 'landed' in line for line in lines), lines


def _runtime_tree(tmp_path: Path) -> tuple[Path, Path]:
    """A planted checkout plus a detached, landed, settled tree holding an ignored ``.venv`` interpreter."""
    work = _planted(tmp_path)
    tree = work / '.claude' / 'worktrees' / 'runtime-2'
    _run(work, 'worktree', 'add', '-q', '--detach', str(tree), 'origin/main')
    _plant(tree / '.venv' / 'Scripts' / 'python.exe', '')
    _settled(work)
    return work, tree


def test_a_tree_the_host_config_names_as_a_runtime_is_kept_with_the_reason(tmp_path: Path) -> None:
    work, tree = _runtime_tree(tmp_path)
    runtimes = {'ai_lab': {'python': str(tree / '.venv' / 'Scripts' / 'python.exe')}}
    lines = reclaim(work, _HOLDERS, occupied=_occupied, runtimes=runtimes) or ()
    assert tree.is_dir()
    assert any(line.startswith('kept') and 'runtime-2' in line and 'runtime of ai_lab' in line for line in lines), lines


def test_the_same_tree_without_the_runtime_entry_is_reclaimed(tmp_path: Path) -> None:
    work, tree = _runtime_tree(tmp_path)
    lines = reclaim(work, _HOLDERS, occupied=_occupied, runtimes={'other': {'python': str(tmp_path / 'py')}}) or ()
    assert not tree.exists()
    assert any(line.startswith('removed') and 'runtime-2' in line for line in lines), lines


def test_a_runtime_whose_leaf_links_outside_the_tree_still_keeps_it(tmp_path: Path) -> None:
    """A venv path may be a link to the base interpreter's tree; the value lives in the tree, not its target.

    The link is a directory one, so every host can plant it: a symlink on POSIX, a junction (no privilege) on Windows.
    """
    tree, base = tmp_path / 'runtime-2', tmp_path / 'base-python'
    base.mkdir()
    tree.mkdir()
    leaf = tree / '.venv'
    _link_dir(leaf, base)
    assert leaf.resolve() == base.resolve(), 'the planted leaf points outside the tree'
    assert runtime_of(tree, {'ai_lab': {'python': str(leaf)}}).startswith('runtime of ai_lab')


def _link_dir(link: Path, target: Path) -> None:
    if sys.platform == 'win32':
        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)
