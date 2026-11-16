"""ONE CODE, ONE PLAN: ``sshhold open --plan`` -- the code buys the plan's credentials, then opens its hosts.

User ruling 2026-11-10; topology.md 5.1. The same code first buys one single-use consent credential per grant of the
plan the user was shown (:func:`dev_lab.ops.consent.client.grant_plan`; the digest is ``python -m
dev_lab.ops.consent plan <plan.json>``'s), then opens EVERY plan host, concurrently, inside :data:`OPEN_WINDOW_S` of
the code -- the cluster's one TOTP secret is verified by the issuer and each host's pam_oath, each once
(:mod:`dev_lab.ops.consent.plan`). A host that fails or misses the window is REPORTED, never retried with the code:
granting spends no credential, so no grant on any host is spent, and that host alone is re-opened with a new code
(``open <dest> --hours H``).

A plan host whose session is ALREADY HELD is reused, never re-opened: the code goes to the issuer alone (incident
2026-11-16: the open refused a held host, so a granted plan read as failed and a second code was asked). Before the
code is asked the plan passes :func:`offered` (:func:`dev_lab.ops.consent.door.offer`: a green preflight and an
issuer this client agrees with).
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Final

from lab_commons.config import section

from dev_lab.dev.sshholdstate import audit, read_session
from dev_lab.dev.sshholdwire import HoldRefused, ping
from dev_lab.ops.consent.client import TABLE, grant_plan
from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.consent.door import Send, offer, ssh_send
from dev_lab.ops.consent.plan import STALE_CLIENT, parsed, stale_client
from dev_lab.ops.totp import STEP

__all__ = ['OPEN_WINDOW_S', 'offered', 'open_planned']

#: How long after the code a plan's host session may still be STARTED: one TOTP step. A host not started inside it
#: is reported, never sent the code (topology.md 5.1).
OPEN_WINDOW_S: Final = float(STEP)


def open_planned(
    hours: float, code: str, plan: Path, shown: str, *, routes: Callable[[str], tuple[str, ...]],
    grant: Callable[[Path, str, str, str], list[Path]] = grant_plan,
    opener: Callable[..., str],
    clock: Callable[[], float] = time.monotonic,
    held: Callable[[str], bool] | None = None,
) -> tuple[bool, list[str]]:  # fmt: skip
    """Spend ONE *code* on *plan* (the one *shown*), then on every plan host's session: ``(all open, lines)``.

    The caller checked ``--hours`` against its ceiling; *opener* opens one host (:func:`.sshhold.open_session`).

    The issuer grant comes first; then each host opens concurrently, started only inside :data:`OPEN_WINDOW_S` of
    the code, each on its own *routes* (:func:`.sshhold.route`). A host that fails is a line naming it and how to
    re-open it -- the code is never sent twice. A host *held* already (default: a live session) is reused, never
    re-opened.
    """
    found = parsed(json.loads(plan.read_text(encoding='utf-8')))
    if stale := stale_client(found):
        msg = f'the plan was not granted, no code sent: {stale} unknown to this client: {STALE_CLIENT}'
        raise HoldRefused(msg)
    reused = [dest for dest in found.hosts if (held or _held)(dest)]
    given = clock()
    try:
        written = grant(plan, shown, code, found.hosts[0])
    except ConsentRefused as refused:
        msg = f'the plan was not granted: {refused}'
        raise HoldRefused(msg) from refused
    audit('plan', ','.join(found.hosts), command=shown, status=0, grants=len(written))
    lines = [f'consent granted: {path}' for path in written]
    said = {dest: f'{dest}: held session reused (no code sent)' for dest in reused}

    def one(dest: str) -> None:
        try:
            said[dest] = opener(dest, hours, code, ssh=routes(dest))
        except (HoldRefused, OSError) as refused:
            said[dest] = f'{dest}: NOT opened ({refused})'

    late = clock() - given > OPEN_WINDOW_S
    opening = [dest for dest in found.hosts if dest not in said]
    threads = [threading.Thread(target=one, args=(dest,), daemon=True) for dest in opening if not late]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    for dest in found.hosts:
        if late and dest in opening:
            said[dest] = f'{dest}: NOT opened (the grant took past the {OPEN_WINDOW_S:g} s window; code not sent)'
        if 'NOT opened' in said[dest]:
            said[dest] += (f'; no credential is spent -- re-open it alone with a new code: '
                           f'python -m dev_lab.dev.sshhold open {dest} --hours {hours:g}')  # fmt: skip
        lines.append(said[dest])
    return all('NOT opened' not in said[dest] for dest in found.hosts), lines


def _held(dest: str) -> bool:
    return (session := read_session(dest)) is not None and ping(session)


def offered(plan: Path, *, send: Send = ssh_send) -> None:
    """Refuse *plan* before its code is asked (:func:`dev_lab.ops.consent.door.offer`), as :class:`HoldRefused`."""
    try:
        offer(parsed(json.loads(plan.read_text(encoding='utf-8'))), section(TABLE), send=send)
    except ConsentRefused as refused:
        raise HoldRefused(str(refused)) from refused
