"""THE STATUS COMMAND -- ``python -m lab_commons.dev.forge queue``: the work queue, runs in flight, hosts, starvation.

Read-only, and read from the forge, so any machine with a forge credential sees what a cluster login
node sees: every waiting candidate with its class, value, expected cost, score, wait and what blocks it
(:mod:`lab_commons.dev.forgeschedule`); every run in flight with its owner and the live progress its
claim carries (:class:`lab_commons.dev.forgeclaim.Claim`); every host card, stale ones flagged
(:mod:`lab_commons.dev.forgehosts`) with its supply and what runs on it; every live reservation
(:mod:`lab_commons.compute.ledger`), a refused writer's flagged; and every candidate starved past its
class's bound. A candidate EVERY live host serving it refuses to admit says so, naming each host and the
resources it lacks there (``no host admits it -- box-g lacking cpu; ada/alice lacking mem_gb``). It fetches
``origin`` first so the refs it ranks are the forge's, and posts nothing.
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

from lab_commons.compute import ledger
from lab_commons.compute.learned import learned
from lab_commons.compute.model import REQUEST, Candidate, Ranked, expected_cost, rank, starved
from lab_commons.config import section
from lab_commons.dev.forge import NoCredential, Transport, UnreadableRemote, fetch_origin, https_transport
from lab_commons.dev.forgeclaim import CLAIMED, DONE, Claim, assess, forge_now
from lab_commons.dev.forgehosts import HostCard
from lab_commons.dev.forgeprovides import present, unserved
from lab_commons.dev.forgeschedule import NO_HOST, NOT_ADMITTED, candidates, host_weights, load_schedule, repo_name
from lab_commons.dev.forgestatus import Status, status_history
from lab_commons.dev.forgework import Client, ForgeCallFailed, client_for
from lab_commons.dev.lanepolicy import load_policy
from lab_commons.dev.platformparts import derived, origin_url
from lab_commons.hpc.needsets import Vocabulary, declared_at, needs_of
from lab_commons.log import emit

#: How a stale card reads: the host stopped publishing, and these are why a host stops.
_STALE = '  STALE (no tick published: host down, cron line gone, or its forge credential refused -- see its cron log)'

__all__ = ['main', 'render', 'view']


def _row(item: Ranked) -> dict[str, Any]:
    return {
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
    schedule, repo = load_schedule(root), repo_name(client)
    histories: dict[str, tuple[Status, ...]] = {}  # one read per sha: it derives the parts and assesses each

    def history(sha: str) -> tuple[Status, ...]:
        if sha not in histories:
            histories[sha] = status_history(client, sha) if sha else ()
        return histories[sha]

    found = candidates(
        root, client, repo=repo, parts=lambda sha: derived(history(sha)), schedule=schedule,
        policy=load_policy(root), now=now,
    )  # fmt: skip
    book = ledger.read(client)
    cards = book.cards
    nobody = Claim('', '', now)
    waiting: list[Candidate] = []
    in_flight: list[dict[str, Any]] = []
    for one in found:
        if one.kind != REQUEST:
            state, holder = assess(history(one.sha), one.platform, me=nobody, now=now)
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
    cost = expected_cost(learned(origin_url(root)), schedule.prior_cost_h)
    read: dict[str, tuple[Vocabulary, str]] = {}

    def declared(sha: str) -> tuple[Vocabulary, str]:
        return read.setdefault(sha, declared_at(root, sha) if sha else (Vocabulary(), ''))

    weights = host_weights(section('schedule'))
    ranked = [
        dataclasses.replace(
            item,
            blocked=declared(item.candidate.sha)[1] or _why(item.candidate, cards, now),
        )
        for item in rank(waiting, {repo: schedule}, now, cost_h={repo: cost}, weights=weights)
    ]
    return {
        'now': now.isoformat(),
        'queue': [_row(item) for item in ranked],
        'in_flight': in_flight,
        'hosts': [
            {
                **dataclasses.asdict(card),
                'holds': list(card.holds),
                'alarms': list(card.alarms),
                'running': list(card.running),
                'preempted': list(card.preempted),
                'reservations': [dict(r) for r in card.reservations],
                'stale': card.stale(now),
            }
            for card in cards
        ],
        'reservations': [one.row() for one in book.entries if now < one.reservation.until],
        'starved': [_row(item) for item in starved(ranked, {repo: schedule})],
    }


def _why(candidate: Candidate, cards: Sequence[HostCard], now: datetime) -> str:
    try:
        needed = needs_of(candidate.platform)
    except ValueError as why:
        return str(why)
    live = [card for card in cards if not card.stale(now)]
    unclaimable = unserved(needed, [present(card.platform, card.provides) for card in live])
    if unclaimable:
        return unclaimable
    serving = [card for card in live if needed <= present(card.platform, card.provides)]
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


def render(view_: Mapping[str, Any]) -> list[str]:
    """The view as the lines a human reads."""
    lines = [f'forge time {view_["now"]}', '', 'queue (highest score first):']
    lines.append(f'  {"class":<12} {"value":>8} {"cost_h":>7} {"score":>9} {"wait_h":>7}  candidate -- blocked')
    lines += [
        f'  {r["class"]:<12} {r["value"]:>8.1f} {r["cost_h"]:>7.2f} {r["score"]:>9.2f} {r["wait_h"]:>7.1f}  '
        f'{r["candidate"]} -- {r["blocked"] or "claimable"}'
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
                f'supply {_amounts(h["supply"])}  holds {", ".join(h["holds"]) or "nothing"}'
            ),
            *([f'    running {", ".join(h["running"])}'] if h.get('running') else []),
            *([f'    PREEMPTED {", ".join(h["preempted"])}'] if h.get('preempted') else []),
            *(f'    ALARM {a["kind"]}: {a["subject"]} -- {a["body"]}' for a in h.get('alarms', ())),
        )
    ] or ['  (no host has published a card)']
    lines += ['', 'reservations:']
    lines += [
        f'  {r["id"]}  {r["scope"]}  {_amounts(r["resources"])}  for {r["for"]}  until {r["until"]}  by {r["by"]}'
        + (f'  REFUSED: {r["refused"]}' if r['refused'] else '')
        for r in view_.get('reservations', ())
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
    parser = argparse.ArgumentParser(prog='lab_commons.dev.forge queue', description=__doc__.splitlines()[0])
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
