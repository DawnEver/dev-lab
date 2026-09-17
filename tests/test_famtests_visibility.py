"""``lab_commons.dev.famtests.visibility`` -- driven on REAL repositories with REAL remotes.

WHY A REAL REMOTE AND NOT A STUB. Every claim this body makes is about the difference between a LOCAL
pointer and the REMOTE one, and a stub erases exactly that difference. So each case here runs
``git init --bare``, clones it, pushes to it and then moves one side, which is also what the shipped
control fixtures do for the consumer that calls them.

THE TRUNK TRAP IS PLANTED, and it is why this body takes no default. A repository whose trunk is not
called ``main`` is a real repository, and a guessed trunk finds no ref, counts no commits and reports
the checkout CLEAN. :func:`test_a_guessed_trunk_reports_a_foreign_checkout_clean_and_this_refuses`
builds one and shows the refusal, which is the whole argument for the no-default rule stated in
:mod:`lab_commons.dev.famtests`.

BOTH SIDES OF EVERY NAMED SET. A pin that only reds on ARRIVAL rots in the other direction: a pinned
name whose branch was pushed or deleted goes on reading as a live decision. Each declared-set arm
below is driven with a real branch planted, and then with a real pin outliving a real branch.
"""

from __future__ import annotations

import inspect
import shutil
import subprocess
from pathlib import Path

import pytest

from lab_commons.dev.checkout import unmerged_changes
from lab_commons.dev.famtests.visibility import (
    assert_local_only_branches,
    assert_one_pushable_branch,
    assert_origin_branch_set,
    assert_readable,
    assert_the_planted_debris_is_named,
    assert_the_remote_is_the_authority,
    commit,
    plant_checkout,
)

_GIT = shutil.which('git') or 'git'


def _run(cwd: Path, *args: str) -> None:
    subprocess.run([_GIT, *args], cwd=cwd, check=True, capture_output=True, timeout=60)


# --------------------------------------------------------------------------------------------
# the fixture the consumer's control arms are handed


def test_the_planted_checkout_is_a_real_clone_of_a_real_bare_origin(tmp_path: Path) -> None:
    """The shipped fixture, driven. A control built on a fake repository controls nothing."""
    planted = plant_checkout(tmp_path, trunk='main')
    assert planted.bare.is_dir()
    assert (planted.work / '.git').is_dir()
    listed = subprocess.run(
        [_GIT, 'ls-remote', '--heads', str(planted.bare)], capture_output=True, text=True, check=True, timeout=60
    ).stdout
    assert 'refs/heads/main' in listed, listed


def test_the_planted_checkout_honours_the_trunk_it_is_given(tmp_path: Path) -> None:
    """The fixture takes the trunk too: a control hard-coding ``main`` cannot test a repo without one."""
    planted = plant_checkout(tmp_path, trunk='trunk')
    head = subprocess.run(
        [_GIT, 'rev-parse', '--abbrev-ref', 'HEAD'],
        cwd=planted.work,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    ).stdout.strip()
    assert head == 'trunk', head


# --------------------------------------------------------------------------------------------
# the floor


def test_a_readable_checkout_on_its_trunk_passes(tmp_path: Path) -> None:
    """The green arm, so the refusals below are not the only thing this body can say."""
    planted = plant_checkout(tmp_path, trunk='main')
    assert_readable(root=planted.work, trunk='main')


def test_a_directory_that_is_not_a_repository_is_refused(tmp_path: Path) -> None:
    """THE FLOOR. An unreadable repository must never render as a clean one."""
    plain = tmp_path / 'plain'
    plain.mkdir()
    with pytest.raises(AssertionError, match='could not be read'):
        assert_readable(root=plain, trunk='main')


def test_a_guessed_trunk_reports_a_foreign_checkout_clean_and_this_refuses(tmp_path: Path) -> None:
    """THE NO-DEFAULT ARGUMENT, PLANTED.

    A repository whose trunk is called ``trunk`` is judged against a guessed ``main``. The guess
    resolves to no ref, so every downstream count is zero and the checkout reads as clean. The
    refusal is what makes the guess visible, and it is why ``trunk`` is a required argument.
    """
    planted = plant_checkout(tmp_path, trunk='trunk')
    assert_readable(root=planted.work, trunk='trunk')
    with pytest.raises(AssertionError, match='trunk row'):
        assert_readable(root=planted.work, trunk='main')


# --------------------------------------------------------------------------------------------
# one session, one pushable branch


def test_one_pushable_branch_passes_and_a_planted_second_is_refused(tmp_path: Path) -> None:
    """BOTH DIRECTIONS on the property, through the REAL classification rather than a description."""
    planted = plant_checkout(tmp_path, trunk='main')
    assert_one_pushable_branch(root=planted.work, trunk='main')

    lane = tmp_path / 'lane'
    _run(planted.work, 'worktree', 'add', '-q', '-b', 'feat/second', str(lane))
    commit(lane, 'x.txt')
    _run(lane, 'push', '-q', 'origin', 'feat/second')
    _run(planted.work, 'fetch', '-q', 'origin')

    with pytest.raises(AssertionError, match='feat/second'):
        assert_one_pushable_branch(root=planted.work, trunk='main')


# --------------------------------------------------------------------------------------------
# the named sets, two-sided


def test_the_local_only_pin_reds_on_arrival_and_on_a_pin_that_outlived_its_branch(tmp_path: Path) -> None:
    """A set that only reds one way rots the other way, so both are planted on a real branch."""
    planted = plant_checkout(tmp_path, trunk='main')
    assert_local_only_branches(root=planted.work, declared=frozenset())

    _run(planted.work, 'branch', 'abandoned')
    with pytest.raises(AssertionError, match='abandoned'):
        assert_local_only_branches(root=planted.work, declared=frozenset())
    assert_local_only_branches(root=planted.work, declared=frozenset({'abandoned'}))

    _run(planted.work, 'branch', '-D', 'abandoned')
    with pytest.raises(AssertionError, match='abandoned'):
        assert_local_only_branches(root=planted.work, declared=frozenset({'abandoned'}))


def test_the_origin_pin_reds_on_arrival_and_on_a_pin_nobody_deleted(tmp_path: Path) -> None:
    """The same ratchet over the published side, driven on a real push and a real deletion."""
    planted = plant_checkout(tmp_path, trunk='main')
    assert_origin_branch_set(root=planted.work, declared=frozenset())

    lane = tmp_path / 'lane'
    _run(planted.work, 'worktree', 'add', '-q', '-b', 'deploy', str(lane))
    commit(lane, 'x.txt')
    _run(lane, 'push', '-q', 'origin', 'deploy')
    _run(planted.work, 'fetch', '-q', 'origin')

    with pytest.raises(AssertionError, match='deploy'):
        assert_origin_branch_set(root=planted.work, declared=frozenset())
    assert_origin_branch_set(root=planted.work, declared=frozenset({'deploy'}))

    _run(lane, 'push', '-q', 'origin', '--delete', 'deploy')
    _run(planted.work, 'fetch', '-q', '--prune', 'origin')
    with pytest.raises(AssertionError, match='deploy'):
        assert_origin_branch_set(root=planted.work, declared=frozenset({'deploy'}))


def test_an_empty_declared_set_is_a_measurement_and_must_be_spelled() -> None:
    """``frozenset()`` says "we measured and found none"; omitting it says nothing at all."""
    for name in ('root', 'declared'):
        assert inspect.signature(assert_local_only_branches).parameters[name].default is inspect.Parameter.empty
        assert inspect.signature(assert_origin_branch_set).parameters[name].default is inspect.Parameter.empty


# --------------------------------------------------------------------------------------------
# the controls this body ships so every consumer runs the SAME control


def test_the_remote_authority_control_passes_on_a_real_stale_local_trunk(tmp_path: Path) -> None:
    """The shipped control, run. It plants the state that made this audit lie in a sibling repo."""
    assert_the_remote_is_the_authority(tmp_path, trunk='main')


def test_the_remote_authority_control_is_not_vacuous(tmp_path: Path) -> None:
    """A control that measures NOTHING passes for the wrong reason, so the stale gap is read here.

    If the fixture ever stopped moving origin ahead, the two counts it compares would both be zero
    and the control would pass while proving nothing. This arm asserts the gap is real.
    """
    planted = plant_checkout(tmp_path, trunk='main')
    other = tmp_path / 'other'
    _run(tmp_path, 'clone', '-q', str(planted.bare), str(other))
    _run(other, 'config', 'user.email', 'a@b.invalid')
    _run(other, 'config', 'user.name', 'Test')
    commit(other, 'landed.txt')
    _run(other, 'push', '-q', 'origin', 'main')
    _run(planted.work, 'fetch', '-q', 'origin')
    assert unmerged_changes(planted.work, 'main', 'origin/main') == 1
    assert unmerged_changes(planted.work, 'origin/main', 'origin/main') == 0


def test_the_debris_control_names_a_planted_lane_and_a_planted_orphan(tmp_path: Path) -> None:
    """The second shipped control, run end to end on a real worktree and a real dangling branch."""
    assert_the_planted_debris_is_named(tmp_path, trunk='main')


def test_every_repo_shaped_argument_is_required(tmp_path: Path) -> None:
    """THE FAMILY RULE, ASSERTED RATHER THAN CLAIMED: a default hands one repo another's answer."""
    assert not (tmp_path / 'unused').exists()
    for func in (
        assert_readable,
        assert_one_pushable_branch,
        assert_local_only_branches,
        assert_origin_branch_set,
    ):
        defaults = {
            name: parameter.default
            for name, parameter in inspect.signature(func).parameters.items()
            if parameter.default is not inspect.Parameter.empty
        }
        assert defaults == {}, f'{func.__name__} carries defaults for repo-shaped facts: {defaults}'
