"""One supervision cycle: measure everything, act on what is wrong, say what happened.

The order is the whole design. Measure first and act second, because a remedy chosen before the
measurement is a remedy for last cycle's problem. Say what happened third, because an alert that
precedes the action cannot report its outcome.

CHECKS RUN ONE AT A TIME, and that is deliberate rather than lazy. This family deploys to a
two-core box where a supervisor running its probes concurrently is a supervisor competing with the
service it supervises -- and the memory ceilings the rest of this kit enforces would be beside the
point if the supervisor itself forked a fleet. A check that hangs is bounded by
``cycle.check_timeout``; the thread behind it is ABANDONED rather than killed, because Python
cannot kill a thread, and that limit is stated here rather than hidden.

MUTUAL EXCLUSION IS THE BROKER'S, not a lock of this module's own. A second cycle on the same
target is refused with a message naming the holder. The kit states the rule plainly -- a byte-range
lock, a pid file or a heartbeat would each be a second definition of the same thing -- so the seat
is a seat on the one box ledger (:func:`lab_commons.box.hold`) and there is no other.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from lab_commons.box import hold

from dev_lab.supervise.alert import Delivery, Notice, Notifier
from dev_lab.supervise.component import ActionContext, CheckContext, Registry
from dev_lab.supervise.policy import decide
from dev_lab.supervise.process.base import ProcessManager
from dev_lab.supervise.remedy import Attempt, apply_chain
from dev_lab.supervise.state import (
    StateStore,
    clear_anomaly,
    count_anomaly,
    mark_notified,
    new_state,
    note_cycle,
    note_quiet,
)
from dev_lab.supervise.verdict import Anomaly, CheckResult, Completion, Severity

__all__ = [
    'CHECK_FAILED',
    'DEPLOY_SLICE',
    'STATE_LOST',
    'UNCONFIGURED',
    'CycleResult',
    'run_cycle',
]

#: How long a cycle waits for the seat before giving up. A second cycle that queues behind a slow
#: one is a supervisor whose own schedule slips; refusing says so instead.
SEAT_WAIT: Final = 0.0

#: The most a cycle's seat is held, in seconds: past it the ledger lets the next cycle in.
CYCLE_WALL_S: Final = 3600

#: The severity of an anomaly raised because a check itself failed. It is CRITICAL: a probe that
#: cannot run is worse than a probe that reports a problem, because nothing is watching.
CHECK_FAILED: Final = 'check_failed'

#: Raised when the cycle's own state could not be written. The supervisor is about to forget what
#: it just decided -- its counters, its suppression timestamps, its rollback floor.
STATE_LOST: Final = 'state_lost'

#: The state slice an action is handed WHEN THE CHAIN HAS NO OWNING COMPONENT -- one declared by a
#: configuration override rather than by a component's own ``remedies()``. An action normally shares
#: the slice of the component it belongs to, so that what it records is what that component's check
#: reads back; a chain with no owner shares this one, which is what having no owner means.
DEPLOY_SLICE: Final = 'actions'

#: Raised when nothing is enabled. Also critical, for the same reason and one more: a supervisor
#: that is watching nothing reports a clean run every time, which is the failure that looks most
#: like success.
UNCONFIGURED: Final = 'unconfigured'


@dataclass(frozen=True)
class CycleResult:
    """What one cycle found, did and said.

    Attributes:
        status: ``healthy`` when nothing was wrong, else ``degraded``.
        metrics: every number the checks reported, by metric name.
        anomalies: what was wrong, with sources stamped.
        completions: tasks that finished successfully.
        attempts: every remedy step reached, in order.
        deliveries: what each alert channel did with the notices that were warranted.
        state: the state as it was left, for a caller that wants to report a delta.

    """

    status: str
    metrics: dict[str, float] = field(default_factory=dict)
    anomalies: list[Anomaly] = field(default_factory=list)
    completions: list[Completion] = field(default_factory=list)
    attempts: list[Attempt] = field(default_factory=list)
    deliveries: list[Delivery] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)


def _check_one(
    *,
    component_name: str,
    registry: Registry,
    config: Mapping[str, Any],
    state: dict[str, Any],
    project: Path,
    manager: ProcessManager,
    clock: datetime,
    timeout: int,
) -> CheckResult:
    """Run one component's check under a hard wall.

    Args:
        component_name: the component to run.
        registry: where the component and the component-owned state slice come from.
        config: the merged configuration.
        state: the run's state.
        project: the target's directory.
        manager: how a check that shells out runs its command.
        clock: the instant this cycle is judged at.
        timeout: seconds to allow the check.

    Returns:
        The check's result, or a single critical anomaly when the check itself failed -- including
        when it ran too long, because a check that never answers is a check that is not watching.

    """
    component = registry.get(component_name)
    if component is None:
        return CheckResult()
    scoped = state.setdefault('components', {}).setdefault(component_name, {})
    ctx = CheckContext(
        config=registry.config_for(component_name),
        shared=config,
        state=scoped,
        project=project,
        manager=manager,
        timeline={
            'now': clock.isoformat(),
            'last_cycle': state.get('last_cycle', ''),
            'last_quiet': state.get('last_quiet', ''),
        },
    )
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(component.check, ctx)
        try:
            return future.result(timeout=timeout)
        except TimeoutError:
            return CheckResult(
                anomalies=[
                    Anomaly(
                        kind=CHECK_FAILED,
                        severity=Severity.CRITICAL,
                        message=f'{component_name} did not answer within {timeout}s',
                        signature=f'{component_name}:timeout',
                    )
                ]
            )
        except Exception as exc:  # noqa: BLE001
            return CheckResult(
                anomalies=[
                    Anomaly(
                        kind=CHECK_FAILED,
                        severity=Severity.CRITICAL,
                        message=f'{component_name} raised {type(exc).__name__}: {exc}',
                        signature=f'{component_name}:{type(exc).__name__}',
                    )
                ]
            )
    finally:
        # NOT a `with` block: its __exit__ calls shutdown(wait=True), which joins the very thread
        # the timeout exists to stop waiting for -- so a check that hung would hang the cycle and
        # the wall would bound nothing. `wait=False` abandons the thread instead, which is stated
        # in this module's docstring as the honest limit of a timeout Python cannot enforce.
        pool.shutdown(wait=False)


def _is_enabled(sections: Mapping[str, Any], name: str) -> bool:
    """Return whether the component *name* is on, from the configuration alone.

    Default-ON, which is deliberate: a target that installed a supervisor wants its probes running,
    and an explicit disable is one line. The whole decision is one line here so that the loop and
    the registry cannot answer it differently.

    Args:
        sections: the ``components`` table.
        name: the component's name.

    Returns:
        Whether it should run.

    """
    section = sections.get(name, {})
    return bool(section.get('enabled', True)) if isinstance(section, Mapping) else True


def _unconfigured(message: str) -> Anomaly:
    """Return the anomaly that says a supervisor is watching nothing.

    Args:
        message: which arrangement produced it -- no sections at all, or all of them disabled.

    Returns:
        The anomaly.

    """
    return Anomaly(
        kind=UNCONFIGURED,
        severity=Severity.CRITICAL,
        message=message,
        source=f'supervise.{UNCONFIGURED}',
        signature='unconfigured',
    )


def _gather(
    registry: Registry,
    *,
    config: Mapping[str, Any],
    state: dict[str, Any],
    project: Path,
    manager: ProcessManager,
    clock: datetime,
) -> tuple[dict[str, float], list[Anomaly], list[Completion]]:
    """Run every enabled check, one at a time, and stamp what they found.

    Args:
        registry: the components to run.
        config: the merged configuration.
        state: the run's state.
        project: the target's directory.
        manager: how a check that shells out runs its command.
        clock: the instant this cycle is judged at.

    Returns:
        The metrics, the anomalies with their sources stamped, and the completions.

    """
    timeout = int(config.get('cycle', {}).get('check_timeout', 60))
    metrics: dict[str, float] = {}
    anomalies: list[Anomaly] = []
    completions: list[Completion] = []
    sections = config.get('components', {})
    if not sections:
        # A SCAN THAT READ NOTHING IS NOT A CLEAN SCAN, and this arm was unreachable.
        #
        # `Registry.enabled()` is default-ON for every REGISTERED component -- deliberately, so a
        # target that installed a supervisor gets its probes running without listing them. The
        # consequence is that a config with no component sections leaves eight components enabled
        # with nothing to check: `http_health` has no endpoints, `shell_probe` no probes, `deploy`
        # no repositories, and each of them reports clean because there is nothing for it to find
        # wrong. The cycle came back healthy over a supervisor watching nothing at all.
        #
        # So the refusal the config module documents -- "the loop refuses to call a run with no
        # components enabled healthy" -- tested the one arrangement nobody reaches: a config that
        # explicitly disables all eight. This is the arrangement that happens, and it is what a
        # missing config file, an empty one, or a section header typed with the wrong name all
        # produce.
        nothing = 'no component section is configured, so nothing is being watched'
        return (metrics, [_unconfigured(nothing)], completions)
    # ENABLEMENT IS READ FROM THE CONFIG THIS RUN WAS HANDED, not from the registry's own copy of
    # it. `Registry.enabled()` reads `_configs`, which only `Registry.configure` fills, so the loop
    # and the registry each held a version of the same fact and agreed only because the CLI happens
    # to call `configure` with the same mapping. Two sources for one fact is the arrangement this
    # family refuses everywhere else, and it is invisible precisely until they disagree.
    enabled = [component for name, component in registry.components.items() if _is_enabled(sections, name)]
    if not enabled:
        all_off = 'every configured component is disabled, so nothing is being watched'
        return (metrics, [_unconfigured(all_off)], completions)
    for component in enabled:
        result = _check_one(
            component_name=component.name,
            registry=registry,
            config=config,
            state=state,
            project=project,
            manager=manager,
            clock=clock,
            timeout=timeout,
        )
        metrics.update(result.metrics)
        completions.extend(result.completions)
        for anomaly in result.anomalies:
            anomaly.source = f'{component.name}.{anomaly.kind}'
            anomalies.append(anomaly)
    return metrics, anomalies, completions


def _notify(
    anomalies: list[Anomaly],
    registry: Registry,
    *,
    config: Mapping[str, Any],
    state: dict[str, Any],
    clock: datetime,
    notifier: Notifier,
) -> list[Delivery]:
    """Decide what is worth saying, and say it.

    Args:
        anomalies: what is wrong.
        registry: where each anomaly's escalation threshold comes from.
        config: the merged configuration.
        state: the run's state, whose counters the decision updates.
        clock: the instant to judge cooldowns against.
        notifier: how a warranted notice is delivered.

    Returns:
        One delivery per channel per notice actually sent.

    """
    sent: list[Delivery] = []
    for anomaly in anomalies:
        escalation = _escalation_for(registry, anomaly.kind)
        verdict = decide(
            state, anomaly.source, anomaly.signature or anomaly.message, config, clock=clock, escalate_after=escalation
        )
        if not verdict.notify:
            continue
        notice = Notice(subject=f'{anomaly.source}: {anomaly.message}', body=anomaly.message, severity=anomaly.severity)
        delivered = notifier.send(notice)
        sent.extend(delivered)
        # RECORDED ONLY IF SOMETHING TOOK IT, and this ordering is the point. The decision to send
        # used to write `last_alert` itself, before the notifier ran -- so a notice every channel
        # refused still carried a timestamp saying it had gone, and the cooldown brake measures from
        # that timestamp. One failed delivery suppressed its own retry, and the write-off made the
        # silence permanent: the channel outage became invisible by bookkeeping.
        #
        # An empty list means nothing was enabled, which is a configuration fact rather than a
        # failure -- there was no channel to lose, so there is nothing to retry either.
        if any(one.ok for one in delivered):
            mark_notified(state, anomaly.source, clock.isoformat())
    return sent


def _escalation_for(registry: Registry, kind: str) -> int | None:
    """Return the escalation threshold any step in a chain declares for *kind*.

    Args:
        registry: where the chain comes from.
        kind: the anomaly's type.

    Returns:
        The first non-null threshold, or None when no step declares one.

    """
    for step in registry.remedies(kind):
        if step.escalate_after is not None:
            return step.escalate_after
    return None


def run_cycle(
    registry: Registry,
    store: StateStore,
    config: Mapping[str, Any],
    project: Path,
    manager: ProcessManager,
    *,
    clock: datetime,
    notifier: Notifier | None = None,
    dry_run: bool = False,
) -> CycleResult:
    """Run one cycle: measure, act, say.

    Args:
        registry: the components, actions and chains.
        store: where the state lives.
        config: the merged configuration.
        project: the target's directory.
        manager: how a remedy reaches the service's process.
        clock: the instant this cycle is judged at.
        notifier: how a notice is delivered. Defaults to one over the merged config.
        dry_run: resolve and gate everything, but run no action and send no notice.

    Returns:
        What the cycle found, did and said.

    Raises:
        lab_commons.box.Refused: another cycle holds this target's seat.

    """
    state = store.read() or new_state()
    seat = re.sub(r'[^a-z0-9_]', '_', f'supervise_{config.get("target", {}).get("name", "unknown")}'.lower())
    with hold({seat: 1}, CYCLE_WALL_S, 'supervision cycle', SEAT_WAIT, key=seat):
        metrics, anomalies, completions = _gather(
            registry, config=config, state=state, project=project, manager=manager, clock=clock
        )
        note_cycle(state, clock.isoformat())
        # EACH SOURCE IS CLEARED ON ITS OWN EVIDENCE. Clearing used to be all-or-nothing -- every
        # counter dropped when a cycle came back with no anomalies at all -- so a single live
        # condition kept every dead one on the books, frozen at the count and the alert time it
        # had when it stopped. Measured on the real host: a health probe still carried an entry an
        # hour after the defect behind it was repaired, because two unrelated anomalies were still
        # firing, and its escalation clock kept ticking against a component that was answering.
        reported = {anomaly.source for anomaly in anomalies}
        for source in list(state.get('anomalies', {})):
            if source not in reported:
                clear_anomaly(state, source)
        attempts: list[Attempt] = []
        if anomalies:
            # THE ACTION GETS ITS OWN COMPONENT'S SECTION AND ITS OWN COMPONENT'S SLICE, because
            # `ActionContext` documents both that way and the acting path passed neither.
            #
            # The config half: the whole components table was passed, so every acting component
            # read an empty mapping. The deploy component built an empty plan from it and refused
            # every release, reporting "missing: repositories, unit, health, install, run, probe"
            # for six settings that were in the file the whole time.
            #
            # The state half, and it was the worse one: a check is handed
            # `state['components'][component]` while an action was handed a SHARED
            # `state['components']['actions']`. So the deploy component read its deployment history
            # out of one dict and wrote the snapshot into another -- `check` never saw a verified
            # release, `no_verified_release` warned forever about a target that had deployed
            # successfully, and `failure_streak` counted failures recorded somewhere it never
            # looked, so a release could fail without limit and the escalation could never fire.
            sections = config.get('components', {})
            scoped = state.setdefault('components', {})
            for anomaly in anomalies:
                count_anomaly(state, anomaly.source)
                owner = registry.owner(anomaly.kind)
                ctx = ActionContext(
                    config=sections.get(owner, {}),
                    shared=config,
                    project=project,
                    manager=manager,
                    registry=registry,
                    state=scoped.setdefault(owner or DEPLOY_SLICE, {}),
                )
                attempts.extend(apply_chain(registry, anomaly, ctx, state, metrics=metrics, dry_run=dry_run))
        else:
            note_quiet(state, clock.isoformat())
        deliveries = (
            []
            if dry_run
            else _notify(
                anomalies,
                registry,
                config=config,
                state=state,
                clock=clock,
                notifier=notifier or Notifier(config=config),
            )
        )
        if not store.write(state):
            # A STATE THAT DID NOT PERSIST IS A SUPERVISOR THAT IS ABOUT TO FORGET, and the answer
            # used to be thrown away. `StateStore.write` returns False when the atomic publish did
            # not land, and this was its only production caller -- so the counters, the suppression
            # timestamps and the release history silently rolled back to the previous file's
            # contents on the next read: suppressions release, escalation counts reset, and the
            # rollback floor can be lost. The cycle still completed and reported normally.
            anomalies.append(
                Anomaly(
                    kind=STATE_LOST,
                    severity=Severity.WARNING,
                    message='this cycle could not be written down, so the next one will not remember it',
                    source=f'supervise.{STATE_LOST}',
                    signature='state-lost',
                )
            )
    return CycleResult(
        status='degraded' if anomalies else 'healthy',
        metrics=metrics,
        anomalies=anomalies,
        completions=completions,
        attempts=attempts,
        deliveries=deliveries,
        state=state,
    )
