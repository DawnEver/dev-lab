"""WHAT A RECORDS PRUNE KEEPS -- the record names, the live shas and the selection, with no forge call.

A run record is named ``run-<sha>-<row>-<req>.json.gz`` and a compute unit result
``unit-<unit>-g<generation>-<result>.tar.<ext>``; :func:`doomed_of` reads only those names. A record stays while
its sha is live (:func:`kept_shas`: every ``origin`` tip and the newest first-parent trunk commits) and it is among
the newest :data:`RECORDS_PER_ROW` of its row; a unit result stays while it is among the newest
``unit_results``. :mod:`dev_lab.dev.forgerecords` lists the home and deletes what this names.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door

from dev_lab.dev.forge import _GIT, _GIT_TIMEOUT_S
from dev_lab.dev.partrows import is_row

if TYPE_CHECKING:
    from dev_lab.dev.forgerecords import Attachment

__all__ = [
    'DEFAULT_KEEP_TRUNK',
    'OLD_UNIT_RESULT',
    'RECORDS_PER_ROW',
    'UNIT_RESULT',
    'doomed_of',
    'kept_shas',
    'old_format_of',
    'sha_of',
]

#: How many first-parent trunk commits keep their records by default.
DEFAULT_KEEP_TRUNK: Final = 20

#: How many records one sha's row keeps, newest first: a re-run or a local verify supersedes the older one, so
#: the home grows with shas and never with re-runs (2026-11-15: one sha held a record per verify).
RECORDS_PER_ROW: Final = 2

#: ``run-<sha>-<row>-<req>.json.gz``; the row is a part or an OS-qualified row (``base@windows``), judged by
#: :func:`dev_lab.dev.partrows.is_row` -- 2026-11-15: a ``[a-z]+`` part read no row record, and none was pruned.
_RECORD_NAME: Final = re.compile(r'^run-(?P<sha>[0-9a-f]{40})-(?P<row>[^-/]+)-[^/]+\.json\.gz$')
#: A compute unit result (:func:`dev_lab.dev.forgeunit.result_name`), whatever archive it was posted as.
UNIT_RESULT: Final = re.compile(
    r'^unit-(?P<unit>[0-9a-f]{64})-g(?P<generation>\d+)-(?P<result>[0-9a-f]{64})\.tar\.[a-z]+$'
)
#: A unit result named before results were keyed by generation (``unit-<unit>-<result>.tar.<ext>``): the old
#: format, deleted once by ``records purge-old-format`` and never read (a stored format migrates once).
OLD_UNIT_RESULT: Final = re.compile(r'^unit-[0-9a-f]{64}-[0-9a-f]{64}\.tar\.[a-z]+$')
_TRACKING: Final = 'refs/remotes/origin/'


def _sha_row(name: str) -> tuple[str, str] | None:
    """The ``(sha, row)`` a record's file name carries, or ``None`` for a file that is not a run record."""
    found = _RECORD_NAME.match(name)
    return (found['sha'], found['row']) if found and is_row(found['row']) else None


def sha_of(name: str) -> str | None:
    """The sha a record's file name carries, or ``None`` for a file that is not a run record."""
    found = _sha_row(name)
    return found[0] if found else None


def _git(root: Path, *args: str) -> str:
    return _door.run(
        [_GIT, '-C', str(root), *args],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=True,
        timeout=_GIT_TIMEOUT_S,
    ).stdout


def kept_shas(root: Path, *, trunk: str, keep_trunk: int) -> frozenset[str]:
    """Every ``origin`` branch tip, plus the newest *keep_trunk* first-parent commits of ``origin/<trunk>``.

    Read from the remote-tracking refs, so the caller fetches first; nothing here touches the network.
    """
    tips = _git(root, 'for-each-ref', '--format=%(objectname)', _TRACKING).split()
    trunk_ref = f'{_TRACKING}{trunk}'
    known = _git(root, 'for-each-ref', '--format=%(refname)', trunk_ref).split()
    history = _git(root, 'rev-list', '--first-parent', f'-{keep_trunk}', trunk_ref).split() if known else []
    return frozenset(tips) | frozenset(history)


def doomed_of(
    found: Sequence[Attachment], keep: Collection[str], *, unit_results: int, per_row: int
) -> tuple[Attachment, ...]:
    """What a prune deletes of *found*, oldest first; anything not named here stays.

    Records of shas not in *keep*, each kept sha's row's records but the newest *per_row*, and every unit
    result but the newest *unit_results*.
    """
    units = [item for item in found if UNIT_RESULT.match(item.name)]
    stale = {item.id for item in units[: max(len(units) - unit_results, 0)]}
    rows: dict[tuple[str, str], list[int]] = {}
    for item in found:
        key = _sha_row(item.name)
        if key is None:
            continue
        if key[0] not in keep:
            stale.add(item.id)
        else:
            rows.setdefault(key, []).append(item.id)
    for ids in rows.values():
        stale.update(sorted(ids)[: max(len(ids) - per_row, 0)])
    return tuple(item for item in found if item.id in stale)


def old_format_of(found: Sequence[Attachment]) -> tuple[Attachment, ...]:
    """The unit results of *found* named in the old, generation-less format; nothing else ever matches."""
    return tuple(item for item in found if OLD_UNIT_RESULT.match(item.name))
