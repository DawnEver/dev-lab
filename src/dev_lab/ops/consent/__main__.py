"""``python -m dev_lab.ops.consent grant <request.json> [--code CODE]``: grant one consent credential.

The code is the USER's: they give it, the agent runs this with it (user ruling 2026-11-08) -- as ``--code``, on stdin,
or typed at the no-echo prompt of a terminal. Never invented, logged or reused. Writes the credential under
``state/consent/`` of the machine home (``dev_lab.dev.consentguard.state_dir``). Exit 0 granted, 2 refused.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from lab_commons.log import emit

from dev_lab.ops.consent.client import grant
from dev_lab.ops.consent.credential import ConsentRefused

__all__ = ['main']


def main(argv: Sequence[str] | None = None) -> int:
    """Route ``grant``; see the module docstring."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.ops.consent', description=__doc__.splitlines()[0])
    verbs = parser.add_subparsers(dest='verb', required=True)
    granting = verbs.add_parser('grant')
    granting.add_argument('request', type=Path, help='the request JSON an agent prepared')
    granting.add_argument('--code', default=None, help='the Authenticator code the USER gave (else stdin or a prompt)')
    args = parser.parse_args(argv)
    try:
        written = grant(args.request, code=args.code)
    except (ConsentRefused, OSError, ValueError) as refused:
        emit(f'[consent] refused: {refused}', err=True)
        return 2
    emit(f'[consent] granted: {written}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
