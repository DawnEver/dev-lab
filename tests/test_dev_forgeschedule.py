"""ONE WORK QUEUE: value per cost, aging, user boosts, per-repo overrides and host weights -- each with its control."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from lab_commons.compute.model import Candidate, Ranked, Schedule, boost_of, expected_cost, rank, starved, value
from lab_commons.dev.forgehosts import host_id
from lab_commons.dev.forgeorigin import vouched
from lab_commons.dev.forgeschedule import host_weights, load_schedule, parse_usage
from lab_commons.hpc.shell import FULL

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
FAMILY = Schedule()


def _cand(ref: str, kind: str, *, repo: str = 'o/r', waited_h: float = 0.0, labels: tuple[str, ...] = ()) -> Candidate:
    return Candidate(repo, ref, ref.ljust(40, '0'), 'linux', kind, NOW - timedelta(hours=waited_h), FULL, labels=labels)


def _order(ranked: tuple[Ranked, ...]) -> list[str]:
    return [item.candidate.ref for item in ranked]


def test_the_value_is_base_plus_boost_plus_aging() -> None:
    one = _cand('a', 'pr', waited_h=2, labels=('priority:user', 'priority:5', 'unrelated'))
    assert value(one, FAMILY, NOW) == 60 + 1000 + 5 + 10 * 2


def test_an_undeclared_class_is_refused_by_name() -> None:
    with pytest.raises(ValueError, match="class 'nightly'"):
        value(_cand('a', 'nightly'), FAMILY, NOW)


def test_a_cheap_lower_value_job_beats_an_expensive_higher_one() -> None:
    """Value per cost. PLANTED CONTROL: at equal cost the higher value wins."""
    cheap, dear = _cand('cheap', 'branch', repo='o/cheap'), _cand('dear', 'pr', repo='o/dear')
    schedules = {'o/cheap': FAMILY, 'o/dear': FAMILY}
    assert _order(rank([dear, cheap], schedules, NOW, cost_h={'o/cheap': 1.0, 'o/dear': 4.0})) == ['cheap', 'dear']
    assert _order(rank([cheap, dear], schedules, NOW, cost_h={'o/cheap': 4.0, 'o/dear': 4.0})) == ['dear', 'cheap']


def test_aging_eventually_lifts_a_waiting_job() -> None:
    """PLANTED CONTROL: fresh, the request is outranked; after a day it is not."""
    integration = _cand('integrate/main', 'integration')
    schedules = {'o/r': FAMILY}
    fresh = _cand('issue/1', 'request')
    assert _order(rank([fresh, integration], schedules, NOW, cost_h={}))[0] == 'integrate/main'
    old = _cand('issue/1', 'request', waited_h=24)
    assert _order(rank([integration, old], schedules, NOW, cost_h={}))[0] == 'issue/1'


def test_a_user_boost_jumps_the_queue() -> None:
    """PLANTED CONTROL: the same PR without the label stays behind the integration head."""
    integration = _cand('integrate/main', 'integration')
    plain, boosted = _cand('feat/x', 'pr'), _cand('feat/x', 'pr', labels=('priority:user',))
    assert _order(rank([plain, integration], {'o/r': FAMILY}, NOW, cost_h={}))[0] == 'integrate/main'
    assert _order(rank([integration, boosted], {'o/r': FAMILY}, NOW, cost_h={}))[0] == 'feat/x'
    assert boost_of(('priority:12.5',), FAMILY) == 12.5


def test_a_repo_override_changes_the_order(tmp_path: Path) -> None:
    """PLANTED CONTROL: the family default puts the PR first; the override, key by key, puts the branch first."""
    pr, branch = _cand('feat/x', 'pr'), _cand('exp/y', 'branch')
    assert _order(rank([branch, pr], {'o/r': FAMILY}, NOW, cost_h={}))[0] == 'feat/x'
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.lab_commons.schedule]\nclasses = {branch = 90}\nclasses_by_ref = {"exp/*" = "branch"}\n',
        encoding='utf-8',
    )
    declared = load_schedule(tmp_path)
    assert declared.classes['pr'] == 60, 'a key it omits keeps the family default'
    assert declared.classes_by_ref == {'exp/*': 'branch'}, 'an ordered rule is replaced whole, never merged'
    assert _order(rank([pr, branch], {'o/r': declared}, NOW, cost_h={}))[0] == 'exp/y'


def test_the_class_rule_is_ordered_and_first_match_wins() -> None:
    rule = Schedule(classes_by_ref={'feat/hot/*': 'pr', 'feat/*': 'feature'})
    assert (rule.class_of('feat/hot/x'), rule.class_of('feat/x'), rule.class_of('wip/x')) == ('pr', 'feature', None)
    assert FAMILY.class_of('feat/x') == 'feature', 'the family default: a feature branch is its own class'
    assert FAMILY.class_of('lane/x') == 'branch'
    assert FAMILY.base('pr') > FAMILY.base('feature') > FAMILY.base('branch')
    assert 'feature' in FAMILY.starve_after_hours


def test_a_rule_naming_an_unvalued_class_is_refused(tmp_path: Path) -> None:
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.lab_commons.schedule]\nclasses_by_ref = {"x/*" = "nightly"}\n', encoding='utf-8'
    )
    with pytest.raises(ValueError, match='nightly'):
        load_schedule(tmp_path)


def test_the_retired_allow_list_is_refused_by_name_with_the_rule_that_replaced_it(tmp_path: Path) -> None:
    (tmp_path / 'pyproject.toml').write_text('[tool.lab_commons.schedule]\nbranches = []\n', encoding='utf-8')
    with pytest.raises(ValueError, match='classes_by_ref'):
        load_schedule(tmp_path)


def test_an_unknown_schedule_key_is_refused(tmp_path: Path) -> None:
    (tmp_path / 'pyproject.toml').write_text('[tool.lab_commons.schedule]\nagin_rate = 1\n', encoding='utf-8')
    with pytest.raises(ValueError, match='agin_rate'):
        load_schedule(tmp_path)


def test_a_host_weight_shifts_the_split_between_repos() -> None:
    """PLANTED CONTROL: unweighted, the two repos' equal heads tie broken by age; weighted, the light repo yields."""
    a = _cand('integrate/main', 'integration', repo='o/a', waited_h=1)
    b = _cand('integrate/main', 'integration', repo='o/b')
    schedules = {'o/a': FAMILY, 'o/b': FAMILY}
    assert next(i.candidate.repo for i in rank([a, b], schedules, NOW, cost_h={})) == 'o/a'
    weights = host_weights({'weights': {'o/b': 3}})
    assert next(i.candidate.repo for i in rank([a, b], schedules, NOW, cost_h={}, weights=weights)) == 'o/b'


def test_the_cost_is_measured_core_seconds_else_the_prior() -> None:
    measured = {'durations': {'t1': 3600.0, 't2': 3600.0}, 'overheads': {'build': 3600.0}}
    assert expected_cost(measured, 4.0) == 3.0
    assert expected_cost(measured, 4.0, cores=3) == 1.0, 'a box: wall-hours over its cores'
    assert expected_cost({}, 4.0) == 4.0


def test_a_blocked_candidate_past_its_class_bound_is_starved() -> None:
    """PLANTED CONTROLS: the same wait unblocked, and a wait under the bound, are not starved."""
    old = rank([_cand('feat/x', 'pr', waited_h=13)], {'o/r': FAMILY}, NOW, cost_h={})[0]
    young = rank([_cand('feat/y', 'pr', waited_h=11)], {'o/r': FAMILY}, NOW, cost_h={})[0]
    blocked = [dataclasses.replace(item, blocked='not admitted: lacking cpu') for item in (old, young)]
    assert [i.candidate.ref for i in starved(blocked, {'o/r': FAMILY})] == ['feat/x']
    assert starved([old], {'o/r': FAMILY}) == ()


def test_usage_is_core_hours_per_run_job() -> None:
    sacct = 'run-abcdef123456-base|7200\nrun-abcdef123456-femm|3600\nother|99999\nrun-ffffffffffff-base|\n'
    assert parse_usage(sacct) == {'abcdef123456': 3.0}, "every part of a sha is that sha's use"


def test_a_priority_candidate_ranks_first_over_a_higher_score() -> None:
    """A host's priority orders, it reserves nothing; CONTROL: no priority keeps the score order."""
    head = _cand('integrate/main', 'integration')
    lane = _cand('lane/x', 'branch')
    schedules = {'o/r': Schedule()}
    assert [r.candidate for r in rank([lane, head], schedules, NOW, cost_h={})] == [head, lane]
    first = rank([lane, head], schedules, NOW, cost_h={}, priority=lambda one: one.ref == 'lane/x')
    assert [(r.candidate, r.priority) for r in first] == [(lane, True), (head, False)]


def test_an_origin_host_stands_only_where_its_login_publishes_the_host_card() -> None:
    claimed = dataclasses.replace(_cand('lane/x', 'pr'), origin='bob', origin_host='G')
    owners = {'G': ('alice', 'bob'), 'H': ('carol',)}
    assert vouched([claimed], owners) == (claimed,)
    forged = dataclasses.replace(claimed, origin_host='H')
    assert vouched([forged], owners) == (dataclasses.replace(forged, origin_host=''),)
    unknown = dataclasses.replace(claimed, origin_host='Z')
    assert vouched([unknown], owners)[0].origin_host == ''


def test_a_public_repos_opaque_card_vouches_the_raw_trailer_and_vouches_no_other() -> None:
    """A public repo keys the card by ``host_id``; the trailer still names the raw host. CONTROL: another host."""
    claimed = dataclasses.replace(_cand('lane/x', 'pr'), origin='bob', origin_host='ada/bob')
    owners = {host_id('ada/bob'): ('bob',)}
    assert vouched([claimed], owners) == (claimed,)
    other = dataclasses.replace(claimed, origin_host='ada/eve')
    assert vouched([other], owners)[0].origin_host == ''
