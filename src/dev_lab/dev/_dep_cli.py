"""The ``dep`` door's argv surface: what it accepts and what it refuses to name.

Split from :mod:`dev_lab.dev.dep` so the door keeps the mutation and this keeps the spelling.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def parser(description: str) -> argparse.ArgumentParser:
    """The door's argv: one target, its extras and overlays."""
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
    return parser


def argv_error(args: argparse.Namespace, *, locking: bool) -> str:
    """Why *args* name no change this door makes, else ``''``."""
    if args.bootstrap is None and not locking and not args.sync and not args.upgrade_package:
        return 'use --bootstrap PATH, --lock-upgrade [ROOT], --sync, or --upgrade-package NAME'
    return ''
