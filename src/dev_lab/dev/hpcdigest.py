"""THE DAILY HPC USAGE DIGEST: every account's day, folded into ONE message on the machine's alert channels.

USER RULINGS 2026-11-15 (they partly reverse 2026-11-03's "summary only, no push"): there is a DAILY usage
summary; HPC information never goes to a forge issue -- it is SENT, through Telegram (email accepted); and one
mechanism manages it for every account.

WHEN. The first tick that holds the repo-wide poller lease (:func:`dev_lab.dev.forgepoller.polls`) at or after
``[hpc_digest] hour_utc`` of the machine file, once per UTC day. A machine file without ``[hpc_digest]`` never
sends: declare it on exactly ONE host (the one whose ``[alerts]`` reach the humans), or each declaring host sends
its own. Whether today is done is read from the store, so a second tick the same day sends nothing.

WHAT. One row per account (:class:`Account`):

* a SERVING account's day is its host card's facts (:mod:`dev_lab.dev.forgehosts`): the ``usage`` its tick read
  from its ONE ``sacct`` (:mod:`dev_lab.dev.hpcusage`) and its ``quota_use``. No second read of it is made;
* every other account this machine's ``[hpc] reach`` declares (a research account serves no card) is read here,
  over its own login hosts, with the SAME read -- :data:`dev_lab.dev.hpcusage.COMMAND` parsed by
  :func:`~dev_lab.dev.hpcusage.parse`, the quota by :mod:`dev_lab.dev.diskusage`'s parsers. One it cannot read
  (unreachable, refused by role, a TOTP session it does not hold) is listed ``not read: <why>``;
* a BILLED grant's burn: :func:`lab_commons.hpc.budget.spent_and_committed` over its own
  :func:`~lab_commons.hpc.budget.ledger_command`, against its declared budget and how much of its window is gone.

HISTORY. Each attempt appends one dated row to ``hpc-digest.jsonl`` beside the machine file (where this host's
records live): the accounts' numbers and whether the channels took it. The message shows each account's core-hours
against the last SENT day's. A send that no channel took (or with no channel enabled) is recorded unsent, said in
the tick log, and retried on the next poller tick -- never silent. A channel's reply is never stored: Telegram's
echoes the chat; only each channel's name and outcome are.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

from lab_commons.compute.durable import durable_text
from lab_commons.config import config_path, section
from lab_commons.hpc.budget import ledger_command, spent_and_committed
from lab_commons.hpc.cluster import Runner, runner_for
from lab_commons.hpc.grants import Grant, load_grants

from dev_lab.dev import hpcusage
from dev_lab.dev.diskusage import parse_mmlsquota, parse_quota
from dev_lab.dev.forgehosts import HostCard
from dev_lab.supervise.alert import Delivery, Notifier
from dev_lab.supervise.notice import Notice, host_label
from dev_lab.supervise.verdict import Severity

__all__ = ['STORE_NAME', 'TABLE', 'Account', 'digest', 'due', 'from_cards', 'read_grant', 'render', 'step']

#: The machine-file table that turns the digest on: ``hour_utc`` (0-23).
TABLE: Final = 'hpc_digest'
#: The dated history, beside the machine file.
STORE_NAME: Final = 'hpc-digest.jsonl'
#: The account's quota, read where its login lands: GPFS first, else Linux ``quota -w``.
QUOTA_COMMAND: Final = (
    '/usr/lpp/mmfs/bin/mmlsquota 2>/dev/null || mmlsquota 2>/dev/null || quota -w 2>/dev/null || true'
)


@dataclass(frozen=True)
class Account:
    """One account's day as the digest reads it; *why* is set when it could not be read."""

    name: str
    role: str = ''
    usage: Mapping[str, Any] | None = None
    quota_use: Mapping[str, Any] | None = None
    budget: Mapping[str, Any] | None = None
    why: str = ''
    source: str = 'card'


def store_path() -> Path:
    """The digest history of this host, beside its machine file."""
    return config_path().parent / STORE_NAME


def read_rows(path: Path) -> list[dict[str, Any]]:
    """Every row of *path*, oldest first; an unreadable line is skipped, an absent file is no rows."""
    try:
        text = path.read_text(encoding='utf-8')
    except OSError:
        return []
    rows = []
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def due(rows: Sequence[Mapping[str, Any]], now: datetime, hour: int) -> bool:
    """Whether *now* is at or past *hour* UTC and no row of today's UTC date was sent."""
    today = now.astimezone(UTC).date().isoformat()
    return now.astimezone(UTC).hour >= hour and not any(r.get('day') == today and r.get('sent') for r in rows)


def from_cards(cards: Sequence[HostCard]) -> list[Account]:
    """The serving cluster accounts' days, off their cards: a card with no ``usage`` fact is a box, not an account."""
    return [
        Account(card.host, card.role, card.facts.get('usage'), card.facts.get('quota_use'))
        for card in cards
        if isinstance(card.facts.get('usage'), Mapping)
    ]


def _budget(run: Runner, grant: Grant, today: date) -> dict[str, Any] | None:
    if not grant.billed or grant.budget is None:
        return None
    budget = grant.budget
    since, until = date.fromisoformat(budget.since), date.fromisoformat(budget.until)
    spent, committed = spent_and_committed(run(ledger_command(grant, today=today), None))
    return {
        'core_hours': budget.core_hours,
        'spent': round(spent, 1),
        'committed': round(committed, 1),
        'window': round(min(max((today - since).days / (until - since).days, 0.0), 1.0), 4),
        'until': budget.until,
    }


def read_grant(
    grant: Grant, today: date, *, served: Account | None = None, connect: Callable[[Grant], Runner] = runner_for
) -> Account:
    """*grant*'s day over its own login hosts: the one ``sacct`` read, its quota, its budget; ``why`` on failure.

    A *served* account (its card already carries its day) is read for its budget only, and only when billed.
    """
    name = f'{grant.cluster_name}/{grant.user}' if grant.cluster_name else grant.user
    try:
        if served is not None:
            billed = grant.billed and grant.budget is not None
            return replace(served, budget=_budget(connect(grant), grant, today)) if billed else served
        run = connect(grant)
        usage = hpcusage.parse(run(hpcusage.COMMAND, None)).summary()
        quota = run(QUOTA_COMMAND, None)
        return Account(
            name,
            grant.role,
            usage,
            hpcusage.quota_use(parse_mmlsquota(quota) or parse_quota(quota)),
            _budget(run, grant, today),
            source='ssh',
        )
    except (OSError, RuntimeError, ValueError) as why:  # Unreachable, AccessRefused, a refused TOTP session
        if served is not None:
            return replace(served, budget={'why': ' '.join(str(why).split())[:160] or type(why).__name__})
        return Account(name, grant.role, why=' '.join(str(why).split())[:160] or type(why).__name__, source='ssh')


def _pct(value: object) -> str:
    return f'{float(value) * 100:.0f}%' if isinstance(value, (int, float)) else 'n/a'


def _line(one: Account, before: Mapping[str, Any]) -> str:
    if one.why:
        return f'{one.name}: not read: {one.why}'
    usage = one.usage or {}
    states = usage.get('states', {})
    core = float(usage.get('core_hours') or 0.0)
    was = before.get(one.name, {}).get('core_hours') if isinstance(before.get(one.name), Mapping) else None
    delta = f' ({core - float(was):+.1f})' if isinstance(was, (int, float)) else ''
    bad = ' '.join(f'{k.lower()} {states.get(k, 0)}' for k in ('FAILED', 'OUT_OF_MEMORY', 'TIMEOUT') if states.get(k))
    quota = one.quota_use or {}
    text = (
        f'{one.name}{f" [{one.role}]" if one.role else ""}: {usage.get("jobs", 0)} jobs, {core:.1f} core-h{delta}, '
        f'CPU eff {_pct(usage.get("cpu_efficiency"))}; {bad or "no failures"}; '
        f'storage {_pct(quota.get("bytes"))}, files {_pct(quota.get("files"))}'
    )
    if (budget := one.budget) and 'why' in budget:
        text += f'; budget not read: {budget["why"]}'
    elif budget:
        used = budget['spent'] + budget['committed']
        text += (
            f'; budget {budget["spent"]:.0f}+{budget["committed"]:.0f}/{budget["core_hours"]:g} core-h '
            f'({used / budget["core_hours"]:.0%} used, {budget["window"]:.0%} of window to {budget["until"]})'
        )
    return text


def render(day: str, accounts: Sequence[Account], previous: Mapping[str, Any], *, host: str = '') -> Notice:
    """The ONE message of *day*: a line per account, core-hours against *previous* (the last sent day's rows)."""
    total = sum(float((one.usage or {}).get('core_hours') or 0.0) for one in accounts if not one.why)
    return Notice(
        title=f'HPC usage {day}',
        severity=Severity.INFO,
        host=host,
        value=f'{total:.1f} core-h in 24 h over {sum(not one.why for one in accounts)}/{len(accounts)} accounts',
        findings=tuple(_line(one, previous) for one in accounts) or ('no HPC account is declared or serving',),
        findings_title='Accounts (last 24 h; delta vs the last sent day)',
    )


@dataclass
class Sent:
    """What one attempt did: the channels' names and outcomes only."""

    sent: bool
    channels: list[dict[str, Any]] = field(default_factory=list)


def digest(
    accounts: Sequence[Account],
    *,
    now: datetime,
    path: Path,
    send: Callable[[Notice], list[Delivery]],
    host: str = '',
) -> Sent:
    """Render, send and append today's row to *path*; the row is written whether or not a channel took it."""
    rows = read_rows(path)
    sent_before = [row for row in rows if row.get('sent')]
    previous = sent_before[-1].get('accounts', {}) if sent_before else {}
    day = now.astimezone(UTC).date().isoformat()
    try:
        results = send(render(day, accounts, previous, host=host))
    except (OSError, ValueError) as why:  # a transport that raised is a failed send, recorded like any other
        results = [Delivery('send', ok=False, detail=type(why).__name__)]
    outcome = Sent(
        bool(results) and any(one.ok for one in results), [{'channel': d.channel, 'ok': d.ok} for d in results]
    )
    row = {
        'day': day,
        'at': now.astimezone(UTC).isoformat(),
        'sent': outcome.sent,
        'channels': outcome.channels,
        'accounts': {
            one.name: {k: v for k, v in asdict(one).items() if k != 'name'}
            | {'core_hours': (one.usage or {}).get('core_hours')}
            for one in accounts
        },
    }
    lines = [json.dumps(r, sort_keys=True) for r in [*rows, row]]
    durable_text(path, '\n'.join(lines) + '\n')
    return outcome


def step(
    cards: Sequence[HostCard],
    *,
    say: Callable[[str], None],
    now: datetime | None = None,
    table: Mapping[str, Any] | None = None,
    path: Path | None = None,
    send: Callable[[Notice], list[Delivery]] | None = None,
    grants: Callable[[], Sequence[Grant]] | None = None,
    read: Callable[..., Account] = read_grant,
) -> Sent | None:
    """The poller tick's digest: ``None`` when undeclared or not due; else what the attempt did (said either way).

    Only the poller-lease holder calls this (:func:`dev_lab.dev.forgeservesteps.repo_wide`).
    """
    table = section(TABLE) if table is None else table
    if 'hour_utc' not in table:
        return None
    now = now or datetime.now(UTC)
    path = path or store_path()
    if not due(read_rows(path), now, int(table['hour_utc'])):
        return None
    served = {one.name.rpartition('/')[2]: one for one in from_cards(cards)}  # a card is <cluster>/<account>
    try:
        declared = list((grants or (lambda: load_grants().grants))())
    except (OSError, RuntimeError, ValueError) as why:
        declared = []
        say(f'[serve] hpc digest: no [[hpc.grant]] read here, serving accounts only: {why}')
    today = now.astimezone(UTC).date()
    by_user = {grant.user: grant for grant in declared}  # one read per account, whichever grant names it first
    accounts = [read(by_user[user], today, served=one) if user in by_user else one for user, one in served.items()]
    accounts += [read(grant, today) for user, grant in by_user.items() if user not in served]
    outcome = digest(
        accounts, now=now, path=path, send=send or Notifier({'alerts': section('alerts')}).send, host=host_label()
    )
    told = ', '.join(f'{c["channel"]} {"ok" if c["ok"] else "FAILED"}' for c in outcome.channels) or 'no channel'
    if outcome.sent:
        say(f'[serve] hpc digest sent for {len(accounts)} account(s): {told}')
    else:
        say(f'[serve] ALARM hpc digest NOT sent ({told}); recorded in {path.name}, retried next poller tick')
    return outcome
