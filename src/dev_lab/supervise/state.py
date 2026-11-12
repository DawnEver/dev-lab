"""The one place a supervision run keeps what it learned between cycles.

Watch's predecessor kept THREE stores -- one for the AI loop, one for the daemon, one for the
Claude session hook -- and they did not agree: the same anomaly was counted under
``consecutive_<kind>`` on one path and ``consecutive_<component>_<kind>`` on another, so a
condition that had been failing for an hour read as new to whichever path looked second. There is
one store here, one key scheme, and this module owns the scheme so no caller can invent a key.

WHAT IS IN IT, and nothing else. The bookkeeping a loop needs to tell "this just started" from
"this has been failing since Tuesday": a consecutive count per anomaly, the signature the last
alert carried so an unchanged condition is not re-sent, when that alert went, a bounded history of
remedy attempts, and when the run last found everything quiet. Component-owned state lives under
``components`` as an opaque mapping -- this module does not interpret it, and a component that
wants to persist something does not get to add a top-level key.

WHY THE FILE IS WRITTEN ATOMICALLY. A reader must never see half a state: a cycle that crashed
mid-write would otherwise leave a count of zero where the truth was two hundred, which reads as
"just started" and releases every suppression. :func:`lab_commons._records.publish` is reused
rather than reimplemented because the retry it carries was measured against a real failure (a
reader's open handle refusing a rename on Windows) and a second copy would not carry that.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from lab_commons._records import publish
from lab_commons.log import emit

__all__ = [
    'REMEDY_HISTORY',
    'SCHEMA_VERSION',
    'StateStore',
    'clear_anomaly',
    'count_anomaly',
    'count_remedy',
    'mark_notified',
    'new_state',
    'note_cycle',
    'note_quiet',
    'note_signature',
    'read_anomaly',
]

#: The state file's format version. Written into every new state and checked on read, so a future
#: change to the shape is something a run can DETECT rather than silently misinterpret.
SCHEMA_VERSION: Final = 1

#: How many remedy attempts are kept. A report shows the tail; an unbounded list would make the
#: state file grow for the life of the deployment, which is the defect the predecessor had in its
#: log ring.
REMEDY_HISTORY: Final = 20


def new_state() -> dict[str, Any]:
    """Return an empty state at the current schema version.

    Returns:
        A state mapping with no anomalies, no remedy history and no quiet timestamp.

    """
    return {
        'version': SCHEMA_VERSION,
        'last_cycle': '',
        'last_quiet': '',
        'anomalies': {},
        'remedies': [],
        'components': {},
    }


def _anomalies(state: dict[str, Any]) -> dict[str, Any]:
    existing = state.get('anomalies')
    if not isinstance(existing, dict):
        existing = {}
        state['anomalies'] = existing
    return existing


def _entry(state: dict[str, Any], source: str) -> dict[str, Any]:
    anomalies = _anomalies(state)
    entry = anomalies.get(source)
    if not isinstance(entry, dict):
        entry = {'consecutive': 0, 'signature': '', 'notified': 0, 'last_alert': ''}
        anomalies[source] = entry
    return entry


def read_anomaly(state: dict[str, Any], source: str) -> dict[str, Any]:
    """Return the bookkeeping held for one anomaly source.

    Args:
        state: the state mapping.
        source: the loop-stamped ``<component>.<kind>`` key.

    Returns:
        A copy of the entry for *source*, zeroed when it has never been seen.

    """
    entry = _anomalies(state).get(source)
    if not isinstance(entry, dict):
        return {'consecutive': 0, 'signature': '', 'notified': 0, 'last_alert': ''}
    return dict(entry)


def count_anomaly(state: dict[str, Any], source: str) -> int:
    """Record one more consecutive cycle in which *source* was anomalous.

    Args:
        state: the state mapping.
        source: the loop-stamped ``<component>.<kind>`` key.

    Returns:
        The new consecutive count.

    """
    entry = _entry(state, source)
    entry['consecutive'] = int(entry.get('consecutive') or 0) + 1
    return int(entry['consecutive'])


def clear_anomaly(state: dict[str, Any], source: str) -> None:
    """Drop *source*'s bookkeeping, because this cycle found it clean.

    Args:
        state: the state mapping.
        source: the loop-stamped ``<component>.<kind>`` key.

    """
    _anomalies(state).pop(source, None)


def note_signature(state: dict[str, Any], source: str, signature: str) -> int:
    """Record the alert signature for *source* and count how often it has now been seen.

    An unchanged signature means the same condition is still true, so the count rises and
    suppression eventually engages. A CHANGED signature means the situation genuinely moved, so
    the count restarts -- which is what releases a suppression that would otherwise hide it.

    Args:
        state: the state mapping.
        source: the loop-stamped ``<component>.<kind>`` key.
        signature: the stable identity of the current condition.

    Returns:
        How many cycles this exact signature has now been seen for, starting at 1.

    """
    entry = _entry(state, source)
    if entry.get('signature') != signature:
        entry['signature'] = signature
        entry['notified'] = 0
        entry['last_alert'] = ''
    entry['notified'] = int(entry.get('notified') or 0) + 1
    return int(entry['notified'])


def mark_notified(state: dict[str, Any], source: str, when: str) -> None:
    """Record that an alert for *source* was sent at *when*.

    Args:
        state: the state mapping.
        source: the loop-stamped ``<component>.<kind>`` key.
        when: an ISO-8601 timestamp.

    """
    _entry(state, source)['last_alert'] = when


def count_remedy(state: dict[str, Any], entry: Mapping[str, Any]) -> None:
    """Append one remedy attempt to the bounded history.

    Args:
        state: the state mapping.
        entry: what was attempted -- source, action, result, attempts.

    """
    history = state.get('remedies')
    if not isinstance(history, list):
        history = []
        state['remedies'] = history
    history.append(dict(entry))
    del history[:-REMEDY_HISTORY]


def note_quiet(state: dict[str, Any], when: str) -> None:
    """Record that a cycle found nothing wrong.

    Args:
        state: the state mapping.
        when: an ISO-8601 timestamp.

    """
    state['last_quiet'] = when


def note_cycle(state: dict[str, Any], when: str) -> None:
    """Record that a cycle RAN, whatever it found.

    Separate from :func:`note_quiet` on purpose: a supervisor that is cycling and failing and one
    that has stopped cycling entirely must read differently, and one timestamp cannot say both.

    Args:
        state: the state mapping.
        when: an ISO-8601 timestamp.

    """
    state['last_cycle'] = when


@dataclass(frozen=True)
class StateStore:
    """The one state file a supervision run reads and writes.

    Attributes:
        path: where the state lives. No default: a state path is the adopting project's fact, and
            a default would silently put two projects in one file.

    """

    path: Path

    def read(self) -> dict[str, Any]:
        """Return the state on disk, or a fresh one when there is none to trust.

        An unreadable file is treated as no file rather than as an error: a run that cannot read
        its own history should start a new one and carry on supervising, not refuse to run. The
        file is left where it is so a human can look at it.

        Returns:
            The parsed state, or :func:`new_state` when it is missing, unparseable, or a version
            this build does not know.

        """
        if not self.path.is_file():
            # A MISSING FILE IS THE ORDINARY FIRST RUN and is not worth a word. Everything below is
            # a file that EXISTS and could not be used, and that is a different fact about a
            # different situation.
            return new_state()
        try:
            parsed = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            # SAY SO. Returning a fresh state here is right -- a run that cannot read its history
            # should start a new one rather than refuse to supervise -- but the file is left where
            # it is for a human, and a human who is never told will not look. This discards the
            # release history, which is the rollback floor, and the next write overwrites the
            # evidence.
            emit(
                f'supervise: {self.path} could not be read ({type(exc).__name__}), so this run '
                f'starts from no history and the file is left in place to be looked at',
                flush=True,
            )
            return new_state()
        if not isinstance(parsed, dict) or parsed.get('version') != SCHEMA_VERSION:
            # SCHEMA_VERSION's own docstring says the check exists "so a future change to the shape
            # is something a run can DETECT rather than silently misinterpret". Detecting it and
            # then discarding the whole document -- release history, suppression counters, the
            # rollback floor -- is not the promise the check was written to keep.
            found = parsed.get('version') if isinstance(parsed, dict) else type(parsed).__name__
            emit(
                f'supervise: {self.path} is version {found!r} and this build reads {SCHEMA_VERSION!r}; '
                f'it is left in place and this run starts from no history',
                flush=True,
            )
            return new_state()
        return parsed

    def write(self, state: Mapping[str, Any]) -> bool:
        """Put *state* at the path atomically.

        Args:
            state: the state to persist.

        Returns:
            True when it was published, False when a concurrent reader kept the rename from
            landing. Never raises: a lost state write must not take a supervision cycle down.

        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        return publish(self.path, dict(state))
