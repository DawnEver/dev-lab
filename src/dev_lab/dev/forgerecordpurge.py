"""OLD-FORMAT UNIT RESULTS ARE PURGED ONCE -- ``python -m dev_lab.dev.forgerecordpurge``.

A unit result is named ``unit-<unit>-g<generation>-<result>.tar.<ext>`` (:func:`dev_lab.dev.forgeunit.result_name`).
One posted before results were keyed by generation lacks the ``-g<n>-`` key: a stored format migrates once and is
never read in its old shape, so those attachments are deleted once -- ``--dry-run`` names them and their sizes,
``--apply`` deletes them. Only :data:`~dev_lab.dev.forgerecordkeep.OLD_UNIT_RESULT` matches: a keyed result, a run
record, a tombstone or a named file is never touched.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from lab_commons.log import emit

from dev_lab.dev.forge import Transport, forge_transport
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgerecordkeep import old_format_of
from dev_lab.dev.forgerecords import Attachment, delete, listing
from dev_lab.dev.forgework import Client, client_for

__all__ = ['main', 'purge_old_format', 'report']


def purge_old_format(client: Client, *, apply: bool) -> tuple[Attachment, ...]:
    """Every old-format unit result on *client*'s records home, oldest first; deleted when *apply*."""
    doomed = old_format_of(listing(client))
    if apply:
        delete(client, doomed)
    return doomed


def report(doomed: Sequence[Attachment], *, apply: bool) -> int:
    """Name each purged (or, dry, doomed) result with its size, then the count and total bytes; exit 0."""
    verb = 'deleted' if apply else 'would delete'
    for item in doomed:
        emit(f'{verb} {item.name}  {item.size}')
    emit(f'[records] {verb} {len(doomed)} old-format result(s), {sum(item.size for item in doomed)} bytes')
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    transport: Transport = forge_transport,
) -> int:
    """``--dry-run|--apply`` on the working directory's forge; exit 1 with the forge's remedy when a call fails."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.forgerecordpurge', description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--dry-run', action='store_true', help='name what would be deleted, with sizes; delete nothing')
    mode.add_argument('--apply', action='store_true', help='delete them')
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    client = client_for(Path.cwd() if cwd is None else cwd, env=env, transport=transport)
    try:
        return report(purge_old_format(client, apply=args.apply), apply=args.apply)
    except ForgeCallFailed as failed:
        emit(f'[forge] {failed}', err=True)
        emit(failed.report.attempts[-1].output, err=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
