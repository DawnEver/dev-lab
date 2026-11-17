"""``python -m dev_lab.ops.consent grant <request.json> [--code CODE]`` | ``plan`` | ``recover``: the user's consent.

``recover <plan.json> --digest D`` fetches again the plan's credentials the issuer granted and never registered (a
lost or deleted one), with no code: re-delivery, never a new grant (:meth:`.issuer.Issuer.unspent`).

``grant`` grants one credential. ``plan`` prints what a plan's ONE code would open and consent to, and the digest to
name, and OFFERS it for a code only when :func:`dev_lab.ops.consent.door.offer` passes (a green ``planrun
preflight`` of this plan, an issuer this client agrees with); else it exits 2 naming the blocker, and no code is
asked. The code itself is given to ``python -m dev_lab.dev.sshhold open --plan <plan.json> --digest <D>``, which
opens every plan host not already held.

The code is the USER's: they give it, the agent runs this with it (user ruling 2026-11-08) -- as ``--code``, on stdin,
or typed at the no-echo prompt of a terminal. Never invented, logged or reused. Writes the credential under
``<machine home>/state/consent/``. Exit 0 granted, 2 refused.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from lab_commons.config import section
from lab_commons.log import emit

from dev_lab.ops.consent.client import TABLE, grant, recover
from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.consent.door import Send, offer, ssh_send
from dev_lab.ops.consent.plan import parsed, show

__all__ = ['main']


def main(argv: Sequence[str] | None = None, *, table: Mapping[str, Any] | None = None, send: Send = ssh_send) -> int:
    """Route ``grant``, ``plan`` and ``recover``; see the module docstring."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.ops.consent', description=__doc__.splitlines()[0])
    verbs = parser.add_subparsers(dest='verb', required=True)
    granting = verbs.add_parser('grant')
    granting.add_argument('request', type=Path, help='the request JSON an agent prepared')
    granting.add_argument('--code', default=None, help='the cluster code the USER gave (else stdin or a prompt)')
    verbs.add_parser('plan', help='show a plan and the digest its one code consents to').add_argument('plan', type=Path)
    fetching = verbs.add_parser('recover', help="fetch again a plan's granted, never-used credentials; no code")
    fetching.add_argument('plan', type=Path)
    fetching.add_argument('--digest', required=True, help="the plan's digest, as shown to the user")
    args = parser.parse_args(argv)
    try:
        if args.verb == 'plan':
            emit(show(args.plan))
            plan = parsed(json.loads(args.plan.read_text(encoding='utf-8')))
            offer(plan, section(TABLE) if table is None else table, send=send)
            emit('[consent] offered: ask the user for the one code')
            return 0
        if args.verb == 'recover':
            written = recover(args.plan, args.digest)
            said = '\n'.join(f'[consent] recovered: {path}' for path in written)
            emit(said or '[consent] nothing unspent to recover')
            return 0
        written = grant(args.request, code=args.code)
    except (ConsentRefused, OSError, ValueError) as refused:
        emit(f'[consent] refused: {refused}', err=True)
        return 2
    emit(f'[consent] granted: {written}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
