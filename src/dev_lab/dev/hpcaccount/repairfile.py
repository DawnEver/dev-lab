"""``python -m dev_lab.dev.hpcaccount repair-machine-file [--config <path>] [--apply] [--backups <dir>]``.

THE ONE-TIME MIGRATION of a machine file holding several ``[hpc]`` tables (FORMATS-MIGRATE-ONCE). Before #878,
``grant()`` APPENDED this account's ``[hpc]`` slice below the one the render wrote, so every read raised "Cannot
declare ('hpc',) twice" -- and since the deploy reads the file before the fixed ``grant()`` runs, a redeploy could
never repair it (measured 2026-11-21 on two research accounts). The reader keeps the current shape and refuses
this one naming :data:`~dev_lab.dev.hpcaccount.spec.REPAIR_DOOR`; this verb migrates it.

The repair re-renders the file from its own declarations: each ``[hpc]`` group (a bare ``[hpc]`` header and the
``[hpc.*]`` / ``[[hpc.*]]`` tables below it) is read on its own and the groups are merged key by key, the LATER
winning -- the appended slice is the passed declaration, exactly what the fixed ``grant()`` merges over the file's
other keys -- into ONE ``[hpc]`` table; every other table is kept as written. A dry run by default; ``--apply``
backs the file up first (``--backups``, default ``output/logs/<yy>/<mm>/<dd>/hpcaccount``) and replaces it
atomically. Idempotent: a file that reads needs no repair and is never written. A file broken any other way is
refused untouched -- this door migrates one known shape, nothing else.
"""

from __future__ import annotations

import argparse
import re
import tomllib
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from lab_commons.config import config_path
from lab_commons.log import emit

from dev_lab.dev.backedup import replace_backed_up
from dev_lab.dev.hpcaccount.spec import render_grant, without_hpc

__all__ = ['main', 'repaired']

#: A TOML table or array-of-tables header; group 1 is the table's dotted name.
_HEADER: Final = re.compile(r'^\s*\[\[?\s*([^\]]+?)\s*\]\]?\s*(#.*)?$')


def _hpc_groups(text: str) -> list[str]:
    """The ``[hpc]`` groups of *text*: each bare ``[hpc]`` starts one; its ``[hpc.*]`` tables join it."""
    groups: list[list[str]] = []
    inside = False
    for line in text.splitlines():
        if header := _HEADER.match(line):
            name = header.group(1)
            inside = name == 'hpc' or name.startswith('hpc.')
            if name == 'hpc' or (inside and not groups):
                groups.append([])
        if inside:
            groups[-1].append(line)
    return ['\n'.join(group) + '\n' for group in groups]


def repaired(text: str) -> str | None:
    """*text* with its several ``[hpc]`` groups merged into one (later keys win); ``None`` when it already reads.

    Raises:
        tomllib.TOMLDecodeError: *text* is broken some other way, which this migration does not repair.

    """
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        pass
    else:
        return None
    merged: dict[str, Any] = {}
    for group in _hpc_groups(text):
        merged |= tomllib.loads(group).get('hpc', {})
    fixed = without_hpc(text) + render_grant(merged)
    tomllib.loads(fixed)  # anything else broken is refused, never written
    return fixed


def main(argv: Sequence[str]) -> int:
    """Repair the machine file once: a dry run unless ``--apply``; 2 when it is broken some other way."""
    parser = argparse.ArgumentParser(
        prog='dev_lab.dev.hpcaccount repair-machine-file', description=__doc__.split('\n')[2]
    )
    parser.add_argument('--config', type=Path, default=None, help='the machine file (default: this account its own)')
    parser.add_argument('--apply', action='store_true', help='back the file up, then replace it (default: dry run)')
    parser.add_argument('--backups', type=Path, default=None, help='where the backup goes')
    args = parser.parse_args(list(argv))
    path = args.config or config_path()
    try:
        fixed = repaired(path.read_text(encoding='utf-8')) if path.is_file() else None
    except tomllib.TOMLDecodeError as broken:
        emit(
            f'repair-machine-file: refused -- {path} is not TOML for another reason ({broken}); it is unchanged',
            err=True,
        )
        return 2
    if fixed is None:
        emit(f'repair-machine-file: {path} reads as it is -- nothing to repair')
        return 0
    if not args.apply:
        emit(f'[dry-run] {path} would become (re-run with --apply to write it, after a backup):\n{fixed}')
        return 0
    backups = args.backups or Path('output/logs') / f'{datetime.now(UTC):%y/%m/%d}' / 'hpcaccount'
    backup = replace_backed_up(path, fixed, backups)
    emit(f'repair-machine-file: {path} now holds one [hpc]; the previous file is {backup}')
    return 0
