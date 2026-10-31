"""WHAT A CLUSTER RUN LEARNED, PUBLISHED ON THE FORGE -- read by ``forge run show <sha>``, never over ssh.

User ruling 2026-10-31: never depend on ssh to learn what a verdict did; the cluster being unreachable from a
workstation is NORMAL. A run's status only says ``running 40/93 done 12/93``; which tests a round failed, timed
out or lost to the OOM killer -- and why -- lived in the round's streams under ``~/ci/trees/<sha>/.lab-ci``.

ONE SOURCE, TWO STAGES. Each folded round carries its losses (``rounds[n]['lost']``, written by
:func:`lab_commons.hpc.records.round_losses`): every failed, out-of-memory, timed-out or killed id with its kind,
peak MB, wall seconds and why. While the run is in flight the owner (:mod:`dev_lab.dev.forgerun`) posts those
rounds to the records home as ONE mutable ledger, :func:`ledger_name`, each time a new round folds. When the run
ends its record (``run-<sha>-<part>-<req>.json.gz``) carries the same rounds plus its final cells, and the reader
takes the record over the ledger. Both names carry the sha, so the records prune keeps and drops them together.

THE READER (:func:`show`) needs a forge credential and nothing else: no ssh, no cluster, no tree.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from lab_commons.hpc.pytest_item import badness
from lab_commons.log import emit

from dev_lab.dev.forge import Transport, https_transport
from dev_lab.dev.forgerecords import listing, replace_named
from dev_lab.dev.forgework import Client, ForgeCallFailed, client_for

__all__ = ['LEDGER', 'failing', 'ledger', 'ledger_name', 'main', 'posted_rounds', 'show']

#: The ``<req>`` slot of the in-flight ledger's name: a record name, so it is pruned with its sha.
LEDGER: Final = 'rounds'

_NAME: Final = re.compile(r'^run-(?P<sha>[0-9a-f]{40})-(?P<part>[a-z]+)-(?P<req>[^/]+)\.json\.gz$')

#: :func:`badness` of an answer as declared.
_AS_DECLARED: Final = 2

#: A resource skip is an answer as declared for this host, never a failure of the run.
_NOT_FAILING: Final = frozenset({('unavailable', 'resource')})


def ledger_name(sha: str, part: str) -> str:
    """The one in-flight ledger of *sha*'s *part*: ``run-<sha>-<part>-rounds.json.gz``."""
    return f'run-{sha}-{part}-{LEDGER}.json.gz'


def posted_rounds(rounds: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The FOLDED rounds of a run state (those carrying ``lost``), as the ledger publishes them."""
    return [
        {'round': n, 'job_ids': list(r.get('job_ids', ())), 'lost': list(r['lost'])}
        for n, r in enumerate(rounds)
        if 'lost' in r
    ]


def ledger(client: Client, sha: str, part: str, rounds: Sequence[Mapping[str, Any]]) -> None:
    """Replace *sha*'s *part* ledger on the records home with its folded *rounds*."""
    body = {'sha': sha, 'part': part, 'rounds': posted_rounds(rounds)}
    data = gzip.compress(json.dumps(body, sort_keys=True).encode('utf-8'), mtime=0)
    replace_named(client, ledger_name(sha, part), data)


def failing(cells: Mapping[str, Mapping[str, Any]]) -> list[tuple[str, str, str]]:
    """``(id, status, why)`` of every cell that is not an answer as declared, ids sorted."""
    found = []
    for node, plain in sorted(cells.items()):
        reason = plain.get('reason') or {}
        if badness(plain) == _AS_DECLARED or (plain['status'], reason.get('kind')) in _NOT_FAILING:
            continue
        found.append((node, str(plain['status']), str(reason.get('text', ''))))
    return found


def _loss_line(one: Mapping[str, Any]) -> str:
    peak = 'peak ?' if one.get('peak_mb') is None else f'peak {one["peak_mb"]:.0f} MB'
    wall = 'wall ?' if one.get('wall_s') is None else f'wall {one["wall_s"]:.0f} s'
    return f'    {one["kind"]:<13} {one["id"]}  ({peak}, {wall}) {one.get("why", "")}'.rstrip()


def _part_lines(part: str, body: Mapping[str, Any], *, final: bool) -> list[str]:
    lines = [f'{part}: {"finished" if final else "in flight"}']
    for one in posted_rounds(body.get('rounds', ())) if final else body.get('rounds', ()):
        lost = one['lost']
        lines.append(f'  round {one["round"]}: {len(lost)} lost' if lost else f'  round {one["round"]}: clean')
        lines += [_loss_line(loss) for loss in lost]
    if final:
        bad = failing(body.get('cells', {}))
        lines.append(f'  final: {len(bad)} failing' if bad else '  final: no failing id')
        lines += [f'    {status:<13} {node}  {why}'.rstrip() for node, status, why in bad]
    return lines


def show(client: Client, sha: str) -> list[str]:
    """What *sha*'s cluster runs published, per part: each round's losses, and once finished the failing ids.

    A part's newest record is final and wins over its ledger; a part with only a ledger is in flight.
    """
    newest: dict[str, tuple[bool, str]] = {}
    for item in listing(client):  # oldest first, so the last of a kind is the newest
        found = _NAME.match(item.name)
        if not found or found['sha'] != sha:
            continue
        final = found['req'] != LEDGER
        if final or not newest.get(found['part'], (False, ''))[0]:
            newest[found['part']] = (final, item.url)
    if not newest:
        return [f'{sha[:12]}: nothing published on the forge yet']
    lines = [f'{sha[:12]}:']
    for part, (final, url) in sorted(newest.items()):
        body = json.loads(gzip.decompress(client.download(url)).decode('utf-8'))
        lines += _part_lines(part, body, final=final)
    return lines


def main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    transport: Transport = https_transport,
) -> int:
    """``run show <sha>``: print what the cluster published for *sha*; exit 1 when the forge cannot be read."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.forge run', description=__doc__.splitlines()[0])
    verbs = parser.add_subparsers(dest='verb', required=True)
    shown = verbs.add_parser('show', help="each round's lost ids and the final failing ids, from the forge only")
    shown.add_argument('sha', help='the 40-hex commit')
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    root = Path.cwd() if cwd is None else cwd
    try:
        client = client_for(root, env=env, transport=transport)
        for line in show(client, args.sha.lower()):
            emit(line)
    except ForgeCallFailed as failed:
        emit(f'[forge] {failed}', err=True)
        return 1
    except (OSError, ValueError) as failed:
        emit(f'[run] {failed}', err=True)
        return 1
    return 0
