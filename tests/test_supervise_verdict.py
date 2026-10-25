"""What a check returns, and the gate a remedy step is judged by."""

from __future__ import annotations

import pytest

from dev_lab.supervise.verdict import (
    OPERATORS,
    Action,
    Anomaly,
    CheckResult,
    Completion,
    Condition,
    Gate,
    RemedyStep,
    Severity,
)


def test_an_anomaly_carries_no_source_until_the_loop_stamps_it() -> None:
    """A component reports what is wrong, not the name it happens to be registered under."""
    anomaly = Anomaly(kind='unreachable', severity=Severity.CRITICAL, message='no answer')
    assert anomaly.source == ''
    assert anomaly.value is None
    assert anomaly.threshold is None
    assert anomaly.signature == ''


def test_a_check_that_found_nothing_is_an_empty_result_not_none() -> None:
    """The clean case is a value, so callers never branch on absence."""
    result = CheckResult()
    assert result.anomalies == []
    assert result.completions == []
    assert result.metrics == {}
    assert result.data == {}


def test_a_completion_is_not_an_anomaly() -> None:
    """A finished task is an outcome; modelling it as a warning would read as degraded forever."""
    result = CheckResult(completions=[Completion(kind='done', message='all ops complete')])
    assert result.anomalies == []
    assert result.completions[0].kind == 'done'


def test_the_two_check_results_do_not_share_their_lists() -> None:
    """Dataclass field defaults must be per-instance, or one check's anomalies leak into another."""
    first, second = CheckResult(), CheckResult()
    first.anomalies.append(Anomaly(kind='x', severity=Severity.WARNING, message='x'))
    first.metrics['n'] = 1.0
    assert second.anomalies == []
    assert second.metrics == {}


@pytest.mark.parametrize(
    ('gate', 'severity'),
    [
        (Gate.ALWAYS, Severity.WARNING),
        (Gate.ALWAYS, Severity.CRITICAL),
        (Gate.WARNING, Severity.WARNING),
        (Gate.CRITICAL, Severity.CRITICAL),
    ],
)
def test_a_gate_admits_its_own_severity(gate: Gate, severity: Severity) -> None:
    """`always` admits both; a named severity admits itself."""
    assert gate.admits(severity) is True


@pytest.mark.parametrize(
    ('gate', 'severity'),
    [
        (Gate.WARNING, Severity.CRITICAL),
        (Gate.CRITICAL, Severity.WARNING),
    ],
)
def test_a_gate_is_an_exact_match_not_a_threshold(gate: Gate, severity: Severity) -> None:
    """`on: critical` excludes a warning; a threshold reading would have included it."""
    assert gate.admits(severity) is False


def test_a_remedy_step_defaults_to_running_whatever_the_severity() -> None:
    """Most steps are safe to run either way, so the default is the permissive one."""
    step = RemedyStep(action='restart')
    assert step.on is Gate.ALWAYS
    assert step.condition is None
    assert step.max_attempts == 1
    assert step.escalate_after is None


def test_an_action_with_no_command_is_one_a_component_implements() -> None:
    """The escape from the command surface is a declared handler, not a magic string."""
    action = Action(description='validate then activate')
    assert action.command is None
    assert action.timeout == 30


def test_a_condition_judges_a_metric_against_a_number() -> None:
    """The step gate is data: a metric, an operator from the table, a value."""
    assert Condition(metric='commits', op='>', value=0).holds({'commits': 3.0}) is True
    assert Condition(metric='commits', op='>', value=0).holds({'commits': 0.0}) is False


def test_a_metric_a_check_did_not_report_reads_as_zero() -> None:
    """A gate that cannot be read must not silently stop the remedy from running."""
    assert Condition(metric='absent', op='==', value=0).holds({}) is True


def test_an_operator_outside_the_table_is_refused() -> None:
    """An unreadable comparison is refused rather than silently run.

    The predecessor's string conditions fell back to True for anything unparseable, so a typo
    RAN the step instead of holding it.
    """
    with pytest.raises(ValueError, match='not a comparison'):
        Condition(metric='m', op='=<').holds({'m': 1.0})


def test_every_operator_in_the_table_is_reachable() -> None:
    """A table entry nothing can spell is a comparison the config cannot ask for."""
    assert sorted(OPERATORS) == ['!=', '<', '<=', '==', '>', '>=']
    assert OPERATORS['>'](2.0, 1.0) is True
    assert OPERATORS['>'](1.0, 2.0) is False
    assert OPERATORS['>='](2.0, 2.0) is True
    assert OPERATORS['<'](1.0, 2.0) is True
    assert OPERATORS['<='](2.0, 2.0) is True
    assert OPERATORS['=='](2.0, 2.0) is True
    assert OPERATORS['!='](2.0, 2.0) is False
