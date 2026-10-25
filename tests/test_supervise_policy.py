"""The three brakes, and the sentences that say which one held."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from dev_lab.supervise.policy import Decision, decide
from dev_lab.supervise.state import mark_notified, new_state

_START = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)


def _config(**alerts: object) -> dict[str, Any]:
    base: dict[str, Any] = {'suppress_after_identical': 3, 'cooldown': 600}
    base.update(alerts)
    return {'alerts': base}


def _at(minutes: int) -> datetime:
    return _START + timedelta(minutes=minutes)


def _deliver(
    state: dict[str, Any],
    source: str,
    signature: str,
    config: dict[str, Any],
    *,
    clock: datetime,
    escalate_after: int | None = None,
) -> Decision:
    """Decide, then record the delivery the way the loop does.

    DECIDING TO SEND AND HAVING SENT ARE DIFFERENT FACTS. `decide` used to record the second one
    itself, before the notifier ran, which swallowed the retry of any notice a channel refused.
    A test that drives several cycles has to perform the second half, or it is asserting the
    brakes against a state that says nothing was ever delivered.
    """
    decision = decide(state, source, signature, config, clock=clock, escalate_after=escalate_after)
    if decision.notify:
        mark_notified(state, source, clock.isoformat())
    return decision


def test_a_first_sighting_is_always_told() -> None:
    """Something new is the one case no brake applies to."""
    decision = _deliver(new_state(), 'probe.down', 'sha-a', _config(), clock=_at(0))
    assert decision.notify is True
    assert decision.sightings == 1


def test_a_changed_signature_releases_suppression() -> None:
    """THE BRAKE THAT MATTERS: a condition that moved must not hide behind one that did not."""
    state = new_state()
    for minute in range(0, 60, 10):
        _deliver(state, 'probe.down', 'sha-a', _config(), clock=_at(minute))
    moved = _deliver(state, 'probe.down', 'sha-b', _config(), clock=_at(60))
    assert moved.notify is True
    assert moved.sightings == 1, 'a new signature is a new count'


def test_an_identical_repeat_within_the_cooldown_is_held() -> None:
    """A supervisor failing for an hour has told you already."""
    state = new_state()
    _deliver(state, 'probe.down', 'sha-a', _config(), clock=_at(0))
    again = _deliver(state, 'probe.down', 'sha-a', _config(), clock=_at(1))
    assert again.notify is False
    assert 'cooldown' in again.reason


def test_an_identical_repeat_after_the_cooldown_is_told_once_more() -> None:
    """Persistent but not yet written off: worth repeating at the configured pace."""
    state = new_state()
    _deliver(state, 'probe.down', 'sha-a', _config(), clock=_at(0))
    later = _deliver(state, 'probe.down', 'sha-a', _config(), clock=_at(11))
    assert later.notify is True


def test_the_repeats_stop_once_the_condition_is_written_off() -> None:
    """Continuing to send it trains a reader to ignore the channel."""
    state = new_state()
    decision = Decision(notify=False, reason='')
    for minute in range(0, 200, 11):
        decision = _deliver(state, 'probe.down', 'sha-a', _config(), clock=_at(minute))
    assert decision.notify is False
    assert 'silent' in decision.reason


def test_escalation_overrides_the_write_off() -> None:
    """Persistence is itself the problem, and this is how a write-off is deliberately lifted."""
    state = new_state()
    decision = Decision(notify=False, reason='')
    for minute in range(0, 200, 11):
        decision = _deliver(state, 'probe.down', 'sha-a', _config(), clock=_at(minute), escalate_after=5)
    assert decision.notify is True
    assert 'unresolved' in decision.reason


def test_the_reason_names_the_brake_that_held() -> None:
    """`no alert` and `no supervisor` look the same from outside, so the reason is load-bearing."""
    state = new_state()
    _deliver(state, 'probe.down', 'sha-a', _config(), clock=_at(0))
    held = _deliver(state, 'probe.down', 'sha-a', _config(), clock=_at(1))
    told = _deliver(new_state(), 'probe.down', 'sha-a', _config(), clock=_at(0))
    assert held.reason != told.reason
    assert 'cooldown' in held.reason


def test_two_sources_are_judged_apart() -> None:
    """One loud component must not exhaust another's cooldown."""
    state = new_state()
    config = _config()
    _deliver(state, 'a.down', 'sha-a', config, clock=_at(0))
    _deliver(state, 'b.down', 'sha-b', config, clock=_at(0))
    assert _deliver(state, 'a.down', 'sha-a', config, clock=_at(1)).notify is False
    assert _deliver(state, 'b.down', 'sha-b', config, clock=_at(1)).notify is False
    other = _deliver(state, 'c.down', 'sha-c', config, clock=_at(1))
    assert other.notify is True


def test_a_state_that_has_never_been_written_still_decides() -> None:
    """A first run has no history, and must start rather than refuse."""
    assert _deliver({}, 'probe.down', 'sha-a', _config(), clock=_at(0)).notify is True


def test_an_unreadable_last_alert_timestamp_does_not_hold_forever() -> None:
    """A corrupt stamp must not become a permanent silence; absence of evidence is not a brake."""
    state = new_state()
    state['anomalies']['probe.down'] = {
        'consecutive': 1,
        'signature': 'sha-a',
        'notified': 2,
        'last_alert': 'not a timestamp',
    }
    assert _deliver(state, 'probe.down', 'sha-a', _config(), clock=_at(0)).notify is True


def test_deciding_to_notify_does_not_claim_it_was_delivered() -> None:
    """THE REGRESSION. A decision to send is not a delivery, and recording it as one lost alerts.

    `decide` wrote `last_alert` before the notifier was called. So a notice that every channel
    refused left a timestamp saying it had gone, and the cooldown brake -- which measures from
    that timestamp -- suppressed the retry. One failed delivery became permanent silence, and the
    identical-sighting write-off then guaranteed it. The alert-channel outage was converted into
    silence by the bookkeeping rather than by any decision.

    The caller records what was delivered, once something has been.
    """
    state = new_state()
    decision = decide(state, 'probe.down', 'sha-a', _config(), clock=_at(0))
    assert decision.notify is True
    assert not state['anomalies']['probe.down'].get('last_alert'), 'a notice that has not been sent'
