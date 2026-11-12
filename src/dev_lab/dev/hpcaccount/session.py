"""THE INTEGRATOR IS A SESSION ROLE, PROVED BY A CONSENT CREDENTIAL -- never a host's (user correction 2026-11-12).

A host file declares only what its MACHINE may reach (``[dev] hpc``, rendered as ``[hpc] reach``). Verification
accounts are reached by a SESSION holding the integrator role, on a machine whose reach is not empty: the family
declares ``[hpc] session_reach = { integrator = ["verification"] }`` and ``[hpc] session_verifier`` naming
:func:`roles`, which :func:`lab_commons.hpc.grants.load_grants` calls -- so the ``lab_commons.hpc`` door and every
``dev_lab.dev.hpcaccount`` verb (all of which load through it) check the role before they touch an account.

THE ROLE IS NEVER SELF-CLAIMED. It is a :data:`ACTION` credential of :mod:`dev_lab.ops.consent`: the user grants it
with one TOTP code for THIS session (subject = ``$CLAUDE_CODE_SESSION_ID``), the issuer signs it with a lifetime
bounded by the action's ``max_ttl``, and :func:`dev_lab.ops.consent.client.grant` stores it in the machine-local
consent state. :func:`held` verifies it OFFLINE on every load -- signature, registry row, expiry, subject -- so an
expired credential, another session's, or a forged one grants nothing. Nothing is registered with the issuer per
use: the code was the consent, for the session, until it expires.

Granting it (the code is the USER's, CONSENT-CODE-FROM-THE-USER)::

    python -m dev_lab.dev.hpcaccount.session request [--hours H] > <request.json>   # this session's request
    python -m dev_lab.ops.consent grant <request.json> --code <the user's code>
    python -m dev_lab.dev.hpcaccount.session status                                  # the roles this session holds
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from lab_commons.log import emit

from dev_lab.dev.consentguard import state_dir
from dev_lab.dev.sessionprs import SESSION_ENV
from dev_lab.ops.consent.actions import ACTIONS
from dev_lab.ops.consent.client import public_key
from dev_lab.ops.consent.credential import ConsentRefused, verify

__all__ = ['ACTION', 'INTEGRATOR', 'held', 'main', 'request', 'roles']

#: The session role this module proves.
INTEGRATOR: Final = 'integrator'
#: The consent action that grants it (:data:`dev_lab.ops.consent.actions.ACTIONS`).
ACTION: Final = 'session.integrator'


def held(
    *,
    session: str | None = None,
    home: Path | None = None,
    now: float | None = None,
    table: Mapping[str, Any] | None = None,
) -> frozenset[str]:
    """The session roles *session* (default: this one) holds by a valid credential in the consent state; fail closed.

    No session id, no issuer key, or no credential verifying for this action AND this session: no role.
    """
    session = os.environ.get(SESSION_ENV, '') if session is None else session
    if not session:
        return frozenset()
    try:
        key = public_key(table)
    except ConsentRefused:
        return frozenset()
    when = time.time() if now is None else now
    for path in sorted(state_dir(home).glob('*.json')):
        try:
            found = verify(json.loads(path.read_text(encoding='utf-8')), key, now=when)
        except (ConsentRefused, ValueError, OSError):
            continue
        if found.action == ACTION and found.subject == session:
            return frozenset({INTEGRATOR})
    return frozenset()


def roles() -> frozenset[str]:
    """The current session's verified roles -- the ``[hpc] session_verifier`` lab-commons calls."""
    return held()


def request(session: str, hours: float | None = None) -> dict[str, Any]:
    """The consent request granting *session* the integrator role for *hours* (default: the action's default)."""
    if not session:
        msg = f'no session id (${SESSION_ENV}): the integrator role is granted to one session, never to a machine'
        raise ValueError(msg)
    ttl = ACTIONS[ACTION].default_ttl if hours is None else hours * 3600
    return {'action': ACTION, 'subject': session, 'ttl': ttl}


def main(argv: list[str] | None = None) -> int:
    """``request [--hours H]`` prints this session's request; ``status`` prints the roles it holds."""
    parser = argparse.ArgumentParser(
        prog='python -m dev_lab.dev.hpcaccount.session', description=__doc__.splitlines()[0]
    )
    verbs = parser.add_subparsers(dest='verb', required=True)
    verbs.add_parser('request').add_argument('--hours', type=float, default=None)
    verbs.add_parser('status')
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    session = os.environ.get(SESSION_ENV, '')
    if args.verb == 'status':
        emit(f'session {session or "(none)"} holds {sorted(held(session=session)) or "no session role"}')
        return 0
    try:
        emit(json.dumps(request(session, args.hours)))
    except ValueError as refused:
        emit(f'hpcsession refused: {refused}', err=True)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
