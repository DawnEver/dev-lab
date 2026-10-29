"""THE STATUS COMMAND -- ``python -m dev_lab.dev.forge queue``: the work queue, runs in flight, hosts, starvation.

Read-only, and read from the forge, so any machine with a forge credential sees what a cluster login
node sees: every waiting candidate with its class, value, expected cost, score, wait and what blocks it
(:mod:`dev_lab.dev.forgeschedule`); every run in flight with its owner and the live progress its
claim carries (:class:`dev_lab.dev.forgeclaim.Claim`); every host card, stale ones flagged
(:mod:`dev_lab.dev.forgehosts`) with its supply and what runs on it; and every candidate starved
past its class's bound. A candidate EVERY live host serving it refuses to admit says so, naming each host and the
resources it lacks there (``no host admits it -- box-g lacking cpu; ada/alice lacking mem_gb``). It fetches
``origin`` first so the refs it ranks are the forge's, and posts nothing.

It also lists every undeclared origin branch idle past its grace (:mod:`dev_lab.dev.branchprune`):
``deletable`` (merged, the repo has not opted into pruning), ``delete`` (any serving host prunes it on
its next tick) or ``stale`` (unmerged: alarmed, never deleted).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from lab_commons.compute.learned import learned
from lab_commons.compute.model import REQUEST, Candidate, Ranked, Schedule, expected_cost, rank, starved
from lab_commons.compute.priority import Priority
from lab_commons.compute.serves import EVERY, Serves
from lab_commons.config import section
from lab_commons.hpc.declared import OutdatedKit
from lab_commons.hpc.needsets import declared_at, needs_of
from lab_commons.log import emit

from dev_lab.dev.branchprune import listing
from dev_lab.dev.branchset import BranchSetNotDeclared
from dev_lab.dev.forge import NoCredential, Transport, UnreadableRemote, fetch_origin, https_transport
from dev_lab.dev.forgecarry import docs_only, part_standing
from dev_lab.dev.forgeclaim import CLAIMED, DONE, Claim, assess, forge_now
from dev_lab.dev.forgecoalesce import behind
from dev_lab.dev.forgehosts import HostCard, read_cards
from dev_lab.dev.forgeprovides import supplied, unserved
from dev_lab.dev.forgerequest import UndeclaredRequest, declared_request, request_context
from dev_lab.dev.forgescarce import unreached
from dev_lab.dev.forgeschedule import (
    NO_HOST,
    NOT_ADMITTED,
    candidates,
    host_weights,
    load_schedule,
    repo_name,
)
from dev_lab.dev.forgesettled import SettledHistories
from dev_lab.dev.forgestatus import CommitStatus
from dev_lab.dev.forgework import Client, ForgeCallFailed, client_for
from dev_lab.dev.lanepolicy import load_policy
from dev_lab.dev.platformparts import derived, origin_url, part_context

#: How a stale card reads: the host stopped publishing, and these are why a host stops.
_STALE = '  STALE (no tick published: host down, cron line gone, or its forge credential refused -- see its cron log)'

__all__ = ['forge_queue', 'main', 'render', 'unadmitted', 'view']


def _row(item: Ranked, favoured: Sequence[str] = ()) -> dict[str, Any]:
    return {
        'priority': list(favoured),
        'candidate': item.candidate.key,
        'class': item.candidate.kind,
        'value': round(item.value, 2),
        'cost_h': round(item.cost_h, 3),
        'score': round(item.score, 3),
        'wait_h': round(item.wait_h, 2),
        'blocked': item.blocked,
    }


def view(root: Path, client: Client, *, fetch: Callable[[Path], None] = fetch_origin) -> dict[str, Any]:
    """The whole picture as data: ``queue``, ``in_flight``, ``hosts``, ``starved`` (module docstring)."""
    fetch(root)
    now = forge_now(client)
    schedule = load_schedule(root)
    cards = read_cards(client)
    ranked, in_flight = forge_queue(root, client, cards, now=now, schedule=schedule)
    repo = repo_name(client)
    live = [card for card in cards if not card.stale(now)]

    def row(item: Ranked) -> dict[str, Any]:
        return _row(item, [card.host for card in live if card.favours(item.candidate)])

    try:
        branches = [dataclasses.asdict(row) for row in listing(root, client, now=now)]
    except BranchSetNotDeclared as undeclared:  # the queue still reads; the branch rows say why they are absent
        branches = [{'action': 'unread', 'ref': '-', 'sha': '', 'rule': str(undeclared), 'idle_h': 0.0}]
    return {
        'now': now.isoformat(),
        'queue': [row(item) for item in ranked],
        'branches': branches,
        'in_flight': in_flight,
        'hosts': [
            {
                **dataclasses.asdict(card),
                'holds': list(card.holds),
                'alarms': list(card.alarms),
                'running': list(card.running),
                'stale': card.stale(now),
            }
            for card in cards
        ],
        'starved': [row(item) for item in starved(ranked, {repo: schedule})],
    }


def forge_queue(
    root: Path, client: Client, cards: Sequence[HostCard], *, now: datetime, schedule: Schedule
) -> tuple[list[Ranked], list[dict[str, Any]]]:
    """The queue ACROSS hosts, ranked, each waiting candidate blocked by what every live card says; and in flight.

    Fetches nothing: the caller holds origin as fresh as it needs.
    """
    repo = repo_name(client)
    history = SettledHistories(client)  # one read per sha, none once settled (dev_lab.dev.forgesettled)

    policy = load_policy(root)
    found = candidates(
        root, client, repo=repo, parts=lambda sha: derived(history(sha)), schedule=schedule, policy=policy, now=now,
        waived=lambda sha: unreached(root, client, policy.integration, sha, history(sha)),
    )  # fmt: skip
    waiting, in_flight = _standing(found, history, now)
    cost = expected_cost(learned(origin_url(root)), schedule.prior_cost_h)
    read: dict[str, str] = {}

    def refused(one: Candidate) -> str:
        """Why *one* cannot be produced as its sha declares it: a request's producer, a part's vocabulary."""
        if one.kind == REQUEST:
            return _refused(lambda: declared_request(root, one.sha, one.producer, one.paths) and '')
        if one.sha not in read:
            read[one.sha] = _refused(lambda: declared_at(root, one.sha)[1] if one.sha else '')
        return read[one.sha]

    def carried_hold(one: Candidate) -> str:
        """Why *one* is never claimed: its part carries from a docs-only ancestor (DOCS-ONLY-CARRIES)."""
        if one.kind == REQUEST:
            return ''
        carry = docs_only(root, one.sha, part_standing(history, part_context(one.platform), now))
        return carry.hold if carry is not None else ''

    weights = host_weights(section('schedule'))
    ranked = [
        dataclasses.replace(
            item,
            blocked=refused(item.candidate)
            or carried_hold(item.candidate)
            or behind(root, item.candidate, schedule, history, now)
            or _why(item.candidate, cards, now),
        )
        for item in rank(waiting, {repo: schedule}, now, cost_h={repo: cost}, weights=weights)
    ]
    return ranked, in_flight


def unadmitted(blocked: str) -> bool:
    """Whether *blocked*, a reason read across every live card, says NO host can take it (not one host's wait)."""
    return blocked.startswith(NO_HOST)


def _refused(read: Callable[[], str]) -> str:
    """What *read* says refuses a declaration; a reader older than the sha says so, and the sha waits."""
    try:
        return read()
    except (UndeclaredRequest, OutdatedKit) as why:
        return str(why)


def _standing(
    found: Sequence[Candidate], history: Callable[[str], Sequence[CommitStatus]], now: datetime
) -> tuple[list[Candidate], list[dict[str, Any]]]:
    """``(waiting, in flight)``: a part and a request are one job, each assessed in its own context."""
    nobody = Claim('', '', now)
    waiting: list[Candidate] = []
    in_flight: list[dict[str, Any]] = []
    for one in found:
        context = request_context(one.number) if one.kind == REQUEST else part_context(one.platform)
        state, holder = assess(history(one.sha), context, me=nobody, now=now)
        if state == DONE:
            continue
        if state == CLAIMED and holder is not None:
            owner = holder.hpc or holder.machine or '-'
            in_flight.append(
                {'candidate': one.key, 'owner': owner, 'login': holder.login, 'progress': holder.progress}
                | {'until': holder.until.isoformat()}
            )
            continue
        waiting.append(one)
    return waiting, in_flight


def _why(candidate: Candidate, cards: Sequence[HostCard], now: datetime) -> str:
    try:
        needed = needs_of(candidate.platform)
    except ValueError as why:
        return str(why)
    unclaimable = unserved(needed, [supplied(card, now) for card in cards])
    if unclaimable:
        return unclaimable
    serving = [card for card in cards if (has := supplied(card, now)) and needed <= has]  # a stale card has nothing
    skipping = [(card.host, Serves(card.serves, frozenset(card.withholds)).skips(needed)) for card in serving]
    if serving and all(why for _, why in skipping):
        return f'{NO_HOST} claims it -- ' + '; '.join(f'{host} {why}' for host, why in skipping)
    serving = [card for card in serving if not Serves(card.serves, frozenset(card.withholds)).skips(needed)]
    reasons = [(card.host, card.waiting[candidate.key]) for card in serving if candidate.key in card.waiting]
    refused = [(host, why) for host, why in reasons if why.startswith(f'{NOT_ADMITTED}: ')]
    if refused and len(refused) == len(serving):
        named = '; '.join(f'{host} {why.removeprefix(f"{NOT_ADMITTED}: ")}' for host, why in refused)
        return f'{NO_HOST} admits it -- {named}'
    return reasons[0][1] if reasons else ''


def _amounts(resources: Mapping[str, float] | str) -> str:
    if isinstance(resources, str):  # a whole-scope lease: 'all'
        return resources
    return ','.join(f'{name}={amount:g}' for name, amount in sorted(resources.items()))


def _holds(host: Mapping[str, Any]) -> str:
    """What a card holds; a STALE card's claims are unrenewed, so each is retaken once its lease lapses."""
    held = ', '.join(host['holds']) or 'nothing'
    return f'{held} (unrenewed: retaken once its lease lapses)' if host['stale'] and host['holds'] else held


def render(view_: Mapping[str, Any]) -> list[str]:
    """The view as the lines a human reads."""
    lines = [f'forge time {view_["now"]}', '', 'queue (highest score first; * = a host orders it first):']
    lines.append(f'  {"class":<12} {"value":>8} {"cost_h":>7} {"score":>9} {"wait_h":>7}  candidate -- blocked')
    lines += [
        f'  {r["class"]:<12} {r["value"]:>8.1f} {r["cost_h"]:>7.2f} {r["score"]:>9.2f} {r["wait_h"]:>7.1f}  '
        f'{r["candidate"]} -- {r["blocked"] or "claimable"}'
        + (f'  * priority on {", ".join(r["priority"])}' if r.get('priority') else '')
        for r in view_['queue']
    ] or ['  (empty)']
    lines += ['', 'in flight:']
    lines += [
        f'  {r["candidate"]}  {r["owner"]} ({r["login"]})  {r["progress"] or "no progress posted"}'
        for r in view_['in_flight']
    ] or ['  (none)']
    lines += ['', 'hosts:']
    lines += [
        line
        for h in view_['hosts']
        for line in (
            (
                f'  {h["host"]:<20} {h["platform"]:<8} ticked {h["ticked"]}{_STALE if h["stale"] else ""}  '
                f'supply {"none (stale)" if h["stale"] else _amounts(h["supply"])}  holds {_holds(h)}'
            ),
            *([f'    running {", ".join(h["running"])}'] if h.get('running') else []),
            *([f'    priority {Priority.of(h["priority"]).text()}'] if any(h.get('priority', {}).values()) else []),
            *([f'    serves {Serves(h["serves"]).text()}'] if h.get('serves', EVERY) != EVERY else []),
            *(f'    ALARM {a["kind"]}: {a["subject"]} -- {a["body"]}' for a in h.get('alarms', ())),
        )
    ] or ['  (no host has published a card)']
    lines += ['', 'origin branches (undeclared, idle past the grace):']
    lines += [
        f'  {b["action"]:<9} {b["ref"]}  {b["sha"][:12]}  {b["rule"]}, idle {b["idle_h"]:.0f} h'
        for b in view_.get('branches', ())
    ] or ['  (none)']
    lines += ['', 'starved:']
    lines += [f'  {r["candidate"]} waited {r["wait_h"]:.1f} h -- {r["blocked"]}' for r in view_['starved']] or [
        '  (none)'
    ]
    return lines


def main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    transport: Transport = https_transport,
    fetch: Callable[[Path], None] = fetch_origin,
) -> int:
    """``queue [--json]``; exit 1 when the forge cannot be read."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.forge queue', description=__doc__.splitlines()[0])
    parser.add_argument('--json', action='store_true', help='print the whole view as JSON')
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    root = Path.cwd() if cwd is None else cwd
    try:
        built = client_for(root, env=dict(os.environ) if env is None else env, transport=transport)
        seen = view(root, built, fetch=fetch)
    except (ForgeCallFailed, NoCredential, UnreadableRemote, OSError, ValueError) as failed:
        emit(f'[queue] {failed}', err=True)
        return 1
    emit(json.dumps(seen, indent=2) if args.json else '\n'.join(render(seen)))
    return 0
