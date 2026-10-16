"""INTENT BEFORE ACTION FOR A LOCAL RUN -- its claim is journaled before the producer starts; a restart re-attaches.

THE HAZARD (design D19, 2026-10-16). ``forge serve`` runs a claimed local job as a child process and holds
its lease while it runs. When serve itself dies -- a reboot, a killed terminal, a crashed tick -- nothing on
this host remembered the run: its lease stayed ``pending`` on the forge until it expired hours later, so the
job waited for nobody, and a producer still alive went unwatched.

THE RULE. :func:`journal` writes the run's :class:`Intent` -- job, sha, context, the claim that holds it --
fsynced, BEFORE its tree is built or its producer spawned, and again with the producer's pid once it runs;
:func:`forget` removes it once the run was released. Every ``forge serve`` first re-attaches (:func:`reattach`) to what
is journaled and not its own: a producer still ALIVE is watched (its lease renewed on the forge's clock, so
it is not taken from under it); a DEAD one is released as claimable -- ``error`` prefixed
:data:`~lab_commons.dev.producer.RETRYABLE`, naming why -- when its claim is still the forge's last word,
and its tree is closed (record and log kept, :func:`~lab_commons.dev.shatree.close_tree`). A run that
already posted its result is only forgotten.

WHERE IT LIVES. ``output/forge/runs/`` in the MAIN checkout (beside the outbox), one file per job.
"""

from __future__ import annotations

import dataclasses
import functools
import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import timedelta
from pathlib import Path
from typing import Final

from lab_commons.dev._forge_journal import durable_write
from lab_commons.dev.forgeclaim import Claim, forge_now
from lab_commons.dev.forgestatus import status_history, status_post
from lab_commons.dev.forgework import Client, ForgeCallFailed
from lab_commons.dev.producer import RETRYABLE
from lab_commons.dev.shatree import close_tree
from lab_commons.dev.worktreeplace import main_checkout
from lab_commons.proc import pid_alive

__all__ = ['RUNS_REL', 'Intent', 'forget', 'journal', 'journaled', 'reattach']

#: The run journal, relative to the MAIN checkout's root.
RUNS_REL: Final = 'output/forge/runs'


@dataclass(frozen=True)
class Intent:
    """One local run this host took on: the job, the claim holding it, and its producer's pid once spawned."""

    ref: str
    sha: str
    platform: str
    context: str
    holder: str  # the claim's description (:class:`~lab_commons.dev.forgeclaim.Claim`)
    pid: int = 0


@functools.cache
def _runs(root: Path) -> Path:
    """The journal directory of *root*'s repository, asked of git once per process (a producer's hot path)."""
    return main_checkout(root) / RUNS_REL


def _path(root: Path, sha: str, context: str) -> Path:
    return _runs(root) / f'{hashlib.sha256(f"{sha} {context}".encode()).hexdigest()[:24]}.json'


def journal(root: Path, intent: Intent) -> Path:
    """Write *intent* durably (temp, fsync, rename) BEFORE the action it announces."""
    return durable_write(_path(root, intent.sha, intent.context), json.dumps(asdict(intent)).encode('utf-8'))


def forget(root: Path, sha: str, context: str) -> None:
    """The run of *context* on *sha* was released: its intent goes."""
    _path(root, sha, context).unlink(missing_ok=True)


def journaled(root: Path) -> tuple[Intent, ...]:
    """Every journaled run of *root*'s repository; a torn entry is skipped."""
    directory = _runs(root)
    found = []
    for path in sorted(directory.glob('*.json')) if directory.is_dir() else ():
        try:
            found.append(Intent(**json.loads(path.read_text(encoding='utf-8'))))
        except (ValueError, TypeError):
            continue
    return tuple(found)


def reattach(
    root: Path,
    client: Client,
    *,
    lease: timedelta,
    say: Callable[[str], None],
    alive: Callable[[int], bool] = pid_alive,
) -> list[str]:
    """Watch every journaled producer still alive; release and forget every dead one (module docstring)."""
    lines: list[str] = []
    for intent in journaled(root):
        tag = f'[{intent.platform}] {intent.sha[:12]}'
        holder = Claim.parse(intent.holder)
        try:
            if intent.pid and alive(intent.pid):
                if holder is not None:
                    renewed = dataclasses.replace(holder, until=forge_now(client) + lease)
                    status_post(
                        client, intent.sha, context=intent.context, state='pending', description=renewed.description()
                    )
                lines.append(f'{tag}: re-attached to its producer (pid {intent.pid}), still running -- watching')
                continue
            posts = [one for one in status_history(client, intent.sha) if one.context == intent.context]
            if posts and posts[-1].state == 'pending':
                why = f'{RETRYABLE} -- this host restarted and its run died (pid {intent.pid or "never spawned"})'
                status_post(client, intent.sha, context=intent.context, state='error', description=why)
                lines.append(f'{tag}: released as claimable -- its producer died with the host')
            else:
                lines.append(f'{tag}: its producer died after it posted -- forgotten')
        except ForgeCallFailed as failed:  # the forge is down: keep the intent, the next tick re-attaches
            lines.append(f'{tag}: could not re-attach, kept: {failed}')
            continue
        say(f'{tag} {close_tree(root, intent.sha, intent.context)}')
        forget(root, intent.sha, intent.context)
    return lines
