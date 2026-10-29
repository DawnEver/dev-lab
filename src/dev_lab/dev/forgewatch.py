"""``python -m dev_lab.dev.forge watch <sha>`` -- READ-ONLY: print a commit's verdicts until settled or a deadline.

It only reads commit statuses (:func:`dev_lab.dev.forgestatus.status_list`) and prints each change, one line
per ``tests/<part>`` context. SETTLED means at least one test status and none ``pending``. Exit 0 settled
and every part ``success``, 1 settled with a red or an error, 3 when the deadline passed first. It never
posts, claims or cancels anything.

``--stream`` is the shape a Claude Code ``Monitor`` reads (PUSHED-HEAD-IS-WATCHED, :mod:`dev_lab.dev.pushwatch`):
ONE flushed line per status CHANGE of any context -- ``<sha12> <context> <state>`` -- and a last line
``<sha12> green|red|deadline``; a re-read status that did not change prints nothing.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final

from lab_commons.log import emit

from dev_lab.dev.forgestatus import CommitStatus, status_list
from dev_lab.dev.forgework import Client, ForgeCallFailed, client_for

__all__ = ['TESTS', 'main', 'settled', 'watch']

#: The context prefix a part's verdict is posted under.
TESTS: Final = 'tests/'
_DEADLINE: Final = 3


def settled(statuses: Sequence[CommitStatus]) -> bool:
    """Whether every test status is final and there is at least one."""
    tests = [s for s in statuses if s.context.startswith(TESTS)]
    return bool(tests) and all(s.state != 'pending' for s in tests)


def watch(
    client: Client,
    sha: str,
    *,
    deadline_s: float,
    every_s: float,
    say: Callable[[str], None],
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    stream: bool = False,
) -> int:
    """Poll *sha*'s statuses, printing each change, until settled or *deadline_s* has passed (``--stream``: above)."""
    end, seen = clock() + deadline_s, set()
    while True:
        statuses = status_list(client, sha)
        for status in statuses:
            line = (
                f'{sha[:12]} {status.context} {status.state}'
                if stream
                else f'{status.context}: {status.state} {status.description}'
            )
            if (stream or status.context.startswith(TESTS)) and line not in seen:
                seen.add(line)
                say(line)
        if settled(statuses):
            green = all(s.state == 'success' for s in statuses if s.context.startswith(TESTS))
            if stream:
                say(f'{sha[:12]} {"green" if green else "red"}')
            return 0 if green else 1
        if clock() >= end:
            say(f'{sha[:12]} deadline' if stream else f'watch: {sha[:12]} not settled by the deadline')
            return _DEADLINE
        sleep(every_s)


def main(argv: Sequence[str] | None = None) -> int:
    """``forge watch <sha> [--deadline-minutes M] [--every-seconds S] [--stream]``."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.forge watch', description=main.__doc__)
    parser.add_argument('sha')
    parser.add_argument('--deadline-minutes', type=float, default=120.0)
    parser.add_argument('--every-seconds', type=float, default=60.0)
    parser.add_argument('--stream', action='store_true', help='one flushed line per status change, for a Monitor')
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    try:
        return watch(
            client_for(Path.cwd()),
            args.sha,
            deadline_s=args.deadline_minutes * 60,
            every_s=max(args.every_seconds, 5.0),
            say=lambda line: emit(line, flush=True),
            stream=args.stream,
        )
    except (ForgeCallFailed, ValueError) as failed:
        emit(f'watch: {failed}', err=True)
        return 2
