"""ONE CODE, ONE PLAN: ``sshhold open --plan`` -- the code opens the plan's hosts, then buys its credentials.

User ruling 2026-11-10; topology.md 5.1. The same code first opens EVERY plan host not already held, concurrently,
then buys one single-use consent credential per grant of the plan the user was shown
(:func:`dev_lab.ops.consent.client.grant_plan`; the digest is ``python -m dev_lab.ops.consent plan <plan.json>``'s)
-- the cluster's one TOTP secret is verified by each host's pam_oath and the issuer, each once
(:mod:`dev_lab.ops.consent.plan`). HOSTS FIRST (issue #1072): granting first and then logging in to a host whose
hold had expired spent the code at the issuer and the login was refused, so a second code was needed. A host that
fails is REPORTED, never retried with the code, and the code then never reaches the issuer: the hosts that opened
stay held, so the same command with a new code reuses them and spends it on the issuer alone.

A plan host whose session is ALREADY HELD is reused, never re-opened: the code goes to the issuer alone (incident
2026-11-16: the open refused a held host, so a granted plan read as failed and a second code was asked). Before the
code is read the door PREFLIGHTS THE PLAN ITSELF (:func:`offered`, :func:`dev_lab.dev.planrunoffer.reproved`: the
steps file its last green preflight recorded, or ``--steps``): not green NOW refuses ``no code used`` (user ruling
2026-11-22: the stale green was refused only after the code was given, and the code's window was lost). A code GIVEN
IN ADVANCE is sent at once on a fresh recorded green; on an older one the door re-runs the preflight itself and sends
the code right after it (issue #1064, the code-first rule #985: refusing it unspent wasted two user codes on
2026-11-27), refusing it unspent only when that fresh preflight is not green.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from pathlib import Path

from dev_lab.dev.planrunoffer import reproved
from dev_lab.dev.sshholdstate import audit
from dev_lab.dev.sshholdwire import HoldRefused
from dev_lab.dev.sshholdwire import held as live_hold
from dev_lab.ops.consent.client import grant_plan
from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.consent.door import CODE_PREFLIGHT_FRESH_S, green_age
from dev_lab.ops.consent.plan import not_registered, parsed, unregistered

__all__ = ['offered', 'open_planned']


def open_planned(
    hours: float, code: str, plan: Path, shown: str, *, routes: Callable[[str], tuple[str, ...]],
    grant: Callable[[Path, str, str, str], list[Path]] = grant_plan,
    opener: Callable[..., str],
    clock: Callable[[], float] = time.monotonic,
    held: Callable[[str], bool] | None = None,
    received: float | None = None,
) -> tuple[bool, list[str]]:  # fmt: skip
    """Spend ONE *code* on every unheld plan host's session, then on *plan* (the one *shown*): ``(all done, lines)``.

    The caller checked ``--hours`` against its ceiling; *opener* opens one host (:func:`.sshhold.open_session`).

    THE HOSTS OPEN FIRST (issue #1072), each unheld one concurrently on its own *routes* (:func:`.sshhold.route`).
    A host *held* already is reused, never re-opened -- held means LIVE (:func:`.sshholdwire.held`: its holder
    answers and its ssh connection still runs); a dead hold's record is removed and the host is opened like any
    other. Only once EVERY host is held does the code go to the issuer. A host that fails is a line naming it, and
    the code never reaches the issuer: the hosts that opened stay held, so the same command with a new code reuses
    them and spends that code on the failed hosts and the issuer -- the code is never sent twice to one verifier.
    """
    found = parsed(json.loads(plan.read_text(encoding='utf-8')))
    if stale := unregistered(found):
        msg = f'the plan was not granted, no code sent: {not_registered(stale)}'
        raise HoldRefused(msg)
    said = {dest: f'{dest}: held session reused (no code sent)' for dest in found.hosts if (held or live_hold)(dest)}

    def one(dest: str) -> None:
        try:
            said[dest] = opener(dest, hours, code, ssh=routes(dest))
        except (HoldRefused, OSError) as refused:
            said[dest] = f'{dest}: NOT opened ({refused})'

    threads = [threading.Thread(target=one, args=(dest,), daemon=True) for dest in found.hosts if dest not in said]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    lines = [said[dest] for dest in found.hosts]
    if failed := ', '.join(dest for dest in found.hosts if 'NOT opened' in said[dest]):
        lines.append(
            f'the plan was NOT granted: {failed} did not open, so the code was never sent to the issuer; the hosts '
            f'that opened stay held -- re-run this same open with a new code: it opens {failed} and grants the plan'
        )
        return False, lines
    given = clock()
    lines.append(
        f'code sent to the issuer {given - (given if received is None else received):.1f} s after it was given'
    )
    try:
        written = grant(plan, shown, code, found.hosts[0])
    except ConsentRefused as refused:
        msg = f'the plan was not granted (every host is held): {refused}'
        raise HoldRefused(msg) from refused
    audit('plan', ','.join(found.hosts), command=shown, status=0, grants=len(written))
    return True, [*lines, *(f'consent granted: {path}' for path in written)]


def offered(
    plan: Path, steps: Path | None = None, *, code_given: bool = False,
    rerun: Callable[[Path, Path | None], list[str]] | None = None, held: Callable[[str], bool] | None = None,
    home: Path | None = None, now: float | None = None,
) -> str:  # fmt: skip
    """Run *plan*'s preflight NOW, before its code is read; not green refuses ``no code used``, as :class:`HoldRefused`.

    *steps* defaults to the steps file the plan's last green preflight recorded (:func:`.planrunoffer.reproved`).
    Every plan host is first proven LIVE-held or cleared (:func:`.sshholdwire.held`), so green means each host is
    reached through a live hold or is one the code will open -- never a dead hold read as reused.

    A code GIVEN IN ADVANCE (*code_given*) is already counting down: a green recorded for the SAME digest within
    :data:`~dev_lab.ops.consent.door.CODE_PREFLIGHT_FRESH_S` stands in for the re-run. Older (or none), the door
    re-runs the preflight HERE and the code is sent right after it (issue #1064: refusing it unspent and asking the
    user to re-run preflight wasted two codes); only a fresh preflight that is not green refuses it, ``no code used``.
    A code asked at the prompt (asked only after this returns) always runs the preflight. Returns the line saying
    which.
    """
    try:
        found = parsed(json.loads(plan.read_text(encoding='utf-8')))
        for dest in found.hosts:
            (held or live_hold)(dest)  # a dead hold goes BEFORE the preflight: its host is then one the code opens
        if code_given:
            age = green_age(found, home=home, now=now)
            if age is not None and age <= CODE_PREFLIGHT_FRESH_S:
                return f'preflight: recorded green {age:.0f} s ago (within {CODE_PREFLIGHT_FRESH_S:.0f} s): not re-run'
            why = 'none recorded' if age is None else f'the recorded green was {age:.0f} s old'
            (rerun or reproved)(plan, steps)
            return (f'preflight: re-run here before the given code ({why}, past {CODE_PREFLIGHT_FRESH_S:.0f} s), '
                    'green: the code is sent now')  # fmt: skip
        (rerun or reproved)(plan, steps)
    except (ConsentRefused, OSError, ValueError) as refused:
        raise HoldRefused(str(refused)) from refused
    return 'preflight: re-run here, green'
