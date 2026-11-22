"""PLANRUN OFFER: a green preflight completed by the issuer and recorded -- and run AGAIN by the door taking the code.

Split out of :mod:`dev_lab.dev.planrunpreflight` (what a preflight checks). Two entries:

* :func:`offered` completes a preflight's verdict with the issuer handshake and records the green for the plan's
  digest TOGETHER WITH the steps file it ran with (:func:`dev_lab.ops.consent.door.record_preflight`).
* :func:`reproved` is what a code-taking door (``sshhold open --plan``) runs right before it uses the code: the
  same preflight, with the recorded steps file (or the one named), NOW. Not green now refuses ``no code used``
  (user ruling 2026-11-22: a code was given on a green that had aged out, the door refused only after the code
  was in hand, and its 30 s window was gone before the preflight could be run again). It costs seconds and no code.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from lab_commons.config import section

from dev_lab.dev.planremote import remote_for
from dev_lab.dev.planrunpreflight import BLOCKED, Readers, preflight
from dev_lab.dev.planrunsteps import Remotes, load_steps
from dev_lab.ops.consent.client import TABLE
from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.consent.door import PLAN_PREFLIGHT_DOOR, Send, handshake, preflighted_steps, record_preflight, ssh_send
from dev_lab.ops.consent.plan import Plan, parsed

__all__ = ['offered', 'reproved']


def offered(
    plan: Plan, found: tuple[bool, list[str]], *, steps: Path | None = None, table: Mapping[str, Any] | None = None,
    send: Send = ssh_send, home: Path | None = None,
) -> tuple[bool, list[str]]:  # fmt: skip
    """*found*, a preflight's verdict, completed by the issuer handshake and recorded for its digest when green.

    *steps* is the steps file the preflight ran with, recorded so the code's door can run it again.
    """
    green, lines = found
    if not green:
        return found
    try:
        asked = [grant['action'] for grant in plan.grants]
        runs = handshake(section(TABLE) if table is None else table, send=send, actions=asked)
    except ConsentRefused as skewed:
        return False, [*lines[:-1], f'issuer: BLOCKED -- {skewed}', BLOCKED]
    record_preflight(plan, steps=steps, home=home)
    said = f'runs dev-lab {runs[:12]}' if runs else 'reports no dev-lab commit'
    return True, [*lines, f'issuer: agrees ({said}); plan {plan.digest[:12]} offered for one code']


def reproved(
    plan_file: Path, steps_file: Path | None = None, *, remotes: Remotes = remote_for, readers: Readers | None = None,
    table: Mapping[str, Any] | None = None, send: Send = ssh_send, home: Path | None = None,
) -> list[str]:  # fmt: skip
    """Run the plan's preflight NOW, for the door about to use a code; its lines when green.

    *steps_file* defaults to the one the plan's last green preflight recorded.

    Raises:
        ConsentRefused: ``no code used`` -- no steps file is known, or the preflight is not green now (its lines).

    """
    plan = parsed(json.loads(plan_file.read_text(encoding='utf-8')))
    named = steps_file or preflighted_steps(plan, home=home)
    if named is None:
        msg = (f'no code used: plan {plan.digest[:12]} has no green preflight recorded with its steps file, so this '
               f'door cannot check it now: run `{PLAN_PREFLIGHT_DOOR}` (or pass --steps <steps.json>), then give '
               'the code')  # fmt: skip
        raise ConsentRefused(msg)
    try:
        steps = load_steps(named, plan)
    except (ConsentRefused, OSError, ValueError) as unread:
        msg = f'no code used: the steps file {named} does not fit plan {plan.digest[:12]} ({unread})'
        raise ConsentRefused(msg) from unread
    green, lines = offered(
        plan, preflight(plan, steps, remotes, readers=readers), steps=named, table=table, send=send, home=home
    )
    if not green:
        said = '\n'.join(lines)
        msg = f'no code used: the preflight this door ran itself (steps {named}) is not green now --\n{said}'
        raise ConsentRefused(msg)
    return lines
