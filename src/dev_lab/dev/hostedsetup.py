"""A HOSTED PART'S SETUP, run by its job and posted under its own class when it fails (dev-lab#998).

A declared hosted part's ``setup`` (:mod:`dev_lab.dev.hostedparts`) runs before its producer. Failed as a bare
shell step, the job concluded failure with no record and ``absent`` posted it ``class=environment``, naming
nothing. Run here instead, a failed setup posts its part ``error`` itself, naming the exit and the setup's last
line, under its own class: :data:`EX_TEMPFAIL` (sysexits' "a third-party source did not answer, try again") is
``network``; any other exit is ``setup``. Neither is ``code``: a setup's failure is never a test's red.

``python -m dev_lab.dev.hostedsetup <part> [--root <checkout>]``
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev.forgeclient import client_for
from dev_lab.dev.forgestatus import status_post
from dev_lab.dev.harness import actions_run
from dev_lab.dev.hostedparts import hosted_parts
from dev_lab.dev.jobparts import head_sha
from dev_lab.dev.platformparts import part_context
from dev_lab.dev.producer import Owner, owned

if TYPE_CHECKING:
    from collections.abc import Sequence

    from dev_lab.dev.forgework import Client
    from dev_lab.dev.harness import ActionsRun

__all__ = ['EX_TEMPFAIL', 'main', 'run_setup']

#: sysexits' EX_TEMPFAIL: the setup declares that a source it fetches from did not answer -- ``network``, not its own.
EX_TEMPFAIL: Final = 75


def run_setup(root: Path, part: str, client: Client, *, run: ActionsRun) -> int:
    """Run *part*'s declared setup at *root* under bash, echoing its output; its exit code.

    A non-zero exit posts the part ``error`` at HEAD naming the exit and the last line said, ``class=network``
    for :data:`EX_TEMPFAIL`, else ``class=setup``, linking *run* (the job's Actions run, read once at the entry by
    :func:`~dev_lab.dev.harness.actions_run`). A part declaring no setup is refused by name.
    """
    text = (root / 'pyproject.toml').read_text(encoding='utf-8')
    setup = hosted_parts(text).get(part)
    if setup is None or not setup.setup:
        msg = f'[tool.dev_lab.parts] hosted part {part!r} declares no setup: nothing to run'
        raise ValueError(msg)
    done = _door.run(
        ['bash', '-c', setup.setup],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=False,
    )
    said = done.stdout or ''
    if said:
        emit(said.rstrip())  # the setup's own output, echoed through the one console writer
    if done.returncode == 0:
        return 0
    last = next((line.strip() for line in reversed(said.splitlines()) if line.strip()), 'it said nothing')
    owner = Owner.NETWORK if done.returncode == EX_TEMPFAIL else Owner.SETUP
    description = owned(owner, f'setup exited {done.returncode}: {last}')
    context = part_context(part)
    status_post(client, head_sha(root), context=context, state='error', description=description, target_url=run.url)
    emit(f'[hostedsetup] {context}: error {description}', err=True)
    return done.returncode


def main(argv: Sequence[str] | None = None) -> int:
    """``<part> [--root <checkout>]``: run the part's declared setup (module docs)."""
    parser = argparse.ArgumentParser(
        prog='python -m dev_lab.dev.hostedsetup', description=(__doc__ or '').splitlines()[0]
    )
    parser.add_argument('part')
    parser.add_argument('--root', type=Path, default=Path.cwd(), help='the checkout declaring the part')
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    return run_setup(args.root, args.part, client_for(args.root), run=actions_run())


if __name__ == '__main__':
    raise SystemExit(main())
