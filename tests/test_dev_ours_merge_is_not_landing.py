"""ANCESTRY IS NOT LANDING (dev-lab #611): a branch an ``-s ours`` merge made an ancestor is never silently "landed".

The retire merges of 2026-11-23 (``chore(merge): retire stale ... (idle >24h, unlanded)``) were ``git merge -s ours``:
the branch's commits became ancestors of integration while none of their content arrived, and every judge that asks
``merge-base --is-ancestor`` then read the work as landed -- the prune, the branch policy, LOSSLESS-DELETE and the
integrator's queue. Driven on the prune's REAL bare origin (:mod:`tests.test_dev_branchprune`): ``lane/unmerged``
carries one commit writing ``unmerged``, and is merged into integration ``-s ours``.

PLANTED CONTROL beside every refusal: the same branch merged for real (``--no-ff``) IS landed by each judge, so the
judges tell a discard from a landing rather than refusing every merged branch.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.dev.branchpolicy import STALE as POLICY_STALE
from dev_lab.dev.branchpolicy import derive
from dev_lab.dev.branchprune import DELETABLE, MERGED, STALE, UNKNOWN_IDLE, UNMERGED, survey
from dev_lab.dev.branchset import declared_branchset
from dev_lab.dev.deletejudge import ORIGIN, discarded, judge, landed
from dev_lab.dev.integrator import _absorbed
from dev_lab.dev.lanepolicy import load_policy
from tests.test_dev_branchprune import ACTIVITY, NOW, BareForge, _git, _on_origin, _planted, _prune

_HOLDER = f'{ORIGIN}integrate/main'


def _merged(tmp_path: Path, *strategy: str) -> tuple[Path, Path, str]:
    """The planted repo with lane/unmerged merged into integration by *strategy*; its root, origin and tip."""
    root, origin = _planted(tmp_path, extra='max_idle_hours = 12\n')
    tip = _git(root, 'rev-parse', 'lane/unmerged')
    _git(root, 'checkout', '-q', 'integrate/main')
    _git(root, 'merge', '-q', '--no-ff', *strategy, '-m', 'retire stale lane/unmerged', 'lane/unmerged')
    _git(root, 'push', '-q', 'origin', 'integrate/main')
    _git(root, 'fetch', '-q', '--prune', 'origin')
    return root, origin, tip


@pytest.fixture
def ours(tmp_path: Path) -> tuple[Path, Path, str]:
    return _merged(tmp_path, '-s', 'ours')


@pytest.fixture
def real(tmp_path: Path) -> tuple[Path, Path, str]:
    return _merged(tmp_path)


def test_the_discard_names_the_merge_and_the_file_it_dropped(ours: tuple[Path, Path, str]) -> None:
    root, _, tip = ours
    assert _git(root, 'merge-base', '--is-ancestor', tip, _HOLDER) == '', 'the premise: ancestry says landed'
    found = discarded(root, tip, _HOLDER)
    assert found is not None
    merge, files = found
    assert merge == _git(root, 'rev-parse', _HOLDER)
    assert files == ('unmerged',)
    assert not landed(root, tip, (_HOLDER,))


def test_a_real_merge_discards_nothing_and_is_landed(real: tuple[Path, Path, str]) -> None:
    """PLANTED control."""
    root, _, tip = real
    assert discarded(root, tip, _HOLDER) is None
    assert landed(root, tip, (_HOLDER,))


def test_a_branch_on_the_first_parent_chain_landed_directly(tmp_path: Path) -> None:
    """A fast-forwarded tip has no landing merge: it is integration's own history."""
    root, _ = _planted(tmp_path)
    tip = _git(root, 'rev-parse', 'refs/remotes/origin/integrate/main~1')
    assert discarded(root, tip, _HOLDER) is None


def test_the_prune_keeps_and_alarms_a_discarded_branch(ours: tuple[Path, Path, str]) -> None:
    root, origin, _ = ours
    rows = survey(root, declared_branchset(root), load_policy(root), open_heads=frozenset(), now=NOW, activity=ACTIVITY)
    assert {(row.rule, row.action) for row in rows if row.ref == 'lane/unmerged'} == {(UNMERGED, STALE)}
    _, alarms, _ = _prune(root, BareForge(origin))
    assert 'lane/unmerged' in _on_origin(origin)
    body = '\n'.join(alarm.body for alarm in alarms)
    assert 'dropping it discards 1 commit(s)' in body
    assert 'with content in: unmerged' in body


def test_the_prune_lists_a_really_merged_branch_as_merged(real: tuple[Path, Path, str]) -> None:
    """PLANTED control."""
    root, _, _ = real
    rows = survey(root, declared_branchset(root), load_policy(root), open_heads=frozenset(), now=NOW, activity=ACTIVITY)
    assert {(row.rule, row.action) for row in rows if row.ref == 'lane/unmerged'} == {(MERGED, DELETABLE)}


def test_the_policy_raises_the_stale_row_listing_what_a_discard_drops(ours: tuple[Path, Path, str]) -> None:
    root, _, tip = ours
    rows = derive(root, declared_branchset(root), load_policy(root), now=NOW, activity=ACTIVITY)
    (row,) = [row for row in rows if row.branch == 'lane/unmerged']
    assert row.kind == POLICY_STALE
    assert f'1 commit(s) ({tip[:12]}) with content in: unmerged' == row.discards
    body = row.body('integrate/main', 'max_idle_hours = 12')
    assert 'branchprune discard lane/unmerged --approved' in body
    assert 'merge -s ours` PR' not in body


def test_the_policy_acquits_a_really_merged_branch(real: tuple[Path, Path, str]) -> None:
    """PLANTED control."""
    root, _, _ = real
    rows = derive(root, declared_branchset(root), load_policy(root), now=NOW, activity=ACTIVITY)
    assert [row for row in rows if row.branch == 'lane/unmerged'] == []


def test_lossless_delete_refuses_a_branch_only_a_discard_holds(ours: tuple[Path, Path, str]) -> None:
    root, _, tip = ours
    verdict = judge(root, load_policy(root), 'lane/unmerged', tip, open_heads={})
    assert verdict.container == ''
    assert 'kept none of its content in: unmerged' in verdict.refused
    assert verdict.lost == (tip,)


def test_lossless_delete_passes_a_really_merged_branch(real: tuple[Path, Path, str]) -> None:
    """PLANTED control."""
    root, _, tip = real
    verdict = judge(root, load_policy(root), 'lane/unmerged', tip, open_heads={})
    assert verdict.refused == ''
    assert verdict.container == 'integrate/main'


def test_the_integrator_never_reads_a_discarded_lane_as_absorbed(ours: tuple[Path, Path, str]) -> None:
    root, _, tip = ours
    assert not _absorbed(root, 'integrate/main', tip)


def test_the_integrator_reads_a_really_merged_lane_as_absorbed(real: tuple[Path, Path, str]) -> None:
    """PLANTED control."""
    root, _, tip = real
    assert _absorbed(root, 'integrate/main', tip)


def test_an_unknown_activity_is_listed_and_never_deleted_or_retired(tmp_path: Path) -> None:
    """IDLE-IS-ACTIVITY: with no push or PR on record the age is UNKNOWN -- no delete, no stale alarm, no retire row."""
    root, origin = _planted(tmp_path, extra='max_idle_hours = 12\nprune_merged = true\n')
    branchset, policy = declared_branchset(root), load_policy(root)
    rows = survey(root, branchset, policy, open_heads=frozenset(), now=NOW, activity=lambda _b: None)
    unknown = {row.ref: row for row in rows if row.action == UNKNOWN_IDLE}
    assert {'lane/merged', 'lane/unmerged'} <= set(unknown)
    assert 'idle UNKNOWN' in unknown['lane/merged'].line()
    assert 'lane/young' not in unknown, 'a commit inside the bound is not idle, whatever the forge says'
    assert derive(root, branchset, policy, now=NOW, activity=lambda _b: None) == ()
    forge = BareForge(origin)
    forge.activity = dict.fromkeys(('lane/merged', 'lane/unmerged', 'feat/session'), '')
    _prune(root, forge)
    assert 'lane/merged' in _on_origin(origin), 'an UNKNOWN age never deletes'
