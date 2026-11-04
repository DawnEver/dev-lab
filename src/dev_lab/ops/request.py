"""THE ONE PARSER of a break-glass request: every field typed and bounded before any state is read or code spent.

A request is one JSON line ``{"action": ..., ...}`` (:mod:`dev_lab.ops.breakglass`). Everything a client could get
wrong is refused HERE as :class:`Malformed`, so the role's own code never sees an unchecked field -- and an internal
failure deeper down is never mistaken for, or relabelled as, a bad request.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any, Final

__all__ = ['ACTIONS', 'Ack', 'Malformed', 'Merge', 'Open', 'Request', 'parse']

#: Every action the role answers.
ACTIONS: Final = ('open', 'merge', 'close', 'ack', 'status')
_SHA: Final = re.compile(r'^[0-9a-f]{40}([0-9a-f]{24})?$')


class Malformed(ValueError):
    """The request is not one the role can read; the message names the field."""


@dataclass(frozen=True)
class Open:
    """``open``: the code, and the optional bounds the client asks for (``None`` = the configured one)."""

    code: str
    hours: float | None = None
    max_merges: int | None = None


@dataclass(frozen=True)
class Merge:
    """``merge``: which PR, at which head, why."""

    repo: str
    pr: int
    head: str
    reason: str


@dataclass(frozen=True)
class Ack:
    """``ack``: which wave (``''`` = the oldest unacknowledged), and who acknowledges it."""

    id: str
    by: str


@dataclass(frozen=True)
class Request:
    """One parsed request: its action and that action's fields (``None`` for ``close`` / ``status``)."""

    action: str
    fields: Open | Merge | Ack | None


def _str(data: dict[str, Any], key: str, *, required: bool = True) -> str:
    value = data.get(key, '' if not required else None)
    if not isinstance(value, str) or (required and not value.strip()):
        msg = f'{key} must be a non-empty string'
        raise Malformed(msg)
    return value.strip()


def _int(value: object, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        msg = f'{key} must be a positive integer'
        raise Malformed(msg)
    return value


def _hours(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value) or value <= 0:
        msg = 'hours must be a positive finite number'
        raise Malformed(msg)
    return float(value)


def parse(line: str) -> Request:
    """The request on *line*; raises :class:`Malformed` naming the first bad field."""
    try:
        data = json.loads(line)
    except ValueError as bad:
        msg = f'not one JSON line ({bad})'
        raise Malformed(msg) from bad
    if not isinstance(data, dict) or data.get('action') not in ACTIONS:
        msg = f'action must be one of {"|".join(ACTIONS)}'
        raise Malformed(msg)
    action = data['action']
    if action == 'open':
        cap = data.get('max_merges')
        return Request(action, Open(_str(data, 'code'), _hours(data.get('hours')),
                                    None if cap is None else _int(cap, 'max_merges')))  # fmt: skip
    if action == 'merge':
        head = _str(data, 'head')
        if not _SHA.match(head):
            msg = 'head must be a full commit sha'
            raise Malformed(msg)
        return Request(action, Merge(_str(data, 'repo'), _int(data.get('pr'), 'pr'), head, _str(data, 'reason')))
    if action == 'ack':
        return Request(action, Ack(_str(data, 'id', required=False), _str(data, 'by', required=False) or 'unnamed'))
    return Request(action, None)
