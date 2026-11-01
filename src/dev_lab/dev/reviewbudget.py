"""REVIEW-BUDGET: a PR's review is capped in rounds and US dollars, inside the family's month (ruling 2026-10-31).

WHERE EACH FACT LIVES. The family's monthly budget and every call's cost are ai-lab's (``python -m ai_lab.spend
--json``: the token ledger priced at each call's time, one row per call, tagged with what it was charged to). What
ONE PR may spend of that month is the policy here; it restates no number of ai-lab's. A review round runs its
commands with :data:`TAG_ENV` set to the PR (:func:`tag_of`), so its calls are charged to it.

THE CAP IS FITTED, NOT GUESSED (:func:`fit`). From the last 90 days of per-PR spend: the expected PRs a month
(``PRs seen / days * 30``) and a per-PR cap that is the :data:`CAP_QUANTILE` of measured per-PR cost, lowered until
``PRs a month * mean(min(cost, cap))`` fits the monthly budget -- so a month of typical PRs cannot overrun it.
Below :data:`MIN_FITTED_PRS` measured PRs the cap is the INITIAL one, ``budget / INITIAL_PRS_PER_MONTH``.
``python -m dev_lab.dev.reviewbudget`` prints the fit and the month (``--json`` for a reader).

THE MONTH BOUNDS EVERY CAP (:func:`gate`). A PR's cap -- fitted, or raised by the integrator -- is never above what
the month has left. Below :data:`DEGRADE_BELOW` of the budget left, a round DEGRADES before anything stops: one
round per PR (:data:`DEGRADED_ROUNDS`) on the cheaper :data:`DEGRADED_MODEL`. With nothing left, nothing runs.

A REACHED CAP WAITS, NAMED. A PR at its round cap or its dollar cap is neither reviewed again nor passed: its
review status is ``pending`` saying which cap (``budget reached: <spent>/<cap> USD``, ``round cap reached: r/R``)
and the remedy -- split the PR, or the integrator raises its cap with a recorded reason (:data:`RAISE_DOOR`, a
trusted ``review-cap`` comment, :func:`raised_of`).

A host whose ai-lab cannot report spend (an older ai-lab, no ``[runtimes.ai_lab]``) enforces the round cap only,
and the line it says names that.
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
from typing import TYPE_CHECKING, Any, Final

import lab_commons.launch as _door

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping, Sequence
    from pathlib import Path

__all__ = [
    'CAP_QUANTILE',
    'DEGRADED_MODEL',
    'DEGRADED_ROUNDS',
    'DEGRADE_BELOW',
    'INITIAL_PRS_PER_MONTH',
    'MIN_FITTED_PRS',
    'RAISE_DOOR',
    'SPEND_SCHEMA',
    'TAG_ENV',
    'Fit',
    'Gate',
    'Raised',
    'Spend',
    'charged_to',
    'fit',
    'gate',
    'raise_line',
    'raised_of',
    'read_spend',
    'tag_of',
]

#: The environment variable ai-lab tags a call's ledger row from: the cross-process contract (ai-lab's
#: ``ai_lab.budget.TAG_ENV``), like the command's arguments -- dev-lab imports no ai-lab.
TAG_ENV: Final = 'AI_LAB_SPEND_TAG'

#: The ai-lab spend report version this reader knows.
SPEND_SCHEMA: Final = 1

#: INITIAL, until :data:`MIN_FITTED_PRS` PRs are measured: about 100 reviewed PRs a month across the family's six
#: repos (each push re-reviewed, up to three rounds), so a PR's initial cap is 1000/100 = 10 USD -- several full
#: rounds of a 200 kB slice on the family model, and a hard stop on a runaway one.
INITIAL_PRS_PER_MONTH: Final = 100

#: Below this many measured PRs a 0.9 quantile is the maximum of a handful: the initial cap holds instead.
MIN_FITTED_PRS: Final = 20

#: The fitted cap covers this share of measured PRs; the rest wait, named, for a split or a raise.
CAP_QUANTILE: Final = 0.9

#: Below this share of the monthly budget left, rounds degrade (:data:`DEGRADED_ROUNDS` on :data:`DEGRADED_MODEL`).
DEGRADE_BELOW: Final = 0.25

#: Rounds per PR while degraded: the first review still runs, its re-reviews wait.
DEGRADED_ROUNDS: Final = 1

#: The cheaper tier a degraded round runs on (ai-lab's ``haiku`` role of the family provider).
DEGRADED_MODEL: Final = 'claude-haiku-5-5'

#: The integrator's door to raise one PR's cap, with its reason recorded on the PR.
RAISE_DOOR: Final = 'forge review cap {pr} --usd <n> --rounds <n> --why "<reason>"'

_DAYS_PER_MONTH: Final = 30
_SPEND_TIMEOUT_S: Final = 300
_RAISED: Final = re.compile(r'<!-- review-cap (?P<json>\{.*?\}) -->', re.DOTALL)


@dataclass(frozen=True)
class Spend:
    """ai-lab's spend report: the month against its budget, and the per-PR history a cap is fitted from."""

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
        """The :class:`Spend` an ai-lab report says; a schema this reader does not know is refused."""
        if doc.get('schema') != SPEND_SCHEMA:
            msg = f'an ai-lab spend report of schema {doc.get("schema")!r}; this reader knows {SPEND_SCHEMA}'
            raise ValueError(msg)
        window = doc['window']
        return cls(doc['budget_usd'], doc['spent_usd'], window['days'], dict(window['by_tag']), doc['unpriced_calls'])


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
    """The integrator's raise of one PR's caps, with its reason."""

    usd: float | None
    rounds: int | None
    why: str


def raise_line(raised: Raised) -> str:
    """The hidden line a trusted ``review-cap`` comment records *raised* by (``>`` escaped)."""
    doc = {'usd': raised.usd, 'rounds': raised.rounds, 'why': raised.why}
    return f'<!-- review-cap {json.dumps(doc, ensure_ascii=False).replace(">", "\\u003e")} -->'


def raised_of(bodies: Iterable[str]) -> Raised | None:
    """The newest raise among *bodies* (trusted comment bodies only); ``None`` when the PR was never raised."""
    found = None
    for body in bodies:
        for match in _RAISED.finditer(body):
            doc = json.loads(match['json'])
            found = Raised(doc.get('usd'), doc.get('rounds'), doc.get('why', ''))
    return found


@dataclass(frozen=True)
class Gate:
    """Whether a PR's next round runs (``run``) or waits (``wait``), why, and the rounds and model it runs with."""

    state: str
    why: str
    max_rounds: int
    model: str | None = None  # a degraded round's cheaper model; ``None`` keeps the review's


def gate(
    *, number: int, spent_usd: float, rounds_done: int, max_rounds: int, spend: Spend | None,
    raised: Raised | None = None,
) -> Gate:  # fmt: skip
    """Whether PR *number*, having spent *spent_usd* over *rounds_done* rounds, gets another (the module docstring)."""
    door = RAISE_DOOR.format(pr=number)
    rounds = raised.rounds if raised is not None and raised.rounds is not None else max_rounds
    if spend is None:
        cap, model, note = math.inf, None, ''
    else:
        if spend.remaining_usd <= 0:
            why = f'monthly review budget spent: {spend.spent_usd:.2f}/{spend.budget_usd:.2f} USD; waits for next month'
            return Gate('wait', why, rounds)
        own = raised.usd if raised is not None and raised.usd is not None else fit(spend).cap_usd
        cap = min(own, spend.remaining_usd)
        model, note = None, ''
        if spend.remaining_usd < DEGRADE_BELOW * spend.budget_usd:
            rounds, model, note = min(rounds, DEGRADED_ROUNDS), DEGRADED_MODEL, ' (degraded: month low)'
    if rounds_done >= rounds:
        return Gate('wait', f'round cap reached: {rounds_done}/{rounds} rounds{note}; split the PR, or {door}', rounds)
    if spent_usd >= cap:
        why = f'budget reached: {spent_usd:.2f}/{cap:.2f} USD{note}; split the PR, or {door}'
        return Gate('wait', why, rounds)
    return Gate('run', f'round {rounds_done + 1}/{rounds}, {spent_usd:.2f}/{cap:.2f} USD{note}', rounds, model)


def tag_of(pull_url: str, number: int) -> str:
    """What one PR's calls are charged to: ``<owner>/<repo>#<number>`` from its URL."""
    owner_repo = '/'.join(re.split(r'/pulls?/', pull_url)[0].rstrip('/').split('/')[-2:])
    return f'{owner_repo}#{number}'


@contextmanager
def charged_to(tag: str) -> Iterator[None]:
    """Every command started inside charges its model calls to *tag* (:data:`TAG_ENV`), restored after."""
    before = os.environ.get(TAG_ENV)
    os.environ[TAG_ENV] = tag
    try:
        yield
    finally:
        if before is None:
            os.environ.pop(TAG_ENV, None)
        else:
            os.environ[TAG_ENV] = before


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
    from pathlib import Path  # noqa: PLC0415 -- typing-only at module level

    from dev_lab.dev.forgereview_runtimes import host_runtimes  # noqa: PLC0415 -- the CLI alone reads the machine file

    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.reviewbudget', description=__doc__.splitlines()[0])
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    spend = read_spend(host_runtimes(), Path.cwd())
    if spend is None:
        sys.stderr.write('this host has no ai-lab spend report ([runtimes.ai_lab] python, ai_lab.spend)\n')
        return 2
    got = fit(spend)
    doc = {
        'budget_usd': spend.budget_usd, 'spent_usd': spend.spent_usd, 'remaining_usd': spend.remaining_usd,
        'unpriced_calls': spend.unpriced_calls, 'cap_usd': got.cap_usd, 'prs_per_month': got.prs_per_month,
        'samples': got.samples, 'source': got.source,
    }  # fmt: skip
    if args.json:
        sys.stdout.write(json.dumps(doc, indent=1) + '\n')
    else:
        sys.stdout.write(
            f'month: {spend.spent_usd:.2f}/{spend.budget_usd:.2f} USD spent ({spend.unpriced_calls} unpriced calls)\n'
            f'per-PR cap: {got.cap_usd:.2f} USD ({got.source}, {got.samples} PRs, {got.prs_per_month:.0f} PRs/month)\n'
        )
    return 0


if __name__ == '__main__':
    sys.exit(main())
