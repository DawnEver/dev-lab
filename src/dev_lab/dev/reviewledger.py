"""THE HOSTED REVIEW'S MONTH: a host with no machine file reviews under the base's declared month, charged on the forge.

WHERE EACH FACT LIVES. The month's amount is the base's ``[tool.dev_lab.review] month`` (:class:`~dev_lab.dev.
reviewbudget.Month`), read from ``origin/<base>`` like the rest of the review (:func:`~dev_lab.dev.
forgereview_declared.review_at`). It governs ONLY a host with no machine file -- a GitHub-hosted runner, whose
ai-lab has neither ``[ai_lab.standing] review`` nor a ledger that outlives the job: a host WITH a machine file keeps
its own ``[ai_lab.standing] review`` (the judge's path is unchanged), so the number is never read from two places
on one host. The month's SPEND is the forge's: append-only entries on the run-records home
(:mod:`dev_lab.dev.forgerecords`), one name per charge (:class:`Entry`), so every run of the repo reads one ledger.

A RUN HOLDS ITS CAP BEFORE IT SPENDS (:func:`hold`). It appends a ``hold`` of its gated cap, re-reads the ledger,
and is ADMITTED only when every charge whose hold is no newer than its own (forge asset ids are monotonic) fits the
month; otherwise it withdraws its hold and is skipped, named. A charge is its run's ``spent`` entry once settled
(:func:`settle`, what ai-lab reported the run spent), else its hold. THE RACE BOUND: any set of concurrent runs
admits holds summing to at most the month's amount -- each admitted hold was checked against every older one,
withdrawn or not -- so the month is overrun only by what a run spends past its own hold, which ai-lab bounds (its
share is opened at the hold; a call under way may finish past it by its input).

AI-LAB ENFORCES THE SHARE AS ON A JUDGE HOST (:func:`derived_config`): the run points ai-lab
(``$LAB_COMMONS_CONFIG``) at a machine file DERIVED for the run -- the provider's cap and the ``review`` standing
allotment both at what the month has left -- so the PR's share opens, and every call is refused past it, exactly
as a judge host's ai-lab does. The file is regenerated per run and holds no secret.
"""

from __future__ import annotations

import json
import re
import secrets
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol

from lab_commons.config import CONFIG_ENV, config_path

from dev_lab.dev import forgerecords
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.reviewbudget import REVIEW_ALLOTMENT, Spend

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, MutableMapping

    from dev_lab.dev.forgework import Client
    from dev_lab.dev.reviewbudget import Month

__all__ = [
    'HELD_ELSEWHERE',
    'HOLD',
    'LEDGER_UNREAD',
    'PREFIX',
    'SPENT',
    'Entry',
    'ForgeLedger',
    'Hosted',
    'Ledger',
    'derived_config',
    'hold',
    'hosted_here',
    'month_key',
    'settle',
    'spend_of',
]

#: Every ledger entry's name starts so; nothing else on the records home does.
PREFIX: Final = 'review-spend-'
#: A run's charge before it spends: its gated cap.
HOLD: Final = 'hold'
#: A run's settled charge: what ai-lab reported it spent.
SPENT: Final = 'spent'

#: Why a hosted review is skipped when concurrent reviews' older holds fill the month (:func:`hold`).
HELD_ELSEWHERE: Final = 'the monthly review budget is held by concurrent reviews'

#: Why a hosted review is skipped when the forge ledger cannot be read or written: no hold, no run.
LEDGER_UNREAD: Final = 'the review spend ledger on the forge could not be read or written'

_NAME: Final = re.compile(
    rf'^{PREFIX}(?P<month>\d{{4}}-\d{{2}})-(?P<number>\d+)-(?P<run>[0-9a-f]+)-(?P<kind>{HOLD}|{SPENT})'
    r'-(?P<usd>\d+(?:\.\d+)?)\.json$'
)


@dataclass(frozen=True)
class Entry:
    """One charge on the ledger: the month, the PR, the run it belongs to, ``hold`` or ``spent``, its USD, its id."""

    month: str
    number: int
    run: str
    kind: str
    usd: float
    id: int = 0  # the forge's asset id: monotonic, so it orders the holds

    @property
    def name(self) -> str:
        """The asset name that IS the entry (the content repeats it for a reader of the asset alone)."""
        return f'{PREFIX}{self.month}-{self.number}-{self.run}-{self.kind}-{self.usd:.6f}.json'

    @classmethod
    def parse(cls, name: str, ident: int) -> Entry | None:
        """The entry *name* spells, else ``None`` (another file on the records home)."""
        found = _NAME.match(name)
        if found is None:
            return None
        return cls(found['month'], int(found['number']), found['run'], found['kind'], float(found['usd']), ident)


class Ledger(Protocol):
    """The shared spend store: list every entry, append one (its id assigned), withdraw one."""

    def entries(self) -> tuple[Entry, ...]:
        """Every entry, oldest first."""
        ...

    def append(self, entry: Entry) -> Entry:
        """Store *entry*; it, with its id."""
        ...

    def withdraw(self, entry: Entry) -> None:
        """Delete *entry* (only a hold that never ran is withdrawn)."""
        ...


@dataclass(frozen=True)
class ForgeLedger:
    """The ledger as assets of the forge's run-records home (:mod:`dev_lab.dev.forgerecords`)."""

    client: Client

    def entries(self) -> tuple[Entry, ...]:
        """Every ledger asset of the records home, oldest first."""
        found = (Entry.parse(one.name, one.id) for one in forgerecords.listing(self.client))
        return tuple(one for one in found if one is not None)

    def append(self, entry: Entry) -> Entry:
        """Upload *entry* as one asset; idempotent by name (:func:`~dev_lab.dev.forgerecords.attach`)."""
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / entry.name
            path.write_text(json.dumps(entry.__dict__ | {'id': None}), encoding='utf-8')
            stored = forgerecords.attach(self.client, path)
        return Entry(entry.month, entry.number, entry.run, entry.kind, entry.usd, stored.id)

    def withdraw(self, entry: Entry) -> None:
        """Delete *entry*'s asset."""
        forgerecords.remove_named(self.client, entry.name)


def month_key(now: datetime) -> str:
    """The UTC month *now* is in, ``YYYY-MM``: the period a declared month spans."""
    return now.astimezone(UTC).strftime('%Y-%m')


def _charges(entries: Iterable[Entry], month: str) -> dict[str, tuple[int, int, float]]:
    """Per run of *month*: ``(its hold's id, its PR, its charge)`` -- the settled spend, else the hold."""
    held: dict[str, tuple[int, int, float]] = {}
    spent: dict[str, float] = {}
    for one in entries:
        if one.month != month:
            continue
        if one.kind == HOLD:
            held.setdefault(one.run, (one.id, one.number, one.usd))
        else:
            spent[one.run] = one.usd
    return {run: (ident, number, spent.get(run, usd)) for run, (ident, number, usd) in held.items()}


def spend_of(month: Month, entries: Iterable[Entry], *, now: datetime, repo_tag: str) -> Spend:
    """The :class:`~dev_lab.dev.reviewbudget.Spend` the ledger says of *month* at *now*: per PR ``<repo_tag>#n``."""
    by_tag: dict[str, float] = {}
    for _, number, usd in _charges(entries, month_key(now)).values():
        by_tag[f'{repo_tag}#{number}'] = by_tag.get(f'{repo_tag}#{number}', 0.0) + usd
    return Spend(month.amount, sum(by_tag.values()), max(now.astimezone(UTC).day, 1), by_tag, 0, month.provider)


def hold(ledger: Ledger, month: Month, *, number: int, usd: float, now: datetime) -> Entry | None:
    """Hold *usd* of *month* for PR *number*; the hold when admitted, else ``None`` (withdrawn): the race bound."""
    mine = ledger.append(Entry(month_key(now), number, secrets.token_hex(8), HOLD, usd))
    older = [charge for ident, _, charge in _charges(ledger.entries(), mine.month).values() if ident <= mine.id]
    if sum(older) <= month.amount:
        return mine
    ledger.withdraw(mine)
    return None


def settle(ledger: Ledger, held: Entry, usd: float) -> Entry:
    """Settle *held* at what its run spent (append-only: the hold stays, the ``spent`` entry supersedes it)."""
    return ledger.append(Entry(held.month, held.number, held.run, SPENT, usd))


def hosted_here() -> bool:
    """Whether this host has no machine file -- the one host a declared month governs."""
    return not config_path().is_file()


def derived_config(month: Month, left_usd: float) -> str:
    """The machine file a hosted run's ai-lab reads: its provider's cap and the review allotment at *left_usd*."""
    row = f'{{ amount = {left_usd!r}, currency = "{month.currency}" }}'
    return (
        f'[ai_lab.spend_cap]\n{json.dumps(month.provider)} = {row}\n\n'
        f'[ai_lab.standing]\n{REVIEW_ALLOTMENT} = {{ provider = {json.dumps(month.provider)}, amount = {left_usd!r}, '
        f'currency = "{month.currency}" }}\n'
    )


@dataclass(frozen=True)
class Hosted:
    """A hosted review's month and ledger, and how it reads what the run spent (ai-lab's report under the file)."""

    month: Month
    ledger: Ledger
    spend: Spend
    read_spent: Callable[[], float | None]
    now: datetime

    @contextmanager
    def run(self, *, number: int, usd: float, env: MutableMapping[str, str]) -> Iterator[str | None]:
        """Hold *usd*, point ai-lab at the derived file inside, settle on exit; yields why not, ``None`` when admitted.

        *env* is the process environment (``os.environ``): :data:`~lab_commons.config.CONFIG_ENV` is set inside
        and restored after, so the share's ``allot`` and every review command read the derived file.
        """
        try:
            held = hold(self.ledger, self.month, number=number, usd=usd, now=self.now)
        except (ForgeCallFailed, OSError, ValueError) as unread:
            yield f'{LEDGER_UNREAD}: {unread}'
            return
        if held is None:
            yield f'{HELD_ELSEWHERE}: {self.month.amount:.2f} USD'
            return
        before = env.get(CONFIG_ENV)
        with tempfile.TemporaryDirectory(dir=env.get('RUNNER_TEMP') or None) as scratch:
            derived = Path(scratch) / 'config.toml'
            derived.write_text(derived_config(self.month, self.spend.remaining_usd), encoding='utf-8')
            env[CONFIG_ENV] = str(derived)
            try:
                yield None
            finally:
                spent = self.read_spent()
                if before is None:
                    env.pop(CONFIG_ENV, None)
                else:
                    env[CONFIG_ENV] = before
                if spent is not None:
                    settle(self.ledger, held, spent)
