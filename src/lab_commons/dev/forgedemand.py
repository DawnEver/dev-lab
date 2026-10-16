"""THE ONE READER OF SHARED DEMAND (D4, 2026-10-16): the forge's run records, folded into the learned cache.

Every finished run -- a box verify, a forge producer, a Slurm array -- attaches its record to the forge
(:mod:`lab_commons.dev.forgerecords`), and each record carries per-file peaks and per-test durations. So
the forge already holds every host's measurements; a machine-local table written only by that machine's
own runs is a second source that disagrees with the first. :func:`refresh` reads the attached records this
machine has not folded yet, newest last, into :mod:`lab_commons.compute.learned`, which is from then on
a CACHE of the forge: every host prices a selection from the same numbers.

A forge that cannot be read is not a refusal: the cache stands as last folded, and the caller is told how
many records were folded (0). At most *limit* new records are read per call, newest first, so a host that
was away a month pays a bounded download and catches up over its next calls.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import TYPE_CHECKING, Final

from lab_commons.compute import learned
from lab_commons.dev.forgerecords import listing
from lab_commons.dev.forgework import ForgeCallFailed

if TYPE_CHECKING:
    from lab_commons.dev.forgework import Client

__all__ = ['LIMIT', 'refresh', 'refresh_checkout']

#: The most records one call downloads.
LIMIT: Final = 20


def refresh(repo: str, client: Client | None, *, limit: int = LIMIT) -> int:
    """Fold *repo*'s attached run records not folded yet into its learned cache; how many were folded.

    *client* ``None`` (no forge credential, no forge) folds nothing. A record that cannot be read is
    skipped and not remembered, so the next call retries it.
    """
    if client is None:
        return 0
    try:
        attached = listing(client)
    except (ForgeCallFailed, OSError):
        return 0
    known = learned.folded(repo)
    fresh = sorted((a for a in attached if a.name not in known), key=lambda a: a.id)[-limit:]
    count = 0
    for attachment in fresh:
        try:
            record = json.loads(gzip.decompress(client.download(attachment.url)).decode('utf-8'))
        except (ForgeCallFailed, OSError, ValueError):
            continue
        learned.learn_record(repo, attachment.name, record)
        count += 1
    return count


def refresh_checkout(root: Path, *, limit: int = LIMIT) -> int:
    """:func:`refresh` for the checkout at *root*: its origin URL and its unprompted forge client."""
    from lab_commons.dev.forgeoutbox import unprompted_client  # noqa: PLC0415 -- the forge client only when asked
    from lab_commons.dev.platformparts import origin_url  # noqa: PLC0415

    try:
        repo, client = origin_url(root), unprompted_client(root)
    except Exception:  # noqa: BLE001 -- no origin or no credential is no forge, never a crashed run
        return 0
    return refresh(repo, client, limit=limit)
