"""THE FAMILY'S REVIEW MONTH: one amount, one ledger, charged by every reviewer -- the judge host and every runner.

ONE MONTH (user ruling 2026-11-10: Gitea and GitHub together, one monthly amount). Its ONE source is the machine's
family layer: ``section('ai_lab')['standing']['review']`` (ai-lab's own allotment, ``{ provider, amount, currency
}``) and ``section('review')['ledger']``, the URL of the ONE repository the spend is charged to
(:func:`declared_month`). A host with a machine file -- the judge -- reads it there. A GitHub-hosted runner has none
and cannot read the private family repo, so the month reaches it only as DERIVED data: ``forge secrets month``
(:mod:`dev_lab.dev.forgesecrets`) writes that same value as the repository variable :data:`MONTH_VAR` on every
GitHub member, and the review job reads it from env (:func:`month_here`). A repo with no variable declares no
budget: the named skip (:data:`~dev_lab.dev.reviewbudget.NO_REVIEW_ALLOTMENT`).

ONE LEDGER. Every reviewer charges the SAME store: append-only entries on the run-records home
(:mod:`dev_lab.dev.forgerecords`) of the declared ledger repository, one name per charge (:class:`Entry`, tagged
with the reviewed PR's ``<owner>/<repo>#<n>``). It is written with a dedicated token, :data:`LEDGER_TOKEN` -- a
fine-grained token with contents:write on that one repository only: a runner gets it as the secret ``forge secrets
sync --secret`` distributes, the judge from the file its ``[review] ledger_token_file`` names (:func:`forge_ledger`).
The review job's own job token keeps exactly the permissions it has; the ledger token never reaches a log line.

A RUN HOLDS ITS CAP BEFORE IT SPENDS (:func:`hold`). It appends a ``hold`` of its gated cap, re-reads the ledger,
and is ADMITTED only when every charge whose hold is no newer than its own (forge asset ids are monotonic) fits the
month; otherwise it withdraws its hold and is skipped, named. A charge is its run's ``spent`` entry once settled
(:func:`settle`, what ai-lab reported the run spent), else its hold. THE RACE BOUND: any set of concurrent runs, of
any repos on any hosts, admits holds summing to at most the month's amount -- each admitted hold was checked against
every older one, withdrawn or not -- so the month is overrun only by what a run spends past its own hold, which
ai-lab bounds.

A RUNNER'S AI-LAB ENFORCES THE SHARE AS ON THE JUDGE (:func:`derived_config`): with no machine file, the run points
ai-lab (``$LAB_COMMONS_CONFIG``) at a machine file DERIVED for the run -- the provider's cap and the ``review``
standing allotment both at what the month has left. The judge keeps its own machine file (its keys live there).
"""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol

from lab_commons.config import CONFIG_ENV, config_path, section

from dev_lab.dev import forgerecords
from dev_lab.dev.forge import forge_of_url
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgework import stored_client
from dev_lab.dev.reviewbudget import MONTH_CURRENCY, REVIEW_ALLOTMENT, Month, Spend

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Mapping, MutableMapping

    from dev_lab.dev.forgework import Client

__all__ = [
    'HELD_ELSEWHERE',
    'HOLD',
    'LEDGER_TOKEN',
    'LEDGER_UNREAD',
    'MONTH_VAR',
    'NO_LEDGER',
    'NO_LEDGER_TOKEN',
    'PREFIX',
    'SPENT',
    'Entry',
    'FamilyMonth',
    'ForgeLedger',
    'Hosted',
    'Ledger',
    'declared_month',
    'derived_config',
    'forge_ledger',
    'hold',
    'hosted_here',
    'month_here',
    'month_key',
    'settle',
    'spend_of',
]

#: The repository variable a GitHub member's review job reads the family month from (written by ``secrets month``).
MONTH_VAR: Final = 'DEV_LAB_REVIEW_MONTH'
#: The secret (runner) / env name of the ledger token: contents:write on the ledger repository alone.
LEDGER_TOKEN: Final = 'DEV_LAB_LEDGER_TOKEN'  # noqa: S105 -- a variable's name, no secret

#: Every ledger entry's name starts so; nothing else on the records home does.
PREFIX: Final = 'review-spend-'
#: A run's charge before it spends: its gated cap.
HOLD: Final = 'hold'
#: A run's settled charge: what ai-lab reported it spent.
SPENT: Final = 'spent'

#: Why a review is skipped when concurrent reviews' older holds fill the month (:func:`hold`).
HELD_ELSEWHERE: Final = 'the monthly review budget is held by concurrent reviews'
#: Why a review is skipped when the ledger cannot be read or written: no hold, no run.
LEDGER_UNREAD: Final = 'the review spend ledger could not be read or written'
#: Why a declared month is refused when it names no ledger.
NO_LEDGER: Final = 'the review month names no ledger: [review] ledger = "<forge URL of the one ledger repository>"'
#: Why the ledger is unwritable: no token on this host.
NO_LEDGER_TOKEN: Final = f'no ledger token: ${LEDGER_TOKEN} on a runner, [review] ledger_token_file on a host'

_NAME: Final = re.compile(
    rf'^{PREFIX}(?P<month>\d{{4}}-\d{{2}})-(?P<repo>[a-z2-7]+)-(?P<number>\d+)-(?P<run>[0-9a-f]+)'
    rf'-(?P<kind>{HOLD}|{SPENT})-(?P<usd>\d+(?:\.\d+)?)\.json$'
)


def _encoded(repo: str) -> str:
    """*repo* (``owner/repo``) in the asset-name alphabet: lower-case base32, unambiguous whatever the name holds."""
    return base64.b32encode(repo.encode('utf-8')).decode('ascii').rstrip('=').lower()


def _decoded(text: str) -> str:
    padded = text.upper() + '=' * (-len(text) % 8)
    return base64.b32decode(padded).decode('utf-8')


@dataclass(frozen=True)
class FamilyMonth:
    """The family's ONE review month and the URL of the ONE repository its spend is charged to."""

    month: Month
    ledger: str

    def __post_init__(self) -> None:
        """Refuse a month with no ledger."""
        if not isinstance(self.ledger, str) or not self.ledger.strip():
            raise ValueError(NO_LEDGER)

    def text(self) -> str:
        """The value :data:`MONTH_VAR` holds: one JSON line (derived data; no secret)."""
        month = self.month
        return json.dumps({'provider': month.provider, 'amount': month.amount, 'currency': month.currency,
                           'ledger': self.ledger}, sort_keys=True)  # fmt: skip

    @classmethod
    def from_text(cls, text: str) -> FamilyMonth:
        """The month a :data:`MONTH_VAR` value spells; a malformed one is refused."""
        try:
            value = json.loads(text)
        except json.JSONDecodeError as bad:
            msg = f'{MONTH_VAR} is no JSON object: {bad}'
            raise ValueError(msg) from bad
        ledger = value.pop('ledger', '') if isinstance(value, dict) else ''
        return cls(Month.from_declared(value), ledger)


def declared_month(
    ai_lab: Mapping[str, object] | None = None, review: Mapping[str, object] | None = None
) -> FamilyMonth | None:
    """The month this machine's family layer declares (module docstring); ``None`` when it allots no review."""
    ai_lab = section('ai_lab') if ai_lab is None else ai_lab
    review = section('review') if review is None else review
    standing = ai_lab.get('standing', {})
    row = standing.get(REVIEW_ALLOTMENT) if isinstance(standing, dict) else None
    if not isinstance(row, dict):
        return None
    month = Month(row.get('provider', ''), row.get('amount', -1), row.get('currency', MONTH_CURRENCY))
    return FamilyMonth(month, str(review.get('ledger', '')))


def month_here(env: Mapping[str, str] | None = None) -> FamilyMonth | None:
    """The month on this host: the machine file's when there is one, else the derived :data:`MONTH_VAR`."""
    if not hosted_here():
        return declared_month()
    text = (os.environ if env is None else env).get(MONTH_VAR, '').strip()
    return FamilyMonth.from_text(text) if text else None


@dataclass(frozen=True)
class Entry:
    """One charge: the month, the PR's repo and number, its run, ``hold`` or ``spent``, its USD, its asset id."""

    month: str
    repo: str  # ``<owner>/<repo>`` of the reviewed PR
    number: int
    run: str
    kind: str
    usd: float
    id: int = 0  # the forge's asset id: monotonic, so it orders the holds

    @property
    def tag(self) -> str:
        """The PR the charge is for, ``<owner>/<repo>#<n>`` (:func:`~dev_lab.dev.reviewbudget.tag_of`)."""
        return f'{self.repo}#{self.number}'

    @property
    def name(self) -> str:
        """The asset name that IS the entry (the content repeats it for a reader of the asset alone)."""
        return (f'{PREFIX}{self.month}-{_encoded(self.repo)}-{self.number}-{self.run}-{self.kind}-{self.usd:.6f}'
                '.json')  # fmt: skip

    @classmethod
    def parse(cls, name: str, ident: int) -> Entry | None:
        """The entry *name* spells, else ``None`` (another file on the records home)."""
        found = _NAME.match(name)
        if found is None:
            return None
        try:
            repo = _decoded(found['repo'])
        except (ValueError, UnicodeDecodeError):
            return None
        return cls(found['month'], repo, int(found['number']), found['run'], found['kind'], float(found['usd']), ident)


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
    """The ledger as assets of the ledger repository's run-records home (:mod:`dev_lab.dev.forgerecords`)."""

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
        return Entry(entry.month, entry.repo, entry.number, entry.run, entry.kind, entry.usd, stored.id)

    def withdraw(self, entry: Entry) -> None:
        """Delete *entry*'s asset."""
        forgerecords.remove_named(self.client, entry.name)


def _machine_token() -> str:
    """The ledger token the machine file's ``[review] ledger_token_file`` holds; ``''`` with none declared."""
    if hosted_here():
        return ''
    path = section('review').get('ledger_token_file')
    return Path(str(path)).expanduser().read_text(encoding='utf-8').strip() if path else ''


def forge_ledger(family: FamilyMonth, *, token: str = '') -> ForgeLedger:
    """The ONE ledger *family* names, written with the ledger token: *token*, else :data:`LEDGER_TOKEN`, else the file.

    Raises:
        ValueError: no ledger token on this host (:data:`NO_LEDGER_TOKEN`).

    """
    token = token or os.environ.get(LEDGER_TOKEN, '').strip() or _machine_token()
    if not token:
        raise ValueError(NO_LEDGER_TOKEN)
    return ForgeLedger(stored_client(forge_of_url(family.ledger), cwd=Path.cwd(), token=token))


def month_key(now: datetime) -> str:
    """The UTC month *now* is in, ``YYYY-MM``: the period a declared month spans."""
    return now.astimezone(UTC).strftime('%Y-%m')


def _charges(entries: Iterable[Entry], month: str) -> dict[str, tuple[int, str, float]]:
    """Per run of *month*: ``(its hold's id, its PR tag, its charge)`` -- the settled spend, else the hold."""
    held: dict[str, tuple[int, str, float]] = {}
    spent: dict[str, float] = {}
    for one in entries:
        if one.month != month:
            continue
        if one.kind == HOLD:
            held.setdefault(one.run, (one.id, one.tag, one.usd))
        else:
            spent[one.run] = one.usd
    return {run: (ident, tag, spent.get(run, usd)) for run, (ident, tag, usd) in held.items()}


def spend_of(month: Month, entries: Iterable[Entry], *, now: datetime) -> Spend:
    """The :class:`~dev_lab.dev.reviewbudget.Spend` the ledger says of *month* at *now*, per PR of every repo."""
    by_tag: dict[str, float] = {}
    for _, tag, usd in _charges(entries, month_key(now)).values():
        by_tag[tag] = by_tag.get(tag, 0.0) + usd
    return Spend(month.amount, sum(by_tag.values()), max(now.astimezone(UTC).day, 1), by_tag, 0, month.provider)


def hold(ledger: Ledger, month: Month, *, repo: str, number: int, usd: float, now: datetime) -> Entry | None:
    """Hold *usd* of *month* for *repo*'s PR *number*; the hold when admitted, else ``None`` (withdrawn)."""
    mine = ledger.append(Entry(month_key(now), repo, number, secrets.token_hex(8), HOLD, usd))
    older = [charge for ident, _, charge in _charges(ledger.entries(), mine.month).values() if ident <= mine.id]
    if sum(older) <= month.amount:
        return mine
    ledger.withdraw(mine)
    return None


def settle(ledger: Ledger, held: Entry, usd: float) -> Entry:
    """Settle *held* at what its run spent (append-only: the hold stays, the ``spent`` entry supersedes it)."""
    return ledger.append(Entry(held.month, held.repo, held.number, held.run, SPENT, usd))


def hosted_here() -> bool:
    """Whether this host has no machine file: a runner, whose ai-lab reads a derived one (:func:`derived_config`)."""
    return not config_path().is_file()


def derived_config(month: Month, left_usd: float) -> str:
    """The machine file a runner's ai-lab reads: its provider's cap and the review allotment at *left_usd*."""
    row = f'{{ amount = {left_usd!r}, currency = "{month.currency}" }}'
    return (
        f'[ai_lab.spend_cap]\n{json.dumps(month.provider)} = {row}\n\n'
        f'[ai_lab.standing]\n{REVIEW_ALLOTMENT} = {{ provider = {json.dumps(month.provider)}, amount = {left_usd!r}, '
        f'currency = "{month.currency}" }}\n'
    )


@dataclass(frozen=True)
class Hosted:
    """A review's family month and its ledger, and how it reads ai-lab's spend (the run's is the difference)."""

    month: Month
    ledger: Ledger
    spend: Spend
    read_spent: Callable[[], float | None]
    now: datetime
    #: Whether ai-lab reads a derived machine file for the run (a runner); the judge keeps its own.
    derive: bool = True

    @contextmanager
    def run(self, *, repo: str, number: int, usd: float, env: MutableMapping[str, str]) -> Iterator[str | None]:
        """Hold *usd*, run inside (a runner: ai-lab at the derived file), settle on exit; yields why not, else ``None``.

        *env* is the process environment (``os.environ``): on a runner :data:`~lab_commons.config.CONFIG_ENV` is set
        inside and restored after, so the share's ``allot`` and every review command read the derived file.
        """
        try:
            held = hold(self.ledger, self.month, repo=repo, number=number, usd=usd, now=self.now)
        except (ForgeCallFailed, OSError, ValueError) as unread:
            yield f'{LEDGER_UNREAD}: {unread}'
            return
        if held is None:
            yield f'{HELD_ELSEWHERE}: {self.month.amount:.2f} USD'
            return
        before = env.get(CONFIG_ENV)
        with tempfile.TemporaryDirectory(dir=env.get('RUNNER_TEMP') or None) as scratch:
            if self.derive:
                derived = Path(scratch) / 'config.toml'
                derived.write_text(derived_config(self.month, self.spend.remaining_usd), encoding='utf-8')
                env[CONFIG_ENV] = str(derived)
            start = self.read_spent()
            try:
                yield None
            finally:
                end = self.read_spent()
                if self.derive:
                    if before is None:
                        env.pop(CONFIG_ENV, None)
                    else:
                        env[CONFIG_ENV] = before
                if start is not None and end is not None:
                    settle(self.ledger, held, max(end - start, 0.0))
