"""What a person reads, what a digest reads back, and what neither is allowed to leak."""

from __future__ import annotations

from datetime import UTC, datetime

from dev_lab.supervise.alert import Delivery
from dev_lab.supervise.loop import CycleResult
from dev_lab.supervise.remedy import Attempt
from dev_lab.supervise.report import digest, record, redact, summary
from dev_lab.supervise.verdict import Anomaly, Severity

_AT = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)


def _anomaly(source: str = 'probe.down') -> Anomaly:
    return Anomaly(kind='down', severity=Severity.CRITICAL, message='down', source=source)


def test_a_clean_cycle_says_so_in_one_line() -> None:
    """The common case is the one a reader sees most, so it is the shortest."""
    assert summary(CycleResult(status='healthy')) == 'HEALTHY -- every check passed'


def test_a_degraded_summary_names_every_source_once() -> None:
    """Two anomalies from one component are one thing to report, not two."""
    result = CycleResult(status='degraded', anomalies=[_anomaly(), _anomaly()])
    assert summary(result).count('probe.down') == 1
    assert summary(result).startswith('DEGRADED')


def test_a_summary_separates_remedies_that_ran_from_ones_a_gate_held() -> None:
    """'we chose not to' and 'we tried and it failed' are different facts to act on."""
    result = CycleResult(
        status='degraded',
        anomalies=[_anomaly()],
        attempts=[
            Attempt(source='probe.down', action='restart', ok=True),
            Attempt(source='probe.down', action='deploy', ok=False, detail='gated', skipped=True),
        ],
    )
    assert '1 remedy ran, 1 held by a gate' in summary(result)


def test_a_summary_counts_the_channels_that_took_the_notice() -> None:
    """A partial delivery is the failure that looks like success from the sender's side."""
    result = CycleResult(
        status='degraded',
        anomalies=[_anomaly()],
        deliveries=[Delivery(channel='email', ok=True), Delivery(channel='telegram', ok=False)],
    )
    assert '1/2 channels reached' in summary(result)


def test_a_record_is_scalars_and_sorted_lists() -> None:
    """A digest sums a day of these; a field whose shape drifts stops the roll-up counting."""
    result = CycleResult(status='degraded', anomalies=[_anomaly('b.x'), _anomaly('a.x')])
    entry = record(result, _AT)
    assert entry['anomalies'] == ['a.x', 'b.x']
    assert entry['at'] == _AT.isoformat()
    assert isinstance(entry['remedies_ran'], int)


def test_a_record_keeps_a_failed_channel_and_redacts_it() -> None:
    """A channel that refuses an address refuses it by name, and a report is copied widely."""
    result = CycleResult(
        status='degraded',
        anomalies=[_anomaly()],
        deliveries=[Delivery(channel='email', ok=False, detail='refused ops@example.org')],
    )
    failed = record(result, _AT)['channels_failed']
    assert failed == ['email: refused <address>']


def test_redaction_masks_addresses_and_token_shaped_runs() -> None:
    """A crude redactor with misses is worse than a crude one without; these are deliberately crude."""
    assert redact('ops@example.org') == '<address>'
    assert 'abcdefghijklmnopqrstuvwxyz123456' not in redact('Bearer abcdefghijklmnopqrstuvwxyz123456')
    assert redact('a short word') == 'a short word'


def test_an_empty_digest_says_so_rather_than_saying_nothing() -> None:
    """Silence from a supervisor is indistinguishable from a supervisor that is not running."""
    assert 'No supervision cycles' in digest([])


def test_a_digest_adds_up_the_window() -> None:
    """The roll-up states the count, the failures, and what was done."""
    good = record(CycleResult(status='healthy'), _AT)
    bad = record(CycleResult(status='degraded', anomalies=[_anomaly()]), _AT)
    text = digest([good, bad])
    assert '2 cycles' in text
    assert '1 degraded' in text
    assert 'probe.down x1' in text


def test_a_digest_ranks_the_persistent_ones_first() -> None:
    """A reader wants the thing that would not go away, not the alphabetical order."""
    records = [record(CycleResult(status='degraded', anomalies=[_anomaly('loud.x')]), _AT) for _ in range(3)]
    records.append(record(CycleResult(status='degraded', anomalies=[_anomaly('quiet.x')]), _AT))
    assert digest(records).index('loud.x x3') < digest(records).index('quiet.x x1')


def test_a_digest_reports_channels_that_did_not_take_a_notice() -> None:
    """Otherwise a silently broken channel reads as a quiet week."""
    result = CycleResult(
        status='degraded',
        anomalies=[_anomaly()],
        deliveries=[Delivery(channel='webhook', ok=False, detail='timeout')],
    )
    assert 'webhook' in digest([record(result, _AT)])


def test_a_digest_carries_the_window_it_covers() -> None:
    """A roll-up with no window cannot be compared with the one before it."""
    assert '2026-10-03' in digest([record(CycleResult(status='healthy'), _AT)], since='2026-10-03')
