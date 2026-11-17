"""A REPORTED CREDENTIAL REFUSAL IS CHECKED AGAINST THE NEXT ANSWER: the feedback on ``auth check|status``.

Measured 2026-11-10: workstations kept reporting "the local Gitea API token is invalid" when a retry of the same
command, with the same token, authenticated. Two defects made that report: ``auth check`` read every failed call
(a dropped connection, a 5xx, Gitea's known attempt-1 "Failed to authenticate user") as a refusal, and nothing ever
compared a refusal with what came after it, so a misread could repeat for weeks unseen.

So every refusal ``auth check|status`` reports is REMEMBERED: ``<machine home>/state/forgeauth/<host>.json`` holds
when, why, and the sha256 prefix of the refused token (never the token). The next time the same host authenticates:

- with the SAME token, the refusal was a misread. It is appended to ``misreads.jsonl`` beside it and said on
  stderr, naming the file to attach to a report -- the classifier (:mod:`dev_lab.dev.forgefailure`) is what to fix;
- with a different token, the refusal was real and a re-login cured it; the record is just dropped.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from lab_commons.home import part

__all__ = ['MISREADS', 'answered', 'misreads_path', 'refused']

#: The append-only log of refusals a later answer with the same token disproved.
MISREADS: Final = 'misreads.jsonl'


def _dir() -> Path:
    return part('state') / 'forgeauth'


def _path(host: str) -> Path:
    return _dir() / f'{re.sub(r"[^\w.-]", "_", host)}.json'


def misreads_path() -> Path:
    """Where misread refusals are logged."""
    return _dir() / MISREADS


def refused(host: str, digest: str, why: str) -> None:
    """Remember that a refusal of the token with sha256 prefix *digest* on *host* was reported, and why."""
    record = {'host': host, 'at': datetime.now(UTC).isoformat(timespec='seconds'), 'digest': digest, 'why': why}
    path = _path(host)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record) + '\n', encoding='utf-8')


def answered(host: str, digest: str) -> str:
    """Settle *host*'s remembered refusal now that it authenticated; the misread message, else ``''``."""
    path = _path(host)
    try:
        record = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return ''
    path.unlink(missing_ok=True)
    if record.get('digest') != digest:
        return ''
    record['disproved'] = datetime.now(UTC).isoformat(timespec='seconds')
    with misreads_path().open('a', encoding='utf-8') as log:
        log.write(json.dumps(record) + '\n')
    return (
        f'MISREAD: the refusal reported for {host} at {record["at"]} ({record["why"]}) was wrong -- the same '
        f'token authenticates now, so it was a transient read as a refusal. Do not re-store the token; report it '
        f'with {misreads_path()}'
    )
