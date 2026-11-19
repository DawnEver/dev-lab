"""A break-glass wave awaiting acknowledgement reaches each session ONCE, through the feed -- never as an issue.

User ruling 2026-11-19: issues never record break-glass merges. The audit lives once, in the wave ledger the
break-glass endpoint keeps (``forge breakglass status`` lists each wave and its state; ``forge breakglass ack
<wave>`` records the review). The machine hearer (:mod:`dev_lab.dev.forgefeed`) asks that endpoint for its status
at most every :data:`EVERY_S` and keeps the waves in state ``audit`` (:func:`refresh`); each session's inbox hook
then says each such wave once (:func:`news`). No ``[breakglass]`` endpoint in the machine file: nothing is asked.
"""

from __future__ import annotations

import json
import re
import time
from typing import TYPE_CHECKING, Final

from lab_commons.config import section

from dev_lab.dev.forgethreads import feed_dir, read_json

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path
    from typing import Any

__all__ = ['EVERY_S', 'awaiting', 'news', 'refresh']

#: How often the hearer asks the endpoint: an audit waits for a human, so half an hour is prompt enough.
EVERY_S: Final = 1800.0

#: A ``status`` line of a wave awaiting acknowledgement (:meth:`dev_lab.ops.breakglass.Breakglass._status`).
_AUDIT: Final = re.compile(r'^wave (?P<id>\S+): audit, (?P<merges>\d+) merge\(s\)$', re.MULTILINE)


def awaiting(said: str) -> dict[str, int]:
    """``wave id -> merges`` of each wave in state ``audit`` in a ``status`` answer."""
    return {found['id']: int(found['merges']) for found in _AUDIT.finditer(said)}


def _store() -> Path:
    return feed_dir() / 'waves.json'


def refresh(
    send: Callable[[Mapping[str, Any], dict[str, Any]], tuple[int, str]],
    *,
    table: Mapping[str, Any] | None = None,
    now: float | None = None,
) -> bool:
    """Ask the endpoint once when :data:`EVERY_S` has passed; whether it was asked.

    A failed ask keeps the last answer.
    """
    found = section('breakglass') if table is None else table
    if not found.get('endpoint'):
        return False
    kept = read_json(_store())
    at = time.time() if now is None else now
    if at - float(kept.get('asked', 0.0)) < EVERY_S:
        return False
    status, said = send(found, {'action': 'status'})
    waves = awaiting(said) if status == 0 else kept.get('waves', {})
    _store().parent.mkdir(parents=True, exist_ok=True)
    _store().write_text(json.dumps({'asked': at, 'waves': waves}), encoding='utf-8')
    return True


def news(session: str) -> list[str]:
    """One line per wave awaiting acknowledgement that *session* was not yet told; each is told once."""
    waves = read_json(_store()).get('waves', {})
    told_path = feed_dir() / 'waves-told' / f'{session}.json'
    told = read_json(told_path).get('told', [])
    fresh = [wave for wave in sorted(waves) if wave not in told]
    if fresh:
        told_path.parent.mkdir(parents=True, exist_ok=True)
        told_path.write_text(json.dumps({'told': [*told, *fresh]}), encoding='utf-8')
    return [
        f'break-glass wave {wave} ({waves[wave]} merge(s)) awaits review: '
        f'`python -m dev_lab.dev.forge breakglass status`, then `forge breakglass ack {wave}`'
        for wave in fresh
    ]
