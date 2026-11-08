"""REVIEW-BUDGET: every PR's review capped in USD inside the review allotment's month (user ruling 2026-10-31).

Every skip has its planted control: the same PR one step under the cap runs. A skipped review merges
Unreviewed (user ruling 2026-11-06), so no gate text sends its author anywhere but the raise door.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from _branch_repos import advance
from _forge_state import StateForge, called_due
from _review_doubles import _doc, _state
from test_dev_forgereview import FakeCommand, _forge, _work

from dev_lab.dev.forge import Forge
from dev_lab.dev.forgepulls import Marker, comment_upsert
from dev_lab.dev.forgereview import review_tick
from dev_lab.dev.forgereview_advice import Record, record_of, recorded_usd, trusted_bodies
from dev_lab.dev.forgereview_claim import UNREVIEWED_STATUS
from dev_lab.dev.forgereview_declared import RANGE_FIELD, Review
from dev_lab.dev.forgereview_identity import Identity
from dev_lab.dev.forgereview_stands import ask_again
from dev_lab.dev.forgetakeover import raise_cap
from dev_lab.dev.reviewbudget import (
    CAP_QUANTILE,
    DEGRADED_MODEL,
    INITIAL_PRS_PER_MONTH,
    MIN_FITTED_PRS,
    REVIEW_ALLOTMENT,
    SCOPE_ENV,
    SPEND_SCHEMA,
    TAG_ENV,
    Raised,
    ShareRefused,
    Spend,
    charged_to,
    fit,
    gate,
    raise_line,
    raised_of,
    share_of,
    tag_of,
)

_BUDGET = 1000.0
_REVIEW = Review(command=('reviewer', '--range', RANGE_FIELD))


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
    assert got.prs_per_month == pytest.approx(100.0, abs=1e-9)  # PRs/month; a float fit of an exact count
    assert got.cap_usd == pytest.approx(0.1 + CAP_QUANTILE * 9.9, abs=1e-9)  # USD, sub-nano-dollar


def test_a_fitted_cap_never_lets_a_month_of_typical_prs_overrun_the_budget() -> None:
    """The same 100 PRs a month against 300 USD: the quantile is lowered until the expected month fits exactly."""
    costs = [i / 10 for i in range(1, 101)]
    got = fit(Spend(300.0, 0.0, 30, _history(costs)))
    assert got.cap_usd < 0.1 + CAP_QUANTILE * 9.9
    assert got.prs_per_month * sum(min(c, got.cap_usd) for c in costs) / len(costs) == pytest.approx(
        300.0, abs=1e-6
    )  # USD per month, sub-micro-dollar


def test_a_planted_spend_record_moves_the_fit() -> None:
    """PLANTED: ten more expensive PRs raise the quantile; untagged spend (no ``#``) is not a PR and moves nothing."""
    costs = [1.0] * 30
    before = fit(_spend(by_tag=_history(costs)))
    assert fit(_spend(by_tag={**_history(costs), 'untagged-batch': 500.0})) == before
    after = fit(_spend(by_tag=_history([*costs, *[20.0] * 10])))
    assert after.cap_usd > before.cap_usd


# --- the gate ------------------------------------------------------------------------------------------------


def test_a_pr_over_its_usd_cap_is_skipped_named_and_one_under_runs() -> None:
    skipped = gate(number=7, spent_usd=12.0, spend=_spend())
    assert skipped.state == 'skip'
    assert skipped.why.startswith('budget reached: 12.00/10.00 USD; the integrator may forge review cap 7 --usd')
    assert 'sp' + 'lit' not in skipped.why
    assert gate(number=7, spent_usd=9.99, spend=_spend()).state == 'run'


def test_the_months_remainder_bounds_every_cap_even_a_raised_one() -> None:
    month = _spend(spent=_BUDGET - 3.0)
    raised = Raised(50.0, 'one large refactor')
    skipped = gate(number=7, spent_usd=4.0, spend=month, raised=raised)
    assert skipped.state == 'skip'
    assert 'budget reached: 4.00/3.00 USD' in skipped.why
    spent = gate(number=7, spent_usd=0.0, spend=_spend(spent=_BUDGET), raised=raised)
    assert (spent.state, spent.why.split(':')[0]) == ('skip', 'monthly review budget spent')


def test_a_raise_lifts_the_pr_cap_within_the_month() -> None:
    assert gate(number=7, spent_usd=12.0, spend=_spend(), raised=Raised(40.0, 'one migration')).state == 'run'


def test_a_low_month_degrades_the_tier_before_anything_stops() -> None:
    low = gate(number=7, spent_usd=0.0, spend=_spend(spent=_BUDGET * 0.8))
    assert (low.state, low.model) == ('run', DEGRADED_MODEL)
    assert gate(number=7, spent_usd=0.0, spend=_spend()).model is None


def test_with_no_spend_report_nothing_is_capped() -> None:
    assert gate(number=7, spent_usd=99.0, spend=None).state == 'run'


def test_an_unknown_spend_report_schema_is_refused() -> None:
    with pytest.raises(ValueError, match='schema 1'):
        Spend.from_report({'schema': 1, 'budget_usd': 1000.0})


def _report(budgets: dict) -> dict:
    return {'schema': SPEND_SCHEMA, 'budgets': budgets, 'spent_usd': 99.0, 'unpriced_calls': 0,
            'window': {'days': 3, 'by_tag': {'o/r#1': 2.0}}}  # fmt: skip


def test_the_review_month_is_the_review_allotment_ai_lab_reports_never_a_number_of_ours() -> None:
    """PLANTED CONTROL: another allotment's dollars (a campaign's) never move the review's month."""
    got = Spend.from_report(_report({
        REVIEW_ALLOTMENT: {'provider': 'anthropic', 'allotted_usd': 300.0, 'spent_usd': 40.0, 'standing': True},
        'campaign:T3': {'provider': 'anthropic', 'allotted_usd': 50.0, 'spent_usd': 49.0, 'standing': False},
    }))  # fmt: skip
    assert (got.budget_usd, got.spent_usd, got.of('o/r#1')) == (300.0, 40.0, 2.0)


def test_a_report_with_no_review_allotment_is_refused_naming_the_row_to_declare() -> None:
    with pytest.raises(ValueError, match=r'\[ai_lab\.standing\] review'):
        Spend.from_report(_report({}))


def test_a_pr_share_is_a_child_of_the_review_allotment() -> None:
    assert share_of('o/r#5') == 'review>o/r#5'
    assert share_of('o/r#5', reserve=True) == 'reserve>o/r#5'


# --- the reserve (user ruling 2026-11-03, kept 2026-11-06) -----------------------------------------------------


def test_once_the_review_month_is_spent_a_pr_is_skipped_naming_the_reserve_door() -> None:
    held = gate(number=7, spent_usd=0.0, spend=_spend(spent=_BUDGET))
    assert held.state == 'skip'
    assert held.why.startswith(f'monthly review budget spent: {_BUDGET:.2f}/{_BUDGET:.2f} USD')
    assert 'forge review cap 7' in held.why
    assert '--reserve' in held.why
    assert gate(number=7, spent_usd=0.0, spend=_spend(spent=_BUDGET - 10.0)).state == 'run', 'planted: one step under'


def test_a_raise_that_draws_the_reserve_runs_past_the_review_month_undegraded_on_its_provider() -> None:
    month = Spend(_BUDGET, _BUDGET, 30, {}, 0, 'anthropic')
    drawn = Raised(20.0, 'the release blocker', reserve=True)
    got = gate(number=7, spent_usd=0.0, spend=month, raised=drawn)
    assert (got.state, got.model, got.usd, got.reserve) == ('run', None, 20.0, 'anthropic')
    assert 'reserve' in got.why
    plain = Raised(20.0, 'no draw')  # planted control: a raise without the draw stays in the review's month
    assert gate(number=7, spent_usd=0.0, spend=month, raised=plain).state == 'skip'
    assert gate(number=7, spent_usd=20.0, spend=month, raised=drawn).state == 'skip', 'the raised cap still bounds it'


def test_the_reserve_draw_is_recorded_in_the_raise_and_read_back() -> None:
    drawn = Raised(20.0, 'the release blocker', 'DawnEver', reserve=True)
    assert '"reserve": true' in raise_line(drawn)
    assert raised_of([raise_line(drawn)]) == drawn
    assert raised_of([raise_line(Raised(5.0, 'plain', 'DawnEver'))]).reserve is False


def test_a_reserve_review_opens_its_share_on_the_provider_not_under_the_review(tmp_path: Path) -> None:
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    opened: list[tuple] = []

    def allot(_runtimes: object, _root: Path, share: str, usd: float, provider: str | None = None) -> str:
        opened.append((share, usd, provider))
        return share

    raise_cap(forge, number, Raised(25.0, 'release', reserve=True), by=Identity('i', 'box', 'S-int'))
    month = Spend(_BUDGET, _BUDGET, 30, {}, 0, 'anthropic')
    review_tick(work, forge, _REVIEW, base='integrate/main', run=FakeCommand(_doc()), ready=lambda *_: None,
                host='box', spend=lambda *_: month, allot=allot)  # fmt: skip
    assert opened == [(f'reserve>o/r#{number}', 25.0, 'anthropic')]


# --- the raise, the tag ----------------------------------------------------------------------------------------


def test_the_newest_raise_wins_and_its_reason_cannot_close_the_comment() -> None:
    hostile = Raised(30.0, 'a --> b')
    line = raise_line(hostile)
    assert '-->' not in line.removesuffix(' -->')
    assert raised_of([raise_line(Raised(20.0, 'first')), f'x\n{line}']) == hostile
    assert raised_of(['nothing here']) is None


def test_a_pr_is_charged_by_owner_repo_and_number_on_either_forge() -> None:
    assert tag_of('https://github.com/DawnEver/dev-lab/pull/11', 11) == 'DawnEver/dev-lab#11'
    assert tag_of('https://forge.example.org/o/r/pulls/3', 3) == 'o/r#3'


def test_charged_to_sets_the_tag_and_the_share_for_the_commands_and_restores_them() -> None:
    before = (os.environ.get(TAG_ENV), os.environ.get(SCOPE_ENV))
    with charged_to('o/r#1', 'review>o/r#1'):
        assert (os.environ[TAG_ENV], os.environ[SCOPE_ENV]) == ('o/r#1', 'review>o/r#1')
    assert (os.environ.get(TAG_ENV), os.environ.get(SCOPE_ENV)) == before


@pytest.mark.parametrize('refuse', [False, True], ids=['opens', 'refused'])
def test_a_review_opens_the_prs_cap_as_its_share_and_runs_charged_in_it(tmp_path: Path, *, refuse: bool) -> None:
    """The gate's cap (the initial 1000/100) is the share opened; the command sees it in ``AI_LAB_SCOPE``.

    PLANTED CONTROL: a share ai-lab refuses to open runs no command, and the line names the refusal.
    """
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    opened: list[tuple[str, float]] = []
    seen: list[str | None] = []
    command = FakeCommand(_doc())
    refusal = 'review: cannot hold the share'

    def allot(_runtimes: object, _root: Path, share: str, usd: float) -> str:
        if refuse:
            raise ShareRefused(refusal)
        opened.append((share, usd))
        return share

    def run(argv: list[str], root: Path) -> str:
        seen.append(os.environ.get(SCOPE_ENV))
        return command(argv, root)

    said = review_tick(work, forge, _REVIEW, base='integrate/main', run=run, ready=lambda *_: None, host='box',
                       spend=lambda *_: _spend(), allot=allot)  # fmt: skip
    if refuse:
        assert seen == []
        assert f'did not open: {refusal}' in said[0]
    else:
        assert opened == [(f'review>o/r#{number}', _BUDGET / INITIAL_PRS_PER_MONTH)]
        assert seen
        assert set(seen) == {f'review>o/r#{number}'}


# --- the forge -------------------------------------------------------------------------------------------------


def _tick(work: Path, forge: object, command: FakeCommand, spend: Spend | None) -> tuple[str, ...]:
    return review_tick(work, forge, _REVIEW, base='integrate/main', run=command, ready=lambda *_: None, host='box',
                       spend=lambda *_: spend)  # fmt: skip


def test_a_pr_over_its_usd_cap_merges_unreviewed_until_the_integrator_raises_it(tmp_path: Path) -> None:
    """User ruling 2026-11-06: a cap never holds the merge; its cause is recorded; a raise and a request run it."""
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    command = FakeCommand(_doc())
    _tick(work, forge, command, _spend(by_tag={f'o/r#{number}': 11.0}))
    assert command.ran == [], 'over its cap, no reviewer runs'
    state, why = _state(forge, head)
    assert (state, why.startswith(f'{UNREVIEWED_STATUS} review budget reached: 11.00/10.00 USD')) == ('pending', True)
    assert 'sp' + 'lit' not in why
    assert any('review-capped' in one['body'] for one in forge.comments[number]), 'the cause is recorded for the merge'
    raise_cap(forge, number, Raised(25.0, 'one indivisible migration'), by=Identity('i', 'box', 'S-int'))
    ask_again(forge, number, head, 'i@box')
    _tick(work, forge, command, _spend(by_tag={f'o/r#{number}': 11.0}))
    assert len(command.ran) == 1, 'the raise and the request run the review'
    assert _state(forge, head)[0] == 'success'


def _raised_as_seen_by(forge: object, number: int, job: str) -> Raised | None:
    forge.login = job
    return raised_of(trusted_bodies(forge, number))


def test_a_raise_is_read_from_its_raiser_by_a_job_of_another_login(tmp_path: Path) -> None:
    """#17: DawnEver's raise was never read by the GitHub Actions job. PLANTED control: a forged raiser is not."""
    _, head = _work(tmp_path)
    forge, number = _forge(head)
    forge.permissions['DawnEver'] = 'write'
    forge.login = 'DawnEver'
    raise_cap(forge, number, Raised(5.0, 'one indivisible migration'), by=Identity('DawnEver', 'box', 'S-int'))
    assert _raised_as_seen_by(forge, number, 'github-actions[bot]') == Raised(5.0, 'one indivisible migration',
                                                                               'DawnEver')  # fmt: skip
    forge.login = 'mallory'
    forged = raise_line(Raised(99.0, 'forged', 'DawnEver'))
    comment_upsert(forge, number, kind=Marker.REVIEW_CAP, key='own', text=f'raised: {forged}')
    assert _raised_as_seen_by(forge, number, 'github-actions[bot]').usd == 5.0, 'a raise naming another is ignored'


def test_a_raise_line_pasted_into_another_authors_comment_is_ignored(tmp_path: Path) -> None:
    _, head = _work(tmp_path)
    forge, number = _forge(head)
    forge.login = 'mallory'
    pasted = raise_line(Raised(99.0, 'pasted', 'DawnEver'))
    comment_upsert(forge, number, kind=Marker.REVIEW_AGAIN, key='x', text=f'see the raise\n\n{pasted}')
    assert _raised_as_seen_by(forge, number, 'github-actions[bot]') is None


def test_a_raise_by_an_author_without_write_permission_is_ignored_on_github(tmp_path: Path) -> None:
    """F-d5d3c6e517a0: naming yourself proves authorship, not authority. PLANTED control: the same raise by a writer.

    Only GitHub vets authors; on Gitea, the private forge, the same raise is admitted (user ruling 2026-11-06).
    """
    _, head = _work(tmp_path)
    gitea, number = _forge(head)
    gitea.login = 'mallory'
    raise_cap(gitea, number, Raised(99.0, 'self-raised'), by=Identity('mallory', 'box', 'S-m'))
    assert _raised_as_seen_by(gitea, number, 'github-actions[bot]').usd == 99.0
    forge = StateForge(Forge('github.com', 'o', 'r'))
    number = forge.add_pull('pr/x', 'integrate/main', title='add x', sha=head)
    called_due(forge, head)  # the merge decision called its review due
    forge.login = 'mallory'
    raise_cap(forge, number, Raised(99.0, 'self-raised'), by=Identity('mallory', 'box', 'S-m'))
    assert _raised_as_seen_by(forge, number, 'github-actions[bot]') is None
    forge.permissions['mallory'] = 'write'
    assert _raised_as_seen_by(forge, number, 'github-actions[bot]').usd == 99.0


@pytest.mark.parametrize('payload', ['{not json}', '[1, 2]', '"x"', '{"usd": "5", "by": "mallory"}',
                                     '{"usd": 5, "by": ["mallory"]}', '{"usd": true, "by": "mallory"}'])  # fmt: skip
def test_a_malformed_raise_payload_is_no_record_and_no_crash(tmp_path: Path, payload: str) -> None:
    """F-e08ae020d005. PLANTED control: a well-formed payload in the same comment shape is read."""
    _, head = _work(tmp_path)
    forge, number = _forge(head)
    forge.permissions['mallory'] = 'write'
    forge.login = 'mallory'
    comment_upsert(forge, number, kind=Marker.REVIEW_CAP, text=f'<!-- review-cap {payload} -->')
    assert _raised_as_seen_by(forge, number, 'github-actions[bot]') is None
    assert raised_of([f'<!-- review-cap {payload} -->']) is None
    good = '{"usd": 5, "why": "w", "by": "mallory"}'
    forge.login = 'mallory'
    comment_upsert(forge, number, kind=Marker.REVIEW_CAP, text=f'<!-- review-cap {good} -->')
    assert _raised_as_seen_by(forge, number, 'github-actions[bot]').usd == 5


# --- the PR's spend is the reviews it recorded ------------------------------------------------------------------


def test_a_record_holds_its_dollars_and_the_pr_spend_sums_every_head() -> None:
    """Review spend 2026-11-03: each host saw only its own local spend.

    PLANTED CONTROL: a head re-posted counts once.
    """
    one, two = Record('a' * 40, usd=1.5), Record('b' * 40, usd=2.25)
    assert record_of([one.line()]).usd == 1.5
    reposted = Record('b' * 40, usd=2.5)
    assert recorded_usd([one.line(), two.line()]) == 3.75
    assert recorded_usd([one.line(), two.line(), reposted.line()]) == 4.0, 'the newest record of a head wins'
    assert recorded_usd(['no record']) == 0.0


def test_a_review_records_what_it_spent(tmp_path: Path) -> None:
    """The review's dollars are the PR tag's spend after the review less before it, on the host that ran it."""
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    tag = f'o/r#{number}'
    reads = iter([_spend(by_tag={tag: 1.0}), _spend(by_tag={tag: 1.0}), _spend(by_tag={tag: 3.5})])
    review_tick(work, forge, _REVIEW, base='integrate/main', run=FakeCommand(_doc()), ready=lambda *_: None,
                host='box', spend=lambda *_: next(reads))  # fmt: skip
    assert record_of([one['body'] for one in forge.comments[number]]).usd == 2.5


def test_the_pr_cap_reads_the_recorded_reviews_not_this_hosts_spend_alone(tmp_path: Path) -> None:
    """Another host's review recorded 11 USD; this host spent nothing on the PR, and the asked re-review is skipped.

    PLANTED CONTROL: the same recorded review under the cap runs.
    """
    for recorded, runs in ((11.0, 0), (4.0, 1)):
        (tmp_path / str(recorded)).mkdir()
        work, earlier = _work(tmp_path / str(recorded))
        forge, number = _forge(earlier)
        forge.login = 'serve-host'  # a DECLARED review producer
        comment_upsert(forge, number, kind=Marker.REVIEW, key=earlier, text=Record(earlier, usd=recorded).line())
        forge.login = 'ci-job'
        head = advance(work, 'pr/x', 'y.py', 'y = 1\n')
        forge.pulls[number]['head']['sha'] = head
        called_due(forge, head)  # the merge decision called the moved head
        ask_again(forge, number, head, 'S-a')
        command = FakeCommand(_doc())
        review = Review(command=_REVIEW.command, reviewers=('serve-host',))
        review_tick(work, forge, review, base='integrate/main', run=command, ready=lambda *_: None, host='box',
                    spend=lambda *_: _spend())  # fmt: skip
        assert len(command.ran) == runs
        if not runs:
            assert _state(forge, head)[1].startswith(f'{UNREVIEWED_STATUS} review budget reached: 11.00/10.00 USD')
