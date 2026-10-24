"""Whether to say something, and why -- one place, three brakes, one answer.

The predecessor kept half of this in its state module and half in its alert module: the counters
lived with the state, the cooldown lived with the transport, and the rule that joined them existed
in neither. Reading either file could not tell you when an alert would be sent.

There are three brakes and they do different jobs, which is why one of them would not do:

* **the signature** -- what the condition IS. When it changes, the situation genuinely moved, so
  suppression releases. This is the brake that stops a rotating commit sha from being mistaken for
  a condition that will not go away.
* **the cooldown** -- how long between two notifications, whatever they are about. A supervisor
  that has been failing for an hour has told you already; saying it every cycle is noise.
* **the write-off** -- after this many identical sightings the repeats stop entirely. A condition
  that has not moved in twenty cycles is not news, and continuing to send it trains a reader to
  ignore the channel. Escalation is the deliberate exception: it is how a write-off is overridden
  when persistence is itself the problem.

A DECISION IS PURE GIVEN THE STATE, but this function does update the state's counters, because
they are the inputs to the next decision and separating the read from the write would leave the
rule split across two calls -- which is the defect this module exists to undo.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from dev_lab.supervise.state import note_signature, read_anomaly

__all__ = ['Decision', 'decide', 'now']

#: How long between two notifications when nothing else suppresses them.
DEFAULT_COOLDOWN: Final = 600

#: How many identical sightings before the repeats stop.
DEFAULT_WRITE_OFF: Final = 3


def now() -> datetime:
    """Return the current instant, timezone-aware.

    Returns:
        The current UTC time. Named here so a test substitutes a clock rather than freezing the
        process's.

    """
    return datetime.now(tz=UTC)


@dataclass(frozen=True)
class Decision:
    """Whether to notify about one anomaly, and the sentence that explains it.

    The reason is not decoration: a supervisor that goes quiet must be able to say which brake
    held it, or "no alert" and "no supervisor" look the same from outside.

    Attributes:
        notify: whether the notice should be sent.
        reason: why, in one line.
        sightings: how many consecutive cycles this exact signature has now been seen for.

    """

    notify: bool
    reason: str
    sightings: int = 0


def _elapsed_since(stamp: str, clock: datetime) -> float | None:
    """Return how long ago *stamp* was, in seconds, or None when it is absent or unreadable.

    Args:
        stamp: an ISO-8601 timestamp, possibly empty.
        clock: the instant to measure from.

    Returns:
        The elapsed seconds, or None when there is nothing readable to measure.

    """
    if not stamp:
        return None
    try:
        then = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=UTC)
    return (clock - then).total_seconds()


def decide(
    state: dict[str, Any],
    source: str,
    signature: str,
    config: Mapping[str, Any],
    *,
    clock: datetime,
    escalate_after: int | None = None,
) -> Decision:
    """Decide whether to notify about an anomaly, updating the counters this decision rests on.

    Args:
        state: the run's state, whose entry for *source* is updated in place.
        source: the loop-stamped ``<component>.<kind>`` key.
        signature: the stable identity of the current condition.
        config: the merged configuration, read for its ``alerts`` table.
        clock: the instant to judge the cooldown against.
        escalate_after: override the write-off once this many cycles have passed, for a condition
            whose persistence is the problem rather than its state.

    Returns:
        The decision, with the reason it was reached.

    """
    alerts = config.get('alerts', {})
    write_off = int(alerts.get('suppress_after_identical', DEFAULT_WRITE_OFF))
    cooldown = float(alerts.get('cooldown', DEFAULT_COOLDOWN))

    before = read_anomaly(state, source)
    moved = before.get('signature') != signature
    sightings = note_signature(state, source, signature)

    if moved or sightings == 1:
        return _send(sightings, 'new' if sightings == 1 and moved else 'the condition changed')
    if escalate_after is not None and sightings >= escalate_after:
        return _send(sightings, f'unresolved for {sightings} cycles')
    if sightings > write_off:
        return Decision(
            notify=False, reason=f'silent: the same condition has held for {sightings} cycles', sightings=sightings
        )
    elapsed = _elapsed_since(str(before.get('last_alert', '')), clock)
    if elapsed is not None and elapsed < cooldown:
        return Decision(notify=False, reason=f'cooldown: {int(cooldown - elapsed)}s left', sightings=sightings)
    return _send(sightings, f'still failing after {sightings} cycles')


def _send(sightings: int, reason: str) -> Decision:
    """Return the decision to send a notice.

    IT DOES NOT RECORD THAT ONE WENT, AND THAT IS THE POINT. This used to write `last_alert` here,
    before the notifier was called -- so a notice that every channel refused still left a timestamp
    saying it had gone, and the cooldown brake measures from exactly that timestamp. One failed
    delivery therefore suppressed its own retry, and the identical-sighting write-off then made the
    silence permanent. The alerting outage was converted into silence by bookkeeping rather than by
    any decision anybody made.

    Deciding to send and having sent are different facts, and the caller is the only one that
    knows the second. It records it.

    Args:
        sightings: the consecutive count this decision was reached at.
        reason: why the notice is warranted.

    Returns:
        An affirmative decision.

    """
    return Decision(notify=True, reason=reason, sightings=sightings)
