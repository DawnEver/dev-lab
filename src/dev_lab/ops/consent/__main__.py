"""``python -m dev_lab.ops.consent preflight|grant <request.json>`` | ``receipts`` | ``plan`` | ``recover``: consent.

``preflight <request.json>`` proves, with no code, that the request's grant can succeed and writes its receipt
(:func:`dev_lab.ops.consent.client.preflight`); exit 0 green -- only then is the user asked for the code -- 2 naming
the blocker. ``grant --code`` (or a code on stdin) without a fresh receipt is refused before any network call.
``receipts`` lists the fresh receipts: exit 0 when one exists, 1 naming the preflight door when none (the read a
Stop hook takes before an assistant may ask the user for a code).

``recover <plan.json> --digest D`` fetches again the plan's credentials the issuer granted and never registered (a
lost or deleted one), with no code: re-delivery, never a new grant (:meth:`.issuer.Issuer.unspent`).

``grant`` grants one credential. ``plan`` prints what a plan's ONE code would open and consent to, and the digest to
name, and OFFERS it for a code only when :func:`dev_lab.ops.consent.door.offer` passes (a green ``planrun
preflight`` of this plan, an issuer this client agrees with); else it exits 2 naming the blocker, and no code is
asked. The code itself is given to ``python -m dev_lab.dev.sshhold open --plan <plan.json> --digest <D>``, which
opens every plan host not already held.

The code is the USER's: they give it, the agent runs this with it (user ruling 2026-11-08) -- as ``--code``, on stdin,
or typed at a terminal prompt that shows it as typed. Never invented, logged or reused. Writes the credential under
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

from dev_lab.ops.consent.client import TABLE, grant, preflight, recover
from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.consent.door import PREFLIGHT_DOOR, RECEIPT_FRESH_S, Send, fresh_receipts, offer, ssh_send
from dev_lab.ops.consent.plan import parsed, show

__all__ = ['main']


def main(argv: Sequence[str] | None = None, *, table: Mapping[str, Any] | None = None, send: Send = ssh_send) -> int:
    """Route ``grant``, ``plan`` and ``recover``; see the module docstring."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.ops.consent', description=__doc__.splitlines()[0])
    verbs = parser.add_subparsers(dest='verb', required=True)
    granting = verbs.add_parser('grant')
    granting.add_argument('request', type=Path, help='the request JSON an agent prepared')
    granting.add_argument('--code', default=None, help='the cluster code the USER gave (else stdin or a prompt)')
    verbs.add_parser('preflight', help='prove a request can be granted, with no code; writes its receipt').add_argument(
        'request', type=Path, help='the request JSON an agent prepared'
    )
    verbs.add_parser('receipts', help='the fresh preflight receipts: exit 0 when one exists, 1 when none')
    verbs.add_parser('plan', help='show a plan and the digest its one code consents to').add_argument('plan', type=Path)
    fetching = verbs.add_parser('recover', help="fetch again a plan's granted, never-used credentials; no code")
    fetching.add_argument('plan', type=Path)
    fetching.add_argument('--digest', required=True, help="the plan's digest, as shown to the user")
    args = parser.parse_args(argv)
    if args.verb == 'receipts':
        return _receipts()
    try:
        if args.verb == 'preflight':
            request = json.loads(args.request.read_text(encoding='utf-8'))
            written = preflight(request, table=table, send=send)
            emit(f'[consent] preflight green ({written}): ask the user for the code now; it admits '
                 f'{request["action"]} for {RECEIPT_FRESH_S:.0f} s')  # fmt: skip
            return 0
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


def _receipts() -> int:
    found = fresh_receipts()
    if not found:
        emit(
            f'[consent] no fresh preflight receipt: run `{PREFLIGHT_DOOR}` before asking the user for a code', err=True
        )
        return 1
    emit('\n'.join(f'[consent] fresh: {stamp["action"]} {str(stamp["subject"])[:40]}' for stamp in found))
    return 0


if __name__ == '__main__':
    sys.exit(main())
