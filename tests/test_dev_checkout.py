"""``lab_commons.dev.checkout`` -- driven on REAL git repositories with REAL remotes.

WHY A REAL REMOTE AND NOT A STUB. Every claim this module makes is about the difference between a
LOCAL pointer and the REMOTE one, and that difference is precisely what a stub erases. So each case
builds an origin with ``git init --bare``, pushes to it, and then moves one side.

THE TRAP IS PLANTED EXPLICITLY, in both directions. A stale local trunk is what made a
fully-integrated lane report as a second pushable branch on one box, and the branch had not changed
-- the local pointer had. :func:`test_integration_is_measured_against_the_remote_not_a_stale_local`
arranges exactly that state and shows the module answering about the remote.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from lab_commons.dev.checkout import (
    authority_for,
    classify,
    debris,
    git_out,
    origin_branches,
    orphan_directories,
    stale_branches,
    survey,
    unmerged_changes,
    worktrees,
)

_GIT = shutil.which('git') or 'git'


def _run(cwd: Path, *args: str) -> None:
    subprocess.run([_GIT, *args], cwd=cwd, check=True, capture_output=True, timeout=60)


def _commit(repo: Path, name: str) -> None:
    (repo / name).write_text(name, encoding='utf-8')
    _run(repo, 'add', name)
    _run(repo, 'commit', '-q', '-m', f'add {name}')


def _origin(tmp_path: Path) -> tuple[Path, Path]:
    """A bare origin and a clone of it sitting on ``main`` with one commit pushed."""
    bare = tmp_path / 'origin.git'
    _run(tmp_path, 'init', '-q', '--bare', '-b', 'main', str(bare))
    work = tmp_path / 'work'
    _run(tmp_path, 'clone', '-q', str(bare), str(work))
    _run(work, 'config', 'user.email', 'a@b.invalid')
    _run(work, 'config', 'user.name', 'Test')
    _commit(work, 'base.txt')
    _run(work, 'push', '-q', 'origin', 'main')
    return bare, work


def test_an_unreadable_repository_is_None_and_never_an_empty_answer(tmp_path: Path) -> None:
    """THE VACUOUS-GREEN REFUSAL, and it is the first thing this module must get right.

    A directory that is not a repository must not render as a repository with nothing in it. Every
    reader here is driven against one, because that is the failure this family has paid for.
    """
    not_a_repo = tmp_path / 'plain'
    not_a_repo.mkdir()
    assert git_out(not_a_repo, 'status') is None
    assert worktrees(not_a_repo) is None
    assert classify(not_a_repo) is None
    assert origin_branches(not_a_repo) is None
    assert survey(not_a_repo, 'origin/main') is None
    assert orphan_directories(not_a_repo) is None
    assert stale_branches(not_a_repo) is None
    assert debris(not_a_repo).readable is False


def test_the_main_checkout_is_the_trunk_and_a_lane_is_classified_by_its_STATE(tmp_path: Path) -> None:
    """Four classes, and none of them is decided by the branch's NAME."""
    _, work = _origin(tmp_path)

    # A lane with work of its own, never pushed: fan-out.
    lane = tmp_path / 'lane'
    _run(work, 'worktree', 'add', '-q', '-b', 'feat/x', str(lane))
    _commit(lane, 'x.txt')

    # A lane whose content is already in the trunk: stale, whatever it is called.
    merged = tmp_path / 'merged'
    _run(work, 'worktree', 'add', '-q', '-b', 'feat/done', str(merged))

    rows = classify(work)
    assert rows is not None
    by_branch = {row.branch: row.kind for row in rows}
    assert by_branch['main'] == 'trunk'
    assert by_branch['feat/x'] == 'fan-out', 'commits nowhere else'
    assert by_branch['feat/done'] == 'stale', 'nothing of its own, so it is safe to delete'
    assert rows[0].branch == 'main', "the MAIN checkout is first -- git's own definition, not the caller's cwd"
    assert all(row.note.strip() for row in rows), 'every row names why it is in its class'


def test_a_second_PUSHED_branch_is_the_violation_this_audit_exists_for(tmp_path: Path) -> None:
    """ONE SESSION, ONE PUSHABLE BRANCH -- and the whole point is that it cannot be held unknowingly."""
    _, work = _origin(tmp_path)
    lane = tmp_path / 'lane'
    _run(work, 'worktree', 'add', '-q', '-b', 'feat/pushed', str(lane))
    _commit(lane, 'p.txt')
    _run(lane, 'push', '-q', 'origin', 'feat/pushed')
    _run(work, 'fetch', '-q', 'origin')

    rows = classify(work)
    assert rows is not None
    pushable = [row for row in rows if row.kind == 'primary']
    assert [row.branch for row in pushable] == ['feat/pushed']
    assert 'SECOND pushable' in pushable[0].note


def test_integration_is_measured_against_the_remote_not_a_stale_local(tmp_path: Path) -> None:
    """THE PLANTED TRAP. The branch does not change; the LOCAL POINTER does, and only one answer moves.

    A third party pushes to origin. The local trunk ref is now behind. A lane whose work IS on
    origin's trunk must read as integrated -- against the stale local ref it reads as 1 unmerged
    commit, which is how an audit built to stop debt starts manufacturing it.
    """
    bare, work = _origin(tmp_path)

    other = tmp_path / 'other'
    _run(tmp_path, 'clone', '-q', str(bare), str(other))
    _run(other, 'config', 'user.email', 'a@b.invalid')
    _run(other, 'config', 'user.name', 'Test')
    _commit(other, 'landed.txt')
    _run(other, 'push', '-q', 'origin', 'main')

    _run(work, 'fetch', '-q', 'origin')  # refs/remotes moves; refs/heads/main does NOT
    local_head = git_out(work, 'rev-parse', 'main')
    remote_head = git_out(work, 'rev-parse', 'origin/main')
    assert local_head is not None
    assert remote_head is not None
    assert local_head.strip() != remote_head.strip(), 'the planted state: the local trunk is behind origin'

    assert authority_for(work, 'main') == 'origin/main'
    assert unmerged_changes(work, 'main', 'origin/main') == 1, 'against the stale local ref the change looks new'
    assert unmerged_changes(work, 'origin/main', 'origin/main') == 0, 'against the remote authority it is landed'


def test_the_origin_survey_counts_CHANGES_rather_than_commits(tmp_path: Path) -> None:
    """`git cherry`, never ancestry: a cherry-picked change is already there and must read as 0."""
    _, work = _origin(tmp_path)
    _run(work, 'checkout', '-q', '-b', 'feat/y')
    _commit(work, 'y.txt')
    _run(work, 'push', '-q', 'origin', 'feat/y')
    sha = (git_out(work, 'rev-parse', 'HEAD') or '').strip()
    _run(work, 'checkout', '-q', 'main')

    rows = survey(work, 'origin/main')
    assert rows is not None
    assert [row.name for row in rows] == ['feat/y']
    assert rows[0].unmerged == 1
    assert not rows[0].deletable

    # The SAME change, cherry-picked onto the trunk and pushed. Ancestry still says "not merged";
    # patch-id equality says the change is there, which is the question actually being asked.
    _run(work, 'cherry-pick', sha)
    _run(work, 'push', '-q', 'origin', 'main')
    _run(work, 'fetch', '-q', 'origin')
    rows = survey(work, 'origin/main')
    assert rows is not None, 'the change is on the base; only the commit id differs'
    assert rows[0].deletable, 'the change is on the base; only the commit id differs'
    assert origin_branches(work) == ('feat/y',), '`main` is protected and never a deletion candidate'


def test_debris_is_reported_and_never_guessed(tmp_path: Path) -> None:
    """Both halves, both directions: an orphan directory and a branch nothing holds or published."""
    _, work = _origin(tmp_path)
    home = Path('trees')
    (work / home).mkdir()

    assert orphan_directories(work, home=home) == (), 'a clean home is empty, and that is not the same as unreadable'
    assert stale_branches(work) == ()

    # A worktree git knows about is NOT debris; a plain directory beside it is.
    _run(work, 'worktree', 'add', '-q', '-b', 'feat/live', str(work / home / 'live'))
    (work / home / 'leftover').mkdir()
    orphans = orphan_directories(work, home=home)
    assert orphans is not None
    assert [p.name for p in orphans] == ['leftover']

    # A branch with no origin counterpart, no upstream, and no worktree holding it.
    _run(work, 'branch', 'abandoned')
    assert stale_branches(work) == ('abandoned',)
    assert 'feat/live' not in (stale_branches(work) or ()), 'a checked-out branch is live, however odd its name'

    census = debris(work, home=home)
    assert census.readable
    assert census.stale_branches == ('abandoned',)
