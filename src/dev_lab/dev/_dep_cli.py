"""The ``dep`` door's argv surface: what it accepts, what it refuses to name, and how a held environment is answered.

Split from :mod:`dev_lab.dev.dep` so the door keeps the mutation and this keeps the spelling; a held answer
either refuses or queues the bootstrap in :mod:`dev_lab.dev._dep_pending`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from lab_commons.log import emit

from dev_lab.dev import _dep_pending


def parser(description: str) -> argparse.ArgumentParser:
    """The door's argv: one target, its extras and overlays, and how a held environment is answered."""
    parser = argparse.ArgumentParser(description=description)
    targets = parser.add_mutually_exclusive_group()
    targets.add_argument('--bootstrap', type=Path)
    targets.add_argument('--root', type=Path)
    targets.add_argument('--lock-upgrade', nargs='?', const=Path(), type=Path, metavar='ROOT')
    parser.add_argument('--sync', action='store_true')
    parser.add_argument('--extra', action='append')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--upgrade-package', action='append', default=[])
    parser.add_argument('--local', action='append', default=[], metavar='NAME', help='overlay this sibling for one run')
    parser.add_argument(
        '--when-free', action='store_true', help='held: queue it for the first free door run (_dep_pending), exit 0'
    )
    return parser


def argv_error(args: argparse.Namespace, *, locking: bool) -> str:
    """Why *args* name no change this door makes, else ``''``."""
    if args.bootstrap is None and not locking and not args.sync and not args.upgrade_package:
        return 'use --bootstrap PATH, --lock-upgrade [ROOT], --sync, or --upgrade-package NAME'
    if args.when_free and args.bootstrap is None:
        return '--when-free queues a --bootstrap PATH only'
    return ''


def held(args: argparse.Namespace, root: Path, prefix: Path, held: Exception) -> int:
    """A held environment: refused (1), or with ``--when-free`` queued for the first free door run (0)."""
    if not args.when_free or args.dry_run:
        emit(f'REFUSED: {held}')
        return 1
    queued = ['--bootstrap', str(root)]
    queued += [word for extra in args.extra or () for word in ('--extra', extra)]
    queued += [word for local in args.local for word in ('--local', local)]
    path = _dep_pending.request(prefix, queued)
    emit(
        f'QUEUED: {held}\nThe request waits in {path}; the first hook launch that finds {prefix} free '
        'performs it. A long-lived watcher from it exits at its next poll; re-arm it then.'
    )
    return 0
