"""THE DOOR TO A HUNG TICK: ``hpcaccount tick-status --account <user>`` and ``tick-stop --account <user> [--repo R]``.

Measured 2026-11-23: a verification account's tick held its lock for hours and nothing on the workstation could see
or stop it (raw ssh is forbidden). ``tick-status`` is the ``ticks`` read of :mod:`~dev_lab.dev.hpcaccount.look`
(every tick lock and its holder record). ``tick-stop`` runs, through the same pinned runner on the account's declared
login host, the ACCOUNT'S OWN kit: ``python -m dev_lab.dev.hpcaccount tick-stop-here --root <root> [--repo R]``
(:func:`stop_here`), which for each holder record under ``<root>/serve``:

* refuses a tick YOUNGER THAN ITS WALL by name -- it ends itself there (:mod:`~dev_lab.dev.hpcaccount.tickwall`);
* says a holder whose process is gone (the next tick takes its lock over by name);
* VERIFIES the pid before signalling it: still the process that wrote the record (its creation stamp), this user's,
  and its command line a ``dev_lab.dev.hpcaccount tick`` of that repo -- else refused, nothing signalled;
* then sends SIGTERM: the tick ends its serve, releases the lock and prints ``tick: stopped ...`` to its log.
"""

from __future__ import annotations

import argparse
import os
import signal
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from lab_commons.log import emit

from dev_lab.dev import tickholder
from dev_lab.dev.hpcaccount import look
from dev_lab.dev.hpcaccount.fleet import declared_target, in_checkout
from dev_lab.dev.hpcaccount.storage import Pin, on_host
from dev_lab.dev.hpcaccount.transport import grant_runner

__all__ = ['cmdline', 'main_here', 'main_status', 'main_stop', 'stop_command', 'stop_here']


def cmdline(pid: int) -> tuple[str, int | None]:
    """*pid*'s command line and owner uid, from ``/proc`` (every cluster login host is Linux); ``('', None)`` gone."""
    proc = Path('/proc') / str(pid)
    try:
        words = (proc / 'cmdline').read_bytes().split(b'\0')
        uid = (proc / 'status').read_text(encoding='utf-8').split('Uid:', 1)[1].split()[0]
    except (OSError, IndexError):
        return '', None
    return ' '.join(word.decode('utf-8', 'replace') for word in words if word), int(uid)


def _judged(holder: tickholder.Holder, now: datetime, read: Callable[[int], tuple[str, int | None]], uid: int) -> str:
    """Why *holder* may not be signalled; ``''`` when it may."""
    age = tickholder.age(holder, now)
    if age < holder.wall_s:
        left = tickholder.span(holder.wall_s - age)
        wall = tickholder.span(holder.wall_s)
        return f'refused -- younger than its wall ({tickholder.span(age)} of {wall}): it ends itself in {left}'
    if not tickholder.alive(holder):
        return 'its process is gone: nothing to stop; the next tick takes its lock over by name'
    command, owner = read(holder.pid)
    if owner != uid:
        return f"refused -- pid {holder.pid} is not this user's process"
    words = command.split()
    if 'dev_lab.dev.hpcaccount' not in words or 'tick' not in words or holder.repo.split()[0] not in words:
        return f'refused -- pid {holder.pid} is not a tick of {holder.repo}: {command[:200]!r}'
    return ''


def stop_here(
    root: Path,
    repo: str = '',
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    read: Callable[[int], tuple[str, int | None]] = cmdline,
    kill: Callable[[int, int], None] = os.kill,
    uid: int | None = None,
    say: Callable[[str], None] = emit,
) -> int:
    """Stop every tick under *root*/serve (only *repo*'s when given) older than its wall; 2 when any was refused."""
    records = sorted((root / 'serve').glob(f'{repo or "*"}.lock.holder'))
    if not records:
        say(f'tick-stop: no tick holds a lock under {root}/serve' + (f' for {repo}' if repo else ''))
        return 0
    me = os.getuid() if uid is None else uid  # type: ignore[attr-defined,unused-ignore]  # a POSIX account
    refused = 0
    for record in records:
        holder = tickholder.read(record)
        if holder is None:
            continue
        why = _judged(holder, now(), read, me)
        if not why:
            kill(holder.pid, signal.SIGTERM)
            why = f'stopped (SIGTERM) -- its log says `tick: stopped after ... doing {holder.phase}`'
        refused += why.startswith('refused')
        say(f'tick-stop: {holder.repo}: {tickholder.describe(holder, now())}: {why}')
    return 2 if refused else 0


def stop_command(root: str, repo: str) -> list[str]:
    """The on-account argv of ``tick-stop-here``."""
    return ['-m', 'dev_lab.dev.hpcaccount', 'tick-stop-here', '--root', root, *(['--repo', repo] if repo else [])]


def main_here(argv: Sequence[str]) -> int:
    """``tick-stop-here --root <root> [--repo R]``: run ON the account by ``tick-stop``."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.hpcaccount tick-stop-here')
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--repo', default='')
    args = parser.parse_args(list(argv))
    return stop_here(args.root, args.repo)


def main_status(argv: Sequence[str]) -> int:
    """``tick-status --account <user>``: the ``ticks`` read of ``look`` (read only)."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.hpcaccount tick-status')
    parser.add_argument('--account', required=True)
    return look.look(parser.parse_args(list(argv)).account, 'ticks')


def stop(
    user: str,
    repo: str = '',
    *,
    connect: Callable[..., look.Runner] = grant_runner,
    pin: Pin = on_host,
    say: Callable[[str], None] = emit,
) -> int:
    """Run ``tick-stop-here`` on *user*'s declared login host; 2 refused or unreachable."""
    if repo and not look.REPO_NAME.fullmatch(repo):
        say(f'tick-stop: {repo!r} is not a repo name')
        return 2
    try:
        grant = next(g for g in look.reached_machine([user]).grants if g.user == user)
        target = declared_target(grant, connect(grant))
        if isinstance(target, str):
            say(target)
            return 2
        out = pin(grant, target.host)(in_checkout(target, stop_command(target.root, repo)) + '; echo "rc=$?"', None)
    except (PermissionError, LookupError, RuntimeError, OSError, ValueError) as refused:
        say(f'tick-stop: {user}: refused -- {refused}')
        return 2
    lines = out.rstrip().splitlines()
    for line in lines[:-1] if lines and lines[-1].startswith('rc=') else lines:
        say(line)
    return 0 if lines and lines[-1] == 'rc=0' else 2


def main_stop(argv: Sequence[str]) -> int:
    """``tick-stop --account <user> [--repo R]``."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.hpcaccount tick-stop')
    parser.add_argument('--account', required=True)
    parser.add_argument('--repo', default='')
    args = parser.parse_args(list(argv))
    return stop(args.account, args.repo)
