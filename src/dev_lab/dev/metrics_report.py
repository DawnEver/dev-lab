"""THE TOOLCHAIN'S METRICS, REPORTED: every family repository over one window, and the metrics CLI.

``python -m dev_lab.dev.metrics_report [--since T] [--until T] [--days N] [--json]`` reads every repository of
the family -- the machine file's ``[serve] repos`` under its ``root`` (:func:`family`) -- over one window with
both bounds; ``record <kind> ...`` appends one line through :func:`dev_lab.dev.metrics.record` (the agent guard
engine calls it). The figures are :mod:`dev_lab.dev.metrics_compute`'s.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from lab_commons.config import config_path, section
from lab_commons.log import emit

from dev_lab.dev.forgepulls import pages
from dev_lab.dev.forgework import client_for
from dev_lab.dev.lanepolicy import policy_at
from dev_lab.dev.metrics import KINDS, read, record, repo_of
from dev_lab.dev.metrics_compute import Metrics, compute, landings

__all__ = ['family', 'main']


def family(table: Mapping[str, Any] | None = None) -> list[Path]:
    """Every family checkout: the machine file's ``[serve] repos`` under its ``root`` (*table*, default that table)."""
    table = section('serve') if table is None else table
    repos, root = table.get('repos'), table.get('root')
    if not (isinstance(repos, list) and repos and isinstance(root, str)):
        msg = f'no [serve] repos and root in {config_path()}: the family is declared there (`workstation deploy`)'
        raise ValueError(msg)
    return [Path(root) / name for name in repos]


def _cli_record(args: argparse.Namespace) -> int:
    record(
        args.kind,
        root=Path.cwd(),
        repo=args.repo or repo_of(Path.cwd()),
        rule=args.rule,
        reason=args.reason,
        vcs_ref_head_revision=args.sha,
    )
    return 0


def _integration_ref(root: Path) -> str:
    """``origin/<integration>`` as *root*'s ``HEAD`` declares it; a ``HEAD`` declaring none is refused by name."""
    return f'origin/{policy_at(root, "HEAD").integration}'


def _measure(root: Path, *, since: datetime, until: datetime) -> Metrics:
    client = client_for(root)
    pulls = pages(client, f'{client.repo}/pulls', {'state': 'all'})
    landed = landings(root, _integration_ref(root), since=since, until=until)
    records = {kind: read(kind, root=root) for kind in KINDS}
    return compute(repo_of(root), records, pulls, since=since, until=until, landings=landed)


def _cli_read(args: argparse.Namespace) -> int:
    until = args.until or datetime.now(UTC)
    since = args.since or until - timedelta(days=args.days)
    found = {root.name: asdict(_measure(root, since=since, until=until)) for root in family()}
    if args.json:
        emit(json.dumps(found, indent=2))
        return 0
    emit(f'window [{since.isoformat()}, {until.isoformat()})')
    names = list(found)
    emit(f'{"":<30}' + ''.join(f'{name:>17}' for name in names))
    for field in next(iter(found.values()), {}):
        if field in {'repo', 'since', 'until'}:
            continue
        cells = [found[name][field] for name in names]
        shown = ['-' if v is None else round(v, 3) if isinstance(v, float) else v for v in cells]
        emit(f'{field:<30}' + ''.join(f'{cell!s:>17}' for cell in shown))
    return 0


def _instant(text: str) -> datetime:
    when = datetime.fromisoformat(text)
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m dev_lab.dev.metrics [--since T] [--until T] [--days N] [--json]``; ``record <kind> ...`` appends."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.metrics_report', description=__doc__.splitlines()[0])
    parser.add_argument('--since', type=_instant, help='the window opens here (ISO 8601); default --until - --days')
    parser.add_argument('--until', type=_instant, help='the window closes here, exclusive (ISO 8601); default now')
    parser.add_argument('--days', type=float, default=30.0, help='the window length when --since is not given')
    parser.add_argument('--json', action='store_true')
    verbs = parser.add_subparsers(dest='verb')
    one = verbs.add_parser('record', help='append one line (the agent guard engine calls this)')
    one.add_argument('kind', choices=KINDS)
    one.add_argument('--repo', default='', help="the repository's URL; this checkout's origin by default")
    one.add_argument('--rule', default='')
    one.add_argument('--reason', default='')
    one.add_argument('--sha', default='')
    args = parser.parse_args(argv)
    return _cli_record(args) if args.verb == 'record' else _cli_read(args)


if __name__ == '__main__':
    raise SystemExit(main())
