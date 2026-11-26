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

from dev_lab.dev import branchpolicy
from dev_lab.dev.branchpolicy import OVER_AHEAD, PREFIX, STALE, derive, observe, run_here, wanted
from dev_lab.dev.branchprune import prune
from dev_lab.dev.branchset import BranchSetKeyRetired, BranchSetNotDeclared, declared_branchset
from dev_lab.dev.forgealarm import INTEGRATION
from dev_lab.dev.lanepolicy import load_policy
from dev_lab.dev.roles import CI, HOST, HPC, PRUNE, Executor, Roles, performs
from tests._forge_state import StateForge
from tests.test_dev_branchprune import ACTIVITY, NOW, BareForge, _commit, _git, _on_origin, _planted

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


def _heavy(root: Path, commits: int) -> None:
    """Give lane/unmerged *commits* more unlanded commits (it already holds one)."""
    _git(root, 'checkout', '-q', 'lane/unmerged')
    for n in range(commits):
        _commit(root, f'work-{n}')
    _git(root, 'push', '-q', 'origin', 'lane/unmerged')
    _git(root, 'fetch', '-q', '--prune', 'origin')


def test_rows_name_the_unmerged_stale_and_the_over_ahead_lane_and_acquit_the_rest(tmp_path: Path) -> None:
    """lane/unmerged holds 3 unlanded commits and is idle 72 h; merged, declared and young lanes are never rows."""
    root, _ = _planted(tmp_path, extra='max_ahead = 2\nmax_idle_hours = 12\n')
    _heavy(root, 2)
    rows = derive(root, declared_branchset(root), load_policy(root), now=NOW, activity=ACTIVITY)
    assert {(row.kind, row.branch) for row in rows} == {(OVER_AHEAD, 'lane/unmerged'), (STALE, 'lane/unmerged')}
    over = next(row for row in rows if row.kind == OVER_AHEAD)
    assert over.ahead == 3


def test_a_lane_at_its_bound_is_not_over_ahead(tmp_path: Path) -> None:
    """PLANTED: exactly max_ahead unlanded commits is inside the bound."""
    root, _ = _planted(tmp_path, extra='max_ahead = 3\nmax_idle_hours = 1000\n')
    _heavy(root, 2)
    assert derive(root, declared_branchset(root), load_policy(root), now=NOW, activity=ACTIVITY) == ()


def test_an_over_ahead_row_says_land_it_now_and_record_why_and_never_split(tmp_path: Path) -> None:
    """User correction 2026-11-19: the doors are landing and recording the cause; no door splits the work."""
    root, _ = _planted(tmp_path, extra='max_ahead = 0\nmax_idle_hours = 1000\n')
    branchset, policy = declared_branchset(root), load_policy(root)
    (row,) = derive(root, branchset, policy, now=NOW, activity=ACTIVITY)
    body = wanted((row,), branchset, policy.integration)[row.title]
    assert 'land it now' in body
    assert 'record why it ran past' in body
    assert all(word in body for word in ('no test producer', 'nobody integrating', 'withheld finished work'))
    lowered = body.lower()
    assert not any(word in lowered for word in ('split', 'slice', 'smaller')), body


def test_a_lane_inside_both_bounds_is_no_row(tmp_path: Path) -> None:
    root, _ = _planted(tmp_path, extra='max_ahead = 100\nmax_idle_hours = 1000\n')
    assert derive(root, declared_branchset(root), load_policy(root), now=NOW, activity=ACTIVITY) == ()


# ---------------------------------------------------------------------------------------------- the alarms


def test_observe_raises_one_alarm_per_row_and_none_once_the_row_clears(tmp_path: Path) -> None:
    """A row is an alarm, never an issue (2026-11-19); a cleared row raises nothing -- nothing is stored."""
    root, _ = _planted(tmp_path, extra='max_idle_hours = 12\n')
    first = observe(root, 'o/r', now=NOW, activity=ACTIVITY)
    assert [(a.kind, a.about, a.subject) for a in first] == [
        (INTEGRATION, f'{STALE} lane/unmerged', f'{PREFIX}{STALE} lane/unmerged')
    ]
    _git(root, 'checkout', '-q', 'integrate/main')
    _git(root, 'merge', '-q', '--no-ff', '-m', 'land it', 'lane/unmerged')
    _git(root, 'push', '-q', 'origin', 'integrate/main')
    _git(root, 'fetch', '-q', '--prune', 'origin')
    assert observe(root, 'o/r', now=NOW, activity=ACTIVITY) == ()


def test_the_alarm_key_carries_no_sha_so_a_moved_branch_repeats_as_one(tmp_path: Path) -> None:
    root, _ = _planted(tmp_path, extra='max_idle_hours = 12\n')
    before = observe(root, 'o/r', now=NOW, activity=ACTIVITY)
    _git(root, 'checkout', '-q', 'lane/unmerged')
    _commit(root, 'more')
    _git(root, 'push', '-q', 'origin', 'lane/unmerged')
    _git(root, 'fetch', '-q', '--prune', 'origin')
    after = observe(root, 'o/r', now=NOW, activity=ACTIVITY)
    assert [a.about for a in after] == [a.about for a in before]


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
    monkeypatch.setattr(branchpolicy, 'prune_duty', lambda root, _client, _repo, **_kw: ran.append(root))
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
    assert branchpolicy.prune_duty_s({}) == branchpolicy.DEFAULT_PRUNE_DUTY_S
    assert branchpolicy.prune_duty_s({'prune_duty_s': 600}) == 600
    with pytest.raises(ValueError, match='prune_duty_s'):
        branchpolicy.prune_duty_s({'prune_duty_s': 0})


def test_the_duty_runs_once_per_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    runs: list[datetime] = []
    monkeypatch.setattr(branchpolicy, 'run_here', lambda _c, **kw: runs.append(kw['now']) or ())
    start = datetime(2026, 11, 19, 12, 0, tzinfo=UTC).timestamp()
    assert branchpolicy.duty_once(clients=lambda _f: StateForge(), now=start, every_s=1800, checkouts=[]) == ()
    assert branchpolicy.duty_once(clients=lambda _f: StateForge(), now=start + 600, every_s=1800, checkouts=[]) is None
    assert branchpolicy.duty_once(clients=lambda _f: StateForge(), now=start + 1800, every_s=1800, checkouts=[]) == ()
    assert len(runs) == 2
