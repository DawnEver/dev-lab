"""COMMAND-PART: a repo whose tests are not pytest posts its part as ONE cell -- the command, judged by its exit.

A JavaScript repo (``npm test``, ``node --test``) has no collection to cut into need-sets, so it has one part,
``base``, and that part is one test: the command. It is declared as the repo's producer like any other::

    [tool.lab_commons.tests]
    produce = ["-m", "dev_lab.dev.commandpart", "{part}", "--", "npm", "test"]

``python -m dev_lab.dev.commandpart <part> -- <command...>`` runs *command* in the checkout, and writes and posts
the run record of *part* at HEAD in the shape a local verify's has (:func:`dev_lab.dev.localpart.local_record`):
one cell, id = the command, ``ok`` on exit 0 else ``rejected``. Its exit code is the command's.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import lab_commons.launch as _door
from lab_commons.hpc.shell import FULL
from lab_commons.hpc.testcells import upgraded
from lab_commons.log import emit

from dev_lab.dev.localpart import local_record, post_local
from dev_lab.dev.platformparts import record_directory

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ['main']


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command after ``--`` as *part* at the checkout's HEAD and post it; the command's exit code."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.commandpart', description=__doc__.splitlines()[0])
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('part')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        parser.error('no command: python -m dev_lab.dev.commandpart <part> -- <command...>')
    head = _door.run(
        ['git', 'rev-parse', 'HEAD'], cwd=args.root, capture_output=True, text=True, encoding='utf-8', check=True
    )
    sha = head.stdout.strip()
    code = _door.run(command, cwd=args.root, check=False).returncode
    node = ' '.join(command)
    cell = upgraded('passed') if code == 0 else upgraded('failed', f'{node} exited {code}')
    record = local_record(
        sha=sha, part=args.part, scope=FULL, req='command', cells={node: cell}, owned={node: args.part}
    )
    emit(post_local(args.root, record, record_directory(args.root, sha)))
    return code


if __name__ == '__main__':
    sys.exit(main())
