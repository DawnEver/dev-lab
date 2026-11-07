"""``python -m dev_lab.ops.consent grant <request.json>``: the USER grants one consent credential.

Run in YOUR interactive terminal: it reads your Authenticator code without echo, refuses a pipe or a heredoc, and
writes the credential under ``~/.motronics/state/consent/``. Exit 0 granted, 2 refused.
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
    verbs.add_parser('grant').add_argument('request', type=Path, help='the request JSON an agent prepared')
    args = parser.parse_args(argv)
    try:
        written = grant(args.request)
    except (ConsentRefused, OSError, ValueError) as refused:
        emit(f'[consent] refused: {refused}', err=True)
        return 2
    emit(f'[consent] granted: {written}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
