"""BRANCH-POLICY-OBSERVED (D46): the declaration, the rows, one stable issue per row, and who runs the duty.

Driven on a REAL bare origin (the prune's planted repo, :mod:`tests.test_dev_branchprune`), the issues through the
in-memory forge. Every bound has its planted acquittal beside it: a merged branch, a declared branch and a branch
inside both bounds are never rows; a base rewound at delete time keeps the branch; a machine the family does not bind
never runs the duty.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from dev_lab.dev import branchpolicy, forgefeed
from dev_lab.dev.branchpolicy import OVER_AHEAD, PREFIX, STALE, derive, observe, run_here
from dev_lab.dev.branchprune import prune
from dev_lab.dev.branchset import BranchSetKeyRetired, BranchSetNotDeclared, declared_branchset
from dev_lab.dev.lanepolicy import load_policy
from dev_lab.dev.roles import CI, HOST, HPC, PRUNE, Executor, Roles, performs
from tests._forge_state import StateForge
from tests.test_dev_branchprune import NOW, BareForge, _commit, _git, _on_origin, _planted

# ---------------------------------------------------------------------------------------------- the declaration


def test_the_declaration_names_both_bounds(tmp_path: Path) -> None:
    root, _ = _planted(tmp_path, extra='max_ahead = 10\nmax_idle_hours = 12\n')
    declared = declared_branchset(root)
    assert (declared.max_ahead, declared.max_idle_hours) == (10, 12.0)


def test_an_absent_max_ahead_judges_nothing(tmp_path: Path) -> None:
    root, _ = _planted(tmp_path)
    assert declared_branchset(root).max_ahead is None


@pytest.mark.parametrize('extra', ['max_ahead = -1\n', 'max_ahead = 2.5\n', 'max_ahead = true\n'])
def test_a_malformed_max_ahead_is_refused_by_name(tmp_path: Path, extra: str) -> None:
    root, _ = _planted(tmp_path, extra=extra)
    with pytest.raises(BranchSetNotDeclared, match='max_ahead'):
        declared_branchset(root)


def test_the_retired_grace_hours_is_refused_naming_its_replacement(tmp_path: Path) -> None:
    root, _ = _planted(tmp_path, extra='grace_hours = 24\n')
    with pytest.raises(BranchSetKeyRetired, match='grace_hours is retired: renamed max_idle_hours'):
        declared_branchset(root)


# ---------------------------------------------------------------------------------------------- the rows


def _behind(root: Path, commits: int) -> None:
    """Move origin's integration *commits* ahead of every lane."""
    _git(root, 'checkout', '-q', 'integrate/main')
    for n in range(commits):
        _commit(root, f'base-{n}', date='2026-10-13T11:30:00+00:00')
    _git(root, 'push', '-q', 'origin', 'integrate/main')
    _git(root, 'fetch', '-q', '--prune', 'origin')


def test_rows_name_the_unmerged_stale_and_the_over_ahead_lane_and_acquit_the_rest(tmp_path: Path) -> None:
    """lane/unmerged is idle 72 h and 3 behind; merged, declared and young lanes are never rows (by NAME)."""
    root, _ = _planted(tmp_path, extra='max_ahead = 2\nmax_idle_hours = 12\n')
    _behind(root, 3)
    rows = derive(root, declared_branchset(root), load_policy(root), now=NOW)
    assert {(row.kind, row.branch) for row in rows} == {(OVER_AHEAD, 'lane/unmerged'), (STALE, 'lane/unmerged')}
    over = next(row for row in rows if row.kind == OVER_AHEAD)
    assert (over.ahead, over.behind) == (1, 11)  # 4 landed lanes x (commit + merge) + 3 base commits it lacks


def test_a_lane_inside_both_bounds_is_no_row(tmp_path: Path) -> None:
    root, _ = _planted(tmp_path, extra='max_ahead = 100\nmax_idle_hours = 1000\n')
    assert derive(root, declared_branchset(root), load_policy(root), now=NOW) == ()


# ---------------------------------------------------------------------------------------------- the issues


def test_observe_keeps_one_issue_per_row_writes_nothing_twice_and_closes_a_cleared_row(tmp_path: Path) -> None:
    root, _ = _planted(tmp_path, extra='max_idle_hours = 12\n')
    forge = StateForge()
    first = observe(root, forge, now=NOW)
    assert [(r.area, r.action) for r in first] == [(f'{PREFIX}{STALE} lane/unmerged', 'created')]
    again = observe(root, forge, now=NOW)
    assert [r.action for r in again] == ['unchanged']
    _git(root, 'checkout', '-q', 'integrate/main')
    _git(root, 'merge', '-q', '--no-ff', '-m', 'land it', 'lane/unmerged')
    _git(root, 'push', '-q', 'origin', 'integrate/main')
    _git(root, 'fetch', '-q', '--prune', 'origin')
    cleared = observe(root, forge, now=NOW)
    assert [(r.area, r.action) for r in cleared] == [(f'{PREFIX}{STALE} lane/unmerged', 'closed')]


def test_the_issue_key_carries_no_sha_so_a_moved_branch_keeps_its_issue(tmp_path: Path) -> None:
    root, _ = _planted(tmp_path, extra='max_idle_hours = 12\n')
    forge = StateForge()
    observe(root, forge, now=NOW)
    _git(root, 'checkout', '-q', 'lane/unmerged')
    _commit(root, 'more')
    _git(root, 'push', '-q', 'origin', 'lane/unmerged')
    _git(root, 'fetch', '-q', '--prune', 'origin')
    moved = observe(root, forge, now=NOW)
    assert [r.action for r in moved] == ['updated']
    assert len([i for i in forge.issues_by_number.values() if i['title'].startswith(PREFIX)]) == 1


# ---------------------------------------------------------------------------------------------- delete time


def test_a_base_rewound_after_the_survey_keeps_the_branch(tmp_path: Path) -> None:
    """PLANTED: the survey saw lane/merged held; the delete-time fetch sees integration rewound past it."""
    root, origin = _planted(tmp_path, extra='prune_merged = true\n')
    rewind = _git(root, 'rev-parse', 'main')

    def rewound_fetch(at: Path) -> None:
        _git(origin, 'update-ref', 'refs/heads/integrate/main', rewind)
        _git(at, 'fetch', '-q', '--prune', 'origin')

    said: list[str] = []
    prune(root, BareForge(origin), now=NOW, say=said.append, alarm=lambda _a: None, fetch=rewound_fetch)
    assert 'lane/merged' in _on_origin(origin)
    assert any('no longer held' in line and 'lane/merged' in line for line in said)


def test_a_base_still_holding_it_at_delete_time_deletes_it(tmp_path: Path) -> None:
    root, origin = _planted(tmp_path, extra='prune_merged = true\n')
    forge = BareForge(origin)
    prune(root, forge, now=NOW, say=lambda _s: None, alarm=lambda _a: None, fetch=lambda _r: None)
    assert forge.deleted == ['lane/merged']


# ---------------------------------------------------------------------------------------------- who runs it


def _bound(executor: Executor) -> Roles:
    kinds = dict.fromkeys(('tests', 'review', 'merge', 'promote'), Executor(CI))
    return Roles({**kinds, PRUNE: executor})


def test_performs_is_true_only_for_the_bound_host() -> None:
    assert performs(_bound(Executor(HOST, host='box-a')), PRUNE, 'box-a')
    assert not performs(_bound(Executor(HOST, host='box-a')), PRUNE, 'box-b')
    assert not performs(_bound(Executor(HPC, cluster='c', grant_role='r')), PRUNE, 'box-a')


def test_run_here_runs_the_duty_only_on_the_bound_machine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[Path] = []
    monkeypatch.setattr(branchpolicy, 'prune_duty', lambda root, _client, **_kw: ran.append(root))
    monkeypatch.setattr(branchpolicy, 'forge_from_remote', lambda _root: StateForge().forge)
    mine, theirs = tmp_path / 'mine', tmp_path / 'theirs'
    roles = {mine: _bound(Executor(HOST, host='box-a')), theirs: _bound(Executor(CI))}
    done = run_here(
        [mine, theirs],
        clients=lambda _f: StateForge(),
        machine='box-a',
        now=NOW,
        say=lambda _s: None,
        fetch=lambda _r: None,
        roles=roles.__getitem__,
    )
    assert ran == [mine]
    assert len(done) == 1
    ran.clear()
    run_here(
        [mine], clients=lambda _f: StateForge(), machine='box-b', now=NOW, say=lambda _s: None,
        fetch=lambda _r: None, roles=roles.__getitem__,
    )  # fmt: skip
    assert ran == []


# ---------------------------------------------------------------------------------------------- the interval


def test_the_prune_duty_interval_defaults_and_refuses_by_name() -> None:
    assert forgefeed.prune_duty_s({}) == forgefeed.DEFAULT_PRUNE_DUTY_S
    assert forgefeed.prune_duty_s({'prune_duty_s': 600}) == 600
    with pytest.raises(ValueError, match='prune_duty_s'):
        forgefeed.prune_duty_s({'prune_duty_s': 0})


def test_the_duty_runs_once_per_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    runs: list[datetime] = []
    monkeypatch.setattr(branchpolicy, 'run_here', lambda _c, **kw: runs.append(kw['now']) or ())
    start = datetime(2026, 11, 19, 12, 0, tzinfo=UTC).timestamp()
    assert forgefeed.duty_once(clients=lambda _f: StateForge(), now=start, every_s=1800, checkouts=[]) == ()
    assert forgefeed.duty_once(clients=lambda _f: StateForge(), now=start + 600, every_s=1800, checkouts=[]) is None
    assert forgefeed.duty_once(clients=lambda _f: StateForge(), now=start + 1800, every_s=1800, checkouts=[]) == ()
    assert len(runs) == 2
