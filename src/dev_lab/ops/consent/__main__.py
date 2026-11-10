"""``python -m dev_lab.ops.consent grant <request.json> [--code CODE]`` | ``plan <plan.json>``: the user's consent.

``grant`` grants one credential. ``plan`` prints what a plan's ONE code would open and consent to, and the digest to
name; the code itself is given to ``python -m dev_lab.dev.sshhold open <dest> --plan <plan.json> --digest <D>``.

The code is the USER's: they give it, the agent runs this with it (user ruling 2026-11-08) -- as ``--code``, on stdin,
or typed at the no-echo prompt of a terminal. Never invented, logged or reused. Writes the credential under
``<machine home>/state/consent/``. Exit 0 granted, 2 refused.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from lab_commons.log import emit

from dev_lab.ops.consent.client import grant
from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.consent.plan import show

__all__ = ['main']


def main(argv: Sequence[str] | None = None) -> int:
    """Route ``grant`` and ``plan``; see the module docstring."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.ops.consent', description=__doc__.splitlines()[0])
    verbs = parser.add_subparsers(dest='verb', required=True)
    granting = verbs.add_parser('grant')
    granting.add_argument('request', type=Path, help='the request JSON an agent prepared')
    granting.add_argument('--code', default=None, help='the Authenticator code the USER gave (else stdin or a prompt)')
    verbs.add_parser('plan', help='show a plan and the digest its one code consents to').add_argument('plan', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.verb == 'plan':
            emit(show(args.plan))
            return 0
        written = grant(args.request, code=args.code)
    except (ConsentRefused, OSError, ValueError) as refused:
        emit(f'[consent] refused: {refused}', err=True)
        return 2
    emit(f'[consent] granted: {written}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
