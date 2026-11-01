"""REVIEW-BUDGET: every PR's review capped in rounds and USD inside the family's month (user ruling 2026-10-31).

Every refusal has its planted control: the same PR one step under the cap runs.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from _branch_repos import advance
from test_dev_forgereview import JUDGE, FakeCommand, _forge, _work
from test_dev_forgereview_rounds import _doc, _finding, _state

from dev_lab.dev.forgepulls import Marker, comment_upsert
from dev_lab.dev.forgereview import RANGE_FIELD, Review, review_tick
from dev_lab.dev.forgereview_claim import CAPPED
from dev_lab.dev.forgereview_dispose import raise_cap
from dev_lab.dev.forgereview_judge import Identity
from dev_lab.dev.forgereview_rounds import FAMILY_MAX_ROUNDS, trusted_bodies
from dev_lab.dev.reviewbudget import (
    CAP_QUANTILE,
    DEGRADED_MODEL,
    DEGRADED_ROUNDS,
    INITIAL_PRS_PER_MONTH,
    MIN_FITTED_PRS,
    TAG_ENV,
    Raised,
    Spend,
    charged_to,
    fit,
    gate,
    raise_line,
    raised_of,
    tag_of,
)

_BUDGET = 1000.0
_REVIEW = Review(judge=JUDGE, command=('reviewer', '--range', RANGE_FIELD))


def _spend(spent: float = 0.0, by_tag: dict[str, float] | None = None, days: int = 30) -> Spend:
    return Spend(_BUDGET, spent, days, by_tag or {})


def _history(costs: list[float]) -> dict[str, float]:
    return {f'o/r#{i}': cost for i, cost in enumerate(costs)}


# --- the fit -------------------------------------------------------------------------------------------------


def test_below_enough_measured_prs_the_cap_is_the_named_initial_one() -> None:
    got = fit(_spend(by_tag=_history([50.0] * (MIN_FITTED_PRS - 1))))
    assert (got.source, got.cap_usd, got.prs_per_month) == ('initial', _BUDGET / INITIAL_PRS_PER_MONTH, 100)
    assert got.cap_usd == 10.0


def test_the_fit_reproduces_a_known_distribution_and_its_quantile() -> None:
    """100 PRs in 30 days costing 0.1 .. 10.0 USD: 100 PRs a month, cap at the 0.9 quantile (9.01), affordable."""
    got = fit(_spend(by_tag=_history([i / 10 for i in range(1, 101)])))
    assert got.source == 'fitted'
    assert got.prs_per_month == pytest.approx(100.0)
    assert got.cap_usd == pytest.approx(0.1 + CAP_QUANTILE * 9.9)


def test_a_fitted_cap_never_lets_a_month_of_typical_prs_overrun_the_budget() -> None:
    """The same 100 PRs a month against 300 USD: the quantile is lowered until the expected month fits exactly."""
    costs = [i / 10 for i in range(1, 101)]
    got = fit(Spend(300.0, 0.0, 30, _history(costs)))
    assert got.cap_usd < 0.1 + CAP_QUANTILE * 9.9
    assert got.prs_per_month * sum(min(c, got.cap_usd) for c in costs) / len(costs) == pytest.approx(300.0)


def test_a_planted_spend_record_moves_the_fit() -> None:
    """PLANTED: ten more expensive PRs raise the quantile; untagged spend (no ``#``) is not a PR and moves nothing."""
    costs = [1.0] * 30
    before = fit(_spend(by_tag=_history(costs)))
    assert fit(_spend(by_tag={**_history(costs), 'untagged-batch': 500.0})) == before
    after = fit(_spend(by_tag=_history([*costs, *[20.0] * 10])))
    assert after.cap_usd > before.cap_usd


# --- the gate ------------------------------------------------------------------------------------------------


def test_a_pr_over_its_round_cap_waits_named_and_one_under_runs() -> None:
    held = gate(number=7, spent_usd=0.0, rounds_done=3, max_rounds=3, spend=_spend())
    assert held.state == 'wait'
    assert held.why.startswith('round cap reached: 3/3 rounds; split the PR, or forge review cap 7')
    assert gate(number=7, spent_usd=0.0, rounds_done=2, max_rounds=3, spend=_spend()).state == 'run'


def test_a_pr_over_its_usd_cap_waits_named_and_one_under_runs() -> None:
    held = gate(number=7, spent_usd=12.0, rounds_done=1, max_rounds=3, spend=_spend())
    assert held.state == 'wait'
    assert held.why.startswith('budget reached: 12.00/10.00 USD; split the PR, or forge review cap 7 --usd')
    assert gate(number=7, spent_usd=9.99, rounds_done=1, max_rounds=3, spend=_spend()).state == 'run'


def test_the_months_remainder_bounds_every_cap_even_a_raised_one() -> None:
    month = _spend(spent=_BUDGET - 3.0)
    raised = Raised(50.0, 9, 'one large refactor')
    held = gate(number=7, spent_usd=4.0, rounds_done=0, max_rounds=3, spend=month, raised=raised)
    assert held.state == 'wait'
    assert 'budget reached: 4.00/3.00 USD' in held.why
    spent = gate(number=7, spent_usd=0.0, rounds_done=0, max_rounds=3, spend=_spend(spent=_BUDGET), raised=raised)
    assert (spent.state, spent.why.split(':')[0]) == ('wait', 'monthly review budget spent')


def test_a_raise_lifts_the_pr_caps_within_the_month() -> None:
    raised = Raised(40.0, 5, 'the split would separate one migration')
    assert gate(number=7, spent_usd=12.0, rounds_done=3, max_rounds=3, spend=_spend(), raised=raised).state == 'run'


def test_a_low_month_degrades_rounds_and_tier_before_anything_stops() -> None:
    low = _spend(spent=_BUDGET * 0.8)
    first = gate(number=7, spent_usd=0.0, rounds_done=0, max_rounds=3, spend=low)
    assert (first.state, first.max_rounds, first.model) == ('run', DEGRADED_ROUNDS, DEGRADED_MODEL)
    assert gate(number=7, spent_usd=0.0, rounds_done=DEGRADED_ROUNDS, max_rounds=3, spend=low).state == 'wait'
    assert gate(number=7, spent_usd=0.0, rounds_done=0, max_rounds=3, spend=_spend()).model is None


def test_with_no_spend_report_the_round_cap_alone_holds() -> None:
    assert gate(number=7, spent_usd=0.0, rounds_done=2, max_rounds=3, spend=None).state == 'run'
    assert gate(number=7, spent_usd=0.0, rounds_done=3, max_rounds=3, spend=None).state == 'wait'


def test_an_unknown_spend_report_schema_is_refused() -> None:
    with pytest.raises(ValueError, match='schema 2'):
        Spend.from_report({'schema': 2})


# --- the raise, the tag ----------------------------------------------------------------------------------------


def test_the_newest_raise_wins_and_its_reason_cannot_close_the_comment() -> None:
    hostile = Raised(30.0, None, 'a --> b')
    line = raise_line(hostile)
    assert '-->' not in line.removesuffix(' -->')
    assert raised_of([raise_line(Raised(20.0, 4, 'first')), f'x\n{line}']) == hostile
    assert raised_of(['nothing here']) is None


def test_a_pr_is_charged_by_owner_repo_and_number_on_either_forge() -> None:
    assert tag_of('https://github.com/DawnEver/dev-lab/pull/11', 11) == 'DawnEver/dev-lab#11'
    assert tag_of('https://forge.example.org/o/r/pulls/3', 3) == 'o/r#3'


def test_charged_to_sets_the_tag_for_the_commands_and_restores_it() -> None:
    before = os.environ.get(TAG_ENV)
    with charged_to('o/r#1'):
        assert os.environ[TAG_ENV] == 'o/r#1'
    assert os.environ.get(TAG_ENV) == before


# --- the forge -------------------------------------------------------------------------------------------------


def _tick(work: Path, forge: object, command: FakeCommand, spend: Spend | None) -> tuple[str, ...]:
    return review_tick(work, forge, _REVIEW, base='integrate/main', run=command, ready=lambda *_: None, host='box',
                       spend=lambda *_: spend)  # fmt: skip


def test_a_pr_over_its_usd_cap_gets_the_named_waiting_status_until_the_integrator_raises_it(tmp_path: Path) -> None:
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    command = FakeCommand(_doc())
    _tick(work, forge, command, _spend(by_tag={f'o/r#{number}': 11.0}))
    assert command.ran == [], 'over its cap, no reviewer runs'
    state, why = _state(forge, head)
    assert (state, why.startswith(f'{CAPPED} budget reached: 11.00/10.00 USD')) == ('pending', True)
    assert _tick(work, forge, command, _spend(by_tag={f'o/r#{number}': 11.0})) == (), 'said once'
    raise_cap(forge, number, Raised(25.0, None, 'one indivisible migration'), by=Identity('i', 'box', 'S-int'))
    _tick(work, forge, command, _spend(by_tag={f'o/r#{number}': 11.0}))
    assert len(command.ran) == 1, 'the raise releases the head'
    assert _state(forge, head)[0] == 'success'


def test_a_pr_over_its_round_cap_waits_named_and_runs_nothing(tmp_path: Path) -> None:
    """Superseding the past-the-cap re-check (ruling 2026-10-31): the head waits for a split or a raise."""
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    capped = Review(judge=JUDGE, command=_REVIEW.command, max_rounds=1)
    high = _finding('F-h', severity='HIGH', file='x.py', anchor='x')
    review_tick(work, forge, capped, base='integrate/main', run=FakeCommand(_doc(high)), ready=lambda *_: None,
                host='box', spend=lambda *_: _spend())  # fmt: skip
    after = advance(work, 'pr/x', 'y.py', 'y = 1\n')
    forge.pulls[number]['head']['sha'] = after
    command = FakeCommand(_doc())
    review_tick(work, forge, capped, base='integrate/main', run=command, ready=lambda *_: None, host='box',
                spend=lambda *_: _spend())  # fmt: skip
    assert command.ran == []
    assert command.judged == [], 'not even the judge runs past the cap'
    state, why = _state(forge, after)
    assert state == 'pending'
    assert why.startswith(f'{CAPPED} round cap reached: 1/1 rounds; split the PR, or forge review cap {number}')
    assert FAMILY_MAX_ROUNDS == Review().max_rounds == 3, 'the family re-reviews each push: three rounds a PR'


def _raised_as_seen_by(forge: object, number: int, job: str) -> Raised | None:
    forge.login = job
    return raised_of(trusted_bodies(forge, number))


def test_a_raise_is_read_from_its_raiser_by_a_job_of_another_login(tmp_path: Path) -> None:
    """#17: DawnEver's raise was never read by the GitHub Actions job. PLANTED control: a forged raiser is not."""
    _, head = _work(tmp_path)
    forge, number = _forge(head)
    forge.permissions['DawnEver'] = 'write'
    forge.login = 'DawnEver'
    raise_cap(forge, number, Raised(None, 5, 'one indivisible migration'), by=Identity('DawnEver', 'box', 'S-int'))
    assert _raised_as_seen_by(forge, number, 'github-actions[bot]') == Raised(None, 5, 'one indivisible migration',
                                                                               'DawnEver')  # fmt: skip
    forge.login = 'mallory'
    forged = raise_line(Raised(None, 99, 'forged', 'DawnEver'))
    comment_upsert(forge, number, kind=Marker.REVIEW_CAP, key='own', text=f'raised: {forged}')
    assert _raised_as_seen_by(forge, number, 'github-actions[bot]').rounds == 5, 'a raise naming another is ignored'


def test_a_raise_line_pasted_into_another_authors_comment_is_ignored(tmp_path: Path) -> None:
    _, head = _work(tmp_path)
    forge, number = _forge(head)
    forge.login = 'mallory'
    pasted = raise_line(Raised(None, 99, 'pasted', 'DawnEver'))
    comment_upsert(forge, number, kind=Marker.CLAIM, key='F-x', text=f'see the raise\n\n{pasted}')
    assert _raised_as_seen_by(forge, number, 'github-actions[bot]') is None


def test_a_raise_by_an_author_without_write_permission_is_ignored(tmp_path: Path) -> None:
    """F-d5d3c6e517a0: naming yourself proves authorship, not authority. PLANTED control: the same raise by a writer."""
    _, head = _work(tmp_path)
    forge, number = _forge(head)
    forge.login = 'mallory'
    raise_cap(forge, number, Raised(None, 99, 'self-raised'), by=Identity('mallory', 'box', 'S-m'))
    assert _raised_as_seen_by(forge, number, 'github-actions[bot]') is None
    forge.permissions['mallory'] = 'write'
    assert _raised_as_seen_by(forge, number, 'github-actions[bot]').rounds == 99


@pytest.mark.parametrize('payload', ['{not json}', '[1, 2]', '"x"', '{"rounds": "5", "by": "mallory"}',
                                     '{"rounds": 5, "by": ["mallory"]}', '{"usd": true, "by": "mallory"}'])  # fmt: skip
def test_a_malformed_raise_payload_is_no_record_and_no_crash(tmp_path: Path, payload: str) -> None:
    """F-e08ae020d005. PLANTED control: a well-formed payload in the same comment shape is read."""
    _, head = _work(tmp_path)
    forge, number = _forge(head)
    forge.permissions['mallory'] = 'write'
    forge.login = 'mallory'
    comment_upsert(forge, number, kind=Marker.REVIEW_CAP, text=f'<!-- review-cap {payload} -->')
    assert _raised_as_seen_by(forge, number, 'github-actions[bot]') is None
    assert raised_of([f'<!-- review-cap {payload} -->']) is None
    good = '{"usd": null, "rounds": 5, "why": "w", "by": "mallory"}'
    forge.login = 'mallory'
    comment_upsert(forge, number, kind=Marker.REVIEW_CAP, text=f'<!-- review-cap {good} -->')
    assert _raised_as_seen_by(forge, number, 'github-actions[bot]').rounds == 5
