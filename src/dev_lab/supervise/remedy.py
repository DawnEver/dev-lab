"""Applying a remedy chain -- one implementation, for every caller that has one.

The predecessor stated this requirement and then split the implementation across two: a module for
the daemon and a loop for the AI, with the chain resolution duplicated between them. It recorded
the debt itself -- *"the remedy chain declared in two places, hardcoded in the component against
configured in the config, with the precedence to be unified"* -- and never paid it, which is why a
chain could mean two things depending on who ran it.

WHAT A STEP IS. A gate, an action, and a retry count. The gate is a severity and an optional
metric comparison; the action is either a shell line or something a component implements; the
retry count is how many times to try before giving up on this step. Nothing here decides WHETHER
to alert about the outcome -- that is :mod:`dev_lab.supervise.policy`, and keeping the two
apart is what lets either be read alone.

A REMEDY COMMAND RUNS UNDER A CEILING. Every command goes through the process manager's capped
runner, so a reinstall or a migration cannot take the host down while the supervisor watches.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from dev_lab.supervise.component import ActionContext, Handler, Registry
from dev_lab.supervise.state import count_remedy
from dev_lab.supervise.verdict import Action, Anomaly, RemedyStep

__all__ = ['Attempt', 'apply_chain']

#: What a remedy command is given when the configuration names no ceiling.
DEFAULT_CEILING: Final = '400M'


@dataclass(frozen=True)
class Attempt:
    """What one step did, or why it did not run.

    Attributes:
        source: the anomaly this step was reached from.
        action: the step's action name.
        ok: whether it succeeded. False for a step that was skipped, which is why *skipped* exists.
        detail: what the action said, or the reason it was skipped.
        skipped: True when a gate held the step rather than the step failing -- a report must be
            able to tell "we chose not to" from "we tried and it did not work".

    """

    source: str
    action: str
    ok: bool
    detail: str = ''
    skipped: bool = False

    @property
    def ran(self) -> bool:
        """Return whether the step actually ran.

        Returns:
            True when the step was attempted rather than skipped.

        """
        return not self.skipped


def apply_chain(
    registry: Registry,
    anomaly: Anomaly,
    ctx: ActionContext,
    state: dict[str, Any],
    *,
    metrics: Mapping[str, float],
    dry_run: bool = False,
) -> list[Attempt]:
    """Run the remedy chain declared for *anomaly*, recording every attempt.

    Args:
        registry: what resolves the chain, the actions and their implementations.
        anomaly: the anomaly to remedy.
        ctx: the acting context -- config, project, process manager, and the registry itself.
        state: the run's state, where each attempt is recorded.
        metrics: the numbers the check reported, for a step's condition to be judged against.
        dry_run: resolve and gate the chain, but do not run anything.

    Returns:
        One attempt per step that was reached, in chain order.

    """
    ceiling = str(ctx.shared.get('cycle', {}).get('command_ceiling', DEFAULT_CEILING))
    attempts: list[Attempt] = []
    for step in registry.remedies(anomaly.kind):
        held = _held(step, anomaly, metrics)
        if held is not None:
            attempts.append(Attempt(source=anomaly.source, action=step.action, ok=False, detail=held, skipped=True))
            continue
        attempts.append(_run(registry, step, anomaly, ctx, state, ceiling=ceiling, dry_run=dry_run))
    return attempts


def _held(step: RemedyStep, anomaly: Anomaly, metrics: Mapping[str, float]) -> str | None:
    """Return why *step* should not run, or None when it should.

    Args:
        step: the step being considered.
        anomaly: the anomaly it would remedy.
        metrics: the numbers the check reported.

    Returns:
        A one-line reason, or None.

    """
    if not step.on.admits(anomaly.severity):
        return f'gated off: this step is for {step.on.value}, the anomaly is {anomaly.severity.value}'
    if step.condition is not None and not step.condition.holds(metrics):
        return f'condition not met: {step.condition.metric} {step.condition.op} {step.condition.value}'
    return None


def _run(
    registry: Registry,
    step: RemedyStep,
    anomaly: Anomaly,
    ctx: ActionContext,
    state: dict[str, Any],
    *,
    ceiling: str,
    dry_run: bool,
) -> Attempt:
    """Run one step, retrying it up to its own attempt count.

    Args:
        registry: the registry, for resolving the action.
        step: the step to run.
        anomaly: the anomaly it remedies.
        ctx: the acting context.
        state: the run's state.
        ceiling: the memory ceiling for a command.
        dry_run: resolve without running.

    Returns:
        What the step did.

    """
    handler = registry.handler(step.action)
    action = registry.action(step.action)
    if handler is None and (action is None or action.command is None):
        detail = f'no action named {step.action!r} is declared by any component'
        count_remedy(state, {'source': anomaly.source, 'action': step.action, 'ok': False, 'detail': detail})
        return Attempt(source=anomaly.source, action=step.action, ok=False, detail=detail)
    if dry_run:
        return Attempt(source=anomaly.source, action=step.action, ok=True, detail='dry run')

    detail = ''
    for _attempt in range(max(1, step.max_attempts)):
        ok, detail = _once(handler, action, ctx, ceiling)
        if ok:
            break
    count_remedy(state, {'source': anomaly.source, 'action': step.action, 'ok': ok, 'detail': detail})
    return Attempt(source=anomaly.source, action=step.action, ok=ok, detail=detail)


def _once(handler: Handler | None, action: Action | None, ctx: ActionContext, ceiling: str) -> tuple[bool, str]:
    """Perform one attempt of an action, by whichever half of it exists.

    Args:
        handler: the component's implementation, when there is one.
        action: the declaration, when there is one.
        ctx: the acting context.
        ceiling: the memory ceiling for a command.

    Returns:
        Whether it succeeded, and what it said.

    """
    if handler is not None:
        try:
            ok = bool(handler(ctx))
        except Exception as exc:  # noqa: BLE001
            return False, f'{type(exc).__name__}: {exc}'
        return ok, 'implemented by the component' if ok else 'the component reported failure'
    if action is None or action.command is None:
        return False, 'the resolved action has neither an implementation nor a command'
    ran = ctx.manager.run_capped(['sh', '-c', action.command], memory_max=ceiling, timeout=action.timeout)
    return ran.ok, ran.detail()
