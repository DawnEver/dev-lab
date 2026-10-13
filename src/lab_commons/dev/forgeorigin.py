"""The commit-msg stamp of a commit's ORIGIN HOST: ``Forge-Host: <host card>`` (``forge reserve --for host:H``).

A reservation ``for host:H`` serves the jobs host H created. Git records no host and the forge records only
the pusher's LOGIN -- every session on a workstation may push as one login -- so the host travels in the
commit, as a trailer this hook writes. It is CLAIMED, never trusted: a reader keeps it only where the
forge-recorded author of the PR vouches for it, as that host card's owner or a ``[reserve]`` delegate
(:func:`lab_commons.dev.forgeschedule.vouched`). The host is the card name a tick on this machine
publishes (``$HARNESS_MACHINE``, else the hostname). The one family hook that rewrites its input: it
appends the trailer (replacing an earlier one) and never refuses a commit.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence

from lab_commons.dev.forge import _GIT, _GIT_TIMEOUT_S
from lab_commons.dev.forgeclaim import this_machine
from lab_commons.dev.forgehosts import card_host
from lab_commons.dev.forgeschedule import ORIGIN_HOST
from lab_commons.log import emit

__all__ = ['main', 'stamp']


def stamp(message_file: str, host: str) -> None:
    """Append ``Forge-Host: <host>`` to *message_file*, replacing a trailer already there."""
    subprocess.run(
        [_GIT, 'interpret-trailers', '--in-place', '--if-exists', 'replace', '--trailer', f'{ORIGIN_HOST}: {host}',
         message_file],
        check=True, timeout=_GIT_TIMEOUT_S,
    )  # fmt: skip


def main(argv: Sequence[str] | None = None) -> int:
    """The hook: stamp the message file git hands it; 0 on every path, and a failure is SAID."""
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        stamp(args[-1], card_host(this_machine(None), None))
    except (IndexError, OSError, subprocess.SubprocessError) as failed:
        emit(f'[forge-host] no origin host stamped: {failed}', err=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
