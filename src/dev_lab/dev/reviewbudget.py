"""REVIEW-BUDGET: a PR's review is capped in US dollars, inside the review's month (ruling 2026-10-31).

WHERE EACH FACT LIVES. The review's monthly budget is ai-lab's STANDING allotment :data:`REVIEW_ALLOTMENT`
(``[ai_lab.standing] review`` in the reviewing host's machine file), carved out of its provider's spend cap so no
campaign can starve it; what it allots and has spent, and every call's cost, are read from ``python -m ai_lab.spend
--json`` (its ``budgets``). What ONE PR may spend of that month is the policy here, and it restates no number of
ai-lab's. Each review OPENS that cap as a child allotment of the standing one, ``review>owner/repo#n``
(:func:`share_of`, :func:`open_share`), and runs its commands charged to it (:func:`charged_to`: :data:`TAG_ENV`
and :data:`SCOPE_ENV`), so ai-lab itself refuses a call past the PR's cap or the review's month, naming the level.

THE CAP IS FITTED, NOT GUESSED (:func:`fit`). From the last 90 days of per-PR spend: the expected PRs a month
(``PRs seen / days * 30``) and a per-PR cap that is the :data:`CAP_QUANTILE` of measured per-PR cost, lowered until
``PRs a month * mean(min(cost, cap))`` fits the monthly budget -- so a month of typical PRs cannot overrun it.
Below :data:`MIN_FITTED_PRS` measured PRs the cap is the INITIAL one, ``budget / INITIAL_PRS_PER_MONTH``.
``python -m dev_lab.dev.reviewbudget`` prints the fit and the month (``--json`` for a reader).

THE MONTH BOUNDS EVERY CAP (:func:`gate`). A PR's cap -- fitted, or raised by the integrator -- is never above what
the month has left. Below :data:`DEGRADE_BELOW` of the budget left, a review runs on the cheaper
:data:`DEGRADED_MODEL`. With nothing left, nothing runs.

A REACHED CAP SKIPS THE REVIEW, NAMED -- NEVER THE MERGE (user rulings 2026-11-05, 2026-11-06,
:mod:`dev_lab.dev.reviewcap`): the PR merges with an ``Unreviewed:`` line naming the cap. The integrator may raise one
PR's cap with a recorded reason (:data:`RAISE_DOOR`, a trusted ``review-cap`` comment, :func:`raised_of`).

A host with no ``[runtimes.ai_lab]`` caps nothing, and says so; an ai-lab whose report has no ``review`` allotment
is refused naming the row to declare.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev.reviewruntime import review_runtimes

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping, Sequence

__all__ = [
    'CAP_QUANTILE',
    'DEGRADED_MODEL',
    'DEGRADE_BELOW',
    'INITIAL_PRS_PER_MONTH',
    'MIN_FITTED_PRS',
    'RAISE_DOOR',
    'REVIEW_ALLOTMENT',
    'SCOPE_ENV',
    'SPEND_SCHEMA',
    'TAG_ENV',
    'Fit',
    'Gate',
    'Raised',
    'ShareRefused',
    'Spend',
    'charged_to',
    'fit',
    'gate',
    'open_share',
    'raise_line',
    'raise_record',
    'raised_of',
    'read_spend',
    'share_of',
    'tag_of',
]

#: The environment variable ai-lab tags a call's ledger row from: the cross-process contract (ai-lab's
#: ``ai_lab.budget.TAG_ENV``), like the command's arguments -- dev-lab imports no ai-lab.
TAG_ENV: Final = 'AI_LAB_SPEND_TAG'

#: The environment variable naming the ai-lab allotment a call is charged in (ai-lab's ``ai_lab.budget.SCOPE_ENV``).
SCOPE_ENV: Final = 'AI_LAB_SCOPE'

#: The ai-lab standing allotment every review draws on: its month is the review's budget.
REVIEW_ALLOTMENT: Final = 'review'

#: The ai-lab spend report version this reader knows: 2 reports each allotment's allotted and spent.
SPEND_SCHEMA: Final = 2

#: INITIAL, until :data:`MIN_FITTED_PRS` PRs are measured: about 100 reviewed PRs a month across the family's six
#: repos, so a PR's initial cap is 1000/100 = 10 USD -- a one-shot review of the full budget, a re-review after
#: growth, and a hard stop on a runaway one.
INITIAL_PRS_PER_MONTH: Final = 100

#: Below this many measured PRs a 0.9 quantile is the maximum of a handful: the initial cap holds instead.
MIN_FITTED_PRS: Final = 20

#: The fitted cap covers this share of measured PRs; the rest merge unreviewed, named, unless raised.
CAP_QUANTILE: Final = 0.9

#: Below this share of the monthly budget left, a review degrades to :data:`DEGRADED_MODEL`.
DEGRADE_BELOW: Final = 0.25

#: The cheaper tier a degraded review runs on (ai-lab's ``haiku`` role of the family provider).
DEGRADED_MODEL: Final = 'claude-haiku-5-5'

#: The integrator's door to raise one PR's cap, with its reason recorded on the PR.
RAISE_DOOR: Final = 'forge review cap {pr} --usd <n> --why "<reason>"'

_DAYS_PER_MONTH: Final = 30
_SPEND_TIMEOUT_S: Final = 300
_RAISED: Final = re.compile(r'<!-- review-cap (?P<json>\{.*?\}) -->', re.DOTALL)


@dataclass(frozen=True)
class Spend:
    """The review's month (its standing allotment, allotted and spent), and the per-PR history a cap is fitted from."""

    budget_usd: float
    spent_usd: float
    window_days: int = 1
    window_by_tag: Mapping[str, float] | None = None
    unpriced_calls: int = 0

    @property
    def remaining_usd(self) -> float:
        """What the month has left, never below zero."""
        return max(0.0, self.budget_usd - self.spent_usd)

    def of(self, tag: str) -> float:
        """What *tag* (one PR) has spent over the window."""
        return (self.window_by_tag or {}).get(tag, 0.0)

    @classmethod
    def from_report(cls, doc: Mapping[str, Any]) -> Spend:
        """The :class:`Spend` an ai-lab report says of :data:`REVIEW_ALLOTMENT`; an unknown schema or none: refused."""
        if doc.get('schema') != SPEND_SCHEMA:
            msg = f'an ai-lab spend report of schema {doc.get("schema")!r}; this reader knows {SPEND_SCHEMA}'
            raise ValueError(msg)
        review = doc['budgets'].get(REVIEW_ALLOTMENT)
        if review is None:
            msg = (
                f"this host's ai-lab allots no {REVIEW_ALLOTMENT!r}: declare [ai_lab.standing] {REVIEW_ALLOTMENT} = "
                "{ provider, amount, currency } in its machine file (the review's month, carved out of the cap)"
            )
            raise ValueError(msg)
        window = doc['window']
        return cls(
            review['allotted_usd'], review['spent_usd'], window['days'], dict(window['by_tag']), doc['unpriced_calls']
        )


@dataclass(frozen=True)
class Fit:
    """A per-PR cap, the PRs a month it assumes, how many PRs it read, and whether it is ``initial`` or ``fitted``."""

    cap_usd: float
    prs_per_month: float
    samples: int
    source: str


def _quantile(sorted_costs: Sequence[float], q: float) -> float:
    at = q * (len(sorted_costs) - 1)
    low, high = math.floor(at), math.ceil(at)
    return sorted_costs[low] + (sorted_costs[high] - sorted_costs[low]) * (at - low)


def _affordable(sorted_costs: Sequence[float], prs_per_month: float, budget: float) -> float:
    """The largest cap c with ``prs_per_month * mean(min(cost, c)) <= budget`` (infinite when every cost fits)."""
    n, below = len(sorted_costs), 0.0
    for i, cost in enumerate(sorted_costs):
        # with c in [previous cost, cost]: mean(min(x, c)) = (below + c * (n - i)) / n
        c = (budget * n / prs_per_month - below) / (n - i)
        if c <= cost:
            return max(c, 0.0)
        below += cost
    return math.inf


def fit(spend: Spend) -> Fit:
    """The per-PR cap *spend*'s measured PRs support (the module docstring); the initial one below enough PRs."""
    costs = sorted(usd for tag, usd in (spend.window_by_tag or {}).items() if '#' in tag)
    if len(costs) < MIN_FITTED_PRS:
        return Fit(spend.budget_usd / INITIAL_PRS_PER_MONTH, INITIAL_PRS_PER_MONTH, len(costs), 'initial')
    prs_per_month = len(costs) / max(spend.window_days, 1) * _DAYS_PER_MONTH
    cap = min(_quantile(costs, CAP_QUANTILE), _affordable(costs, prs_per_month, spend.budget_usd))
    return Fit(cap, prs_per_month, len(costs), 'fitted')


@dataclass(frozen=True)
class Raised:
    """The integrator's raise of one PR's dollar cap, with its reason and the forge login of its raiser."""

    usd: float | None
    why: str
    by: str = ''


def raise_line(raised: Raised) -> str:
    """The hidden line a ``review-cap`` comment records *raised* by (``>`` escaped)."""
    doc = {'usd': raised.usd, 'why': raised.why, 'by': raised.by}
    return f'<!-- review-cap {json.dumps(doc, ensure_ascii=False).replace(">", "\\u003e")} -->'


def _number(value: object) -> bool:
    return value is None or (isinstance(value, int | float) and not isinstance(value, bool))


def _parsed(text: str) -> Raised | None:
    """The raise one record's JSON spells, else ``None``: a malformed or ill-typed payload is no raise."""
    try:
        doc = json.loads(text)
    except ValueError:
        return None
    if not isinstance(doc, dict):
        return None
    usd, why, by = doc.get('usd'), doc.get('why', ''), doc.get('by', '')
    if not (_number(usd) and isinstance(why, str) and isinstance(by, str)):
        return None
    return Raised(usd, why, by)


def raised_of(bodies: Iterable[str]) -> Raised | None:
    """The newest raise among *bodies*; ``None`` when the PR was never raised.

    Only AUTHORISED records arrive here: :func:`~dev_lab.dev.forgereview_advice.trusted_bodies` admits a raise only
    from the forge's own logins or from a raiser the forge records with write permission. Among those, newest wins.
    """
    found = None
    for body in bodies:
        for match in _RAISED.finditer(body):
            found = _parsed(match['json']) or found
    return found


def raise_record(body: str, author: str) -> str | None:
    """The raise record alone in *body*, when the login it names (``by``) is its forge-recorded *author*; else ``None``.

    Only the matched line is returned, so nothing else the comment carries is read as forge state, and a raise
    naming anyone but its author is no raise. This binds the record to its author only; whether that author may
    RAISE is the forge's permission, asked by :func:`~dev_lab.dev.forgereview_advice.trusted_bodies`. A malformed
    payload is no record.
    """
    for match in _RAISED.finditer(body):
        if (raised := _parsed(match['json'])) is not None and raised.by == author:
            return match.group(0)
    return None


@dataclass(frozen=True)
class Gate:
    """Whether a PR's review runs (``run``) or is skipped (``skip``), why, the model and the USD cap it runs with."""

    state: str
    why: str
    model: str | None = None  # a degraded review's cheaper model; ``None`` keeps the review's
    usd: float = math.inf  # the PR's dollar cap, opened as its share of the review allotment; inf: no spend report


def gate(*, number: int, spent_usd: float, spend: Spend | None, raised: Raised | None = None) -> Gate:
    """Whether PR *number*, having spent *spent_usd* on its reviews, gets one now (the module docstring)."""
    door = RAISE_DOOR.format(pr=number)
    if spend is None:
        return Gate('run', f'{spent_usd:.2f} USD spent (no spend report on this host: no dollar cap)')
    if spend.remaining_usd <= 0:
        return Gate('skip', f'monthly review budget spent: {spend.spent_usd:.2f}/{spend.budget_usd:.2f} USD')
    own = raised.usd if raised is not None and raised.usd is not None else fit(spend).cap_usd
    cap = min(own, spend.remaining_usd)
    model, note = None, ''
    if spend.remaining_usd < DEGRADE_BELOW * spend.budget_usd:
        model, note = DEGRADED_MODEL, ' (degraded: month low)'
    if spent_usd >= cap:
        return Gate('skip', f'budget reached: {spent_usd:.2f}/{cap:.2f} USD{note}; the integrator may {door}')
    return Gate('run', f'{spent_usd:.2f}/{cap:.2f} USD{note}', model, cap)


def tag_of(pull_url: str, number: int) -> str:
    """What one PR's calls are charged to: ``<owner>/<repo>#<number>`` from its URL."""
    owner_repo = '/'.join(re.split(r'/pulls?/', pull_url)[0].rstrip('/').split('/')[-2:])
    return f'{owner_repo}#{number}'


def share_of(tag: str) -> str:
    """The ai-lab allotment one PR's review is charged in: a child of :data:`REVIEW_ALLOTMENT`."""
    return f'{REVIEW_ALLOTMENT}>{tag}'


class ShareRefused(RuntimeError):
    """ai-lab refused to open a PR's share of the review allotment (the review's month cannot hold it)."""


def open_share(runtimes: Mapping[str, Mapping[str, Any]], root: Path, share: str, usd: float) -> str | None:
    """Open (or re-allot) *share* at *usd* in this host's ai-lab; the allotment's name, ``None`` with no ai-lab.

    A raise or a refit re-allots the same path; ai-lab refuses one its parent cannot hold: :class:`ShareRefused`.
    """
    python = (runtimes.get('ai_lab') or {}).get('python')
    if not python:
        return None
    done = _door.run(
        [python, '-m', 'ai_lab.budget', 'allot', share, '--usd', repr(usd)], cwd=root, capture_output=True,
        text=True, encoding='utf-8', errors='replace', timeout=_SPEND_TIMEOUT_S, check=False,
    )  # fmt: skip
    if done.returncode != 0:
        raise ShareRefused(done.stderr.strip() or f'ai_lab.budget allot exited {done.returncode}')
    return share


@contextmanager
def charged_to(tag: str, share: str | None = None) -> Iterator[None]:
    """Every command started inside charges its calls to *tag* (:data:`TAG_ENV`) in *share* (:data:`SCOPE_ENV`)."""
    held = {TAG_ENV: tag, SCOPE_ENV: share}
    before = {name: os.environ.get(name) for name in held}
    for name, value in held.items():
        if value is not None:
            os.environ[name] = value
    try:
        yield
    finally:
        for name, value in before.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def read_spend(runtimes: Mapping[str, Mapping[str, Any]], root: Path) -> Spend | None:
    """The host's ai-lab spend report; ``None`` when this host's ai-lab cannot give one (said by the caller)."""
    python = (runtimes.get('ai_lab') or {}).get('python')
    if not python:
        return None
    try:
        done = _door.run(
            [python, '-m', 'ai_lab.spend', '--json'], cwd=root, capture_output=True, text=True, encoding='utf-8',
            errors='replace', timeout=_SPEND_TIMEOUT_S, check=False,
        )  # fmt: skip
    except OSError:
        return None
    if done.returncode != 0:
        return None
    return Spend.from_report(json.loads(done.stdout))


def main(argv: Sequence[str] | None = None) -> int:
    """Print the host's month and the per-PR cap it fits: one line each, or ``--json``."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.reviewbudget', description=__doc__.splitlines()[0])
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    spend = read_spend(review_runtimes(), Path.cwd())
    if spend is None:
        emit('this host has no ai-lab spend report (its locked ai-lab gives no ai_lab.spend)', err=True)
        return 2
    got = fit(spend)
    doc = {
        'allotment': REVIEW_ALLOTMENT, 'budget_usd': spend.budget_usd, 'spent_usd': spend.spent_usd,
        'remaining_usd': spend.remaining_usd, 'unpriced_calls': spend.unpriced_calls, 'cap_usd': got.cap_usd,
        'prs_per_month': got.prs_per_month, 'samples': got.samples, 'source': got.source,
    }  # fmt: skip
    if args.json:
        emit(json.dumps(doc, indent=1))
    else:
        emit(
            f'{REVIEW_ALLOTMENT} month: {spend.spent_usd:.2f}/{spend.budget_usd:.2f} USD spent '
            f'({spend.unpriced_calls} unpriced calls)\n'
            f'per-PR cap: {got.cap_usd:.2f} USD ({got.source}, {got.samples} PRs, {got.prs_per_month:.0f} PRs/month)'
        )
    return 0


if __name__ == '__main__':
    sys.exit(main())
