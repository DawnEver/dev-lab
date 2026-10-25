"""Probes: is it answering, does the answer say what it should, and is the supervisor still going.

Three questions worth telling apart. An endpoint that refuses a connection is down; one that
answers 200 with ``"status": "degraded"`` is UP AND SAYING SO, and a check that only looks at the
socket cannot tell those apart. The predecessor's HTTP probe had exactly that blind spot: it parsed
the body into JSON and then never looked at the status code, so a 500 with a JSON error document
counted as reachable.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from dev_lab.supervise.component import CheckContext, Component
from dev_lab.supervise.transport import OK_CEILING, OK_FLOOR, Transport, fetch_json, scheme_transport
from dev_lab.supervise.verdict import Anomaly, CheckResult, Severity, condition_digest

#: `OK_FLOOR` and `OK_CEILING` are NOT re-exported here. What counts as an HTTP endpoint having
#: answered is HTTP's answer, not this component's, and a name re-exported through the module that
#: merely uses it is how the family ends up with two of them -- which is exactly what had happened:
#: `alert` kept a private second pair of these two numbers until 2026-10-03.
__all__ = ['Heartbeat', 'HttpHealth', 'ShellProbe']


class HttpHealth(Component):
    """Fetch endpoints and assert what their answers must say.

    Config::

        [components.http_health]
        enabled = true
        [[components.http_health.endpoints]]
        name = "api"
        url = "http://127.0.0.1:7001/health/"
        timeout = 5
        optional = false
        expect = { status = "healthy" }

    """

    name = 'http_health'
    description = 'Fetch endpoints, check the status, and assert what the answer must say'

    def __init__(self, transport: Transport | None = None) -> None:
        """Take the transport, so a test can read the request rather than make it.

        Args:
            transport: how a connection is made. Defaults to the one that honours the URL's
                scheme, because a probe against loopback is plain HTTP by design.

        """
        self._transport = transport or scheme_transport

    def check(self, ctx: CheckContext) -> CheckResult:
        """Fetch every configured endpoint and report what is wrong with each.

        Args:
            ctx: the probe's config and the target directory.

        Returns:
            Reachability metrics, and an anomaly per endpoint that failed or answered wrongly.

        """
        result = CheckResult()
        for endpoint in ctx.config.get('endpoints', []):
            name = str(endpoint.get('name', 'endpoint'))
            status, body, detail = fetch_json(
                self._transport, str(endpoint.get('url', '')), float(endpoint.get('timeout', 5))
            )
            result.metrics[f'{name}_status'] = float(status)
            result.data[name] = body
            optional = bool(endpoint.get('optional', False))
            if status == 0:
                result.anomalies.append(
                    Anomaly(
                        kind=f'{name}_unreachable',
                        severity=Severity.WARNING if optional else Severity.CRITICAL,
                        message=f'{name} did not answer: {detail}',
                        signature=f'{name}:unreachable',
                    )
                )
                continue
            if not OK_FLOOR <= status < OK_CEILING:
                result.anomalies.append(
                    Anomaly(
                        kind=f'{name}_status',
                        severity=Severity.CRITICAL,
                        message=f'{name} answered {status}: {detail}',
                        value=float(status),
                        threshold=float(OK_FLOOR),
                        signature=f'{name}:{status}',
                    )
                )
                continue
            result.anomalies.extend(_unexpected(name, endpoint.get('expect'), body))
        return result


def _unexpected(name: str, expect: object, body: object) -> list[Anomaly]:
    """Return one anomaly per field the answer did not say what it was supposed to.

    Args:
        name: the endpoint's name.
        expect: the ``expect`` table: JSON field to required value.
        body: the parsed answer.

    Returns:
        The anomalies, empty when every expectation holds.

    """
    if not isinstance(expect, dict) or not expect:
        return []
    if not isinstance(body, dict):
        return [
            Anomaly(
                kind=f'{name}_unexpected',
                severity=Severity.CRITICAL,
                message=f'{name} was expected to answer JSON but did not',
                signature=f'{name}:not-json',
            )
        ]
    found: list[Anomaly] = []
    for field, wanted in expect.items():
        actual = body.get(field)
        if str(actual) != str(wanted):
            found.append(
                Anomaly(
                    kind=f'{name}_unexpected',
                    severity=Severity.CRITICAL,
                    message=f'{name}.{field} is {actual!r}, expected {wanted!r}',
                    signature=f'{name}:{field}={actual}',
                )
            )
    return found


class ShellProbe(Component):
    """Run a command and judge its output -- by a threshold, or by whether it is moving at all.

    Config::

        [components.shell_probe]
        enabled = true
        [[components.shell_probe.probes]]
        name = "queue"
        command = "wc -l < /var/spool/queue"
        check = "value"      # or "delta" for stall detection
        warning = 100
        critical = 500
        stale_rounds = 3     # only for check = "delta"

    A non-zero exit is an anomaly unless the probe says ``ignore_errors``, because a probe that
    cannot run is not a probe reporting a healthy value.

    """

    name = 'shell_probe'
    description = 'Run a command, parse its output, and check a threshold or detect a stall'

    def check(self, ctx: CheckContext) -> CheckResult:
        """Run every configured probe and judge each.

        Args:
            ctx: the probe's config, its own state slice, and how to run a command.

        Returns:
            The values read, and an anomaly per probe that failed or breached.

        """
        result = CheckResult()
        for probe in ctx.config.get('probes', []):
            result.anomalies.extend(self._one(ctx, probe, result))
        return result

    def _one(self, ctx: CheckContext, probe: dict[str, Any], result: CheckResult) -> list[Anomaly]:
        """Run one probe, recording its value, and return what is wrong with it.

        Args:
            ctx: the check context.
            probe: the probe's table.
            result: the result being built, so a value can be recorded.

        Returns:
            The anomalies this probe produced.

        """
        name = str(probe.get('name', 'probe'))
        command = str(probe.get('command', '')).strip()
        if not command:
            # A PROBE WITH NO COMMAND MEASURED NOTHING, and it used to run `true`. That exits zero
            # with no output, `_as_number('')` reads 0.0, and no threshold is breached -- so a
            # check whose `command` key was misspelled reported a passing value forever. The plan
            # refuses an incomplete deploy plan for exactly this reason; a probe is the same shape
            # one level down.
            return [
                Anomaly(
                    kind=f'{name}_unconfigured',
                    severity=Severity.WARNING,
                    message=f'{name} has no command, so it measures nothing',
                    signature=f'{name}:no-command',
                )
            ]
        ran = ctx.manager.run_capped(
            ['sh', '-c', command],
            memory_max=str(ctx.shared.get('cycle', {}).get('command_ceiling', '400M')),
            timeout=int(probe.get('timeout', 10)),
        )
        if not ran.ok and not probe.get('ignore_errors'):
            return [
                Anomaly(
                    kind=f'{name}_failed',
                    severity=Severity.CRITICAL,
                    message=f'{name} could not run: {ran.detail()}',
                    # THE EXIT CODE IS A CONTAINER, AND A COARSE ONE. `Ran.code` is -1 for a TIMEOUT,
                    # a command that could not be run at all and an OSError alike -- three different
                    # facts under one value -- and two failures that both exit 1 for different reasons
                    # collide just as completely. The policy writes a condition off BY SIGNATURE, so
                    # each of those pairs made the second failure inherit the first one's silence.
                    # The detail is already computed for the message above; it is what names the
                    # condition, so it is what the signature is taken from.
                    signature=f'{name}:{ran.code}:{condition_digest(ran.detail())}',
                )
            ]
        value = _as_number(ran.out)
        result.metrics[name] = value
        if probe.get('check', 'value') == 'delta':
            return _stalled(ctx, probe, name, value)
        return _breached(probe, name, value)


def _as_number(text: str) -> float:
    """Read a number out of a command's output.

    Args:
        text: the output.

    Returns:
        The leading number, or 1.0 when the output is non-empty and has none, or 0.0 when it is
        empty -- so a command that prints a word is still a signal, and one that prints nothing
        is still a zero.

    """
    stripped = text.strip().rstrip('%')
    try:
        return float(stripped)
    except ValueError:
        return 1.0 if stripped else 0.0


def _breached(probe: dict[str, Any], name: str, value: float) -> list[Anomaly]:
    """Judge a value against the probe's thresholds.

    Args:
        probe: the probe's table.
        name: its name.
        value: the value read.

    Returns:
        An anomaly when a threshold was passed, else nothing.

    """
    for label, severity in (('critical', Severity.CRITICAL), ('warning', Severity.WARNING)):
        limit = probe.get(label)
        if limit is not None and value > float(limit):
            return [
                Anomaly(
                    kind=f'{name}_{label}',
                    severity=severity,
                    message=f'{name} is {value}, past its {label} of {limit}',
                    value=value,
                    threshold=float(limit),
                    signature=f'{name}:{label}',
                )
            ]
    return []


def _stalled(ctx: CheckContext, probe: dict[str, Any], name: str, value: float) -> list[Anomaly]:
    """Report when a value has not moved for the configured number of cycles.

    Args:
        ctx: the check context, whose scoped state carries the previous reading.
        probe: the probe's table.
        name: its name.
        value: the value read this cycle.

    Returns:
        An anomaly when the value has been unchanged for long enough.

    """
    previous = ctx.state.get(f'{name}_last')
    unchanged = int(ctx.state.get(f'{name}_unchanged', 0))
    unchanged = unchanged + 1 if previous is not None and float(previous) == value else 0
    ctx.state[f'{name}_last'] = value
    ctx.state[f'{name}_unchanged'] = unchanged
    limit = int(probe.get('stale_rounds', 3))
    if unchanged >= limit:
        return [
            Anomaly(
                kind=f'{name}_stale',
                severity=Severity.CRITICAL,
                message=f'{name} has not moved from {value} in {unchanged} cycles',
                value=value,
                threshold=float(limit),
                signature=f'{name}:stale:{value}',
            )
        ]
    return []


class Heartbeat(Component):
    """Report when the supervisor itself has stopped cycling.

    ``last_cycle`` is written by every cycle, whatever it found. This probe reads it and says
    nothing about the target -- it is the one check whose subject is the supervisor. It only means
    anything when it runs from a DIFFERENT invocation than the one it is judging: a daemon checking
    its own heartbeat is asking a stopped clock for the time.

    Config::

        [components.heartbeat]
        enabled = true
        max_age = 900

    """

    name = 'heartbeat'
    description = 'Report when no cycle has run recently, so a stopped supervisor is not silence'

    def check(self, ctx: CheckContext) -> CheckResult:
        """Compare the last cycle's age against the configured ceiling.

        Args:
            ctx: the probe's config and the framework's read-only timeline.

        Returns:
            An anomaly when no cycle has run within the ceiling.

        """
        limit = float(ctx.config.get('max_age', 900))
        last = str(ctx.timeline.get('last_cycle', ''))
        result = CheckResult()
        seconds = _age(last, str(ctx.timeline.get('now', ''))) if last else None
        if seconds is None:
            # A WATCHDOG THAT CANNOT SEE THE CLOCK IS NOT A WATCHDOG THAT SEES NOTHING WRONG.
            #
            # This is the one component whose job is to notice that the supervisor stopped, and it
            # answered "I could not measure" with silence -- indistinguishable from "the supervisor
            # is fine". `last_cycle` is empty on a state that was never written (missing file,
            # corrupt file, a schema version this build does not know -- see `StateStore.read`),
            # and an unparseable stamp gives the same None.
            #
            # Every other probe in this package treats unmeasurable as an anomaly: an endpoint that
            # answers nothing is CRITICAL, a disk that cannot be read is `disk_check_failed`, a
            # process table with no psutil says so. This one was the outlier.
            result.anomalies.append(
                Anomaly(
                    kind='heartbeat_unmeasurable',
                    severity=Severity.WARNING,
                    message='no cycle has been recorded, so the supervisor cannot tell whether it is still running',
                    signature='supervisor:unmeasurable',
                )
            )
            return result
        result.metrics['cycle_age'] = seconds
        if seconds > limit:
            result.anomalies.append(
                Anomaly(
                    kind='supervisor_stale',
                    severity=Severity.WARNING,
                    message=f'no cycle has run for {int(seconds)}s, past the {int(limit)}s ceiling',
                    value=seconds,
                    threshold=limit,
                    signature='supervisor:stale',
                )
            )
        return result


def _age(stamp: str, at: str) -> float | None:
    """Return how many seconds ago *stamp* was, measured from *at*.

    Args:
        stamp: an ISO-8601 timestamp.
        at: the instant to measure from.

    Returns:
        The age in seconds, or None when either stamp is unreadable.

    """
    try:
        then = datetime.fromisoformat(stamp)
        present = datetime.fromisoformat(at) if at else datetime.now(tz=UTC)
    except ValueError:
        return None
    return (present - then).total_seconds()
