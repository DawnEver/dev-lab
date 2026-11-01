"""What a supervision check returns, and what a remedy chain is made of.

A check measures something and reports a :class:`CheckResult`: the numbers it read, the
:class:`Anomaly` objects it convicts, and the :class:`Completion` signals it celebrates. A
completion is deliberately NOT an anomaly -- a finished task is a first-class outcome, and
modelling it as a warning-severity anomaly makes a run that succeeded read as `degraded`
forever.

Nothing here knows what is being measured. A probe of an HTTP endpoint, a disk, a log tail and
a deployment all return the same four types, which is what lets one registry, one remedy engine
and one daemon drive all of them.
"""

from __future__ import annotations

import hashlib
import operator
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final

__all__ = [
    'OPERATORS',
    'Action',
    'Anomaly',
    'CheckResult',
    'Completion',
    'Condition',
    'Gate',
    'RemedyStep',
    'Severity',
    'condition_digest',
]


def condition_digest(*parts: str) -> str:
    """Digest the text that identifies a condition, so it can be told from a different one.

    IT LIVES BESIDE :attr:`Anomaly.signature` BECAUSE IT IS WHAT THAT FIELD MEANS. A signature is not
    a label for a component or a file or an exit code -- those are CONTAINERS, and a container is
    stable while its contents are not. It is the identity of the CONDITION, and the policy counts
    consecutive cycles per signature and writes a condition off once the count passes its threshold.
    A signature taken from a container therefore has two outcomes for a fresh failure: reported if
    nothing was wrong yet, and absorbed into the old condition's silence if something was.

    NUMBERS ARE FOLDED OUT because the text is reprinted on every cycle: a log line carries a date, a
    clock and an errno, a command's failure detail carries a timeout in seconds or a pid. Digesting
    the raw text would make ONE condition a new signature every cycle -- an alert storm, which is the
    opposite failure and the one that trains a reader to ignore the channel.

    Args:
        *parts: the text that names the condition. Order does not matter; repeats are one part.

    Returns:
        Sixteen hex characters, stable for one condition and different for another.

    """
    folded = sorted({_VOLATILE.sub('#', part) for part in parts})
    return hashlib.sha256('\n'.join(folded).encode('utf-8')).hexdigest()[:16]


#: The part of a message that changes on every write, removed before a condition is digested. See
#: :func:`condition_digest` for why folding rather than hashing the raw text is the whole point.
_VOLATILE: Final = re.compile(r'\d+')

#: The comparisons a condition may make, by the spelling a config uses. An explicit table rather
#: than ``eval`` or a parsed expression: a config is data, and data does not get to run code.
OPERATORS: Final[dict[str, Callable[[float, float], bool]]] = {
    '>': operator.gt,
    '>=': operator.ge,
    '<': operator.lt,
    '<=': operator.le,
    '==': operator.eq,
    '!=': operator.ne,
}


class Severity(StrEnum):
    """How loudly an anomaly should be reported.

    A closed set rather than a string, because a typo in a severity would otherwise silently
    downgrade an alert to something no remedy chain matches.
    """

    INFO = 'info'  # a notice that needs no action: the alert-channel test (D55)
    WARNING = 'warning'
    CRITICAL = 'critical'


class Gate(StrEnum):
    """Which severities a remedy step applies to.

    ``ALWAYS`` is the default: most steps are safe to run whatever the severity. The two named
    severities are exact matches, not thresholds -- a step gated on ``CRITICAL`` does not run for
    a warning, and a step gated on ``WARNING`` does not run for a critical one.
    """

    ALWAYS = 'always'
    WARNING = 'warning'
    CRITICAL = 'critical'

    def admits(self, severity: Severity) -> bool:
        """Return whether *severity* passes this gate.

        Args:
            severity: the severity of the anomaly the step is being considered for.

        Returns:
            True when the step should run for that severity.

        """
        if self is Gate.ALWAYS:
            return True
        return self.value == severity.value


@dataclass
class Anomaly:
    """One thing that is wrong, as a check found it.

    Attributes:
        kind: the anomaly's type, and the key a remedy chain is looked up by.
        severity: how loudly to report it.
        message: one line a human reads, saying what is wrong.
        value: the measurement that breached, when there is one.
        threshold: the value it breached, when there is one.
        source: stamped by the loop as ``<component>.<kind>``. A component leaves it empty --
            it should not have to know the name it was registered under.
        signature: stable identity for alert deduplication. Set it to something that stays
            constant while the condition is unchanged (a commit sha, a file path) and changes when
            the situation genuinely moves, so suppression releases on real change. Empty falls
            back to *message*.

    """

    kind: str
    severity: Severity
    message: str
    value: float | None = None
    threshold: float | None = None
    source: str = ''
    signature: str = ''


@dataclass
class Completion:
    """A task that has finished successfully -- an outcome, not a fault.

    Attributes:
        kind: the completion's type, so a report can tell one finished task from another.
        message: one line a human reads.

    """

    kind: str
    message: str


@dataclass(frozen=True)
class Condition:
    """A test one metric must pass for a remedy step to run.

    The predecessor gated steps on a STRING it parsed by hand -- ``"$new_commits > 0"``, with a
    fallback that returned True for anything it could not read. So a typo in a condition did not
    refuse the step; it silently ran it. Here the same gate is data: a metric, a comparison from
    :data:`OPERATORS`, and a number. A misspelt operator is refused when the chain is built.

    Attributes:
        metric: the metric's name, as the check reported it.
        op: the comparison, one of :data:`OPERATORS`.
        value: what to compare against.

    """

    metric: str
    op: str = '>'
    value: float = 0.0

    def holds(self, metrics: Mapping[str, float]) -> bool:
        """Return whether the condition is satisfied.

        A metric the check did not report counts as zero rather than as a refusal: a condition is
        a gate on an action, and a gate that cannot be read conservatively is how a remedy stops
        running without anyone noticing.

        Args:
            metrics: the numbers the check reported.

        Returns:
            True when the comparison holds.

        """
        compare = OPERATORS.get(self.op)
        if compare is None:
            msg = f'{self.op!r} is not a comparison; this build knows {sorted(OPERATORS)}'
            raise ValueError(msg)
        return compare(float(metrics.get(self.metric, 0.0)), float(self.value))


@dataclass
class RemedyStep:
    """One step of a remedy chain.

    Attributes:
        action: the name of an action the registry can resolve.
        on: which severities this step applies to.
        condition: an optional gate on a collected metric.
        max_attempts: how many times to try the action before giving up on this step.
        escalate_after: after this many consecutive cycles still anomalous, alert instead of
            retrying. None means never escalate on this step.

    """

    action: str
    on: Gate = Gate.ALWAYS
    condition: Condition | None = None
    max_attempts: int = 1
    escalate_after: int | None = None

    def __post_init__(self) -> None:
        """Coerce a gate spelled as a string, and refuse one this build does not know.

        A component author writes ``on='critical'`` and so does a TOML table, and both are strings.
        Without this the string survived construction and the failure arrived later as an
        ``AttributeError`` inside the cycle -- in the middle of applying a remedy, which is the
        worst place to discover a typo. ``Gate(...)`` raises here instead.

        Raises:
            ValueError: the gate is not one this build defines.

        """
        if not isinstance(self.on, Gate):
            self.on = Gate(self.on)


@dataclass
class Action:
    """Something the supervisor can do, as a shell command.

    This is the whole action surface: a command, how to run it, and how long to wait. Watch's
    predecessor carried five shapes in one dataclass (kill/start pairs, port freeing, detached
    spawns, composition) because it hosted processes itself. Process hosting now belongs to a
    :class:`~dev_lab.supervise.process.ProcessManager`, so a restart is
    ``systemctl restart <unit>`` -- a command like any other.

    An action a component implements in Python rather than as a command declares no *command*
    and is resolved through the component's handler table by name.

    ``command`` is a SHELL LINE, always. The predecessor carried a ``shell`` flag to choose between
    a shell line and an argv, which meant every caller had to know which one it had been handed --
    and a remedy written as argv silently became one long executable name. There is one spelling
    here: a line, run by a shell.

    Attributes:
        description: what the action does, for a report.
        command: the command line to run, or None when a component implements the action.
        timeout: seconds to allow the command before killing it.

    """

    description: str = ''
    command: str | None = None
    timeout: int = 30


@dataclass
class CheckResult:
    """Everything one check pass produced.

    Attributes:
        metrics: measured numbers by name, fed to remedy conditions and report deltas.
        anomalies: what is wrong.
        data: anything else a check wants a report to carry, not interpreted here.
        completions: tasks that finished successfully.

    """

    metrics: dict[str, float] = field(default_factory=dict)
    anomalies: list[Anomaly] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    completions: list[Completion] = field(default_factory=list)
