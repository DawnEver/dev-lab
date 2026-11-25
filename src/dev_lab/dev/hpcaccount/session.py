"""THE INTEGRATOR IS A SESSION OR TASK ROLE, PROVED BY A CONSENT CREDENTIAL -- never a host's (2026-11-12, -13).

A host file declares only what its MACHINE may reach (``[dev] hpc``, rendered as ``[hpc] reach``). Verification
accounts are reached by a SESSION holding the integrator role, on a machine whose reach is not empty: the family
declares ``[hpc] session_reach = { integrator = ["verification"] }`` and ``[hpc] session_verifier`` naming
:func:`roles`, which :func:`lab_commons.hpc.grants.load_grants` calls -- so the ``lab_commons.hpc`` door and every
``dev_lab.dev.hpcaccount`` verb (all of which load through it) check the role before they touch an account.

THE ROLE IS NEVER SELF-CLAIMED. It is a consent credential of :mod:`dev_lab.ops.consent` the user grants with one
TOTP code, held by one of two identities:

* a SESSION -- :data:`ACTION`, subject = the canonical native harness identity, a day at most;
* a TASK -- :data:`TASK_ACTION`, subject = the task id ``<slug>@<authority>``, a week at most. A task is a directory
  ``<slug>/`` of the machine's one task ledger (:func:`dev_lab.dev.taskledger.ledger`) whose ``TASK.md`` the
  user's own task-open wrote with the ``authority`` minted then: a task closed and reopened under the same slug is a
  new id, so an old grant never carries over.

A SESSION WORKS ON THE TASK ITS BRANCH NAMES: the checkout's ``pr/<slug>/<feature>`` of a task open in the ledger
(:func:`dev_lab.dev.taskledger.task_of`, user ruling 2026-11-23), read here as the task whose grant it inherits.

:func:`held` verifies OFFLINE on every load -- signature, registry row, expiry, subject, and for a task the
branch's task -- so an expired credential, another session's or task's, or a branch naming no open task grants nothing.

Granting it (the code is the USER's, CONSENT-CODE-FROM-THE-USER)::

    python -m dev_lab.dev.hpcaccount.session request [--task SLUG] [--hours H] > <request.json>
    python -m dev_lab.ops.consent grant <request.json> --code <the user's code>
    python -m dev_lab.dev.hpcaccount.session status      # which identity gives this session the role
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from lab_commons.log import emit

from dev_lab.dev.consentguard import state_dir
from dev_lab.dev.native_session import session_of
from dev_lab.dev.taskledger import ledger, task_in, task_of
from dev_lab.ops.consent.actions import ACTIONS
from dev_lab.ops.consent.client import public_key
from dev_lab.ops.consent.credential import ConsentRefused, verify

__all__ = [
    'ACTION', 'INTEGRATOR', 'TASK_ACTION', 'held', 'holder', 'main', 'request', 'roles',
]  # fmt: skip

#: The role this module proves.
INTEGRATOR: Final = 'integrator'
#: The consent action granting it to one session (:data:`dev_lab.ops.consent.actions.ACTIONS`).
ACTION: Final = 'session.integrator'
#: The consent action granting it to one task, inherited by the sessions the user bound to it.
TASK_ACTION: Final = 'task.integrator'


def _cwd_task() -> str | None:
    """The open task the cwd's branch works on, or ``None``: a branch naming no open task grants nothing."""
    try:
        return task_of(Path.cwd())
    except (ValueError, LookupError):
        return None


def holder(
    *,
    session: str | None = None,
    home: Path | None = None,
    now: float | None = None,
    table: Mapping[str, Any] | None = None,
) -> str | None:
    """Which identity gives *session* (default: this one) the role -- ``session <id>`` or ``task <id>``; fail closed.

    No session id, no issuer key, or no credential verifying for this session or the task the user bound it to: None.
    """
    session = session_of() if session is None else session
    if not session:
        return None
    try:
        key = public_key(table)
    except ConsentRefused:
        return None
    when = time.time() if now is None else now
    wanted = {(ACTION, session): f'session {session}'}
    task = _cwd_task()
    if task:
        wanted[(TASK_ACTION, task)] = f'task {task}'
    for path in sorted(state_dir(home).glob('*.json')):
        try:
            found = verify(json.loads(path.read_text(encoding='utf-8')), key, now=when)
        except (ConsentRefused, ValueError, OSError):
            continue
        if (found.action, found.subject) in wanted:
            return wanted[(found.action, found.subject)]
    return None


def held(
    *,
    session: str | None = None,
    home: Path | None = None,
    now: float | None = None,
    table: Mapping[str, Any] | None = None,
) -> frozenset[str]:
    """The roles *session* holds, by its own credential or its branch's task's (:func:`holder`)."""
    found = holder(session=session, home=home, now=now, table=table)
    return frozenset({INTEGRATOR}) if found else frozenset()


def roles() -> frozenset[str]:
    """The current session's verified roles -- the ``[hpc] session_verifier`` lab-commons calls."""
    return held()


def request(session: str, hours: float | None = None, *, task: str | None = None) -> dict[str, Any]:
    """The consent request granting the role to *task* (a task id) if given, else to *session*, for *hours*."""
    if task is None and not session:
        msg = 'no native session id: the integrator role is granted to one session or task, never a machine'
        raise ValueError(msg)
    action, subject = (ACTION, session) if task is None else (TASK_ACTION, task)
    ttl = ACTIONS[action].default_ttl if hours is None else hours * 3600
    return {'action': action, 'subject': subject, 'ttl': ttl}


def main(argv: list[str] | None = None) -> int:
    """``request [--task SLUG] [--hours H]`` prints a request; ``status`` the holder."""
    parser = argparse.ArgumentParser(
        prog='python -m dev_lab.dev.hpcaccount.session', description=__doc__.splitlines()[0]
    )
    verbs = parser.add_subparsers(dest='verb', required=True)
    asking = verbs.add_parser('request')
    asking.add_argument('--hours', type=float, default=None)
    asking.add_argument('--task', default=None, help='grant the open task SLUG of the task ledger, not this session')
    verbs.add_parser('status')
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    session = session_of()
    if args.verb == 'status':
        task = _cwd_task()
        found = holder(session=session)
        role = f'integrator, by {found}' if found else 'no session role'
        emit(f'session {session or "(none)"} (task {task or "none bound"}) holds {role}')
        return 0
    try:
        task = task_in(ledger(), args.task) if args.task else None
        emit(json.dumps(request(session, args.hours, task=task)))
    except (ValueError, LookupError) as refused:
        emit(f'hpcsession refused: {refused}', err=True)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
